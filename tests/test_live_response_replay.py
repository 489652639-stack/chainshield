"""Offline replays of real public provider responses captured on 2026-10-15.

This verifies parsing regressions; it does NOT make another live API request.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine

FIXTURES=Path(__file__).parent/'fixtures/live_20261015'
CASES={
    'bnb':'0x55d398326f99059ff775485246999027b3197955',
    'eth':'0xdac17f958d2ee523a2206206994597c13d831ec7',
    'sol':'So11111111111111111111111111111111111111112',
}


class RecordedProviderReplay(unittest.TestCase):
    def replay(self, chain):
        def response(url, headers=None):
            host=urlsplit(url).hostname
            name=('goplus-'+chain if host=='api.gopluslabs.io' else 'honeypot-'+chain if host=='api.honeypot.is' else 'rugcheck-sol')
            return json.loads((FIXTURES/(name+'.json')).read_text())
        with patch.object(engine,'get_json',side_effect=response):
            return engine.check_token(chain, CASES[chain])

    def test_bnb_real_payloads_parse_and_simulate(self):
        result=self.replay('bnb')
        self.assertTrue(all(s['status']=='ok' for s in result['sources'].values()))
        self.assertEqual(result['token']['symbol'],'USDT')
        rows={r['id']:r for r in result['checks']}
        self.assertEqual(rows['simulation']['state'],'ok')
        self.assertEqual(rows['sell_tax']['state'],'ok')
        self.assertEqual(rows['mintable']['state'],'warn')

    def test_eth_real_payloads_keep_admin_blacklist_risk(self):
        result=self.replay('eth')
        self.assertTrue(all(s['status']=='ok' for s in result['sources'].values()))
        rows={r['id']:r for r in result['checks']}
        self.assertEqual(result['token']['symbol'],'USDT')
        self.assertEqual(rows['simulation']['state'],'ok')
        self.assertEqual(rows['blacklist']['state'],'high')

    def test_sol_real_payloads_keep_revoked_authorities_and_stale_timestamp(self):
        result=self.replay('sol')
        self.assertTrue(all(s['status']=='ok' for s in result['sources'].values()))
        rows={r['id']:r for r in result['checks']}
        self.assertEqual(result['token']['name'],'Wrapped SOL')
        self.assertEqual(rows['mint']['state'],'ok')
        self.assertEqual(rows['freeze']['state'],'ok')
        self.assertEqual(rows['report_age']['state'],'unknown')
        self.assertEqual(rows['transfer_fee']['state'],'unknown')


if __name__=='__main__': unittest.main()
