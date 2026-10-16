#!/usr/bin/env bash
set -euo pipefail

collect_release_evidence() {
  timeout 10s adb logcat -d > release-device/device-logcat.txt || true
  timeout 10s adb exec-out screencap -p > release-device/device-screen.png || true
}
trap collect_release_evidence EXIT

adb install release-device/app-release.apk
adb install release-device/device-test.apk
adb shell am instrument -w com.chainshield.app.test/com.chainshield.app.SmokeInstrumentation > release-device/device-results.txt
cat release-device/device-results.txt
python3 tools/check_device_result.py release-device/device-results.txt
python3 - <<'PY'
import hashlib,json,subprocess,tempfile
from pathlib import Path
root=Path('release-device')
paths=subprocess.run(['adb','shell','pm','path','com.chainshield.app'],capture_output=True,text=True,check=True).stdout.strip().splitlines()
if len(paths)!=1 or not paths[0].startswith('package:/'):
    raise SystemExit('无法确认设备已安装的正式包路径')
with tempfile.TemporaryDirectory() as temp:
    local=Path(temp)/'installed.apk'
    subprocess.run(['adb','pull',paths[0][8:].strip(),str(local)],capture_output=True,check=True)
    installed=hashlib.sha256(local.read_bytes()).hexdigest()
record=json.loads((root/'verification.json').read_text())
if installed!=record['sha256']:
    raise SystemExit('设备已安装 APK 与公开正式包字节不一致')
record['installed_apk_sha256']=installed
record['installed_apk_matches_public_release']=True
record['device_checks_passed']=8
(root/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
print('已确认设备安装的 APK 与公开正式安装包完全一致，八项设备检查通过。')
PY
