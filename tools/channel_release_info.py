"""Fetch the separately published release metadata, never executes downloaded code."""
import json
import os
from pathlib import Path
import subprocess

repository=os.environ['GITHUB_REPOSITORY']
release=subprocess.run(['gh','api',f'repos/{repository}/releases/latest'],capture_output=True,text=True)
target=Path('maintenance/release.json')
if release.returncode:
    # Keep existing metadata on a first release; failures never invent update claims.
    raise SystemExit(0)
data=json.loads(release.stdout)
assets=[x for x in data.get('assets',[]) if x.get('name')=='chainshield-release-info.json']
if assets:
    asset=assets[0]
    raw=subprocess.run(['gh','api','-H','Accept: application/octet-stream',f'repos/{repository}/releases/assets/{asset["id"]}'],capture_output=True,check=True).stdout
    if len(raw)>8192: raise ValueError('发布说明过大')
    obj=json.loads(raw)
    if obj.get('release_url') != data.get('html_url'): raise ValueError('发布信息与当前正式版本不匹配')
    target.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')
