"""Account-scoped, local phase keyword rules. No Meta writes or model calls."""
import hashlib, json, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FIELDS = {'body':'正文', 'title':'标题', 'description':'描述'}
SCOPES = {'all','campaign_name','adset_name','name'}

def norm(value):
    return unicodedata.normalize('NFKC', str(value)).casefold()

def terms(value):
    if not isinstance(value,list) or len(value)>50: raise ValueError('每类最多填写 50 个关键词。')
    out=[]
    for item in value:
        if not isinstance(item,str) or not item.strip() or len(item)>200: raise ValueError('关键词不能为空，且最多 200 字。')
        if norm(item.strip()) not in [norm(v) for v in out]:out.append(item.strip())
    return out

def draft(text):
    if not isinstance(text,str) or not text.strip() or len(text)>6000:raise ValueError('请用 6000 字以内说明阶段要求。')
    allow=[];deny=[];unparsed=[]
    # Suggestions only: every draft must be reviewed in the editable rule card.
    for clause in re.split(r'[；;\n。]', text):
        if re.search(r'(?<!不)允许|(?<!不)可以|(?<!不)符合规范',clause) and re.search(r'禁止|禁用|不允许|不符合|不能|不可以',clause):
            unparsed.append(clause.strip());continue
        quoted=re.findall(r'[“「"]([^”」"]+)[”」"]',clause)
        if quoted and re.search(r'禁止|禁用|不允许|不符合|不合规|不能|不可以|需暂停|需要暂停|要暂停',clause):deny.extend(quoted)
        elif quoted and re.search(r'允许|符合|合规|可以|可用',clause):allow.extend(quoted)
        elif clause.strip():unparsed.append(clause.strip())
    phase=re.search(r'(?:阶段|活动)\s*[:：]\s*([^；;\n。]+)',text)
    return {'original':text,'phase':phase.group(1).strip() if phase else '', 'allow':list(dict.fromkeys(allow)), 'deny':list(dict.fromkeys(deny)), 'notes':unparsed,
            'message':'已整理为草稿。请核对关键词，并补充范围和日期后保存；其余背景仅记录，不自动变成检查规则。'}

def validate(body):
    r={k:body.get(k) for k in ['phase','original','start','end','scope_field','scope_value','reviewer','allow','deny']}
    for k,label in [('phase','阶段名称'),('reviewer','确认人')]:
        if not isinstance(r[k],str) or not r[k].strip() or len(r[k])>200:raise ValueError('请填写'+label+'（最多200字）。')
        r[k]=r[k].strip()
    r['original']=str(r.get('original') or '')[:6000]
    try:
        start=datetime.strptime(r['start'],'%Y-%m-%d').date();end=datetime.strptime(r['end'],'%Y-%m-%d').date()
    except (ValueError,TypeError):raise ValueError('请填写开始和结束日期。')
    if end<start:raise ValueError('结束日期不能早于开始日期。')
    if r['scope_field'] not in SCOPES:raise ValueError('请选择适用广告范围。')
    r['scope_value']=str(r.get('scope_value') or '').strip()
    if r['scope_field']!='all' and not r['scope_value']:raise ValueError('请填写名称中必须包含的内容。')
    if len(r['scope_value'])>300:raise ValueError('名称筛选条件过长。')
    r['allow']=terms(r['allow']);r['deny']=terms(r['deny'])
    if not r['allow'] and not r['deny']:raise ValueError('至少填写一个允许词或禁用词。')
    if {norm(x) for x in r['allow']} & {norm(x) for x in r['deny']}:raise ValueError('同一个词不能同时允许和禁止，请先消除冲突。')
    return r

def match_copy(rule, text_fields):
    hits=[];allowed=[];read=[]
    for field,label in FIELDS.items():
        value=text_fields.get(field)
        if not isinstance(value,str) or not value.strip():continue
        read.append(field)
        for word in rule['deny']:
            if norm(word) in norm(value):hits.append({'field':label,'word':word,'text':value})
        for word in rule['allow']:
            if norm(word) in norm(value):allowed.append({'field':label,'word':word,'text':value})
    return {'hits':hits,'allowed':allowed,'read_fields':read,'unread_fields':[FIELDS[f] for f in FIELDS if f not in read],
            'status':'FORBIDDEN' if hits else 'NO_FORBIDDEN_IN_READ_FIELDS' if read else 'NO_COPY'}

