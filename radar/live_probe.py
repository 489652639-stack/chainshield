"""Read-only live probes; exit nonzero on incomplete coverage; never signs/sends."""
import concurrent.futures
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
from radar.api import API
from radar.core import SOL,USDC,quote_amount
import engine

SAMPLES={'sol':SOL,'eth':'0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2','bnb':'0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'}
api=API()
def check(name,fn):
    start=time.monotonic()
    try:
        value=fn()
        return {'name':name,'ok':True,'elapsed_ms':round((time.monotonic()-start)*1000),'detail':value}
    except Exception as e:
        status=e.code if isinstance(e,urllib.error.HTTPError) else None
        return {'name':name,'ok':False,'elapsed_ms':round((time.monotonic()-start)*1000),'detail':'连接/授权/响应校验失败','http_status':status,'error_type':type(e).__name__}

def quote():
    q=api.quote(USDC,SOL,1_000_000);quote_amount(q,USDC,SOL,1_000_000,time.time())
    return {k:q.get(k)for k in ('inAmount','outAmount','router','feeBps')}

def ws():
    req=urllib.request.Request('https://api.dexscreener.com/token-boosts/latest/v1',headers={'Connection':'Upgrade','Upgrade':'websocket','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':'dGhlIHNhbXBsZSBub25jZQ=='})
    try:
        with urllib.request.urlopen(req,timeout=8)as r:status=r.status
    except urllib.error.HTTPError as e:status=e.code
    return {'http_status':status,'websocket_upgraded':status==101}

jobs=[('新闻RSS',lambda:{'recent_or_old_items':len(api.news())}),('汇率',lambda:str(api.fx())),('DexScreener搜索',lambda:{'pairs':len(api.search('solana'))}),('JupiterV2只读报价',quote),('DexScreener升级握手',ws)]
for chain,address in SAMPLES.items():
    jobs.append(('GoPlus-'+chain,lambda c=chain,a=address:{'fields':len(engine.goplus(c,engine.normalize_address(c,a)))}))
    if chain!='sol':jobs.append(('Honeypot-'+chain,lambda c=chain,a=address:{'simulationSuccess':engine.honeypot(c,engine.normalize_address(c,a)).get('simulationSuccess')}))
jobs.append(('RugCheck-sol',lambda:{'fields':len(engine.rugcheck('sol',SOL))}))
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    results=list(pool.map(lambda x:check(*x),jobs))
payload={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'read_only':True,'broadcasts':0,'results':results,'all_passed':all(r['ok']for r in results)}
Path('radar/evidence').mkdir(exist_ok=True)
Path('radar/evidence/live-api.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
print(json.dumps(payload,ensure_ascii=False,indent=2))
raise SystemExit(0 if payload['all_passed'] else 1)
