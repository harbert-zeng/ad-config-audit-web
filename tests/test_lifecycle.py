import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lifecycle import Workflow,ONBOARD,REVIEW,gaps
SOURCE=json.loads((Path(__file__).resolve().parents[1]/'dist/data.json').read_text())
class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.w=Workflow(self.tmp.name,SOURCE)
 def decide(self,row,action='接受建议',**extra):
  return self.w.save({'revision':self.w.draft()['revision'],'key':row['key'],'decision':{'action':action,**extra}})
 def approve(self):
  self.w.save({'revision':0,'reviewer':'自动化测试，不是项目审批'})
  for r in self.w.rows:
   if r['required']:self.decide(r)
  return self.w.freeze({'revision':self.w.draft()['revision']})
 def approve_with_country_issue(self):
  self.approve()
  row=next(x for x in self.w.rows if x['kind']=='countries')
  self.decide(row,'修改标准',value=['US'],note='测试产生国家差异')
  return self.w.freeze({'revision':self.w.draft()['revision']})
 def test_enhancements_excluded_even_with_historical_rules(self):
  self.assertFalse(any(x['kind']=='feature' for x in self.w.rows))
  self.assertFalse(any(x['field']=='features' for x in gaps(SOURCE)))
  v=self.approve()
  v['rules'].append({'key':'feature:test','kind':'feature','baseline_source':'CONFIRMED','expected':False})
  self.assertFalse(any(x['kind']=='feature' for x in self.w.evaluate(v,SOURCE)))
  s=copy.deepcopy(SOURCE);s['snapshot_id']='only-feature-change';s['captured_at']='2099-01-01T00:00:00Z'
  for a in s['ads']:a['feature_states']={'test':'ENABLED'}
  r=self.w.daily(s)
  self.assertEqual(r['changes'],[])
  self.assertIn('ai_creative_enhancements',r['excluded_capabilities'])
 def test_before_onboarding_preview_only(self):
  self.assertFalse(self.w.report(True)['official'])
  with self.assertRaises(ValueError):self.w.report()
  with self.assertRaises(ValueError):self.w.freeze({'revision':0})
 def test_onboarding_actions_separate_from_review(self):
  with self.assertRaises(ValueError):self.decide(self.w.rows[0],'已修正待复查')
 def test_incomplete_background_blocks(self):
  self.approve();self.decide(self.w.rows[1],'补充背景')
  with self.assertRaises(ValueError):self.w.freeze({'revision':self.w.draft()['revision']})
 def test_firstday_not_new_changes_and_gaps_preserved(self):
  v=self.approve();r=self.w.report()
  self.assertTrue(r['official']);self.assertEqual(r['changes'],[]);self.assertTrue(r['gaps']);self.assertEqual(r['coverage_status'],'INCOMPLETE')
  self.assertTrue(any(x['baseline_source']=='INHERITED_CURRENT' for x in v['rules']))
  self.assertEqual(self.w.report(),r)
 def test_versions_immutable_and_idempotent(self):
  a=self.approve();self.assertEqual(a,self.w.freeze({'revision':self.w.draft()['revision']}))
  row=next(x for x in self.w.rows if x['kind']=='countries');self.decide(row,'修改标准',value=['US'],note='测试范围')
  b=self.w.freeze({'revision':self.w.draft()['revision']});self.assertEqual(b['parent_version'],a['version']);self.assertEqual(self.w.versions()[0],a)
 def test_exception_and_edits_require_reason(self):
  r=next(x for x in self.w.rows if x['kind']=='countries')
  with self.assertRaises(ValueError):self.decide(r,'修改标准',value=['US'])
  with self.assertRaises(ValueError):self.decide(r,'仅本次例外',note='例外')
 def test_feedback_does_not_claim_fixed(self):
  self.approve_with_country_issue();r=self.w.report();issue=r['issues'][0]
  body={'report_id':r['report_id'],'issue_key':issue['key'],'action':'已修正待复查','reviewer':'测试'}
  self.w.feedback(body);self.assertEqual(self.w.report(),r)
  body['action']='接受建议'
  with self.assertRaises(ValueError):self.w.feedback(body)
 def test_daily_rejects_same_snapshot_and_compares_parent_budget(self):
  self.approve()
  with self.assertRaises(ValueError):self.w.daily(SOURCE)
  s=copy.deepcopy(SOURCE);s['snapshot_id']='test-next';s['captured_at']='2099-01-01T00:00:00Z';s['campaigns'][0]['daily_budget']['value']='999'
  r=self.w.daily(s);self.assertTrue(any(c.get('field')=='daily_budget' for c in r['changes']));self.assertTrue(any(i['kind']=='budget' for i in r['issues']))
 def test_exception_does_not_hide_changed_evidence(self):
  self.approve_with_country_issue();r=self.w.report();issue=r['issues'][0]
  self.w.feedback({'report_id':r['report_id'],'issue_key':issue['key'],'action':'确认例外','reviewer':'测试','note':'测试限期例外','expires_at':'2099-12-31T00:00:00+00:00'})
  checked=self.w.evaluate(self.w.current(),SOURCE)
  self.assertEqual(next(i for i in checked if i['key']==issue['key'])['state'],'例外有效')
  s=copy.deepcopy(SOURCE)
  ad=next(a for a in s['ads'] if a['id']==issue['objects'][0]['id']);ad['countries']=['US']
  checked=self.w.evaluate(self.w.current(),s)
  self.assertEqual(next(i for i in checked if i['key']==issue['key'])['state'],'待处理')
 def test_concurrent_save_rejected(self):
  self.decide(self.w.rows[0])
  with self.assertRaises(ValueError):self.w.save({'revision':0,'reviewer':'stale'})
 def test_paused_parent_excluded(self):
  s=copy.deepcopy(SOURCE);s['campaigns'][0]['effective_status']='PAUSED';w=Workflow(self.tmp.name+'/paused',s)
  ids=set(w.rows[0]['ad_ids']);self.assertFalse(any(a['id'] in ids for a in s['ads'] if a['campaign_id']==s['campaigns'][0]['id']))
if __name__=='__main__':unittest.main()
