import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
import runtime_policy as policy
import engine
import android_bridge


class MaintenanceRegression(unittest.TestCase):
    def setUp(self):
        policy.configure('{}')
        policy._health.clear()
        android_bridge._CACHE.clear()
        android_bridge._CALLS.clear()
        self.payload = {'schema': 1, 'sequence': 10, 'issued_at': 1000, 'expires_at': 2000,
                        'minimum_app_code': 7, 'config': {}, 'app': {}}

    def tearDown(self):
        policy.configure('{}')
        policy._health.clear()
        android_bridge._CACHE.clear()
        android_bridge._CALLS.clear()

    def validate(self, **changes):
        return json.loads(policy.validate_channel(json.dumps(dict(self.payload, **changes)), now=1500, floor=9))

    def test_valid_signed_payload_schema(self):
        self.assertEqual(self.validate()['sequence'], 10)

    def test_rollback_rejected(self):
        with self.assertRaisesRegex(ValueError, '旧版'): self.validate(sequence=8)

    def test_expired_rejected(self):
        with self.assertRaises(ValueError): self.validate(expires_at=1499)

    def test_future_timestamp_rejected(self):
        with self.assertRaises(ValueError): self.validate(issued_at=1900)

    def test_excessive_validity_rejected(self):
        with self.assertRaises(ValueError): self.validate(expires_at=1000+32*86400)

    def test_incompatible_app_rejected(self):
        with self.assertRaises(ValueError): self.validate(minimum_app_code=8)

    def test_bool_sequence_rejected(self):
        with self.assertRaises(ValueError): self.validate(sequence=True)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, '重复'):
            policy.validate_channel('{"schema":1,"schema":1}', now=1500)

    def test_payload_size_bounded(self):
        with self.assertRaises(ValueError): policy.validate_channel('x'*65537)

    def test_remote_code_not_allowed(self):
        with self.assertRaises(ValueError): self.validate(config={'python':'print(1)'})

    def test_remote_host_in_path_rejected(self):
        with self.assertRaises(ValueError): self.validate(config={'paths':{'honeypot':'https://evil.test'}})

    def test_query_injection_rejected(self):
        with self.assertRaises(ValueError): self.validate(config={'paths':{'honeypot':'/v2/IsHoneypot?address=x'}})

    def test_versioned_path_supported(self):
        policy.configure(json.dumps({'paths':{'honeypot':'/v3/IsHoneypot'}}))
        with patch.object(engine, 'get_json', return_value={'summary':{'risk':'unknown'}}) as get:
            engine.honeypot('bnb', '0x'+'1'*40)
        self.assertIn('https://api.honeypot.is/v3/IsHoneypot?', get.call_args.args[0])

    def test_alias_preserves_existing_risk(self):
        policy.configure(json.dumps({'aliases':{'evm':{'is_honeypot':'new_honey'}}}))
        data=policy.adapt('evm', {'is_honeypot':'1', 'new_honey':'0'})
        self.assertEqual(data['is_honeypot'],'1')

    def test_alias_can_restore_missing_field(self):
        policy.configure(json.dumps({'aliases':{'evm':{'is_honeypot':'new_honey'}}}))
        self.assertEqual(policy.adapt('evm', {'new_honey':'1'})['is_honeypot'],'1')

    def test_disabled_source_is_unknown(self):
        policy.configure(json.dumps({'disabled':['Honeypot.is']}))
        with self.assertRaisesRegex(engine.DataError, '维护'):
            engine.honeypot('bnb', '0x'+'1'*40)

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError): policy.validate_config({'disabled':['伪造来源']})

    def test_translation_requires_chinese(self):
        with self.assertRaises(ValueError): policy.validate_config({'translations':{'new risk':'new risk'}})

    def test_config_change_invalidates_cached_results(self):
        android_bridge._CACHE[('bnb','0x'+'1'*40)] = (99999999, {})
        android_bridge.configure(json.dumps({'disabled':['RugCheck']}))
        self.assertEqual(android_bridge._CACHE, {})

    def test_inflight_old_policy_result_not_cached(self):
        def result(*args):
            android_bridge.configure(json.dumps({'disabled':['RugCheck']}))
            return {'sources':{'GoPlus':{'status':'ok'}}}
        with patch.object(android_bridge, 'check_token', side_effect=result):
            android_bridge.check_json('bnb', '0x'+'1'*40)
        self.assertEqual(android_bridge._CACHE,{})

    def test_transient_failure_retried_once(self):
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return b'{"ok":true}'
        with patch.object(engine.urllib.request, 'urlopen', side_effect=[URLError('offline'),Response()]) as get, patch.object(engine.time,'sleep'):
            self.assertTrue(engine.get_json('https://api.gopluslabs.io/test')['ok'])
        self.assertEqual(get.call_count,2)

    def test_rate_limit_not_retried(self):
        with patch.object(engine.urllib.request, 'urlopen', side_effect=HTTPError('url',429,'rate',{},None)) as get:
            with self.assertRaises(engine.DataError): engine.get_json('https://api.gopluslabs.io/test')
        self.assertEqual(get.call_count,1)

    def test_circuit_cools_after_three_failures(self):
        for _ in range(3): policy.record('host',False)
        with self.assertRaisesRegex(ValueError, '冷却'): policy.before_request('host')

    def test_circuit_recovers_after_timeout(self):
        for _ in range(3): policy.record('host',False)
        with patch.object(policy.time,'monotonic',return_value=policy._health['host']['until']+1): policy.before_request('host')
        policy.record('host',True)
        policy.before_request('host')

    def test_fee_unit_can_be_explicitly_changed(self):
        rows,_=engine.normalize_sol({'_fee_unit':'basis_points','transfer_fee':{'current_fee_rate':{'fee_rate':200}}},None)
        row=next(x for x in rows if x['id']=='transfer_fee')
        self.assertIn('2.00%',row['detail'])
        self.assertEqual(row['state'],'warn')

    def test_unknown_fee_unit_never_zero_clean(self):
        rows,_=engine.normalize_sol({'_fee_unit':'unknown','transfer_fee':{'current_fee_rate':{'fee_rate':0}}},None)
        self.assertEqual(next(x for x in rows if x['id']=='transfer_fee')['state'],'unknown')

    def test_known_risk_translation_keeps_severity(self):
        rows=[{'title':'Freeze Authority still enabled','detail':'token frozen','state':'high'}]
        policy.localize_checks(rows)
        self.assertEqual(rows[0]['state'],'high')
        self.assertEqual(rows[0]['title'],'冻结权限仍然启用')

    def test_unknown_english_risk_is_chinese_and_not_cleaned(self):
        rows=[{'title':'BRAND_NEW_ATTACK','detail':'something evil','state':'high'}]
        policy.localize_checks(rows)
        self.assertEqual(rows[0]['state'],'high')
        self.assertTrue(policy.chinese(rows[0]['title']))
        self.assertNotIn('evil',rows[0]['detail'])

    def test_mixed_english_error_not_shown(self):
        rows=[{'title':'买卖模拟','detail':'模拟失败：execution reverted','state':'unknown'}]
        policy.localize_checks(rows)
        self.assertNotIn('execution',rows[0]['detail'])

    def test_unsigned_download_location_cannot_be_injected(self):
        app={'version_code':8,'version_name':'1.7','release_url':'https://evil.test/app.apk','sha256':'a'*64,'notes_zh':'更新说明'}
        with self.assertRaises(ValueError): self.validate(app=app)

    def test_valid_release_link_and_chinese_notes(self):
        app={'version_code':8,'version_name':'1.7','release_url':'https://github.com/example/chainshield/releases/tag/v1.7','sha256':'a'*64,'notes_zh':'更新说明'}
        self.assertEqual(self.validate(app=app)['app']['version_code'],8)

    def test_full_report_translates_new_risk_without_downgrading(self):
        sol='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
        with patch.object(engine,'goplus',return_value={'mintable':'0'}), patch.object(engine,'rugcheck',return_value={'risks':[{'name':'NEW_UNDOCUMENTED_ATTACK','level':'danger','description':'malicious transfer condition'}]}):
            report=engine.check_token('sol',sol)
        self.assertEqual(report['level'],'high')
        row=next(x for x in report['checks'] if x['id']=='rug_0')
        self.assertEqual(row['state'],'high')
        self.assertIn('待核实',row['title'])
        self.assertNotIn('malicious',row['detail'])

    def test_all_three_chain_reports_have_chinese_check_text(self):
        sol='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
        for chain,address in [('bnb','0x'+'1'*40),('eth','0x'+'1'*40),('sol',sol)]:
            with self.subTest(chain=chain), patch.object(engine,'goplus',return_value={}), patch.object(engine,'honeypot',return_value={}), patch.object(engine,'rugcheck',return_value={}):
                report=engine.check_token(chain,address)
                for row in report['checks']:
                    self.assertTrue(policy.chinese(row['title']),row)
                    self.assertTrue(policy.chinese(row['detail']),row)

    def test_rugcheck_fallback_has_bounded_request_attempts(self):
        with patch.object(engine.urllib.request,'urlopen',side_effect=HTTPError('url',503,'busy',{},None)) as get:
            with self.assertRaises(engine.DataError):engine.get_json('https://api.rugcheck.xyz/v1/test')
        self.assertEqual(get.call_count,1)


if __name__ == '__main__': unittest.main()
