"""Local operator import; no GMGN session/cookie access or collection claims."""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description='将已核对的公开人物原文导入本机模拟后台')
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    if args.file.stat().st_size > 60000:
        raise SystemExit('导入文件超过60KB')
    body = args.file.read_bytes()
    token = os.environ.get('RADAR_TOKEN', '')
    if len(token) < 32:
        raise SystemExit('需要现有的服务器RADAR_TOKEN；不要在命令行参数中传密钥')
    # Fixed loopback destination. Never transmit server credentials to a supplied URL.
    request = Request('http://127.0.0.1:8787/api/social/import', data=body,
                      headers={'Authorization': 'Bearer ' + token,
                               'Content-Type': 'application/json'})
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
