"""Regression fixtures based on documented response shapes, all offline."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine

ADDRESS = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'


def get(rows, key):
    return next(row for row in rows if row['id'] == key)

class TestEvmAdditionalDanger(unittest.TestCase):
    def test_take_back_ownership_high_even_when_owner_empty(self):
        rows, _ = engine.normalize_evm({'owner_address':'', 'can_take_back_ownership':'1'}, None)
        self.assertEqual(get(rows, 'owner')['state'], 'ok')
        self.assertEqual(get(rows, 'recover_owner')['state'], 'high')

    def test_missing_owner_field_unknown_despite_open_source(self):
        rows, _ = engine.normalize_evm({'is_open_source':'1'}, None)
        self.assertEqual(get(rows, 'owner')['state'], 'unknown')

    def test_explicit_no_owner_vs_missing_owner(self):
        rows, _ = engine.normalize_evm({'owner_address':''}, None)
        self.assertEqual(get(rows,'owner')['state'], 'ok')
        self.assertIn('明确报告无管理员', get(rows, 'owner')['detail'])

    def test_external_call_and_self_destruct_warn(self):
        rows, _ = engine.normalize_evm({'external_call':'1','selfdestruct':'1'},None)
        self.assertEqual(get(rows, 'external_call')['state'], 'warn')
        self.assertEqual(get(rows, 'selfdestruct')['state'], 'warn')

    def test_gas_abuse_high(self):
        rows, _ = engine.normalize_evm({'gas_abuse':'1'},None)
        self.assertEqual(get(rows,'gas_abuse')['state'], 'high')

    def test_dex_without_verified_liquidity_not_clean(self):
        rows, _ = engine.normalize_evm({'is_in_dex':'1'},None)
        self.assertEqual(get(rows, 'liquidity')['state'], 'unknown')

    def test_missing_new_risk_flags_not_clean(self):
        rows, _ = engine.normalize_evm({},None)
        for k in ('selfdestruct','recover_owner','external_call','gas_abuse'):
            self.assertEqual(get(rows,k)['state'], 'unknown')

class TestSolAdditionalDanger(unittest.TestCase):
    def test_malicious_hook_flag_high(self):
        rows, _ = engine.normalize_sol({'transfer_hook':[{'address':'SOME_ADDR','malicious_address':'1'}]},None)
        self.assertEqual(get(rows,'transfer_hook')['state'], 'warn')
        self.assertEqual(get(rows,'malicious_hook')['state'], 'high')

    def test_benign_hook_not_clean_of_hook_risk(self):
        rows, _ = engine.normalize_sol({'transfer_hook':{'address':'SOME_ADDR','malicious_address':'0'}},None)
        self.assertEqual(get(rows,'malicious_hook')['state'],'ok')
        self.assertEqual(get(rows,'transfer_hook')['state'],'warn')

    def test_rugged_is_high(self):
        rows, _ = engine.normalize_sol({}, {'rugged':True, 'risks':[]})
        self.assertEqual(get(rows,'rugged')['state'],'high')

    def test_no_rugged_flag_is_unknown(self):
        rows, _ = engine.normalize_sol({}, {'risks':[]})
        self.assertEqual(get(rows,'rugged')['state'],'unknown')

class TestProviderShapes(unittest.TestCase):
    @patch('engine.get_json',return_value={'error':'rate limit'})
    def test_honeypot_http_200_error_not_success(self, _mock):
        with self.assertRaises(engine.DataError):
            engine.honeypot('bnb','0x'+'1'*40)

    @patch('engine.get_json',side_effect=[{'message':'upstream unavailable'},{'message':'upstream unavailable'}])
    def test_rugcheck_http_200_error_not_success(self,_mock):
        with self.assertRaises(engine.DataError):
            engine.rugcheck('sol',ADDRESS)

    @patch('engine.get_json',side_effect=[{'error':'not ready'},{'risks':[],'score_normalised':0}])
    def test_rugcheck_falls_back_to_valid_summary(self,_mock):
        response=engine.rugcheck('sol',ADDRESS)
        self.assertTrue(response['_summary_only'])
        self.assertEqual(response['score_normalised'],0)

    @patch('engine.get_json',return_value={'summary':{'risk':'low'}})
    def test_honeypot_summary_is_valid_without_simulation(self,_mock):
        response=engine.honeypot('eth','0x'+'1'*40)
        self.assertEqual(response['summary']['risk'],'low')

if __name__=='__main__': unittest.main()
