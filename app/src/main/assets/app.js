'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const e = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const CHAINS = {bnb:{label:'币安链（BNB）',name:'合约地址 · 0x…',placeholder:'粘贴以 0x 开头的合约地址',explorer:'https://bscscan.com/token/'},sol:{label:'索拉纳链（SOL）',name:'代币铸币地址',placeholder:'粘贴索拉纳代币铸币地址',explorer:'https://solscan.io/token/'},eth:{label:'以太坊链（ETH）',name:'合约地址 · 0x…',placeholder:'粘贴以 0x 开头的合约地址',explorer:'https://etherscan.io/token/'}};
  const ST = {high:{text:'高危',symbol:'!',cls:'high'},warn:{text:'警惕',symbol:'!',cls:'warn'},ok:{text:'当前未见异常',symbol:'✓',cls:'ok'},unknown:{text:'未知 / 未验证',symbol:'?',cls:'unknown'}};
  const GROUP_ORDER = ['交易风险','权限风险','市场风险','合约信息'];
  let chain='bnb', aborter=null, lastResult=null;
  const addr=$('address');
  function cancelPending(){
    if(aborter){aborter.abort();aborter=null;}
    $('progress').hidden=true;
    $('scan').disabled=false;
    $('scan').querySelector('.button-label').textContent='开始安全检测';
  }
  function setChain(c){
    if(!CHAINS[c])return;
    cancelPending();
    chain=c;
    document.querySelectorAll('.chain').forEach(b=>{const active=b.dataset.chain===c;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});
    $('typeLabel').textContent=CHAINS[c].name;addr.placeholder=CHAINS[c].placeholder;
    $('sourceSecond').textContent=c==='sol'?'RugCheck':'Honeypot.is';
    $('progress').hidden=true;$('results').hidden=true;$('inputError').hidden=true;$('inputWrap').classList.remove('invalid');
    lastResult=null;$('scan').disabled=false;$('scan').querySelector('.button-label').textContent='开始安全检测';
  }
  document.querySelectorAll('.chain').forEach(b=>b.addEventListener('click',()=>setChain(b.dataset.chain)));
  $('clear').addEventListener('click',()=>{cancelPending();addr.value='';$('results').hidden=true;$('inputError').hidden=true;$('inputWrap').classList.remove('invalid');addr.focus();});
  $('paste').addEventListener('click',async()=>{
    try{ const s=await navigator.clipboard.readText();cancelPending();addr.value=s.trim();$('results').hidden=true;addr.focus(); }
    catch{addr.focus();error('无法读取剪贴板，请长按输入框粘贴。');}
  });
  addr.addEventListener('input',()=>{cancelPending();$('inputError').hidden=true;$('inputWrap').classList.remove('invalid');$('results').hidden=true;});
  function error(msg){$('inputError').textContent=msg;$('inputError').hidden=false;$('inputWrap').classList.add('invalid');}
  function valid(a){
    if(chain!=='sol') return /^0x[a-fA-F0-9]{40}$/.test(a);
    if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(a))return false;
    // Base58-looking strings may decode to 31 or 33 bytes; reject them early.
    const alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
    // Check decoded 32-byte length without BigInt (older Android WebViews).
    const digits=[0];
    for(const c of a){
      let carry=alphabet.indexOf(c);
      for(let i=0;i<digits.length;i++){
        carry+=digits[i]*58;
        digits[i]=carry&255;
        carry=Math.floor(carry/256);
      }
      while(carry){digits.push(carry&255);carry=Math.floor(carry/256);}
    }
    const leading=a.match(/^1*/)[0].length;
    return digits.length+(digits.length===1 && digits[0]===0 ? -1 : 0)+leading===32;
  }
  function mini(a){return a.length>26?a.slice(0,12)+'…'+a.slice(-9):a;}
  function getHistory(){try{return JSON.parse(localStorage.getItem('cs-history')||'[]').filter(x=>CHAINS[x.chain]&&typeof x.address==='string').slice(0,6);}catch{return [];}}
  function setHistory(c,a){const current=getHistory().filter(x=>!(x.chain===c&&(c==='sol'?x.address===a:x.address.toLowerCase()===a.toLowerCase())));current.unshift({chain:c,address:a});try{localStorage.setItem('cs-history',JSON.stringify(current.slice(0,6)));}catch{}renderHistory();}
  function renderHistory(){const data=getHistory();$('recentSection').hidden=!data.length;const list=$('historyList');list.textContent='';data.forEach(item=>{const b=document.createElement('button');b.className='recent-item';const name=document.createElement('b');name.textContent=item.chain.toUpperCase();b.append(name,document.createTextNode(mini(item.address)));b.addEventListener('click',()=>{setChain(item.chain);addr.value=item.address;scan();});list.append(b);});}
  $('clearHistory').addEventListener('click',()=>{try{localStorage.removeItem('cs-history');}catch{}renderHistory();});
  function render(report){
    const st=ST[report.level]||ST.unknown;
    const n=report.token||{};
    const providers=Object.entries(report.sources||{}).map(([k,v])=>`<div class="provider-line"><span class="provider-name">${e(k)}</span><span class="provider-state ${v.status==='ok'?'good':'bad'}"><span class="status-dot">${v.status==='ok'?'●':'!'}</span>${v.status==='ok'?'已获取数据':e(v.detail||'不可用')}</span></div>`).join('');
    const groups=GROUP_ORDER.map(group=>{
      const rows=(report.checks||[]).filter(item=>item.group===group);
      if(!rows.length)return '';
      return `<div class="group"><div class="group-title">${e(group)} <small>${rows.length} 项</small></div>${rows.map(x=>{const s=ST[x.state]||ST.unknown;return `<div class="finding"><div class="finding-dot ${s.cls}">${s.symbol}</div><div class="finding-content"><div class="finding-top"><span class="finding-title">${e(x.title)}</span><span class="finding-status ${s.cls}">${e(s.text)}</span></div><p class="finding-description">${e(x.detail)}</p><div class="finding-source">数据：${e(x.source)}</div></div></div>`;}).join('')}</div>`;
    }).join('');
    const c=report.counts||{};
    const href=CHAINS[report.chain].explorer+encodeURIComponent(report.address);
    const linkTarget=location.hostname==='appassets.androidplatform.net'?'':'target="_blank"';
    const rug=report.chain==='sol'?`<a class="action-btn" href="https://rugcheck.xyz/tokens/${encodeURIComponent(report.address)}" ${linkTarget} rel="noopener noreferrer">打开 RugCheck ↗</a>`:'';
    const rugtext=report.token && report.token.rugScore!=null ? ` · RugCheck 分数：${e(report.token.rugScore)}（接口返回）` : '';
    $('results').innerHTML=`<div class="result-head"><div class="result-top"><span class="result-kicker">风险报告 / ${e(CHAINS[report.chain].label)}</span><span class="report-status ${st.cls}">${e(st.text)}</span></div><h2>${e(report.title)}</h2><div class="result-meta"><strong>${e(n.name||'未知代币')}</strong>${n.symbol?' · '+e(n.symbol):''}${rugtext}</div><div class="address-line"><div class="address-box" title="${e(report.address)}">${e(report.address)}</div><button class="copy-btn" id="copyAddress" type="button">复制</button></div><div class="stats"><div class="stat high"><b>${c.high||0}</b><span>高危</span></div><div class="stat warn"><b>${c.warn||0}</b><span>警惕</span></div><div class="stat ok"><b>${c.ok||0}</b><span>未见异常</span></div><div class="stat unknown"><b>${c.unknown||0}</b><span>未知</span></div></div><p class="data-note">查询时间：${e(new Date(report.time).toLocaleString('zh-CN'))}${report.cached?' · 45 秒短缓存':''}<br>${e(report.notice||'')} </p></div><div class="section-heading"><h2>数据来源</h2><span>逐源显示结果，不隐藏失败</span></div><div class="provider-card">${providers}</div><div class="section-heading"><h2>检测明细</h2><span>风险与未知分开显示</span></div>${groups}<div class="actions"><a class="action-btn" href="${e(href)}" ${linkTarget} rel="noopener noreferrer">在区块浏览器查看 ↗</a>${rug}<button class="action-btn" id="copyReport" type="button">复制检测报告</button></div>`;
    $('results').hidden=false;
    $('copyAddress').addEventListener('click',()=>copyText(report.address,$('copyAddress')));
    $('copyReport').addEventListener('click',()=>{
      const lines=[`【链盾安全初筛】${CHAINS[report.chain].label}`,report.address,`结论：${report.title}`,`时间：${report.time}`,`风险：高危 ${c.high||0} / 警惕 ${c.warn||0} / 未知 ${c.unknown||0}`];
      for(const x of report.checks||[])lines.push(`[${ST[x.state]?.text||'未知'}] ${x.title}：${x.detail}（${x.source}）`);
      lines.push(report.notice||'不构成审计或投资建议');copyText(lines.join('\n'),$('copyReport'));
    });
  }
  async function copyText(txt,btn){
    let success=false;
    try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(txt);success=true;}}catch{}
    if(!success){
      const box=document.createElement('textarea');box.value=txt;box.setAttribute('readonly','');
      box.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.append(box);
      box.focus();box.select();try{success=document.execCommand('copy');}catch{}box.remove();
    }
    const old=btn.textContent;btn.textContent=success?'已复制 ✓':'复制未授权';
    setTimeout(()=>btn.textContent=old,1300);
  }
  async function scan(){
    const address=addr.value.trim();
    if(!valid(address)){error(chain==='sol'?'请输入有效的索拉纳代币铸币地址（32–44 位地址字符）':'请输入有效的合约地址（0x 开头，后接 40 位十六进制字符）');return;}
    $('inputError').hidden=true;$('inputWrap').classList.remove('invalid');
    if(aborter)aborter.abort();aborter=new AbortController();const ctl=aborter;
    let timedOut=false;
    const timeoutId=setTimeout(()=>{timedOut=true;ctl.abort();},25000);
    $('progress').hidden=false;$('results').hidden=true;
    $('scan').disabled=true;$('scan').querySelector('.button-label').textContent='正在检测中…';
    try{
      const req=`/api/check?chain=${encodeURIComponent(chain)}&address=${encodeURIComponent(address)}`;
      const res=await fetch(req,{signal:ctl.signal,cache:'no-store'});
      const info=await res.json();
      if(!res.ok)throw new Error(info.error||'查询失败，请重试');
      if(ctl!==aborter)return;
      if(info.chain!==chain || (chain==='sol'?info.address!==address:typeof info.address!=='string'||info.address.toLowerCase()!==address.toLowerCase()))throw new Error('返回结果与查询地址不匹配，未展示风险结论');
      lastResult=info;render(info);setHistory(chain,info.address);
      $('results').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(ex){
      if(ctl!==aborter)return; // Switching chain or starting another scan invalidates this response.
      if(ex.name==='AbortError' && !timedOut)return;
      if(ex.name==='AbortError' && timedOut)ex=new Error('检测超时，请稍后重试。服务端或第三方接口可能暂时繁忙。');
      $('results').hidden=false;
      $('results').innerHTML=`<div class="error-card"><strong>查询未完成</strong><p>${e(/[\u3400-\u9fff]/.test(ex.message||'') ? ex.message : '网络连接失败，请检查网络后重试')}</p></div>`;
    }finally{
      clearTimeout(timeoutId);
      if(ctl===aborter){$('progress').hidden=true;$('scan').disabled=false;$('scan').querySelector('.button-label').textContent='重新检测';aborter=null;}
    }
  }
  $('scan').addEventListener('click',scan);
  addr.addEventListener('keydown',ev=>{if(ev.key==='Enter'&&(ev.ctrlKey||ev.metaKey)){ev.preventDefault();scan();}});
  renderHistory();
  // Native Android package loads local verified assets; no service worker is necessary.
})();
