const {chromium:pw}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const browser=await pw.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || undefined,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'],headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const root=path.resolve(__dirname,'../web');
 await page.route('https://radar.test/**',route=>{const name=new URL(route.request().url()).pathname.slice(1)||'index.html';return route.fulfill({contentType:name.endsWith('css')?'text/css':name.endsWith('js')?'text/javascript':'text/html',body:fs.readFileSync(root+'/'+name)});});
 await page.addInitScript(()=>{
  Element.prototype.replaceChildren=undefined;
  window.testState={last:{state:'运行中',at:1800000000},cash_usdc:'1000',enabled:true,counts:{news:2,topics:0,attempts:0,open_positions:0},news:[{title:'<img src=x onerror=alert(1)>',url:'javascript:alert(1)',origin:'news.test',published:1800000000}],topics:[],positions:[],attempts:[],health:{'feeds.bbci.co.uk':{state:'可连接'}}};
  window.Native={config:()=>JSON.stringify({url:'https://server.test',hasToken:false}),request:(p,b)=>JSON.stringify(p==='/api/state'?window.testState:p.startsWith('/api/check')?{title:'部分项目尚未验证',notice:'不能保证安全',level:'unknown',checks:[{title:'增发权限',state:'unknown',detail:'未知',source:'安全接口'}]}:{enabled:JSON.parse(b).enabled}),configure:()=>'{"ok":true}'};
 });
 await page.goto('https://radar.test/');
 if(!await page.locator('#settings').isVisible())throw Error('first use must show settings');
 await page.fill('#token','test-only-token-0000000000000000000000');await page.click('#save');await page.waitForSelector('#radar:visible');
 if(await page.locator('#news-count').textContent()!=='2')throw Error('missing real server counter '+await page.locator('#news-count').textContent()+' status='+await page.locator('#status').innerText()+' errors='+errors.join(','));
 if(await page.locator('#news article').count()!==1)throw Error('news hidden without qualified topics');
 if(await page.locator('#token').inputValue())throw Error('token remains visible');
 if(await page.locator('img,svg,script:not([src])').count())throw Error('XSS');
 if(await page.locator('#news a').count())throw Error('unsafe news URL');
 if(await page.locator('nav button').count()!==4)throw Error('not four pages');
 for(const width of [320,390,440]){
  await page.setViewportSize({width,height:740});
  for(const p of ['shield','trade','settings','radar']){
   await page.click(`[data-page="${p}"]`);
   if(!await page.locator('#'+p).isVisible())throw Error('page hidden');
   const valid=await page.evaluate(()=>{const nav=document.querySelector('nav').getBoundingClientRect();return nav.bottom<=innerHeight+1&&[...document.querySelectorAll('nav button')].every(b=>{const r=b.getBoundingClientRect();return r.width>=48&&r.height>=48&&r.left>=0&&r.right<=innerWidth+1&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2).closest('button')===b;});});
   if(!valid)throw Error('navigation covered or undersized '+width+' '+p);
   if(!await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))throw Error('horizontal overflow');
  }
 }
 await page.evaluate(()=>{window.testState.topics=[{entity:'<img src=x onerror=alert(1)>',created:1800000000,status:'热点已确认',evidence:[{origin:'news.test',title:'<script>bad()</script>',url:'javascript:alert(1)'}]}];});
 await page.click('#refresh');
 if(await page.locator('#topics a,img,script:not([src])').count())throw Error('unsafe topic output');
 await page.click('[data-page="shield"]');await page.fill('#address','So11111111111111111111111111111111111111112');await page.click('#check');await page.waitForSelector('#report .unknown');await page.fill('#address','different');
 if(await page.locator('#report article').count())throw Error('stale report '+await page.evaluate(()=>JSON.stringify({value:document.getElementById('address').value,html:document.getElementById('report').innerHTML})));
 await page.evaluate(()=>{delete window.testState.counts;delete window.testState.news;});
 await page.click('[data-page="radar"]');await page.click('#refresh');
 if(await page.locator('#news-count').textContent()!=='—'||!(await page.locator('#news').textContent()).includes('需要更新'))throw Error('old server shows fabricated zero');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS 320/390/440px: navigation hit targets, four pages, save-to-radar, real counters/news without topics, old server fallback, old WebView, XSS, unknown risk, stale report clearing');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
