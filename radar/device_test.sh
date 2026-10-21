#!/usr/bin/env bash
set -euo pipefail
python3 -m radar.observe_ci > /tmp/radar-observe-ci.log 2>&1 &
fixture_pid=$!
trap 'kill "$fixture_pid" 2>/dev/null || true' EXIT
adb install -r radar/android/app/build/outputs/apk/debug/app-debug.apk
adb install -r radar/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell cmd overlay enable com.android.internal.systemui.navbar.threebutton
adb shell am instrument -w com.chainshield.radar.test/com.chainshield.radar.SmokeTest | tee radar/observe-evidence/observe-fixture-device.txt
python3 - <<'CHECK'
from pathlib import Path
s=Path('radar/observe-evidence/observe-fixture-device.txt').read_text();assert 'INSTRUMENTATION_CODE: -1' in s and '错误=' not in s
CHECK
adb exec-out run-as com.chainshield.radar cat files/observe-overview.png > radar/observe-evidence/observe-overview.png
rm -rf radar/android/app/src/debug
./gradlew -p radar/android --no-daemon :app:assembleDebug
cp radar/android/app/build/outputs/apk/debug/app-debug.apk radar/observe-artifacts/ChainShield-Radar-0.2.0-observe.apk
sha256sum radar/observe-artifacts/*.apk > radar/observe-evidence/apk-sha256.txt
adb install -r radar/observe-artifacts/ChainShield-Radar-0.2.0-observe.apk
adb shell am force-stop com.chainshield.radar
adb shell am instrument -w -e finalOnly true com.chainshield.radar.test/com.chainshield.radar.SmokeTest | tee radar/observe-evidence/final-apk-device.txt
python3 - <<'CHECK'
from pathlib import Path
from zipfile import ZipFile
s=Path('radar/observe-evidence/final-apk-device.txt').read_text();assert 'INSTRUMENTATION_CODE: -1' in s and '错误=' not in s
with ZipFile('radar/observe-artifacts/ChainShield-Radar-0.2.0-observe.apk') as z:assert not any('radar_test_ca' in p or 'network_security_config' in p for p in z.namelist())
CHECK
adb shell pm clear com.chainshield.radar
adb shell am start -W -n com.chainshield.radar/.MainActivity | tee radar/observe-evidence/final-apk-launch.txt
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose --print-certs radar/observe-artifacts/*.apk > radar/observe-evidence/apk-signature.txt
