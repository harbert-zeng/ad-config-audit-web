export const DAY='2026-11-05';
export const product='https://example.com/eu-de/products/demo-product';
export const smb='https://example.com/eu-de/kleinunternehmen';
export const sale='https://example.com/eu-de/black-friday-sale';
const make=(n,start,campaign,adset,url)=>Array.from({length:n},(_,i)=>({id:`demo-${start+i}`,name:`E1_${adset}_${['工作室','礼物定制','全彩打印','桌面场景'][i%4]}_${String(i+1).padStart(2,'0')}`,campaign,adset,url}));
export const ads=[...make(8,1,'DE_E1_BF_TEST','Creative_Test',sale),...make(4,9,'DE_E1_LAUNCH','SMB_New',smb),...make(8,13,'DE_E1_RMKT','Visitors_30D',sale),...make(4,21,'DE_E1_ALWAYS_ON','Interest_DIY',product),...make(24,25,'DE_E1_ALWAYS_ON','Broad',product)];
ads[24]={...ads[24],adset:'Country_Test_FR',name:'E1_Country_Test_FR_工作室_01'};
export const cases=[
 {id:'new',kind:'change',tag:'新增广告',title:'E1 新素材测试，上线 12 条广告',desc:'2 个 Ad Set；其中 4 条新品广告还需要补落地页规则。',before:'未上线',after:'12 条新广告已开启',ids:ads.slice(0,12).map(a=>a.id),priority:'P1'},
 {id:'page',kind:'change',tag:'落地页调整',title:'8 条广告：E1 产品页改为黑五活动页',desc:'DE_E1_RMKT · Visitors_30D',before:'E1 产品介绍页',after:'黑五活动页',before_url:product,after_url:sale,ids:ads.slice(12,20).map(a=>a.id),priority:'P0'},
 {id:'copy',kind:'change',tag:'文案调整',title:'常规广告，更新活动结束时间',desc:'DE_E1_ALWAYS_ON · Interest_DIY',before:'Angebot bis 15. November',after:'Angebot bis 30. November',ids:ads.slice(20,24).map(a=>a.id),priority:'P1'},
 {id:'market',level:'adset',entity_name:'Country_Test_FR',campaign_name:'DE_E1_ALWAYS_ON',kind:'issue',tag:'投放地区',title:'投放国家不符：应投德国，实际投法国',desc:'Country_Test_FR · 下属 1 条广告；已确认的市场为德国。',before:'允许：德国（DE）',after:'Ad Set 实际：法国（FR）',ids:[ads[24].id],priority:'P0'},
 {id:'rule',kind:'rule',tag:'缺少落地页规则',title:'4 条新品广告：小企业落地页尚无匹配规则',desc:'DE_E1_LAUNCH · SMB_New · 4 条广告',before:'当前规则未覆盖',after:'实际使用：小企业页面',ids:ads.slice(8,12).map(a=>a.id),priority:'P0'},
 {id:'old',kind:'history',tag:'此前未处理',title:'视频处理已开启，但未在允许清单中',desc:'昨天已提醒；今天没有变化。按同一问题保留，不重复新增。',before:'规则：不允许开启',after:'实际：已开启',ids:ads.slice(26,29).map(a=>a.id),priority:'P2'}
];
export const fresh=()=>({schema:1,feedback:{},standards:{},rules:[],events:[],run:1,ruleVersion:1,corrections:{}});
export function matched(rule,ad){return (rule.scope!=='batch'||rule.ids.includes(ad.id))&&ad[rule.field].toLowerCase().includes(rule.pattern.trim().toLowerCase());}
export function validURL(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol);}catch{return false;}}
function normalized(value){const u=new URL(value);for(const k of [...u.searchParams.keys()])if(/^utm_/i.test(k)||['fbclid','gclid'].includes(k))u.searchParams.delete(k);u.searchParams.sort();return u.toString().replace(/\/$/,'');}
export function pageStatus(state,ad){
 const rules=state.rules.filter(r=>matched(r,ad)&&(!r.until||r.until>=DAY));
 if(!rules.length)return 'MISSING_RULE';
 if(new Set(rules.map(r=>normalized(r.url))).size>1)return 'RULE_CONFLICT';
 return rules.every(r=>normalized(r.url)===normalized(ad.url))?'MATCH':'URL_MISMATCH';
}
export function previewRule(rule,state){
 const errors=[];if(!rule.pattern.trim())errors.push('请填写名称条件。');if(!validURL(rule.url))errors.push('请填写完整的 http 或 https 网址。');
 if(rule.until&&rule.until<DAY)errors.push('结束日期不能早于演示报告日期 2026-11-05。');
 const targets=rule.pattern.trim()?ads.filter(a=>matched(rule,a)):[];
 if(!targets.length)errors.push('条件没有匹配到广告，请调整后再确认。');
 const overlaps=targets.filter(a=>state.rules.some(r=>r.version!==rule.replaceVersion&&matched(r,a)&&(!r.until||r.until>=DAY)&&validURL(rule.url)&&normalized(rule.url)!==normalized(r.url)));
 // Demonstration of an already-approved, independent mapping.
 const baselineOverlap=targets.filter(a=>a.campaign==='DE_E1_RMKT'&&validURL(rule.url)&&normalized(rule.url)!==normalized(state.standards?.page?.[a.id]?.value||product));
 const conflicts=[...new Set([...overlaps,...baselineOverlap].map(a=>a.id))];
 if(conflicts.length)errors.push(`与已确认页面规则冲突，涉及 ${conflicts.length} 条广告。请缩小范围或单独处理旧规则。`);
 const different=validURL(rule.url)?targets.filter(a=>normalized(a.url)!==normalized(rule.url)):[];
 return {errors,targets,different,conflicts,extra:targets.filter(a=>!cases.find(c=>c.id==='rule').ids.includes(a.id))};
}
export function entries(state,c){return c.ids.map(id=>({ad:ads.find(a=>a.id===id),status:c.id==='rule'?pageStatus(state,ads.find(a=>a.id===id)):state.feedback[c.id]?.[id]?.status||'pending'}));}
export const isOpen=status=>!['accepted','exception','closed','MATCH'].includes(status);
export function remaining(state,c){return entries(state,c).filter(x=>isOpen(x.status)).length;}
export function log(state,text){state.events.unshift({at:new Date().toISOString(),text});}
export function feedback(state,c,ids,status,note=''){
 if(!ids.length||ids.some(id=>!c.ids.includes(id)))throw Error('请先选择本次要处理的广告。');
 if(c.level==='adset'&&(new Set(ids).size!==c.ids.length))throw Error('广告组设置需要整组确认，不按下属广告拆分处理。');
 if(status==='exception'&&!note.trim())throw Error('请写一句本次允许的原因，方便后续追溯。');
 state.feedback[c.id]||={};for(const id of ids)state.feedback[c.id][id]={status,note,level:c.level||'ad',entity_name:c.entity_name||null,at:new Date().toISOString()};
 if(status==='accepted'){state.standards||={};state.standards[c.id]||={};for(const id of ids)state.standards[c.id][id]={value:c.id==='page'?sale:c.after,note,source:'DEMO_USER_APPROVAL'};}
 log(state,`${c.level==='adset'?`广告组 ${c.entity_name}（所属 Campaign：${c.campaign_name}）`:c.title}：${c.level==='adset'?`1 个广告组，影响 ${ids.length} 条广告`:ids.length+' 条'}，${{accepted:'正常，已记录为演示标准',exception:'仅本次允许，通用规则不变',needs_fix:'需要修正，等待复查',help:'需要协助判断'}[status]}`);
}
export function addRule(state,rule){
 const p=previewRule(rule,state);if(p.errors.length)throw Error(p.errors.join(' '));
 if(rule.replaceVersion){const old=state.rules.find(r=>r.version===rule.replaceVersion);if(!old)throw Error('待修改的规则不存在，请重新打开。');state.ruleHistory||=[];state.ruleHistory.push({...old});state.rules=state.rules.filter(r=>r.version!==rule.replaceVersion);}
 state.rules.push({...rule,version:++state.ruleVersion});
 log(state,`规则 v${state.ruleVersion}：${rule.field} 名称包含 ${rule.pattern}；${p.targets.length} 条匹配，${p.different.length} 条页面仍不符。`);
 return p;
}
export const correctionValues={market:['FR','DE'],page:[sale,product],copy:['Angebot bis 30. November','Angebot bis 15. November'],new:['ACTIVE','PAUSED'],old:['ENABLED','DISABLED']};
export function rerun(state){
 state.run++;let closed=0;
 for(const c of cases.filter(c=>correctionValues[c.id]))for(const id of c.ids)if(state.feedback[c.id]?.[id]?.status==='needs_fix'&&state.corrections?.[c.id]===correctionValues[c.id][1]){state.feedback[c.id][id].status='closed';closed++;}
 log(state,`第 ${state.run} 次演示检查：复用原问题记录；${closed} 项修正通过复查。`);return closed;
}
