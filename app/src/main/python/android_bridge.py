"""Only Android-to-Python entry point. Addresses are verified twice (UI + backend).

No secret/private key, wallet signing, or trading functionality exists.
"""
import copy
import json
import threading
import time
import runtime_policy
from collections import deque
from engine import check_token, normalize_address

_LOCK = threading.RLock()
_CACHE = {}
_CALLS = deque()
_POLICY_GENERATION = 0


def check_json(chain: str, address: str) -> str:
    try:
        address = normalize_address(chain, address)
        key = (chain, address)
        now = time.monotonic()
        with _LOCK:
            generation = _POLICY_GENERATION
            entry = _CACHE.get(key)
            if entry is not None and entry[0] > now:
                result = copy.deepcopy(entry[1])
                result['cached'] = True
                return json.dumps(result, ensure_ascii=False, separators=(',', ':'))
            while _CALLS and _CALLS[0] < now - 60:
                _CALLS.popleft()
            if len(_CALLS) >= 16:
                return json.dumps({'_httpStatus': 429, 'error': '查询过于频繁，请稍后再试'}, ensure_ascii=False)
            _CALLS.append(now)
        result = check_token(chain, address)
        with _LOCK:
            # Total upstream outage must be retryable immediately, not masked
            # by a cached 'unknown' for 45 seconds.
            if generation == _POLICY_GENERATION and any(v.get('status') == 'ok' for v in result.get('sources', {}).values()):
                _CACHE[key] = (time.monotonic() + 45, copy.deepcopy(result))
            if len(_CACHE) > 100:
                for key2, value in list(_CACHE.items()):
                    if value[0] < time.monotonic():
                        _CACHE.pop(key2, None)
        result['cached'] = False
    except ValueError as exc:
        result = {'_httpStatus': 400, 'error': str(exc)}
    except Exception:
        result = {'_httpStatus': 502, 'error': '查询暂时失败，稍后重试；未生成任何安全结论'}
    return json.dumps(result, ensure_ascii=False, separators=(',', ':'))


def configure(raw='{}', revision='内置配置'):
    global _POLICY_GENERATION
    with _LOCK:
        if runtime_policy.configure(raw, revision):
            _POLICY_GENERATION += 1
            _CACHE.clear()
    return True
