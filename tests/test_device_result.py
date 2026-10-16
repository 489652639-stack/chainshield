import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('device_result',Path(__file__).resolve().parents[1]/'tools/check_device_result.py')
device=importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


class DeviceEvidenceTests(unittest.TestCase):
    def text(self, rows):
        return 'CHAINSHIELD_TESTS='+json.dumps(rows)+'\nINSTRUMENTATION_CODE: -1\n'

    def rows(self):
        return [{'test':name,'status':'passed'} for name in sorted(device.EXPECTED)]

    def test_all_checks_required(self):
        self.assertEqual(len(device.validate(self.text(self.rows()))),8)
        with self.assertRaises(ValueError): device.validate(self.text(self.rows()[:-1]))

    def test_partial_provider_result_is_not_pass(self):
        rows=self.rows()
        rows[0]['status']='partial'
        with self.assertRaises(ValueError): device.validate(self.text(rows))

    def test_process_exit_without_results_is_not_pass(self):
        with self.assertRaises(ValueError): device.validate('INSTRUMENTATION_CODE: -1')
