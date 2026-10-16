#!/usr/bin/env bash
set -euo pipefail

# Capture while the emulator is still alive; the runner shuts it down afterwards.
collect_logs() {
  timeout 10s adb logcat -d > device-logcat.txt || true
}
trap collect_logs EXIT

adb install device-build/debug/app-debug.apk
adb install device-build/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w com.chainshield.app.test/com.chainshield.app.SmokeInstrumentation > device-results.txt
cat device-results.txt
python3 tools/check_device_result.py device-results.txt