def report(rule, source, now=None):
    tz=ZoneInfo(source.get('timezone') or 'UTC');now=now or datetime.now(timezone.utc);day=now.astimezone(tz).date().isoformat()
    active=rule['start']<=day<=rule['end'] and not rule.get('disabled')
    matched=[]
    for ad in source.get('ads',[]):
        if ad.get('scope_status')!='ACTIVE':continue
        if rule['scope_field']!='all' and norm(rule['scope_value']) not in norm(ad.get(rule['scope_field']) or ''):continue
        result=match_copy(rule,ad)
        matched.append({'ad_id':ad['id'],'campaign':ad['campaign_name'],'adset':ad['adset_name'],'ad':ad['name'],**result})
    return {'mode':'SAVED_SNAPSHOT_PREVIEW','account':source['account'],'snapshot_id':source['snapshot_id'],'captured_at':source['captured_at'],
            'rule_id':rule.get('id'),'phase':rule['phase'],'account_today':day,'timezone':str(tz),'active_today':active,
            'rule_status':'已停用' if rule.get('disabled') else '生效中' if active else '尚未生效' if day<rule['start'] else '已到期',
            'scanned':len(matched),'forbidden_count':sum(bool(x['hits']) for x in matched),
            'allow_count':sum(bool(x['allowed']) and not x['hits'] for x in matched),
            'no_copy_count':sum(not x['read_fields'] for x in matched),'partial_count':sum(bool(x['read_fields']) and bool(x['unread_fields']) for x in matched),
            'objects':matched,'meta_writes':False,'action':'仅形成待核实建议；需最新配置复查后由投手操作暂停',
            'notice':'这是已保存广告文案的历史试查，不是实时 Daily 结果，不证明这些广告今天仍在投。规则有效期按账户时区判断；到期或未生效规则不进入正式检查。只做文字包含匹配，不读取图片、视频压字或 Meta 自动生成的投放文案。'}

class PhaseRules:
    def __init__(self, folder, source):
        self.folder=Path(folder)/'phase-rules';self.folder.mkdir(exist_ok=True);self.path=self.folder/'state.json';self.source=source
    def state(self):
        data=json.loads(self.path.read_text()) if self.path.exists() else {'revision':0,'rules':[]}
        chat_path=self.folder/'conversation.json'
        conversation=json.loads(chat_path.read_text()) if chat_path.exists() else []
        if any(row['account_id']!=self.source['account_id'] for row in conversation):raise ValueError('对话所属账户不一致。')
        return {**data,'conversation':conversation[-50:],'account':self.source['account'],'account_id':self.source['account_id'],'captured_at':self.source['captured_at'],'timezone':self.source.get('timezone','UTC')}
    def chat(self, text):
        result=draft(text)
        path=self.folder/'conversation.json'
        rows=json.loads(path.read_text()) if path.exists() else []
        if any(row['account_id']!=self.source['account_id'] for row in rows):raise ValueError('对话所属账户不一致。')
        rows.append({'account_id':self.source['account_id'],'created_at':datetime.now(timezone.utc).isoformat(),'draft':result})
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2));tmp.replace(path)
        return result
    def confirm(self, body):
        current=self.state()
        if body.get('revision')!=current['revision']:raise ValueError('规则已在其他页面更新，请刷新后再保存。')
        rule=validate(body.get('rule',{}));rule['account_id']=self.source['account_id']
        if any(r.get('account_id')!=self.source['account_id'] for r in current['rules']):raise ValueError('规则所属账户不一致，请核对本地目录。')
        for old in current['rules']:
            if not old.get('disabled') and old['phase']==rule['phase']:raise ValueError('已有同名阶段规则；请先停用旧规则，再确认新版本。')
            same_scope=old['scope_field']==rule['scope_field'] and old['scope_value']==rule['scope_value']
            overlaps=old['start']<=rule['end'] and rule['start']<=old['end']
            clash=({norm(x) for x in old['deny']} & {norm(x) for x in rule['allow']}) | ({norm(x) for x in old['allow']} & {norm(x) for x in rule['deny']})
            if same_scope and overlaps and clash and not old.get('disabled'):raise ValueError('同一范围和日期已有相反的关键词规则，请先停用旧规则。')
        rule['confirmed_at']=datetime.now(timezone.utc).isoformat();rule['id']=hashlib.sha256(json.dumps(rule,sort_keys=True).encode()).hexdigest()[:20]
        rule['disabled']=False;current['rules'].append(rule);return self._save(current)
    def disable(self,body):
        current=self.state()
        if body.get('revision')!=current['revision']:raise ValueError('规则已更新，请刷新。')
        row=next((r for r in current['rules'] if r['id']==body.get('rule_id')),None)
        if not row:raise ValueError('规则不存在。')
        row['disabled']=True;row['disabled_at']=datetime.now(timezone.utc).isoformat();return self._save(current)
    def _save(self,current):
        current['revision']+=1
        current.pop('conversation',None)
        raw=json.dumps(current,ensure_ascii=False,indent=2)
        (self.folder/f'version-{current["revision"]:04d}.json').write_text(raw)
        temp=self.path.with_suffix('.tmp');temp.write_text(raw);temp.replace(self.path)
        return self.state()
    def check(self,body):
        current=self.state();rule=next((r for r in current['rules'] if r['id']==body.get('rule_id')),None)
        if not rule:raise ValueError('请先确认并保存阶段规则。')
        return report(rule,self.source)
