"""Run the real provider tests with the candidate maintenance config active."""
from pathlib import Path
import json
import runpy
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import runtime_policy
runtime_policy.configure((ROOT/'maintenance/config.json').read_text(),'候选配置检查')
module=runpy.run_path(str(ROOT/'tests/live_api_smoke.py'))
raise SystemExit(module['main']())
