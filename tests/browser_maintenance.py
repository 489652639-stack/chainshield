"""Mobile browser integration tests; native signature verification is tested separately."""
import asyncio
import copy
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

ASSETS=Path(__file__).resolve().parents[1]/'app/src/main/assets'
SOL='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
EVM='0x55d398326f99059ff775485246999027b3197955'
STATE={'connected':False,'channel':'','revision':'内置配置','message':'更新服务尚未连接，当前使用内置配置','checked_at':0,'version':'1.6','new_version':None,'health':{'sources':{}}}


async def main():
    async with async_playwright() as p:
        options={'headless':True,'args':['--no-sandbox']}
        if os.environ.get('CHROMIUM_EXECUTABLE'):
            options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
        browser=await p.chromium.launch(**options)
        page=await browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        state=copy.deepcopy(STATE)
        mode={'failure':False,'delay':0,'query_failure':False}
        async def route(request):
            url=request.request.url
            from urllib.parse import urlparse,parse_qs
            parsed=urlparse(url)
            path=parsed.path
            if path.startswith('/api/maintenance/'):
                if mode['delay']: await asyncio.sleep(mode['delay'])
                await request.fulfill(status=503 if mode['failure'] else 200,content_type='application/json',body=json.dumps(state,ensure_ascii=False))
            elif path=='/api/check':
                if mode['query_failure']:
                    await request.abort('failed')
                    return
                query=parse_qs(parsed.query)
                report={'chain':query['chain'][0],'address':query['address'][0],'time':'2026-10-16T00:00:00Z','level':'unknown','title':'部分项目尚未验证','counts':{'unknown':1,'ok':1},'token':{'name':'中文测试代币'},'sources':{'GoPlus':{'status':'ok'}},'checks':[{'group':'交易风险','title':'转账钩子','state':'unknown','detail':'尚无可验证数据','source':'GoPlus'}]}
                await request.fulfill(status=200,content_type='application/json',body=json.dumps(report,ensure_ascii=False))
            else:
                file=ASSETS/('index.html' if path=='/' else path.lstrip('/'))
                if file.is_file():
                    mime='text/javascript' if file.suffix=='.js' else 'text/css' if file.suffix=='.css' else 'application/json' if file.suffix=='.json' else 'text/html'
                    await request.fulfill(status=200,content_type=mime,body=file.read_bytes())
                else: await request.fulfill(status=404,body='未找到内容')
        await page.route('https://appassets.androidplatform.net/**',route)
        await page.goto('https://appassets.androidplatform.net/')
        await page.wait_for_function("document.querySelector('#maintenanceMessage').textContent.includes('尚未连接')")
        text=await page.locator('body').inner_text()
        for unwanted in ('CHAINSHIELD','WEB3 RISK','RISK REPORT','BNB Chain','Ethereum','Solana','SECURITY'):
            assert unwanted not in text,unwanted
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        print('通过：手机静态界面中文与布局检查')
        await page.locator('#checkUpdates').wait_for(state='visible')
        state['new_version']={'version_name':'1.7','release_url':'https://github.com/example/chainshield/releases/tag/v1.7','notes_zh':'修复更新 <img src=x onerror=alert(1)>'}
        await page.locator('#checkUpdates').click()
        await page.locator('#appUpdate').wait_for(state='visible')
        assert await page.locator('#appUpdate img').count()==0
        assert '修复更新' in await page.locator('#updateNotes').inner_text()
        print('通过：中文更新提示与远端说明转义')
        state['new_version']['release_url']='javascript:alert(1)'
        await page.locator('#checkUpdates').click()
        await page.locator('#appUpdate').wait_for(state='hidden')
        assert await page.locator('#updateLink').get_attribute('href') is None
        print('通过：拒绝不受支持的安装包发布链接')
        mode['failure']=True
        await page.locator('#checkUpdates').click()
        await page.wait_for_function("document.querySelector('#maintenanceMessage').textContent.includes('暂时无法连接')")
        assert await page.locator('#scan').is_enabled()
        print('通过：维护服务失败时查询入口仍可使用')
        mode['failure']=False
        mode['delay']=1
        await page.locator('#checkUpdates').click()
        for chain,address,label in [('bnb',EVM,'币安链'),('sol',SOL,'索拉纳链'),('eth',EVM,'以太坊链')]:
            await page.locator(f'.chain[data-chain={chain}]').click()
            await page.locator('#address').fill(address)
            await page.locator('#scan').click()
            await page.locator('#copyReport').wait_for()
            assert label in await page.locator('.result-kicker').inner_text()
            assert '钩子' in await page.locator('.finding-title').inner_text()
        print('通过：维护检查期间三链中文查询流程')
        mode['query_failure']=True
        await page.locator('#scan').click()
        await page.locator('.error-card').wait_for()
        assert '网络连接失败' in await page.locator('.error-card').inner_text()
        assert 'Failed to fetch' not in await page.locator('.error-card').inner_text()
        print('通过：浏览器网络异常转为中文提示')
        assert not errors,errors
        print('通过：无页面脚本异常')
        await browser.close()


if __name__=='__main__':asyncio.run(main())
