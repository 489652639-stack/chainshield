"""Fail CI if adb instrumentation did not complete every real-device check."""
import json
from pathlib import Path
import sys

EXPECTED = {
    'install_launch_chinese_ui', 'live_signed_maintenance_channel',
    'live_bnb_one_click', 'live_eth_one_click', 'live_sol_one_click',
    'invalid_address_validation', 'offline_never_safe_mock', 'clear_input_and_results',
}


def validate(text):
    lines = [line.split('CHAINSHIELD_TESTS=', 1)[1] for line in text.splitlines() if 'CHAINSHIELD_TESTS=' in line]
    if not lines:
        raise ValueError('未找到设备测试完成记录')
    rows = json.loads(lines[-1])
    if {row.get('test') for row in rows} != EXPECTED:
        raise ValueError('设备测试项目未全部完成')
    if any(row.get('status') != 'passed' for row in rows):
        raise ValueError('设备测试存在失败或接口未完全可用，不能记为通过')
    return rows


if __name__ == '__main__':
    rows = validate(Path(sys.argv[1]).read_text())
    print(json.dumps({'结果':'安卓设备测试全部通过','项目数':len(rows)},ensure_ascii=False))
