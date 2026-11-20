import test from 'node:test';
import assert from 'node:assert/strict';
import {buildReport} from '../dist/first-day/model.mjs';
const source={snapshot_id:'s',account_id:'a',ads:[{id:'1',scope_status:'ACTIVE',name:'广告'}]};
const version={snapshot_id:'s',account_id:'a',rule_issues:[{kind:'RULE_MISMATCH',affected_ad_ids:['1']},{kind:'MISSING_RULE',affected_ad_ids:['1']},{kind:'UNREADABLE',affected_ad_ids:['1']}]};
test('separates rule gaps and unavailable evidence from problems',()=>{const r=buildReport(version,source);assert.equal(r.issues.length,1);assert.equal(r.rules.length,1);assert.equal(r.gaps.length,1);});
test('does not mix accounts or snapshots',()=>{assert.throws(()=>buildReport({...version,account_id:'b'},source));assert.throws(()=>buildReport({...version,snapshot_id:'b'},source));});
test('rejects unresolved IDs and inactive evidence',()=>{assert.throws(()=>buildReport(version,{...source,ads:[]}));assert.throws(()=>buildReport(version,{...source,ads:[{id:'1',scope_status:'PAUSED'}]}));});
test('counts affected ads once across issues',()=>{const r=buildReport({...version,rule_issues:[version.rule_issues[0],version.rule_issues[0]]},source);assert.equal(r.affected,1);});
