"""Regressions uncovered in source audit v1.3; don't depend on live vendors."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine


def row(report, code):
    return next(x for x in report if x['id'] == code)

class SolanaAuthorityTests(unittest.TestCase):
    def test_goplus_transfer_hook_list_is_not_ignored(self):
        r, _ = engine.normalize_sol({'transfer_hook':[{'address':'ExternalHook1111111111'}]}, None)
        self.assertEqual(row(r,'transfer_hook')['state'], 'warn')

    def test_goplus_empty_hook_list_is_no_hook(self):
        r, _ = engine.normalize_sol({'transfer_hook':[]}, None)
        self.assertEqual(row(r,'transfer_hook')['state'], 'ok')

    def test_goplus_hook_missing_is_unknown(self):
        r, _ = engine.normalize_sol({}, None)
        self.assertEqual(row(r,'transfer_hook')['state'], 'unknown')

    def test_goplus_hook_object_detected(self):
        r, _ = engine.normalize_sol({'transfer_hook':{'address':'ExternalHook11111'}}, None)
        self.assertEqual(row(r,'transfer_hook')['state'], 'warn')

    def test_rugcheck_summary_root_authorities(self):
        r, _ = engine.normalize_sol(None, {'mintAuthority':'AuthorityABC','freezeAuthority':None,'risks':[]})
        self.assertEqual(row(r,'mint')['state'], 'high')
        self.assertEqual(row(r,'freeze')['state'], 'ok')

    def test_rugcheck_summary_root_fields_absent(self):
        r, _ = engine.normalize_sol(None, {'risks':[]})
        self.assertEqual(row(r,'mint')['state'], 'unknown')
        self.assertEqual(row(r,'freeze')['state'], 'unknown')

    def test_conflicting_rugcheck_high_go_clean_is_high(self):
        r, _ = engine.normalize_sol({'mintable':{'status':'0'}}, {'token':{'mintAuthority':'DangerousAuthority'},'risks':[]})
        self.assertEqual(row(r,'mint')['state'], 'high')

    def test_conflicting_go_high_rugcheck_clean_is_high(self):
        r, _ = engine.normalize_sol({'freezable':{'status':'1'}}, {'freezeAuthority':None,'risks':[]})
        self.assertEqual(row(r,'freeze')['state'], 'high')

    def test_unknown_rug_severity_not_mislabeled_warning(self):
        r, _ = engine.normalize_sol(None, {'risks':[{'name':'Informational item','level':'info'}]})
        self.assertEqual(row(r,'rug_0')['state'], 'unknown')

    def test_rug_info_does_not_hide_other_danger(self):
        r, _ = engine.normalize_sol(None, {'risks':[{'name':'Info','level':'info'},{'name':'Danger','level':'danger'}]})
        self.assertEqual(row(r,'rug_0')['state'], 'high')
        self.assertEqual(row(r,'rug_0')['title'], 'Danger')

class ShippingTests(unittest.TestCase):
    def test_same_engine_shipped_in_android(self):
        parent = Path(__file__).resolve().parent.parent
        self.assertEqual((parent/'engine.py').read_bytes(), (parent/'app/src/main/python/engine.py').read_bytes())
    def test_android_service_worker_disabled_in_js(self):
        js=(Path(__file__).resolve().parent.parent/'app/src/main/assets/app.js').read_text()
        self.assertNotIn('serviceWorker.register(', js)
        self.assertNotIn('BigInt(', js)

if __name__=='__main__': unittest.main()
