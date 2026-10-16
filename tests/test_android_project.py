import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
class TestAndroidPackageStructure(unittest.TestCase):
    def test_bundle_engine_consistency(self):
        self.assertEqual((ROOT/'engine.py').read_bytes(), (ROOT/'app/src/main/python/engine.py').read_bytes())
    def test_all_native_asset_dependencies_exist(self):
        base=ROOT/'app/src/main/assets'
        for file in ('index.html','app.css','app.js','manifest.webmanifest','sw.js','icons/icon-192.png','icons/icon-512.png'):
            with self.subTest(file=file):self.assertTrue((base/file).is_file())
    def test_manifest_internet_only_no_private_data(self):
        root=ET.parse(ROOT/'app/src/main/AndroidManifest.xml').getroot()
        ns='{http://schemas.android.com/apk/res/android}'
        permissions=[e.attrib.get(ns+'name') for e in root.findall('uses-permission')]
        self.assertEqual(permissions,['android.permission.INTERNET'])
        app=root.find('application')
        self.assertEqual(app.get(ns+'allowBackup'),'false')
        self.assertEqual(app.get(ns+'usesCleartextTraffic'),'false')
    def test_target_sdk_and_minimum_sdk(self):
        data=(ROOT/'app/build.gradle').read_text()
        for expected in ('compileSdk 35','targetSdk 35','minSdk 24','versionName \'1.6.1\''):
            self.assertIn(expected,data)
    def test_python_bridge_call_and_virtual_host(self):
        data=(ROOT/'app/src/main/java/com/chainshield/app/MainActivity.java').read_text()
        self.assertIn('appassets.androidplatform.net',data)
        self.assertIn('"/api/check"',data)
        self.assertIn('getModule("android_bridge")',data)
        self.assertIn('shouldInterceptRequest',data)
if __name__ == '__main__':unittest.main()
