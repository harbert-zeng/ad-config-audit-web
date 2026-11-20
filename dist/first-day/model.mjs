export function buildReport(version, source) {
  if (!version || version.snapshot_id !== source.snapshot_id || version.account_id !== source.account_id) throw Error('标准版与配置来源不一致，不能生成报告。');
  const map = new Map(source.ads.map(a => [a.id, a]));
  const buckets = {issues: [], rules: [], gaps: []};
  for (const item of version.rule_issues || []) {
    const ads = [...new Set(item.affected_ad_ids || [])].map(id => map.get(id));
    if (ads.some(a => !a || a.scope_status !== 'ACTIVE')) throw Error('报告明细与保存的在投范围不一致，请核对数据。');
    const row = {...item, ads};
    const bucket = item.kind === 'UNREADABLE' ? 'gaps' : ['MISSING_RULE','UNCONFIRMED_RULE','INVALID_RULE','RULE_CONFLICT'].includes(item.kind) ? 'rules' : 'issues';
    buckets[bucket].push(row);
  }
  return {version:version.version, account:version.account, created_at:version.created_at, captured_at:version.source_captured_at, reviewer:version.reviewer, ...buckets, limitations:version.unresolved || [], total:source.ads.length, affected:new Set(buckets.issues.flatMap(x=>x.ads.map(a=>a.id))).size};
}
