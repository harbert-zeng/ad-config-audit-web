"""Local, read-only audit workflow. Decisions never mutate an advertising account."""
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter
from decimal import Decimal, InvalidOperation
import json, hashlib, os, copy

ONBOARD = ['接受建议', '修改标准', '仅本次例外', '不适用', '补充背景']
REVIEW = ['待处理', '已修正待复查', '暂不处理', '确认例外']
CONTRACT = 'meta-google-lifecycle-2026-11-18-core'
EXCLUDED_CAPABILITIES = ['ai_creative_enhancements']

def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)); os.replace(tmp, path)
def fresh(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f: json.dump(value, f, ensure_ascii=False, indent=2)
def read(path, default): return json.loads(path.read_text()) if path.exists() else default

def active(source):
    campaigns = {c['id']:c for c in source['campaigns']}
    adsets = {s['id']:s for s in source['adsets']}
    return [a for a in source['ads'] if a.get('scope_status') == 'ACTIVE'
            and campaigns.get(a['campaign_id'],{}).get('effective_status') == 'ACTIVE'
            and adsets.get(a['adset_id'],{}).get('effective_status') == 'ACTIVE']

def candidates(source):
    ads = active(source); rows = []
    def add(key, title, kind, members, proposed, required=True, priority='P0', choices=None, note=''):
        rows.append(dict(key=key,title=title,kind=kind,ad_ids=[a['id'] for a in members],proposed=proposed,
                         required=required,priority=priority,choices=choices or [],note=note,
                         scope_label='本次对象范围；不自动覆盖未来新广告'))
    add('scope','账户与开启对象范围','scope',ads,'仅检查 Campaign、Ad Set、Ad 三层开启的广告')
    markets=defaultdict(list)
    for a in ads: markets[tuple(sorted(a.get('countries',[])))].append(a)
    for countries,members in sorted(markets.items()):
        code=','.join(countries)
        add('market:'+code,'投放国家 · '+(code or '检查不到'),'countries',members,list(countries),note='国家集合按实际配置分组；名称不是地区证据。')
        lang={'DE':'德语','FR':'法语','US':'英语','GB':'英语'}.get(code)
        if lang:add('language:'+code,'广告语言 · '+code,'language',members,lang,note='按市场提出建议，正文语言仍需 AI／人工核对，不计为程序检查通过。')
        for field,label,namefield in [('facebook_page_id','Facebook 主页','facebook_page_name'),('instagram_account_id','Instagram 账号','instagram_username')]:
            vals=Counter(a.get('identity',{}).get(field) for a in members if a.get('identity',{}).get(field))
            if not vals:continue
            options=[{'value':v,'label':next((a['identity'].get(namefield) for a in members if a.get('identity',{}).get(field)==v and a['identity'].get(namefield)), '名称检查不到'),'count':n} for v,n in vals.most_common()]
            add(field+':'+code,label+' · '+code,field,members,[options[0]['value']],choices=options,note='多数值只是建议；其他身份不会随主组确认自动获准。合作双方未核实的保留待核验。')
    for level in ['campaigns','adsets']:
        parent='campaign_id' if level=='campaigns' else 'adset_id'
        for obj in source[level]:
            members=[a for a in ads if a[parent]==obj['id']]
            if not members:continue
            for field in ['daily_budget','lifetime_budget']:
                if obj.get(field) is not None:
                    value=obj[field]; value=value if isinstance(value,dict) else {'value':str(value),'unit':source['currency']}
                    add(level+':'+obj['id']+':'+field,('Campaign' if level=='campaigns' else 'Ad Set')+' 预算 · '+obj['name'],'budget',members,value,note='当前金额建议；确认后任何变化进入调整。')
                    rows[-1].update(object_type=level,object_id=obj['id'],field=field)
    landing=defaultdict(list)
    for a in ads:
        if a.get('landing_urls'):landing[tuple(sorted(a['landing_urls']))].append(a)
    for urls,members in landing.items():
        add('page:'+digest(urls)[:16],'落地页 · '+urls[0],'landing',members,list(urls),required=False,note='未操作时仅按首日实际页面继承；不代表未来广告自动获准，也不检查网页安全。')
    add('inherit','人群、版位、出价、归因与已读到的广告内容','inherit',ads,'首日当前值暂定继承',False,'P1/P2',note='无需逐项确认；仅用于以后比对，不表示素材质量通过。')
    add('schedule','排期与活动到期','schedule',ads,'已读取排期留档；促销到期背景检查不到',False,note='没有负责人明确的活动截止时间，不按 BF 等名称标签判断已过期。')
    return rows

def gaps(source):
    ads=active(source); total=len(ads)
    result=[{'field':'Partnership','message':'合作双方完整身份检查不到，不能确认合作广告身份合规。'},
            {'field':'language','message':'广告正文语言与素材含义需 AI／人工核对，本流程未自动完成。'},
            {'field':'schedule','message':'活动到期背景未完整提供；未配置明确期限的促销到期检查不执行。'}]
    for field,label,present in [('landing','落地页',sum(bool(a.get('landing_urls')) for a in ads)),('body','正文',sum(a.get('body') is not None for a in ads))]:
        if present<total:result.append({'field':field,'message':f'{label}检查不到 {total-present} / {total} 条。'})
    for field,label in [('facebook_page_id','Facebook 主页'),('instagram_account_id','Instagram 账号')]:
        count=sum(not a.get('identity',{}).get(field) for a in ads)
        if count:result.append({'field':field,'message':f'{label}检查不到 {count} / {total} 条。'})
    if not source.get('coverage',{}).get('utm'):result.append({'field':'utm','message':'UTM 检查不到。'})
    return result

def parse_date(value):
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
        if not d.tzinfo:raise ValueError()
        return d
    except (ValueError,TypeError,AttributeError):raise ValueError('例外到期时间须带时区。')

def normalize_value(row, value):
    kind=row['kind']
    if kind=='feature':
        if not isinstance(value,bool):raise ValueError('请选择允许或不允许。')
    elif kind=='budget':
        try:
            if not Decimal(str(value['value'])).is_finite() or Decimal(str(value['value']))<0:raise ValueError()
            if value.get('unit')!=row['proposed']['unit']:raise ValueError()
        except (InvalidOperation,KeyError,TypeError,ValueError):raise ValueError('预算金额无效，币种必须保持与账户一致。')
    elif kind in ['countries','landing','facebook_page_id','instagram_account_id']:
        if not isinstance(value,list) or not value or not all(isinstance(x,str) and x.strip() for x in value):raise ValueError('请填写至少一个允许值。')
        if kind=='countries' and any(len(x)!=2 or not x.isalpha() or x!=x.upper() for x in value):raise ValueError('国家请用两位大写代码，例如 DE。')
        if kind=='landing':
            from urllib.parse import urlparse
            if any(urlparse(x).scheme not in ['http','https'] or not urlparse(x).netloc for x in value):raise ValueError('请填写完整的 http 或 https 页面网址。')
        if kind.endswith('_id') and not set(value).issubset({o['value'] for o in row['choices']}):raise ValueError('身份不在已读取目录中，请补充背景。')
    elif not isinstance(value,str) or not value.strip():raise ValueError('请填写标准。')
    return value

def checked_decision(row, decision):
    action=decision.get('action')
    if action not in ONBOARD:raise ValueError('接入动作无效。')
    note=decision.get('note','').strip()
    if action=='修改标准' and row['kind'] in ['scope','inherit','schedule']:raise ValueError('这一项不能直接改成自由文本标准，请选择补充背景后整理新候选。')
    if action in ['修改标准','仅本次例外'] and not note:raise ValueError('修改标准或例外时请填写说明。')
    if action=='不适用' and row['kind']=='scope':raise ValueError('本次账户与开启对象范围必须确认，不能标为不适用。')
    if action=='仅本次例外' and parse_date(decision.get('expires_at'))<=datetime.now(timezone.utc):raise ValueError('例外到期时间必须在未来。')
    value=row['proposed'] if action!='修改标准' else normalize_value(row,decision.get('value'))
    return {'action':action,'note':note,'value':value,'expires_at':decision.get('expires_at') if action=='仅本次例外' else None,'recorded_at':now()}

def readiness(rows, state, source):
    missing=[]
    if not state.get('reviewer','').strip():missing.append('填写确认人')
    if source.get('status_conflicts',{}).get('unresolved'):missing.append('核实对象状态冲突')
    for row in rows:
        d=state.get('decisions',{}).get(row['key'])
        if row['kind']=='countries' and not row['proposed']:missing.append(row['title']+'缺少实际国家配置')
        if (row['required'] and not d) or (d and d['action']=='补充背景'):missing.append(row['title'])
    return missing

class Workflow:
    def __init__(self, folder, source):
        self.root=Path(folder)/'workflow-v2';self.source=copy.deepcopy(source);self.rows=candidates(source)
        self.root.mkdir(parents=True,exist_ok=True)
        snap=self.root/'snapshots'/f"{source['snapshot_id']}.json"
        if not snap.exists():fresh(snap,source)
    def draft(self):
        return read(self.root/'draft.json',{'revision':0,'snapshot_id':self.source['snapshot_id'],'reviewer':'','decisions':{}})
    def versions(self):return [read(p,{}) for p in sorted((self.root/'versions').glob('*.json'))]
    def current(self):
        values=self.versions();return values[-1] if values else None
    def view(self):
        draft=self.draft()
        return {'contract':CONTRACT,'source':self.source,'candidates':self.rows,'draft':draft,'gaps':gaps(self.source),'missing':readiness(self.rows,draft,self.source),'versions':self.versions()}
    def save(self, body):
        draft=self.draft()
        if body.get('revision')!=draft['revision']:raise ValueError('其他页面已修改，请刷新后继续。')
        if draft['snapshot_id']!=self.source['snapshot_id']:raise ValueError('配置快照已变化，请重新生成接入候选。')
        if 'reviewer' in body:draft['reviewer']=str(body['reviewer']).strip()
        if 'key' in body:
            row=next((r for r in self.rows if r['key']==body['key']),None)
            if not row:raise ValueError('候选不存在。')
            if body.get('decision') is None:draft['decisions'].pop(row['key'],None)
            else:draft['decisions'][row['key']]=checked_decision(row,body['decision'])
        draft.update(revision=draft['revision']+1,saved_at=now());write(self.root/'draft.json',draft);return self.view()
    def freeze(self, body):
        d=self.draft()
        if body.get('revision')!=d['revision']:raise ValueError('请先保存最新决定。')
        if d['snapshot_id']!=self.source['snapshot_id']:raise ValueError('配置快照已变化，不能保存旧候选。')
        missing=readiness(self.rows,d,self.source)
        if missing:raise ValueError('接入未完成：'+'；'.join(missing))
        fingerprint=digest({'draft':d,'contract':CONTRACT})
        for old in self.versions():
            if old['fingerprint']==fingerprint:return old
        number=len(self.versions())+1
        v={'version':f'v1.{number-1}','parent_version':self.current()['version'] if self.current() else None,'contract':CONTRACT,
           'onboarding_complete':True,'status':'FROZEN','created_at':now(),'account_id':self.source['account_id'],'excluded_capabilities':EXCLUDED_CAPABILITIES,
           'snapshot_id':self.source['snapshot_id'],'reviewer':d['reviewer'],'fingerprint':fingerprint,
           'scope_ad_ids':[a['id'] for a in active(self.source)],'snapshot_evidence':f"snapshots/{self.source['snapshot_id']}.json",'scope_summary':self.source.get('scope_summary'), 'field_coverage':self.source.get('coverage'), 'coverage_gaps':gaps(self.source),'rules':[]}
        for row in self.rows:
            dec=d['decisions'].get(row['key']); origin='INHERITED_CURRENT' if not dec else {'仅本次例外':'TEMP_EXCEPTION','不适用':'EXCLUDED'}.get(dec['action'],'CONFIRMED_P0' if row['priority']=='P0' else 'CONFIRMED')
            v['rules'].append({**row,'decision':dec,'expected':dec['value'] if dec else row['proposed'],'baseline_source':origin})
        fresh(self.root/'versions'/f'{number:04d}.json',v)
        return v
    def evaluate(self, version, source):
        ads=active(source);byid={a['id']:a for a in ads};issues=[]
        for r in version['rules']:
            if r['kind']=='feature':continue  # Historical rules remain stored, outside current scope.
            if r['baseline_source']=='EXCLUDED':continue
            if r['baseline_source']=='TEMP_EXCEPTION' and parse_date(r['decision']['expires_at'])>datetime.now(timezone.utc):continue
            members=[byid[i] for i in r['ad_ids'] if i in byid]; bad=[]; kind=r['kind']; value=r['expected']
            for a in members:
                actual=None; mismatch=False
                if kind=='countries' and a.get('countries'):
                    actual=a['countries'];mismatch=not set(actual).issubset(value)
                elif kind in ['facebook_page_id','instagram_account_id']:
                    actual=a.get('identity',{}).get(kind);mismatch=bool(actual and actual not in value)
                elif kind=='landing' and a.get('landing_urls'):
                    from landing_pages import canonical_url
                    actual=a['landing_urls'];mismatch=not {canonical_url(u) for u in actual}.issubset({canonical_url(u) for u in value})
                elif kind=='budget':
                    obj=next((o for o in source[r['object_type']] if o['id']==r['object_id']),{})
                    actual=obj.get(r['field']);mismatch=actual is not None and actual!=value
                if mismatch:bad.append({'id':a['id'],'name':a['name'],'campaign_name':a['campaign_name'],'adset_name':a['adset_name'],'actual':actual})
            if bad:issues.append({'key':r['key'],'title':r['title'],'kind':kind,'priority':r['priority'],'expected':value,'objects':bad,'state':'待处理','identity_review':kind.endswith('_id')})
        new=[a for a in ads if a['id'] not in version['scope_ad_ids']]
        if new:issues.append({'key':'missing-rule:'+digest([a['id'] for a in new])[:12],'title':'新广告未纳入已确认对象规则','kind':'MISSING_RULE','priority':'待补规则','objects':[{'id':a['id'],'name':a['name'],'campaign_name':a['campaign_name'],'adset_name':a['adset_name']} for a in new],'state':'待处理'})
        events=self.feedbacks()
        for issue in issues:
            issue['signature']=digest({k:issue.get(k) for k in ['key','kind','expected','objects']})
            prior=next((e for e in reversed(events) if e.get('issue_signature')==issue['signature']),None)
            if prior:
                issue['state']=prior['action'];issue['last_feedback_at']=prior['confirmed_at']
                if prior['action']=='确认例外':issue['state']='例外有效' if parse_date(prior.get('expires_at'))>datetime.now(timezone.utc) else '例外到期，待处理'
        return issues
    def report(self, preview=False):
        v=self.current()
        if not v or not v.get('onboarding_complete'):
            if preview:return {'stage':'CANDIDATE_PREVIEW','official':False,'message':'接入未完成，仅展示候选标准，不是正式报告，也不统计新增广告。','issues':[],'gaps':gaps(self.source)}
            raise ValueError('请先完成接入并保存首日标准；当前只能查看候选预览。')
        report_id=f"first-day-{v['version']}-core20261118"
        path=self.root/'reports'/f"{report_id}.json"
        if path.exists():return read(path,{})
        source=read(self.root/'snapshots'/f"{v['snapshot_id']}.json",None)
        if not source:raise ValueError('冻结快照缺失，不能生成报告。')
        r={'report_id':report_id,'stage':'FIRST_DAY','official':True,'baseline_version':v['version'],'contract':CONTRACT,'excluded_capabilities':EXCLUDED_CAPABILITIES,
           'account_id':v['account_id'],'snapshot_id':v['snapshot_id'],'captured_at':source['captured_at'], 'created_at':now(),
           'changes':[],'change_summary':'首次核查没有上期对照；现有对象不记为新增。','issues':self.evaluate(v,source),'gaps':gaps(source),
           'coverage_status':'INCOMPLETE' if gaps(source) else 'COMPLETE'}
        fresh(path,r);return r
    def feedback(self, body):
        report=read(self.root/'reports'/f"{body.get('report_id','')}.json",None) if str(body.get('report_id','')).replace('-','').replace('.','').isalnum() else None
        if not report:raise ValueError('报告不存在。')
        issue=next((i for i in report['issues'] if i['key']==body.get('issue_key')),None)
        if not issue or body.get('action') not in REVIEW:raise ValueError('请选择本报告有效排查动作。')
        if not body.get('reviewer','').strip():raise ValueError('请填写确认人。')
        if body['action']=='确认例外':
            if not body.get('note','').strip():raise ValueError('确认例外时请填写说明。')
            if parse_date(body.get('expires_at'))<=datetime.now(timezone.utc):raise ValueError('例外到期时间必须在未来。')
        events=read(self.root/'feedback.json',[])
        event={k:body.get(k) for k in ['report_id','issue_key','action','reviewer','note','expires_at']}
        event.update(issue_signature=issue.get('signature'),confirmed_at=now(),snapshot_id=report['snapshot_id'],baseline_version=report['baseline_version'],ad_ids=[a['id'] for a in issue['objects']])
        events.append(event);write(self.root/'feedback.json',events);return event
    def feedbacks(self):return read(self.root/'feedback.json',[])
    def daily(self, source):
        v=self.current()
        if not v:raise ValueError('先完成接入并保存首日标准。')
        history=read(self.root/'daily-history.json',[])
        previous=read(self.root/'snapshots'/f"{history[-1]['snapshot_id'] if history else v['snapshot_id']}.json",None)
        if source['account_id']!=v['account_id']:raise ValueError('账户不一致。')
        if source['snapshot_id']==previous['snapshot_id']:raise ValueError('还没有新的配置快照；不能把同一批数据当作今天的变化。')
        if source['captured_at']<=previous['captured_at']:raise ValueError('新快照的采集时间必须晚于上次。')
        if source.get('status_conflicts',{}).get('unresolved'):raise ValueError('对象状态有冲突，不能生成日常正式报告。')
        old={a['id']:a for a in active(previous)};new={a['id']:a for a in active(source)};changes=[]
        fields=['name','campaign_id','adset_id','countries','landing_urls','body','title','description','cta']
        for key in old.keys()|new.keys():
            if key not in old:changes.append({'name':new[key]['name'],'change':'新增开启对象'})
            elif key not in new:changes.append({'name':old[key]['name'],'change':'离开开启范围；状态需核实，不能仅凭缺失判删除'})
            else:
                for field in fields:
                    if old[key].get(field)!=new[key].get(field):changes.append({'name':new[key]['name'],'field':field,'before':old[key].get(field),'after':new[key].get(field)})
        for level in ['campaigns','adsets']:
            before={o['id']:o for o in previous[level]};after={o['id']:o for o in source[level]}
            refs={a['campaign_id' if level=='campaigns' else 'adset_id'] for a in list(old.values())+list(new.values())}
            for oid in (before.keys() & after.keys()) & refs:
                for field in ['name','status','effective_status','daily_budget','lifetime_budget','start_time','end_time','targeting','bid_strategy','optimization_goal','attribution_spec']:
                    if before[oid].get(field)!=after[oid].get(field):changes.append({'name':after[oid]['name'],'level':level,'field':field,'before':before[oid].get(field),'after':after[oid].get(field)})
        r={'report_id':'daily-'+digest({'source':source,'contract':CONTRACT})[:16],'contract':CONTRACT,'excluded_capabilities':EXCLUDED_CAPABILITIES,'stage':'DAILY','official':True,'baseline_version':v['version'],'snapshot_id':source['snapshot_id'],'previous_snapshot_id':previous['snapshot_id'],'captured_at':source['captured_at'],'previous_captured_at':previous['captured_at'],'created_at':now(),'account_id':v['account_id'],'changes':changes,'issues':self.evaluate(v,source),'gaps':gaps(source),'coverage_status':'INCOMPLETE','change_summary':'上次实际配置 → 本次实际配置；同时对照已确认标准。'}
        path=self.root/'snapshots'/f"{source['snapshot_id']}.json"
        if not path.exists():fresh(path,source)
        fresh(self.root/'reports'/f"{r['report_id']}.json",r);history.append({'report_id':r['report_id'],'snapshot_id':source['snapshot_id']});write(self.root/'daily-history.json',history);return r
