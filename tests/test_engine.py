import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine

BNB_ADDR="0x55d398326f99059fF775485246999027B3197955"
SOL_ADDR="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

class TestInputs(unittest.TestCase):
    def test_valid_evm(self):
        self.assertEqual(engine.normalize_address('bnb',BNB_ADDR),BNB_ADDR.lower())
        self.assertEqual(engine.normalize_address('eth',BNB_ADDR),BNB_ADDR.lower())
    def test_invalid_evm(self):
        for sample in ('0x0','deadbeef',BNB_ADDR[:-1]+'Z','0x'+'0'*41):
            with self.assertRaises(ValueError):engine.normalize_address('bnb',sample)
    def test_sol_valid(self):
        self.assertEqual(engine.normalize_address('sol',SOL_ADDR),SOL_ADDR)
    def test_invalid_sol(self):
        for sample in ('So00000000000000000000000000000','1'*42,'O'*43,'1'*33):
            with self.assertRaises(ValueError):engine.normalize_address('sol',sample)
    def test_invalid_chain(self):
        with self.assertRaises(ValueError):engine.normalize_address('polygon',BNB_ADDR)

class TestEvm(unittest.TestCase):
    def lookup(self,rows,id):return next(x for x in rows if x['id']==id)
    def test_critical_honeypot_and_tax(self):
        go={'token_name':'Risky','is_honeypot':'1','sell_tax':'0.99','slippage_modifiable':'1','is_blacklisted':'1'}
        hp={'honeypotResult':{'isHoneypot':True},'simulationSuccess':False}
        rows,tok=engine.normalize_evm(go,hp)
        self.assertEqual(tok['name'],'Risky')
        for id in ('honeypot','sell_tax','mutable_tax','blacklist'):
            self.assertEqual(self.lookup(rows,id)['state'],'high')
        self.assertEqual(self.lookup(rows,'simulation')['state'],'unknown')
    def test_honeypot_summary_flags_not_ignored(self):
        rows,_=engine.normalize_evm(None,{'summary':{'risk':'medium', 'flags':[{'flag':'TRANSFER_BLOCKED','description':'Transfer blocked','severity':'critical'}]},'simulationSuccess':False})
        self.assertEqual(self.lookup(rows,'hp_flag_0')['state'],'high')
    def test_simulation_fail_does_not_mark_safe(self):
        rows,_=engine.normalize_evm(None,{'simulationSuccess':False,'simulationError':'NO_POOL'})
        self.assertEqual(self.lookup(rows,'honeypot')['state'],'unknown')
        self.assertEqual(self.lookup(rows,'simulation')['state'],'unknown')
        self.assertEqual(self.lookup(rows,'sell_tax')['state'],'unknown')
    def test_false_safe_unknown(self):
        rows,_=engine.normalize_evm({},None)
        self.assertEqual(self.lookup(rows,'proxy')['state'],'unknown')
    def test_conflict_open_source(self):
        rows,_=engine.normalize_evm({'is_open_source':'0'},{'contractCode':{'rootOpenSource':True}})
        self.assertEqual(self.lookup(rows,'opensource')['state'],'warn')
    def test_unsupported_liquidity_is_unknown(self):
        rows,_=engine.normalize_evm(None,None)
        self.assertEqual(self.lookup(rows,'liquidity')['state'],'unknown')
    def test_sell_only_partial_restriction_warn(self):
        rows,_=engine.normalize_evm({'cannot_sell_all':'1'},None)
        self.assertEqual(self.lookup(rows,'sell_restricted')['state'],'warn')

class TestSol(unittest.TestCase):
    def lookup(self,rows,id):return next(x for x in rows if x['id']==id)
    def test_mint_and_freeze_detected(self):
        rows,_=engine.normalize_sol({'mintable':{'status':'1'},'freezable':{'status':'1'},'default_account_state':'2'},None)
        for id in ('mint','freeze','default_frozen'):
            self.assertEqual(self.lookup(rows,id)['state'],'high')
    def test_fallback_rugcheck_authority(self):
        rows,_=engine.normalize_sol(None,{'token':{'mintAuthority':None,'freezeAuthority':'AN_ADDR'},'risks':[]})
        self.assertEqual(self.lookup(rows,'mint')['state'],'ok')
        self.assertEqual(self.lookup(rows,'freeze')['state'],'high')
    def test_missing_authority_unknown(self):
        rows,_=engine.normalize_sol(None,{'risks':[]})
        self.assertEqual(self.lookup(rows,'mint')['state'],'unknown')
        self.assertEqual(self.lookup(rows,'freeze')['state'],'unknown')
    def test_rug_risks_and_scheduled_fee(self):
        rows,_=engine.normalize_sol({'transfer_fee':{'scheduled_fee_rate':[{'fee_rate':0.7}]}},
            {'risks':[{'name':'Low Liquidity','level':'danger','description':'tiny pool'}]})
        self.assertEqual(self.lookup(rows,'transfer_fee')['state'],'high')
        self.assertEqual(self.lookup(rows,'rug_0')['state'],'high')
    def test_market_lp_lock_risk_is_not_silently_lost(self):
        rows,_=engine.normalize_sol(None,{'markets':[{'lp':{'lpLockedPct':12.5}}], 'risks':[]})
        self.assertEqual(self.lookup(rows,'lp_lock')['state'],'warn')
        self.assertIn('12.5%', self.lookup(rows,'lp_lock')['detail'])
    def test_multiple_lp_pools_take_least_locked(self):
        rows,_=engine.normalize_sol(None,{'lpLockedPct':100,'markets':[{'lp':{'lpLockedPct':8}}], 'risks':[]})
        self.assertEqual(self.lookup(rows,'lp_lock')['state'],'warn')
        self.assertIn('8%',self.lookup(rows,'lp_lock')['detail'])
    def test_invalid_lp_lock_unknown(self):
        rows,_=engine.normalize_sol(None,{'lpLockedPct':200, 'risks':[]})
        self.assertEqual(self.lookup(rows,'lp_lock')['state'],'unknown')
    def test_empty_rugcheck_report_unknown(self):
        rows,_=engine.normalize_sol(None,None)
        self.assertEqual(self.lookup(rows,'rug')['state'],'unknown')

class TestAggregator(unittest.TestCase):
    @patch('engine.honeypot', side_effect=engine.DataError('HTTP 429'))
    @patch('engine.goplus',return_value={'is_honeypot':'1'})
    def test_one_source_failure_does_not_hide_risk(self,g,h):
        result=engine.check_token('bnb',BNB_ADDR)
        self.assertEqual(result['level'],'high')
        self.assertEqual(result['sources']['Honeypot.is']['status'],'unavailable')
    @patch('engine.honeypot',side_effect=engine.DataError('HTTP 429'))
    @patch('engine.goplus',side_effect=engine.DataError('HTTP 401'))
    def test_all_sources_fail_unknown(self,g,h):
        result=engine.check_token('bnb',BNB_ADDR)
        self.assertEqual(result['level'],'unknown')
        self.assertGreater(result['counts']['unknown'],0)
    @patch('engine.rugcheck', return_value={'risks':[]})
    @patch('engine.goplus', return_value={ 'mintable':{'status':'0'}})
    def test_partial_sol_data_not_safe(self,g,r):
        result=engine.check_token('sol',SOL_ADDR)
        self.assertEqual(result['level'],'unknown')
    def test_headers_and_query_coming_from_user_never_touch_url(self):
        with self.assertRaises(ValueError):engine.normalize_address('bnb', '0x'+'0'*40+'?address=evil')

if __name__=='__main__':unittest.main()
