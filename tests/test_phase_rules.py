import json,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase_rules import PhaseRules,draft,validate,match_copy,report

class PhaseRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source={'account':'Test Account','account_id':'a','snapshot_id':'snapshot','captured_at':'2026-11-04T00:00:00Z','timezone':'Europe/Berlin','ads':[
         {'id':'one','scope_status':'ACTIVE','campaign_name':'DE_BF','adset_name':'Visitors','name':'same-name','body':'Early Black Friday — LAST CHANCE!'},
         {'id':'two','scope_status':'ACTIVE','campaign_name':'FR_BF','adset_name':'Visitors','name':'same-name','body':'Last chance!'},
         {'id':'paused','scope_status':'PAUSED','campaign_name':'DE_BF','adset_name':'Visitors','name':'old','body':'Last chance!'},
         {'id':'missing','scope_status':'ACTIVE','campaign_name':'DE_BF','adset_name':'Visitors','name':'unknown','body':None},
         {'id':'okay','scope_status':'ACTIVE','campaign_name':'DE_BF','adset_name':'Visitors','name':'safe','body':'Early Black Friday'}]}
        self.rule={'phase':'BF预热','original':'用户规则','start':'2026-11-18','end':'2026-11-25','scope_field':'campaign_name','scope_value':'DE_','reviewer':'测试','allow':['Early Black Friday'],'deny':['Last chance']}
        self.store=PhaseRules(self.tmp.name,self.source)
    def test_background_survives_reload_without_becoming_rule(self):
        self.store.chat('本阶段重点是预热，具体折扣稍后给出。')
        loaded=PhaseRules(self.tmp.name,self.source).state()
        self.assertEqual(loaded['rules'],[])
        self.assertEqual(loaded['conversation'][0]['draft']['original'],'本阶段重点是预热，具体折扣稍后给出。')
    def test_draft_is_not_approval(self):
        d=draft('阶段：黑五预热；允许使用“Early Black Friday”；禁止使用“Last chance”和“Ends tonight”。')
        self.assertEqual(d['allow'],['Early Black Friday']);self.assertEqual(d['deny'],['Last chance','Ends tonight'])
        self.assertEqual(self.store.state()['rules'],[])
    def test_ambiguous_mixed_clause_preserved_not_guessed(self):
        d=draft('允许“A”，禁止“B”');self.assertEqual(d['allow'],[]);self.assertEqual(d['deny'],[]);self.assertTrue(d['notes'])
        self.assertEqual(draft('不允许使用“ABC”')['deny'],['ABC'])
    def test_forbidden_wins_and_missing_is_not_pass(self):
        self.assertEqual(match_copy(self.rule,{'body':'early black friday LAST CHANCE'})['status'],'FORBIDDEN')
        self.assertEqual(match_copy(self.rule,{})['status'],'NO_COPY')
    def test_scope_and_parent_names_and_paused(self):
        r=report(self.rule,self.source,datetime(2026,11,18,tzinfo=timezone.utc))
        self.assertEqual(r['scanned'],3);self.assertEqual(r['forbidden_count'],1)
        self.assertEqual([x['ad_id'] for x in r['objects'] if x['hits']],['one']);self.assertFalse(r['meta_writes']);self.assertEqual(r['mode'],'SAVED_SNAPSHOT_PREVIEW')
    def test_timezone_expiry_boundaries(self):
        self.assertTrue(report(self.rule,self.source,datetime(2026,11,17,23,30,tzinfo=timezone.utc))['active_today'])
        self.assertFalse(report(self.rule,self.source,datetime(2026,11,25,23,30,tzinfo=timezone.utc))['active_today'])
    def test_validation_requires_dates_scope_and_no_conflict(self):
        for patch in [{'end':''},{'end':'2026-11-01'},{'scope_field':''},{'scope_value':''},{'deny':['EARLY BLACK FRIDAY']}]:
            with self.assertRaises(ValueError):validate({**self.rule,**patch})
    def test_persistence_revisions_and_disable(self):
        s=self.store.confirm({'revision':0,'rule':self.rule});self.assertEqual(s['revision'],1)
        self.assertEqual(PhaseRules(self.tmp.name,self.source).state()['rules'][0]['phase'],'BF预热')
        with self.assertRaises(ValueError):self.store.confirm({'revision':0,'rule':self.rule})
        r=self.store.check({'rule_id':s['rules'][0]['id']});self.assertEqual(r['forbidden_count'],1)
        s=self.store.disable({'revision':1,'rule_id':s['rules'][0]['id']});self.assertTrue(s['rules'][0]['disabled'])
        self.assertTrue((self.store.folder/'version-0001.json').exists())
    def test_duplicate_and_conflicting_rules_rejected(self):
        self.store.confirm({'revision':0,'rule':self.rule})
        with self.assertRaises(ValueError):self.store.confirm({'revision':1,'rule':self.rule})
        with self.assertRaises(ValueError):self.store.confirm({'revision':1,'rule':{**self.rule,'phase':'另一个阶段','allow':['Last chance'],'deny':[]}})

if __name__=='__main__':unittest.main()
