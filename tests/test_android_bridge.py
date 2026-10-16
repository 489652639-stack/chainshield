import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app/src/main/python'))
import android_bridge

ADDR = '0x55d398326f99059fF775485246999027B3197955'

class TestBridge(unittest.TestCase):
    def setUp(self):
        android_bridge._CACHE.clear()
        android_bridge._CALLS.clear()

    def test_rejects_bad_address(self):
        data = json.loads(android_bridge.check_json('bnb','../../../etc/passwd'))
        self.assertEqual(data['_httpStatus'], 400)

    @patch('android_bridge.check_token', return_value={'level':'unknown','checks':[],'sources':{'GoPlus':{'status':'ok'}}})
    def test_calls_same_engine_and_caches_result(self, mock):
        first=json.loads(android_bridge.check_json('bnb', ADDR))
        second=json.loads(android_bridge.check_json('bnb', ADDR))
        self.assertEqual(first['level'],'unknown')
        self.assertFalse(first['cached'])
        self.assertTrue(second['cached'])
        mock.assert_called_once()

    @patch('android_bridge.check_token', return_value={'level':'unknown','checks':[], 'sources':{'GoPlus':{'status':'unavailable'},'Honeypot.is':{'status':'unavailable'}}})
    def test_total_outage_not_cached(self, mock):
        first=json.loads(android_bridge.check_json('bnb',ADDR))
        second=json.loads(android_bridge.check_json('bnb',ADDR))
        self.assertFalse(first['cached'])
        self.assertFalse(second['cached'])
        self.assertEqual(mock.call_count,2)

    @patch('android_bridge.check_token', side_effect=OSError('unexpected / private'))
    def test_does_not_expose_internal_errors(self, mock):
        data=json.loads(android_bridge.check_json('bnb', ADDR))
        self.assertEqual(data['_httpStatus'],502)
        self.assertNotIn('private',data['error'])

    @patch('android_bridge.check_token', return_value={'level':'unknown'})
    def test_rate_limit(self, mock):
        for i in range(16):
            address='0x'+str(i).zfill(40)
            res=json.loads(android_bridge.check_json('bnb',address))
            self.assertEqual(res['level'],'unknown')
        res=json.loads(android_bridge.check_json('bnb','0x'+'99'.zfill(40)))
        self.assertEqual(res['_httpStatus'],429)

if __name__=='__main__':unittest.main()
