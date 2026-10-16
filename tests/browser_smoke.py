import asyncio
import json
import sys
import os
from pathlib import Path
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parent.parent/'app/src/main/assets'
ADDRESS='0x55d398326f99059fF775485246999027B3197955'
SOL='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
REPORT={'chain':'bnb','address':ADDRESS.lower(),'time':'2026-10-15T10:00:00+00:00','level':'high','title':'发现高危风险','counts':{'high':1,'warn':0,'ok':0,'unknown':1},'token':{'name':'<img src=x onerror=alert(1)>','symbol':'EVIL'},'sources':{'GoPlus':{'status':'ok','detail':'loaded'}, 'Honeypot.is':{'status':'unavailable','detail':'HTTP 429'}},'checks':[{'id':'honeypot','group':'交易风险','title':'蜜罐 / 无法卖出','state':'high','detail':'检测出蜜罐风险','source':'GoPlus'},{'id':'unknown','group':'权限风险','title':'代理','state':'unknown','detail':'<script>alert(1)</script>','source':'Honeypot.is'}], 'notice':'模拟数据，不做交易'}

async def main():
    async with async_playwright() as p:
        chromium_path=Path(os.environ.get('CHROMIUM_EXECUTABLE','/usr/bin/chromium'))
        opts={'headless':True,'args':['--no-sandbox']}
        if chromium_path.exists(): opts['executable_path']=str(chromium_path)
        browser=await p.chromium.launch(**opts)
        context=await browser.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True)
        page=await context.new_page()
        errors=[]
        page.on('pageerror',lambda ex:errors.append(str(ex)))
        html=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/app.css">','').replace('<script src="/app.js" defer></script>','').replace('<script src="/maintenance.js" defer></script>','')
        await page.route('https://chainshield.test/',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
        await page.goto('https://chainshield.test/',wait_until='domcontentloaded')
        await page.add_style_tag(content=(ROOT/'app.css').read_text())
        await page.evaluate('''(report)=> {
          window.__state = {report, mode:'ok', pending:[]};
          window.fetch = (url, opts) => {
            const s=window.__state;
            if(s.mode==='deferred') return new Promise((resolve,reject)=>{
              const onabort=()=>reject(new DOMException('Aborted','AbortError'));
              if(opts?.signal?.aborted) return onabort();
              opts?.signal?.addEventListener('abort', onabort,{once:true});
              s.pending.push(()=>{opts?.signal?.removeEventListener('abort',onabort);resolve(new Response(JSON.stringify(s.report), {status:200,headers:{'content-type':'application/json'}}));});
            });
            if(s.mode==='429')return Promise.resolve(new Response(JSON.stringify({error:'查询过于频繁，请稍后再试'}),{status:429,headers:{'content-type':'application/json'}}));
            return Promise.resolve(new Response(JSON.stringify(s.report),{status:200,headers:{'content-type':'application/json'}}));
          };
        }''',REPORT)
        # Android 11's stock WebView 83 lacks this newer DOM method.
        await page.evaluate('Element.prototype.replaceChildren = undefined')
        await page.add_script_tag(content=(ROOT/'app.js').read_text())
        await page.locator('#address').fill(ADDRESS)
        await page.locator('#scan').click()
        await page.locator('#copyReport').wait_for()
        assert await page.locator('.report-status.high').count()==1
        assert await page.locator('.provider-state.bad').count()==1
        assert await page.locator('img[src=x]').count()==0
        assert await page.locator('.finding-description script').count()==0
        assert 'onerror' in await page.locator('.result-meta').inner_text()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        print('PASS mobile result/XSS/provider/overflow')
        await page.locator('.chain[data-chain=sol]').click()
        assert await page.locator('#results').is_hidden()
        assert await page.locator('#sourceSecond').inner_text()=='RugCheck'
        await page.locator('#address').fill('1'*42)
        await page.locator('#scan').click()
        assert not await page.locator('#inputError').is_hidden()
        await page.locator('#address').fill(SOL)
        assert await page.locator('#inputError').is_hidden()
        print('PASS chain changes/SOL base58 validation')
        await page.locator('.chain[data-chain=bnb]').click()
        await page.evaluate("window.__state.mode='429'")
        await page.locator('#address').fill(ADDRESS)
        await page.locator('#scan').click()
        await page.locator('.error-card').wait_for()
        assert '频繁' in await page.locator('.error-card').inner_text()
        print('PASS 429 displayed')
        await page.evaluate("window.__state.mode='deferred'")
        await page.locator('#scan').click()
        await page.locator('#progress').wait_for(state='visible')
        await page.locator('#address').fill(ADDRESS[:-1]+'1')
        assert await page.locator('#progress').is_hidden()
        await page.evaluate('window.__state.pending.forEach(fn=>fn())')
        await asyncio.sleep(.1)
        assert await page.locator('#results').is_hidden()
        print('PASS input change while pending cancels outdated result')
        await page.evaluate("window.__state.mode='ok';window.__state.report.chain='eth'")
        await page.locator('.chain[data-chain=eth]').click()
        await page.locator('#address').fill(ADDRESS)
        await page.locator('#scan').click()
        await page.locator('#copyReport').wait_for()
        assert '以太坊链' in await page.locator('.result-kicker').inner_text()
        print('PASS ETH tab and query result')
        await page.evaluate("window.__state.report.chain='sol'")
        second_sol=SOL[:3]+SOL[3].swapcase()+SOL[4:]
        for mint in (SOL,second_sol):
            await page.locator('.chain[data-chain=sol]').click()
            await page.evaluate('(a)=>window.__state.report.address=a',mint)
            await page.locator('#address').fill(mint)
            await page.locator('#scan').click()
            await page.locator('#copyReport').wait_for()
        history=await page.evaluate("JSON.parse(localStorage.getItem('cs-history')).filter(x=>x.chain==='sol')")
        assert len(history)==2 and {x['address'] for x in history}=={SOL,second_sol}
        await page.locator('#clearHistory').click()
        assert await page.locator('#recentSection').is_hidden()
        print('PASS case-sensitive SOL history and clear history')
        await page.locator('.chain[data-chain=bnb]').click()
        await page.evaluate("window.__state.report.chain='eth'")
        await page.locator('#address').fill(ADDRESS)
        await page.locator('#scan').click()
        await page.locator('.error-card').wait_for()
        assert '不匹配' in await page.locator('.error-card').inner_text()
        assert await page.locator('.result-head').count()==0
        print('PASS mismatched chain/address response is rejected')
        assert not errors, errors
        print('PASS no JavaScript crashes')
        await browser.close()

asyncio.run(main())
