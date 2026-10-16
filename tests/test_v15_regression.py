"""Risk and identity regressions found during the actual Android build audit."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine

SOL = 'So11111111111111111111111111111111111111112'
EVM = '0x55d398326f99059ff775485246999027b3197955'


def row(rows, key):
    return next(x for x in rows if x['id'] == key)


class IdentityRegression(unittest.TestCase):
    @patch('engine.get_json', return_value={'code':1,'result':{SOL.lower():{'mintable':{'status':'0'}}}})
    def test_sol_address_case_mismatch_is_rejected(self, _):
        with self.assertRaises(engine.DataError): engine.goplus('sol', SOL)

    @patch('engine.get_json', return_value={'code':1,'result':{EVM.upper():{'is_honeypot':'0'}}})
    def test_evm_case_insensitive_lookup_is_retained(self, _):
        self.assertEqual(engine.goplus('bnb', EVM)['is_honeypot'], '0')

    def test_honeypot_wrong_token_or_chain_rejected(self):
        for extra in ({'token':{'address':'0x'+'1'*40}}, {'chain':{'id':1}}, {'pair':{'chainId':1}}):
            with self.subTest(extra=extra), patch('engine.get_json', return_value={'summary':{'risk':'low'}, **extra}):
                with self.assertRaises(engine.DataError): engine.honeypot('bnb', EVM)

    def test_empty_honeypot_reports_not_verified(self):
        for data in ({'summary':{}}, {'honeypotResult':{}}, {'summary':{'risk':'made_up'}}):
            with self.subTest(data=data), patch('engine.get_json', return_value=data):
                with self.assertRaises(engine.DataError): engine.honeypot('bnb', EVM)

    @patch('engine.get_json', return_value={'mint':SOL.lower(),'risks':[]})
    def test_rugcheck_wrong_case_mint_rejected(self, _):
        with self.assertRaises(engine.DataError): engine.rugcheck('sol', SOL)

    def test_empty_rugcheck_token_or_null_score_not_verified(self):
        for data in ({'token':{}}, {'score':None}, {'score_normalised':'NaN'}):
            with self.subTest(data=data), patch('engine.get_json', return_value=data):
                with self.assertRaises(engine.DataError): engine.rugcheck('sol', SOL)

    @patch('engine.get_json', return_value={'score':0})
    def test_zero_rugcheck_score_is_valid(self, _):
        self.assertEqual(engine.rugcheck('sol', SOL)['score'], 0)


class RiskRegression(unittest.TestCase):
    def test_failed_simulation_zero_tax_is_unknown(self):
        rows, _ = engine.normalize_evm(None, {'simulationSuccess':False, 'simulationResult':{'buyTax':0,'sellTax':0}})
        for key in ('buy_tax','sell_tax'):
            self.assertEqual(row(rows,key)['state'],'unknown')

    def test_successful_simulation_taxes_still_work(self):
        rows, _ = engine.normalize_evm(None, {'simulationSuccess':True, 'simulationResult':{'sellTax':99}})
        self.assertEqual(row(rows,'sell_tax')['state'],'high')

    def test_small_nonzero_tax_is_not_rounded_to_clean_zero(self):
        rows,_=engine.normalize_evm({'sell_tax':'0.000001'},None)
        self.assertEqual(row(rows,'sell_tax')['state'],'warn')

    def test_detected_at_does_not_promise_report_freshness(self):
        rows,_=engine.normalize_sol(None,{'risks':[],'detectedAt':engine.datetime.now(engine.timezone.utc).isoformat()})
        self.assertEqual(row(rows,'report_age')['state'],'unknown')

    def test_failed_honeypot_simulation_keeps_goplus_tax(self):
        rows, _ = engine.normalize_evm({'sell_tax':'0.8'}, {'simulationSuccess':False,'simulationResult':{'sellTax':0}})
        self.assertEqual(row(rows,'sell_tax')['state'],'high')
        self.assertNotIn('Honeypot.is 0%',row(rows,'sell_tax')['detail'])

    def test_sol_ratio_fee_and_scheduled_array(self):
        rows,_=engine.normalize_sol({'transfer_fee':{'current_fee_rate':{'fee_rate':'0.02'},'scheduled_fee_rate':[{'fee_rate':'0.03'},{'fee_rate':'0.6'}]}},None)
        fee=row(rows,'transfer_fee')
        self.assertEqual(fee['state'],'high')
        self.assertIn('2.00%',fee['detail'])
        self.assertIn('60.00%',fee['detail'])

    def test_sol_high_current_fee_is_not_diluted_by_10000(self):
        rows,_=engine.normalize_sol({'transfer_fee':{'current_fee_rate':{'fee_rate':'0.9'}}},None)
        self.assertEqual(row(rows,'transfer_fee')['state'],'high')

    def test_invalid_fee_unit_not_guessed(self):
        rows,_=engine.normalize_sol({'transfer_fee':{'current_fee_rate':{'fee_rate':750}}},None)
        self.assertEqual(row(rows,'transfer_fee')['state'],'unknown')
        self.assertEqual(row(rows,'transfer_fee_format')['state'],'unknown')

    def test_invalid_future_fee_does_not_make_zero_clean(self):
        rows,_=engine.normalize_sol({'transfer_fee':{'current_fee_rate':{'fee_rate':0},'scheduled_fee_rate':[{'fee_rate':None}]}},None)
        self.assertEqual(row(rows,'transfer_fee')['state'],'unknown')

    def test_both_documented_transfer_spellings_are_supported(self):
        rows,_=engine.normalize_sol({'none_transferable':'1','non_transferable':'0'},None)
        self.assertEqual(row(rows,'no_transfer')['state'],'high')

    def test_malformed_rug_authority_not_clean(self):
        for value in ('', {}, [], 0, False):
            with self.subTest(value=value):
                rows,_=engine.normalize_sol(None,{'token':{'mintAuthority':value}})
                self.assertEqual(row(rows,'mint')['state'],'unknown')

    def test_rug_metadata_mutable_not_ignored(self):
        rows,_=engine.normalize_sol(None,{'tokenMeta':{'mutable':True}})
        self.assertEqual(row(rows,'metadata')['state'],'warn')

    def test_stale_rug_report_explicitly_unknown(self):
        rows,_=engine.normalize_sol(None,{'risks':[],'detectedAt':'2020-01-01T00:00:00Z'})
        self.assertEqual(row(rows,'report_age')['state'],'unknown')

    def test_missing_rug_report_time_unknown(self):
        rows,_=engine.normalize_sol(None,{'risks':[]})
        self.assertEqual(row(rows,'report_age')['state'],'unknown')

    def test_huge_numeric_field_cannot_crash_query(self):
        self.assertIsNone(engine.num(10**10000))


if __name__ == '__main__': unittest.main()
