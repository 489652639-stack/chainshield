"""Build a signed, expiring, data-only maintenance channel (private key stays outside source)."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime_policy


def build(config, private_key, release, output, timestamp=None):
    now = int(time.time()) if timestamp is None else timestamp
    payload = {'schema':1, 'sequence':now, 'issued_at':now, 'expires_at':now+14*86400,
               'minimum_app_code':7, 'config':config, 'app':release}
    raw = runtime_policy.validate_channel(json.dumps(payload,ensure_ascii=False),now=now).encode('utf-8')
    pinned = (ROOT/'app/src/main/assets/maintenance-public.der').read_bytes()
    public = subprocess.run(['openssl','pkey','-in',str(private_key),'-pubout','-outform','DER'],capture_output=True,check=True).stdout
    if pinned != public: raise ValueError('签名私钥与应用固定公钥不匹配，拒绝发布')
    with tempfile.TemporaryDirectory() as temp:
        file = Path(temp)/'payload'
        file.write_bytes(raw)
        sig = subprocess.run(['openssl','dgst','-sha256','-sign',str(private_key),str(file)],capture_output=True,check=True).stdout
    envelope = {'algorithm':'RSA-SHA256','payload':base64.b64encode(raw).decode(), 'signature':base64.b64encode(sig).decode()}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(envelope,separators=(',',':')),encoding='utf-8')
    return payload


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='maintenance/config.json')
    parser.add_argument('--release',default='maintenance/release.json')
    parser.add_argument('--private-key',required=True)
    parser.add_argument('--output',default='_site/channel.json')
    args=parser.parse_args()
    payload=build(json.loads(Path(args.config).read_text()),Path(args.private_key),json.loads(Path(args.release).read_text()),Path(args.output))
    print(json.dumps({'结果':'维护配置签名成功','版本':payload['sequence'],'有效期秒':14*86400},ensure_ascii=False))
