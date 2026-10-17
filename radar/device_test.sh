#!/usr/bin/env bash
set -euo pipefail
export RADAR_TOKEN='radar-ci-readonly-test-token-0000000000'
python3 -m radar.server --db /tmp/radar-device.sqlite3 > /tmp/radar-server.log 2>&1 &
server_pid=$!
python3 -m radar.ci_tls > /tmp/radar-tls.log 2>&1 &
tls_pid=$!
trap 'kill "$server_pid" "$tls_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 20); do
  if curl --fail --silent --cacert /tmp/radar-ci.crt -H "Authorization: Bearer $RADAR_TOKEN" https://127.0.0.1:9443/api/state > /tmp/radar-ready.json; then break; fi
  sleep 1
done
python3 - <<'CHECK'
import json
with open('/tmp/radar-ready.json') as f:assert json.load(f)['mode']=='模拟交易'
CHECK
adb install -r radar/android/app/build/outputs/apk/debug/app-debug.apk
adb install -r radar/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell cmd overlay enable com.android.internal.systemui.navbar.threebutton
adb shell am instrument -w com.chainshield.radar.test/com.chainshield.radar.SmokeTest | tee radar/evidence/device-results.txt
adb exec-out run-as com.chainshield.radar cat files/radar-overview.png > radar/evidence/android35-overview.png
python3 - <<'CHECK'
from pathlib import Path
s=Path('radar/evidence/device-results.txt').read_text()
assert 'INSTRUMENTATION_CODE: -1' in s and 'INSTRUMENTATION_CODE: 0' not in s and '错误=' not in s
CHECK
# Deliver without CI-only certificate trust, then reinstall/start these exact bytes.
rm -rf radar/android/app/src/debug
./gradlew -p radar/android --no-daemon :app:assembleDebug
cp radar/android/app/build/outputs/apk/debug/app-debug.apk radar/artifacts/ChainShield-Radar-0.1.1-paper-debug.apk
sha256sum radar/artifacts/*.apk > radar/evidence/apk-sha256.txt
adb install -r radar/artifacts/ChainShield-Radar-0.1.1-paper-debug.apk
adb shell am force-stop com.chainshield.radar
adb shell am start -W -n com.chainshield.radar/.MainActivity | tee radar/evidence/final-apk-launch.txt
python3 - <<'CHECK'
from pathlib import Path
from zipfile import ZipFile
assert 'Status: ok' in Path('radar/evidence/final-apk-launch.txt').read_text()
with ZipFile('radar/artifacts/ChainShield-Radar-0.1.0-paper-debug.apk') as z:
    assert not any('radar_test_ca' in name or 'network_security_config' in name for name in z.namelist())
print('交付APK重新安装启动通过；未包含CI测试CA信任')
CHECK
