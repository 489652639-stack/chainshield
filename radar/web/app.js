'use strict';
if(!Element.prototype.replaceChildren)Element.prototype.replaceChildren=function(){while(this.firstChild)this.removeChild(this.firstChild);};
let state=null,busy=false;
const $=id=>document.getElementById(id);
const labels={high:'高危',warn:'警惕',unknown:'未知',ok:'当前未发现该风险'};
const sourceNames={'feeds.bbci.co.uk':'BBC国际新闻','www.bbc.com':'BBC国际新闻','www.bbc.co.uk':'BBC国际新闻','www.theguardian.com':'卫报国际新闻','api.frankfurter.app':'人民币参考汇率','api.dexscreener.com':'代币搜索','api.jup.ag':'Jupiter只读报价'};
function sourceName(s){return sourceNames[s]||s;}
function message(s){$('message').textContent=s;$('message').style.display='block';setTimeout(()=>{$('message').style.display='none';},6000);}
function card(parent,title,detail,style=''){const a=document.createElement('article');a.className=style;const b=document.createElement('strong');b.textContent=title;a.append(b);const p=document.createElement('p');p.textContent=detail;a.append(p);parent.append(a);return a;}
function time(t){return t?new Date(t*1000).toLocaleString('zh-CN'):'等待扫描';}
function newsLink(parent,url){try{const u=new URL(url);if(u.protocol==='https:'){const a=document.createElement('a');a.textContent='查看新闻原文';a.href=u.href;a.rel='noopener noreferrer';parent.append(a);}}catch{}}
async function api(path,body){let data;if(window.Native){data=JSON.parse(window.Native.request(path,body?JSON.stringify(body):''));}else{const r=await fetch(path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+sessionStorage.getItem('radar-token'),'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});data=await r.json();}if(data.error)throw Error(data.error);return data;}
function show(page){document.querySelectorAll('.page').forEach(s=>s.hidden=s.id!==page);document.querySelectorAll('nav button').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});document.querySelector('h1').textContent={radar:'热点雷达',shield:'链盾检查',trade:'自动交易',settings:'系统设置'}[page];window.scrollTo(0,0);}
async function refresh(){
    if(busy)return false;busy=true;
    try{
        state=await api('/api/state');
        $('status').textContent='服务器已连接 · '+state.last.state+' · '+time(state.last.at);
        if(state.last.error)$('status').textContent+=' · '+state.last.error;
        $('cash').textContent=Number(state.cash_usdc).toFixed(2);
        $('toggle').disabled=false;
        $('toggle').textContent=state.enabled?'暂停模拟入场':'继续模拟入场';
        $('trade-state').textContent=state.enabled?'自动模拟入场已开启 · 不使用真实资金':'模拟入场已暂停 · 已有持仓仍继续监控';
        const counts=state.counts||{};
        for(const [id,key]of [['news-count','news'],['topic-count','topics'],['attempt-count','attempts'],['position-count','open_positions']])$(id).textContent=Number.isInteger(counts[key])?String(counts[key]):'—';
        $('radar-note').textContent=state.last.error?'本轮数据接口异常，等待恢复。下方保留已记录数据。':!state.enabled?'模拟入场已暂停；新闻扫描与持仓监控继续运行。':state.topics.length?'已发现热点，后台继续匹配新币并检查风险。':'正在采集新闻，暂未出现符合条件的热点。没有热点时不会强行买入。';
        $('topics').replaceChildren();
        for(const t of state.topics){const a=card($('topics'),t.entity,'发现于 '+time(t.created)+' · '+t.status);for(const e of t.evidence){const p=document.createElement('p');p.textContent=sourceName(e.origin)+' · '+e.title;a.append(p);newsLink(a,e.url);}}
        if(!state.topics.length)card($('topics'),'暂未发现达标热点','新闻仍会显示在下方。只有新闻先触发热点，才会继续匹配新币。');
        $('news').replaceChildren();
        for(const n of state.news||[]){const a=card($('news'),n.title,sourceName(n.origin)+' · '+time(n.published));newsLink(a,n.url);}
        if(!state.news)card($('news'),'服务器需要更新','当前后台尚未提供新闻明细，其他功能仍可使用。');
        else if(!state.news.length)card($('news'),'暂无近期新闻记录','等待下一轮采集；不会用示例新闻填充。');
        $('positions').replaceChildren();
        for(const p of state.positions)card($('positions'),p.symbol||p.mint,(p.closed?'已模拟退出 · '+p.reason+' · 净损益 '+Number(p.pnl).toFixed(4)+' USDC':'模拟持仓 · 成本 '+p.cost+' USDC')+' · '+time(p.opened)+' · '+p.evidence.warnings);
        if(!state.positions.length)card($('positions'),'暂无模拟持仓','热点、安全检查与双向报价通过后，服务器自动模拟入场。');
        $('attempts').replaceChildren();
        for(const a of state.attempts)card($('attempts'),a.status,a.mint+' · '+a.detail);
        if(!state.attempts.length)card($('attempts'),'暂无代币筛选记录','出现达标热点并匹配到新交易池后，这里会显示风险拦截或模拟入场结果。');
        $('health').replaceChildren();
        for(const [k,v]of Object.entries(state.health))card($('health'),sourceName(k),v.state+(v.date?' · '+v.date:'')+(v.rate?' · '+v.rate:''));
        return true;
    }catch(e){message(e.message);$('status').textContent='连接或刷新失败 · '+e.message;return false;}finally{busy=false;}
}
document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>show(b.dataset.page)));
$('refresh').onclick=refresh;
$('save').onclick=async()=>{
    $('save').disabled=true;
    try{
        if(window.Native){const r=JSON.parse(window.Native.configure($('server').value,$('token').value));if(r.error)throw Error(r.error);}
        else{const u=$('server').value;if(u&&new URL(u).origin!==location.origin)throw Error('浏览器请打开目标服务器网页后连接');if($('token').value)sessionStorage.setItem('radar-token',$('token').value);if((sessionStorage.getItem('radar-token')||'').length<32)throw Error('访问密钥至少32位');}
        $('token').value='';
        if(await refresh()){show('radar');message('服务器已连接，已进入热点雷达');}
    }catch(e){message(e.message);}finally{$('save').disabled=false;}
};
$('address').addEventListener('input',()=>$('report').replaceChildren());
$('chain').addEventListener('change',()=>$('report').replaceChildren());
$('check').onclick=async()=>{const chain=$('chain').value,address=$('address').value.trim();$('report').replaceChildren();$('check').disabled=true;try{const r=await api('/api/check?'+new URLSearchParams({chain,address}));if(chain!==$('chain').value||address!==$('address').value.trim()){message('输入已改变，请重新检查');return;}card($('report'),r.title,r.notice,r.level);for(const c of r.checks)card($('report'),c.title+' · '+labels[c.state],c.detail+' · '+c.source,c.state);}catch(e){message(e.message);}finally{$('check').disabled=false;}};
$('toggle').disabled=true;
$('toggle').onclick=async()=>{if(!state)return;try{await api('/api/entry',{enabled:!state.enabled});await refresh();}catch(e){message(e.message);}};
if(window.Native){try{const c=JSON.parse(window.Native.config());$('server').value=c.url;if(c.hasToken)refresh();else show('settings');}catch(e){message('读取连接设置失败');}}else{$('server').value=location.origin;if(sessionStorage.getItem('radar-token'))refresh();else show('settings');}
setInterval(()=>{if(state&&!document.hidden)refresh();},15000);
