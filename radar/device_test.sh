#!/usr/bin/env bash
set -euo pipefail
export RADAR_TOKEN='radar-ci-readonly-test-token-0000000000'
python3 -m radar.server --db /tmp/radar-device.sqlite3 > /tmp/radar-server.log 2>&1 &
server_pid=$!
python3 -m radar.ci_tls > /tmp/radar-tls.log 2>&1 &
tls_pid=$!
trap 'kill "$server_pid" "$tls_pid" 2>/dev/null || true' EXIT
adb install -r radar/android/app/build/outputs/apk/debug/app-debug.apk
adb install -r radar/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w com.chainshield.radar.test/com.chainshield.radar.SmokeTest | tee radar/evidence/device-results.txt
rg 'INSTRUMENTATION_CODE: -1' radar/evidence/device-results.txt
! rg 'INSTRUMENTATION_CODE: 0|错误=' radar/evidence/device-results.txt
