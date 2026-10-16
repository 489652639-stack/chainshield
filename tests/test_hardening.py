"""Regression tests for risk-report correctness and provider edge cases."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine

EVM = '0x55d398326f99059fF775485246999027B3197955'
SOL = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'


def item(rows, field):
    return next(x for x in rows if x['id'] == field)


class BoundaryChecks(unittest.TestCase):
    def test_owner_null_is_unknown_even_with_open_source(self):
        rows, _ = engine.normalize_evm({'owner_address':None, 'is_open_source':'1'}, None)
        self.assertEqual(item(rows,'owner')['state'],'unknown')
    def test_owner_empty_is_known_no_admin_when_source_known(self):
        rows, _ = engine.normalize_evm({'owner_address':'', 'is_open_source':'1'}, None)
        self.assertEqual(item(rows,'owner')['state'],'ok')
    def test_owner_burn_address_is_known_no_admin(self):
        rows, _ = engine.normalize_evm({'owner_address':'0x'+'0'*40}, None)
        self.assertEqual(item(rows,'owner')['state'],'ok')
    def test_whitelist_explicitly_reported(self):
        rows,_=engine.normalize_evm({'is_whitelisted':'1'}, None)
        self.assertEqual(item(rows,'whitelist')['state'],'warn')
    def test_b20_whitelist_explicitly_reported(self):
        rows,_=engine.normalize_evm({'b20_token': {'b20_info': {'whitelist': {'status':'1'}}}}, None)
        self.assertEqual(item(rows,'whitelist')['state'],'warn')
    def test_nested_delegatecall_not_ignored(self):
        rows,_=engine.normalize_evm({'is_proxy':'0'}, {'contractCode': {'isProxy':False, 'hasProxyCalls':True}})
        self.assertEqual(item(rows,'proxy')['state'],'ok')
        self.assertEqual(item(rows,'delegatecall')['state'],'warn')
    def test_honey_summary_still_high_without_honeypot_result(self):
        rows,_=engine.normalize_evm({'is_honeypot':'0'}, {'summary':{'risk':'honeypot'}})
        self.assertEqual(item(rows,'honeypot')['state'],'high')
    def test_honey_summary_unknown_keeps_unknown(self):
        rows,_=engine.normalize_evm({'is_honeypot':'0'}, {'summary':{'risk':'unknown'}, 'simulationSuccess':True})
        self.assertEqual(item(rows,'hp_risk')['state'],'unknown')
    def test_honey_flags_prioritized_to_show_most_serious(self):
        flags=[{'flag':f'INFO_{i}','severity':'info'} for i in range(18)]
        flags.append({'flag':'critical','severity':'critical'})
        rows,_=engine.normalize_evm(None,{'summary': {'risk':'low','flags':flags}})
        self.assertEqual(item(rows,'hp_flag_0')['state'],'high')
        self.assertEqual(item(rows,'hp_flag_0')['title'],'critical')
    def test_rug_risks_prioritized_to_show_danger(self):
        risks=[{'name':f'warn_{i}','level':'warn'} for i in range(13)]
        risks.append({'name':'Dangerous','level':'danger'})
        rows,_=engine.normalize_sol(None,{'risks':risks})
        self.assertEqual(item(rows,'rug_0')['state'],'high')
        self.assertEqual(item(rows,'rug_0')['title'],'Dangerous')
        self.assertEqual(item(rows,'rug_more')['state'],'warn')
    def test_sol_fee_ratio_converts_correctly(self):
        rows,_=engine.normalize_sol({'transfer_fee':{'current_fee_rate':{'fee_rate':'0.075'}}},None)
        self.assertEqual(item(rows,'transfer_fee')['state'],'warn')
        self.assertIn('7.50%',item(rows,'transfer_fee')['detail'])
    def test_nonfinite_liquidity_ignored(self):
        rows,_=engine.normalize_evm(None, {'pair':{'liquidity':'NaN'},'summary':{'risk':'unknown'}})
        self.assertEqual(item(rows,'liquidity')['state'],'unknown')
    def test_missing_provider_is_never_zero_tax(self):
        rows,_=engine.normalize_evm(None,None)
        self.assertEqual(item(rows,'sell_tax')['state'],'unknown')
    def test_one_negative_provider_wins_over_other_clean(self):
        rows,_=engine.normalize_evm({'is_open_source':'0'}, {'contractCode':{'rootOpenSource':True}})
        self.assertEqual(item(rows,'opensource')['state'],'warn')
    def test_malicious_source_name_cannot_change_backend_states(self):
        rows,_=engine.normalize_evm({'token_name':'<img src=x onerror=alert(1)>'},None)
        self.assertTrue(any(x['state']=='unknown' for x in rows))


class TransportChecks(unittest.TestCase):
    def test_honeypot_chainid_and_address(self):
        with patch.object(engine,'get_json',return_value={'summary':{'risk':'unknown'}}) as fn:
            engine.honeypot('bnb',EVM)
            url=fn.call_args.args[0]
        self.assertIn('chainID=56',url)
        self.assertIn(EVM,url)
    def test_goplus_url_chain_and_normalization(self):
        with patch.object(engine,'get_json',return_value={'code':1,'result':{EVM.lower():{'is_open_source':'1'}}}) as fn:
            val=engine.goplus('eth',EVM.lower())
            self.assertEqual(val['is_open_source'],'1')
            self.assertIn('/token_security/1?',fn.call_args.args[0])
    def test_goplus_missing_result_fails_conservatively(self):
        with patch.object(engine,'get_json',return_value={'code':1,'result':{}}):
            with self.assertRaises(engine.DataError):engine.goplus('eth',EVM)
    def test_invalid_payload_rejected(self):
        class Resp:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,maxbytes):return b'[]'
        with patch.object(engine.urllib.request,'urlopen',return_value=Resp()):
            with self.assertRaises(engine.DataError):engine.get_json('https://example.com')
    def test_http_429_is_not_swallowed(self):
        with patch.object(engine.urllib.request,'urlopen',side_effect=HTTPError('url',429,'limited',{},None)):
            with self.assertRaisesRegex(engine.DataError,'429'):engine.get_json('https://example.com')
    def test_network_failure_is_not_marked_success(self):
        with patch.object(engine.urllib.request,'urlopen',side_effect=URLError('offline')):
            with self.assertRaises(engine.DataError):engine.get_json('https://example.com')
    def test_provider_auth_header_not_logged(self):
        with patch.dict(engine.os.environ,{'GOPLUS_ACCESS_TOKEN':'secret-test-key'}):
            with patch.object(engine,'get_json',side_effect=engine.DataError('HTTP 401')):
                with self.assertRaises(engine.DataError) as ctx:engine.goplus('bnb',EVM)
        self.assertNotIn('secret-test-key',str(ctx.exception))

if __name__=='__main__':unittest.main()
