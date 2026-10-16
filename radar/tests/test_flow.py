import copy
import json
from decimal import Decimal
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from radar.core import Radar, Store, CRITICAL, USDC, SOL, risk_gate, quote_amount, matches, entities
from radar.server import make_handler

NOW=1800000000
MINT=SOL

def report():
    return {'sources':{'GoPlus':{'status':'ok'},'RugCheck':{'status':'ok'}},'checks':[{'id':k,'state':'ok'}for k in CRITICAL|{'rug'}]+[{'id':'report_age','state':'unknown'}]}

class Fake:
    """Explicit fixture backend; never used by production."""
    def __init__(self):self.multiplier=1;self.danger=False;self.fail=False;self.health={}
    def check(self,*args):
        r=report()
        if self.danger:r['checks'][0]['state']='high'
        return r
    def quote(self,a,b,n):
        if self.fail:raise ValueError('fixture outage')
        return {'inputMint':a,'outputMint':b,'inAmount':str(n),'outAmount':str(n*2 if b==MINT else int(n/2*self.multiplier)), 'feeBps':30,'_at':NOW}
    def fx(self):return Decimal('7.1')
    def news(self):return [{'title':'Nebulax launched new vehicle','url':'https://one.example/a','published':NOW},{'title':'Nebulax reveals new engines','url':'https://two.example/b','published':NOW}]
    def search(self,e):return [{'chainId':'solana','baseToken':{'address':MINT,'name':'Nebulax','symbol':'NEBULAX'},'pairCreatedAt':(NOW-50)*1000}]

class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'test.db');self.db=Store(self.path);self.api=Fake();self.r=Radar(self.db,self.api,lambda:NOW)
    def tearDown(self):self.db.db.close();self.tmp.cleanup()
    def test_complete_news_first_flow_and_restart_no_duplicate(self):
        self.r.cycle();s=self.r.snapshot();self.assertEqual(len(s['positions']),1);self.assertEqual(s['topics'][0]['entity'],'nebulax');self.assertFalse(s['live_available']);self.assertEqual(s['mode'],'模拟交易')
        self.assertEqual(len(s['topics'][0]['evidence']),2)
        cash=self.db.get('cash');self.r.cycle();self.assertEqual(self.db.get('cash'),cash)
        db2=Store(self.path);Radar(db2,self.api,lambda:NOW).cycle();self.assertEqual(len(db2.rows('SELECT * FROM positions')),1);db2.db.close()
    def test_one_source_or_stale_news_cannot_buy(self):
        self.api.news=lambda:[{'title':'Nebulax first','url':'https://one.example/a','published':NOW},{'title':'Nebulax second','url':'https://one.example/b','published':NOW}]
        self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
        self.api.news=lambda:[{'title':'Nebulax old','url':'https://two.example/c','published':NOW-1801}]
        self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
    def test_no_substring_or_wrong_chain_or_old_pool(self):
        self.assertFalse(matches('cat',{'baseToken':{'name':'SCAT'}}))
        self.api.search=lambda e:[{'chainId':'solana','baseToken':{'address':MINT,'name':'Nebulax'},'pairCreatedAt':(NOW-86401)*1000}]
        self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
    def test_unknown_and_high_risk_block(self):
        for key in CRITICAL:
            r=report();next(c for c in r['checks']if c['id']==key)['state']='unknown';self.assertFalse(risk_gate(r)[0],key)
        r=report();r['sources']['GoPlus']['status']='unavailable';self.assertFalse(risk_gate(r)[0])
        self.api.danger=True;self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
    def test_fee_unknown_stale_wrong_amount_quote_rejected(self):
        q=self.api.quote(USDC,MINT,100)
        for patch in ({'feeBps':None},{'feeBps':101},{'_at':NOW-16},{'inAmount':'99'},{'outAmount':'0'},{'feeBps':'NaN'}):
            with self.assertRaises(Exception):quote_amount({**q,**patch},USDC,MINT,100,NOW)
    def test_quote_outage_does_not_record_fill(self):
        self.api.fail=True;self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
    def test_take_profit_atomic_accounting_and_single_exit(self):
        self.r.cycle();self.api.multiplier=1.5;self.r.cycle();s=self.r.snapshot();p=s['positions'][0];self.assertEqual(p['reason'],'止盈');self.assertIsNotNone(p['closed']);self.assertGreater(Decimal(p['pnl']),0)
        self.assertEqual(Decimal(s['cash_usdc']),Decimal('1000')+Decimal(p['pnl']));self.r.cycle();self.assertEqual(self.r.snapshot()['cash_usdc'],s['cash_usdc'])
    def test_stop_loss_and_pause_preserves_exit(self):
        self.r.cycle();self.db.set('enabled','false');self.api.multiplier=.8;self.r.cycle();self.assertEqual(self.r.snapshot()['positions'][0]['reason'],'止损')
    def test_risk_exit_and_failed_exit_remains_open(self):
        self.r.cycle();self.api.fail=True;self.r.monitor();self.assertIsNone(self.r.snapshot()['positions'][0]['closed']);self.api.fail=False;self.api.danger=True;self.r.monitor();self.assertEqual(self.r.snapshot()['positions'][0]['reason'],'风险异常')
    def test_syndicated_identical_title_not_two_sources(self):
        self.api.news=lambda:[{'title':'Nebulax same','url':u,'published':NOW}for u in ('https://one.example/a','https://two.example/b')]
        self.r.cycle();self.assertFalse(self.r.snapshot()['topics'])
    def test_no_trade_from_popular_coin_without_news(self):
        self.api.news=lambda:[];self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
    def test_insufficient_cash_rolls_back(self):
        self.db.set('cash','1');self.r.cycle();self.assertFalse(self.r.snapshot()['positions']);self.assertEqual(self.db.get('cash'),'1')
    def test_http_auth_pause_and_live_rejection(self):
        srv=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.r,'x'*32));th=threading.Thread(target=srv.serve_forever,daemon=True);th.start();base='http://127.0.0.1:'+str(srv.server_port)
        try:
            with self.assertRaises(HTTPError) as err:urlopen(base+'/api/state')
            self.assertEqual(err.exception.code,401)
            with urlopen(Request(base+'/api/state',headers={'Authorization':'Bearer '+'x'*32})) as r:self.assertFalse(json.load(r)['live_available'])
            with urlopen(Request(base+'/api/entry',data=b'{"enabled":false}',headers={'Authorization':'Bearer '+'x'*32})) as r:self.assertFalse(json.load(r)['enabled'])
            with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/live',data=b'{"mode":"live"}',headers={'Authorization':'Bearer '+'x'*32}))
            self.assertEqual(err.exception.code,400)
        finally:srv.shutdown();srv.server_close()
    def test_pause_during_safety_check_prevents_inflight_entry(self):
        original=self.api.check
        def check(*args):
            self.db.set('enabled','false')
            return original(*args)
        self.api.check=check;self.r.cycle();self.assertFalse(self.r.snapshot()['positions'])
    def test_entities_keep_events_without_cashtags(self):
        self.assertIn('nebulax',entities('Nebulax announces rocket'))

if __name__=='__main__':unittest.main()
