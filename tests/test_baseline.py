import unittest, tempfile, sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store, rule_issues

class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.store.source['status_conflicts']={'unresolved':False} # Unit fixture for the normal approval path
        self.s={'snapshot_id':self.store.source['snapshot_id'],'reviewer':'界面测试（非项目审批）',
                'scope':True,'budget':True,'inherit':True,'features':True,'gap_ack':True,'page_reviewed':True,
                'markets':[{'pattern':'de_demo_','value':'DE','confirmed':True},{'pattern':'fr_demo_','value':'FR','confirmed':True}],
                'languages':[{'pattern':'de_demo_','value':'德语','confirmed':True},{'pattern':'fr_demo_','value':'法语','confirmed':True}],
                'allowed_features':[f['key'] for f in self.store.source['features'] if f['count']],
                'feature_rule_keys':[f['key'] for f in self.store.source['features'] if f.get('checkable')],
                'page_mode':'inherit','pages':[]}
        self.s['identity_rules']=[{'country':g['country'],'allowed_fb_ids':[g['recommended_page_id']],'confirmed':True} for g in self.store.source['identity_summary']['groups']]
        self.s['instagram_rules']=[{'country':g['country'],'allowed_ids':[g['recommended_instagram_id']],'confirmed':True} for g in self.store.source['identity_summary']['groups'] if g.get('instagram_known')]
        self.s['landing_group_ok']=[g['key'] for g in self.store.source.get('landing_groups',[])]
    def save(self):return self.store.save({'revision':self.store.state()['revision'],'state':self.s})
    def test_status_dispute_blocks_baseline(self):
        self.store.source['status_conflicts']={'unresolved':True};self.save()
        with self.assertRaises(ValueError):self.store.publish(1)
    def test_identity_suggestion_needs_confirmation(self):
        self.s['identity_rules'][0]['confirmed']=False;self.save()
        with self.assertRaises(ValueError):self.store.publish(1)
    def test_instagram_suggestion_needs_confirmation(self):
        if not self.s['instagram_rules']:self.skipTest('Instagram not yet imported')
        self.s['instagram_rules'][0]['confirmed']=False;self.save()
        with self.assertRaises(ValueError):self.store.publish(1)
    def test_instagram_rule_mismatch_is_review_not_automatic_error(self):
        if not self.s['instagram_rules']:self.skipTest('Instagram not yet imported')
        self.s['instagram_rules'][0]['allowed_ids']=[]
        result=[x for x in rule_issues(self.store.source,self.s) if 'Instagram' in x['title']]
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['kind'],'IDENTITY_REVIEW')
        self.assertEqual(len(result[0]['affected_ad_ids']),2)

    def test_incomplete_cannot_publish(self):
        self.s['gap_ack']=False;self.save()
        with self.assertRaises(ValueError):self.store.publish(1)
    def test_provisional_not_false_pass(self):
        self.save();v=self.store.publish(1)
        self.assertEqual(v['status'],'PROVISIONAL');self.assertFalse(v['formal_baseline_published'])
        self.assertEqual(v['coverage']['urls'],self.store.source['coverage']['urls']);self.assertTrue(v['unresolved']);self.assertEqual(v['rule_issues'],[])
        self.assertEqual(len(v['landing_baseline']),self.store.source['coverage']['urls'])
    def test_versions_immutable_and_idempotent(self):
        self.save();first=self.store.publish(1);self.assertEqual(self.store.publish(1),first)
        self.s['reviewer']='第二位测试人';self.save();second=self.store.publish(2)
        self.assertEqual(second['version'],'v0.2')
        self.assertEqual(json.loads((self.store.folder/'versions/0001.json').read_text()),first)
    def test_conflicting_save_rejected(self):
        self.save()
        with self.assertRaises(ValueError):self.store.save({'revision':0,'state':self.s})
    def test_country_conflict_retained_enhancements_excluded(self):
        self.s['markets'][0]['value']='US';self.s['allowed_features']=[];self.save()
        v=self.store.publish(1)
        self.assertEqual(len(v['rule_issues']),1)
        self.assertIn('ai_creative_enhancements',v['excluded_capabilities'])
        self.assertTrue(all(x['affected_ad_ids'] for x in v['rule_issues']))
    def test_new_rule_needs_confirmation(self):
        self.s['markets'][0]['confirmed']=False;self.save()
        with self.assertRaises(ValueError):self.store.publish(1)
    def test_enhancement_confirmation_no_longer_required(self):
        self.s['features']=False
        self.s['feature_rule_keys']=[]
        self.s['allowed_features']=[]
        self.assertFalse(any(x['kind']=='RULE_MISMATCH' for x in rule_issues(self.store.source,self.s)))
        self.save()
        self.assertEqual(self.store.publish(1)['rule_issues'],[])
    def test_unconfirmed_landing_group_blocks_baseline(self):
        self.s['landing_group_ok']=[];self.save()
        with self.assertRaises(ValueError):self.store.publish(1)

if __name__=='__main__':unittest.main()
