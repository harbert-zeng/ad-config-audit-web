const $=id=>document.getElementById(id);
const fields=['mode','version','creative_id','url','auth','secret'];
function toggle(){$('meta').hidden=$('mode').value!=='meta';$('custom').hidden=$('mode').value!=='custom';}
$('mode').onchange=toggle;
async function api(path,body){const r=await fetch('/api/connection'+path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Local-Review':'1'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
function status(d){$('credential').textContent=d.credential_loaded?'密钥已载入本地服务内存；不会回显，重启后需要重新填写。':'密钥未载入。只在本地服务内存保留，重启后需重新填写。';}
async function run(test=false){document.querySelectorAll('button').forEach(b=>b.disabled=true);$('result').textContent=test?'正在保存并读取接口，最长约 20 秒…':'正在保存…';try{const body=Object.fromEntries(fields.map(k=>[k,$(k).value]));const d=await api('',body);$('secret').value='';status(d);if(test){const r=await api('/test',{});$('result').textContent=r.message+(r.features?.length?'\n\n'+r.features.map(f=>`${f.field}：${f.state==='OPT_IN'?'开启':f.state==='OPT_OUT'?'明确关闭':'检查不到明确状态'} (${f.state})`).join('\n'):'')+(r.scope?'\n\n'+r.scope:'');}else $('result').textContent='连接配置已保存。可以继续点击“保存并测试读取”。';}catch(e){$('result').textContent=e.message;}finally{document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
$('form').onsubmit=e=>{e.preventDefault();run();};$('test').onclick=()=>run(true);
$('clear').onclick=async()=>{try{status(await api('/clear',{}));$('secret').value='';$('result').textContent='已清除本次服务保存的密钥。';}catch(e){$('result').textContent=e.message;}};
api('').then(d=>{for(const k of fields.filter(k=>k!=='secret'))if(d.config[k]!==undefined)$(k).value=d.config[k];status(d);toggle();if(!d.credential_loaded)$('result').textContent='当前服务尚未载入密钥。请填写后点“保存连接配置”；旧的连接成功结果不代表当前仍连接。';}).catch(e=>$('result').textContent=e.message);
let wasLoaded=false;
async function refreshConnection(){try{const d=await api('');status(d);if(!d.credential_loaded&&wasLoaded)$('result').textContent='本地服务已重启或密钥已清除。请重新填写并保存密钥，旧测试结果已失效。';wasLoaded=d.credential_loaded;}catch(e){$('credential').textContent='本地服务暂时无法连接；此前成功结果不代表当前连接正常。';}}
setInterval(refreshConnection,5000);
window.addEventListener('focus',refreshConnection);
