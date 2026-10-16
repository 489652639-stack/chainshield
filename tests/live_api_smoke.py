"""Optional live provider probe: prints status only, never asserts a token is safe.

Runs on GitHub's network, not in an offline unit test. Exit nonzero if ANY
provider fails; the APK workflow captures failure but can still compile APK.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine

CASES = [
    ('BNB GoPlus', engine.goplus, 'bnb', '0x55d398326f99059ff775485246999027b3197955'),
    ('BNB Honeypot.is', engine.honeypot, 'bnb', '0x55d398326f99059ff775485246999027b3197955'),
    ('ETH GoPlus', engine.goplus, 'eth', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'),
    ('ETH Honeypot.is', engine.honeypot, 'eth', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'),
    ('SOL GoPlus', engine.goplus, 'sol', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'),
    ('SOL RugCheck', engine.rugcheck, 'sol', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'),
]


def main():
    result=[]
    for name, fn, chain, address in CASES:
        try:
            response=fn(chain,address)
            if not isinstance(response,dict) or not response:
                raise engine.DataError('Empty result')
            result.append({'provider':name,'status':'ok'})
        except Exception as exc:
            message=str(exc) if isinstance(exc, engine.DataError) else type(exc).__name__
            result.append({'provider':name,'status':'unavailable','detail':message[:120]})
    print(json.dumps({'purpose':'connectivity only; not a safety certificate', 'results':result},ensure_ascii=False,indent=2))
    return 0 if all(row['status']=='ok' for row in result) else 1

if __name__ == '__main__': sys.exit(main())
