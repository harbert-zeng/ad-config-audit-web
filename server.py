"""Loopback-only review app; optional explicit read-only API connection test."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
import argparse, hashlib, json, os, threading
from landing_pages import check_rules,expected_urls
from media_plan_io import MediaPlanStore
from lifecycle import Workflow
from api_connection import Connection
from phase_rules import PhaseRules, terms as phase_terms, match_copy as phase_match_copy

ROOT = Path(__file__).parent
LOCK = threading.Lock()

def rule_issues(source, state):
    results = []
    def add(kind, title, ads):
        results.append({'kind':kind,'title':title,'affected_ad_ids':[a['id'] for a in ads],
                        'affected_ad_names':[a['name'] for a in ads]})
    for key in ['markets','languages']:
        rules = [r for r in state.get(key,[]) if r.get('confirmed')]
        matched = lambda a,r: bool(r.get('pattern','').strip()) and r['pattern'].strip().lower() in a['campaign_name'].lower()
        if rules:
            uncovered=[a for a in source['ads'] if not any(matched(a,r) for r in rules)]
            if uncovered:add('MISSING_RULE',key+' 存在未匹配范围',uncovered)
            conflict=[a for a in source['ads'] if len({r['value'].strip().lower() for r in rules if matched(a,r)})>1]
            if conflict:add('RULE_CONFLICT',key+' 存在冲突',conflict)
        if key=='markets':
            for r in rules:
                allowed=r['value'].upper().replace('，',',').replace(' ',',').split(',')
                bad=[a for a in source['ads'] if matched(a,r) and any(c not in allowed for c in a['countries'])]
                if bad:add('RULE_MISMATCH','国家不符合 '+r['pattern'],bad)
    if state.get('page_mode')=='rules':
        checks=check_rules(source['ads'],state.get('pages',[]))
        for status,title in [('MISSING_RULE','广告没有页面规则'),('UNCONFIRMED_RULE','页面规则尚未确认'),('INVALID_RULE','页面规则的网址格式有误'),('RULE_CONFLICT','广告同时匹配不同页面规则'),('UNREADABLE','广告落地页检查不到'),('URL_MISMATCH','实际落地页不符合已确认规则')]:
            ids={c['ad_id'] for c in checks if c['status']==status}
            if ids:
                add(status,title,[a for a in source['ads'] if a['id'] in ids])
                results[-1]['evidence']=[c for c in checks if c['ad_id'] in ids]
    for key,reason in state.get('material_flags',{}).items():
        group=next((g for g in source['material_groups'] if g['key']==key),None)
        if group:
            add('HUMAN_REVIEW', reason or '素材文案搭配待核验', [a for a in source['ads'] if a['id'] in group['ad_ids']])
    for r in state.get('identity_rules',[]):
        if not r.get('confirmed'):continue
        bad=[a for a in source['ads'] if r['country'] in a['countries'] and a.get('identity',{}).get('facebook_page_id') and a['identity']['facebook_page_id'] not in r.get('allowed_fb_ids',[])]
        if bad:add('IDENTITY_REVIEW',r['country']+' 帖子归属主页不在允许名单；需先核实合作关系',bad)
    for r in state.get('instagram_rules',[]):
        if not r.get('confirmed'):continue
        bad=[a for a in source['ads'] if r['country'] in a['countries'] and a.get('identity',{}).get('instagram_account_id') and a['identity']['instagram_account_id'] not in r.get('allowed_ids',[])]
        if bad:add('IDENTITY_REVIEW',r['country']+' Instagram 账号不在允许名单；需先核实合作关系',bad)
    return results

def atomic_write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    os.replace(tmp, path)

class Store:
    def __init__(self, folder, source_file=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / 'versions').mkdir(exist_ok=True)
        self.source = json.loads(Path(source_file or ROOT / 'dist/data.json').read_text())
        snapshot = self.folder / 'source-snapshot.json'
        if not snapshot.exists(): atomic_write(snapshot, self.source)
        elif json.loads(snapshot.read_text())['snapshot_id'] != self.source['snapshot_id']:
            raise ValueError('当前目录已有另一份数据，请使用新的保存目录。')

    def state(self):
        p = self.folder / 'state.json'
        return json.loads(p.read_text()) if p.exists() else {'revision': 0, 'state': None}

    def save(self, body):
        current = self.state()
        if body.get('revision') != current['revision']: raise ValueError('另一个页面已保存修改，请刷新后继续。')
        state = body.get('state', {})
        if state.get('snapshot_id') != self.source['snapshot_id']: raise ValueError('配置来源不同，请刷新。')
        result = {'revision': current['revision'] + 1, 'state': state, 'saved_at': datetime.now(timezone.utc).isoformat()}
        atomic_write(self.folder / 'state.json', result)
        return result

    def publish(self, revision):
        if self.source.get('status_conflicts',{}).get('unresolved'):
            raise ValueError('Campaign 状态与负责人反馈不一致；先核实投放范围。当前仅保存草稿。')
        saved = self.state()
        if saved['revision'] != revision: raise ValueError('请先保存最新修改。')
        s = saved['state'] or {}
        required = ['scope', 'budget', 'inherit', 'gap_ack', 'page_reviewed']
        if not s.get('reviewer', '').strip() or any(not s.get(k) for k in required):
            raise ValueError('请先填写确认人，并完成范围、预算、首日继承和待补查确认。')
        for field in ['markets', 'languages']:
            if not s.get(field) or any(not r.get('confirmed') or not r.get('pattern', '').strip() or not r.get('value', '').strip() for r in s[field]):
                raise ValueError('市场与语言规则还未确认完整。')
        if s.get('page_mode') not in ['inherit', 'rules']: raise ValueError('请选择页面规则的接入方式。')
        if s.get('page_mode') == 'rules' and (not s.get('pages') or any(not p.get('confirmed') or not p.get('url','').strip() or not p.get('value','').strip() for p in s['pages'])):
            raise ValueError('请确认已填写的页面规则，或选择补齐后继承。')
        if s.get('page_mode')=='rules' and any(None in expected_urls(r) or not expected_urls(r) for r in s['pages']):raise ValueError('页面规则中有无效网址。')
        if s.get('page_mode')=='inherit' and any(g['key'] not in s.get('landing_group_ok',[]) for g in self.source.get('landing_groups',[])):raise ValueError('请先按组确认当前实际页面。')
        identities=self.source.get('identity_summary',{})
        rules=s.get('identity_rules',[])
        known_pages={p['page_id'] for p in identities.get('account_available_pages',[])}
        for group in identities.get('groups',[]):
            selected=[r for r in rules if r.get('country')==group['country']]
            if len(selected)!=1 or not selected[0].get('confirmed') or not selected[0].get('allowed_fb_ids'):
                raise ValueError('请先确认各国家的 Facebook 主页建议。')
            if not set(selected[0]['allowed_fb_ids']).issubset(known_pages):raise ValueError('主页不在本次已识别目录中。')
        ig_known={a['account_id'] for a in identities.get('instagram_accounts',[])}
        for group in identities.get('groups',[]):
            if not group.get('instagram_known'):continue
            selected=[r for r in s.get('instagram_rules',[]) if r.get('country')==group['country']]
            if len(selected)!=1 or not selected[0].get('confirmed') or not selected[0].get('allowed_ids'):
                raise ValueError('请先确认各国家的 Instagram 账号建议。')
            if not set(selected[0]['allowed_ids']).issubset(ig_known):raise ValueError('Instagram 账号不在本次已识别目录中。')
        # This snapshot is known to lack identity, destination and complete creative data.
        # A user acknowledgment can never promote missing evidence to a pass.
        fingerprint_state = {k:v for k,v in s.items() if k not in ['step','saved_at']}
        fingerprint_state['audit_scope'] = 'core-20261118'
        fingerprint = hashlib.sha256(json.dumps(fingerprint_state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        paths = sorted((self.folder / 'versions').glob('*.json'))
        for path in paths:
            old = json.loads(path.read_text())
            if old['fingerprint'] == fingerprint: return old
        number = len(paths) + 1
        v = {'version': f'v0.{number}', 'status': 'PROVISIONAL', 'formal_baseline_published': False,
             'created_at': datetime.now(timezone.utc).isoformat(), 'reviewer': s['reviewer'],
             'account': self.source['account'], 'account_id': self.source['account_id'],
             'snapshot_id': self.source['snapshot_id'], 'source_snapshot_file':'../source-snapshot.json',
             'source_captured_at':self.source['captured_at'], 'review_scope':self.source.get('scope_summary'), 'coverage': self.source['coverage'],
             'unresolved': ([f"{self.source['counts']['ads']-self.source['coverage']['urls']} 条广告落地页检查不到"] if self.source['coverage']['urls']<self.source['counts']['ads'] else []) + [f"Facebook 帖子归属已识别；Instagram 账号已关联 {identities.get('instagram_named_count',0)} / {self.source['counts']['ads']} 条；Partnership 双方完整身份仍待核验",
                            f"{self.source['counts']['ads']-self.source['coverage']['body']} 条广告未取回正文，不能判断完整素材文案搭配", 'UTM 检查不到',
                            '素材画面 / 完整视频语义未自动核验；规则与设置矛盾按待处理保留'],
             'rules_and_confirmations': s, 'fingerprint': fingerprint,
             'excluded_capabilities':['ai_creative_enhancements'],
             'landing_baseline':{a['id']:a['landing_urls'] for a in self.source['ads'] if a.get('landing_urls')} if s.get('page_mode')=='inherit' else None,
             'landing_baseline_basis':'INHERITED_CURRENT' if s.get('page_mode')=='inherit' else 'APPROVED_NAME_RULES',
             'rule_issues': rule_issues(self.source, s),
             'baseline_policy': {
                 'name_matching':'case_insensitive_contains',
                 'landing_page_conditions':'AND',
                 'landing_page_url_comparison':'scheme_host_path_business_query_fragment; ignore_known_tracking_query_and_trailing_slash',
                 'missing_landing_page':'unresolved_never_inherit_empty',
                 'unknown_feature_state':'unknown_not_off',
                 'future_unknown_feature':'out_of_scope',
                 'enhancement_rule_scope':[],
                 'enhancement_coverage':[{k:f[k] for k in ['key','enabled_count','disabled_count','unknown_count']} for f in self.source['features']],
                 'confirmed_pairs':s.get('material_ok',[]),
                 'unconfirmed_pairs':'inherited_observation_only_not_approved',
                 'partnership_partner_scope':'only_verified_partnership_with_approved_brand_identity',
                 'unconfirmed_identity':'unresolved_not_approved',
                 'facebook_identity_basis':'observed_post_owner_page_country_rule_after_human_confirmation',
                 'majority_is_approval':False,
                 'instagram_media_id_is_account_id':False,
                 'instagram_identity_basis':'ads_manager_export_account_id_and_ad_identity_panel_username',
                 'new_unmatched_scope':'requires_new_rule',
             },
             'note':'首日试运行版本；确认规则不等于修改广告。未读到的字段没有继承为已通过。'}
        path = self.folder / 'versions' / f'{number:04d}.json'
        with path.open('x') as f: json.dump(v, f, ensure_ascii=False, indent=2)
        return v

def serve(port=8772, data_dir=None, source_file=None):
    store = Store(data_dir or ROOT / 'local-data', source_file)
    media_store = MediaPlanStore(store.folder)
    workflow = Workflow(store.folder, store.source)
    connection = Connection(store.folder)
    phase_rules = PhaseRules(store.folder, store.source)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT/'dist'), **kwargs)
        def log_message(self, *args): pass
        def output(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def valid_host(self): return self.headers.get('Host') in [f'127.0.0.1:{port}', f'localhost:{port}']
        def do_GET(self):
            if not self.valid_host(): return self.output({'error':'仅限本机访问'},403)
            path = urlparse(self.path).path
            if path == '/data.json': return self.output(store.source)
            if path == '/api/health': return self.output({'status':'ok','mode':'saved_snapshot','account_id':store.source['account_id'],'snapshot_id':store.source['snapshot_id']})
            if path == '/api/phase-rules': return self.output(phase_rules.state())
            if path == '/api/connection': return self.output(connection.view())
            if path == '/api/lifecycle': return self.output(workflow.view())
            if path == '/api/lifecycle/feedback': return self.output(workflow.feedbacks())
            if path == '/api/lifecycle/preview': return self.output(workflow.report(preview=True))
            if path == '/api/state': return self.output(store.state())
            if path == '/api/source-snapshot': return self.output(json.loads((store.folder/'source-snapshot.json').read_text()))
            if path == '/api/media-plan/state': return self.output(media_store.state())
            if path == '/api/versions':
                return self.output([json.loads(p.read_text()) for p in sorted((store.folder/'versions').glob('*.json'))])
            if path.startswith('/api/'): return self.output({'error':'未找到'},404)
            return super().do_GET()
        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.valid_host() or origin not in [None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'] or self.headers.get('X-Local-Review') != '1':
                return self.output({'error':'仅接受本地页面的保存请求'},403)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if size > (24_000_000 if self.path.startswith('/api/media-plan/') else 2_000_000): raise ValueError('内容过大')
                body = json.loads(self.rfile.read(size))
                with LOCK:
                    if self.path == '/api/phase-rules/draft': result = phase_rules.chat(body.get('text'))
                    elif self.path == '/api/phase-rules/confirm': result = phase_rules.confirm(body)
                    elif self.path == '/api/phase-rules/disable': result = phase_rules.disable(body)
                    elif self.path == '/api/phase-rules/check': result = phase_rules.check(body)
                    elif self.path == '/api/phase-rules/test': result = phase_match_copy({'allow':phase_terms(body.get('allow',[])),'deny':phase_terms(body.get('deny',[]))},{'body':body.get('text','')})
                    elif self.path == '/api/connection': result = connection.save(body)
                    elif self.path == '/api/connection/test': result = connection.test()
                    elif self.path == '/api/connection/probe': result = connection.probe(body)
                    elif self.path == '/api/connection/clear': result = connection.clear()
                    elif self.path == '/api/lifecycle/decision': result = workflow.save(body)
                    elif self.path == '/api/lifecycle/freeze': result = workflow.freeze(body)
                    elif self.path == '/api/lifecycle/report': result = workflow.report()
                    elif self.path == '/api/lifecycle/feedback': result = workflow.feedback(body)
                    elif self.path == '/api/lifecycle/daily': result = workflow.daily(json.loads(Path(source_file or ROOT/'dist/data.json').read_text()))
                    elif self.path == '/api/state': result = store.save(body)
                    elif self.path == '/api/versions': result = store.publish(body.get('revision'))
                    elif self.path == '/api/media-plan/import': result = media_store.upload(body)
                    elif self.path == '/api/media-plan/state': result = media_store.save(body)
                    else: return self.output({'error':'未找到'},404)
                self.output(result)
            except (ValueError, TypeError, KeyError, OSError) as e: self.output({'error':str(e)},400)
    print(f'Local onboarding: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8772)
    parser.add_argument('--data-dir')
    parser.add_argument('--source-file', help='Path to the saved account snapshot; defaults to dist/data.json')
    args = parser.parse_args()
    serve(args.port, args.data_dir, args.source_file)
