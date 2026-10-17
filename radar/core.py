"""Small, persistent news-first paper trader. No signer or broadcast capability."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlsplit

D = Decimal
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SOL = 'So11111111111111111111111111111111111111112'
STOP = set('the a an and or in on at to for from with of new breaking news live world latest how why what this that says said after before as is are us uk china russia president report reports market bitcoin ethereum solana crypto'.split())
CRITICAL = {'mint', 'freeze', 'close', 'mutable_balance', 'fee_change', 'hook_change', 'state_change', 'no_transfer', 'default_frozen', 'transfer_hook', 'transfer_fee', 'rugged'}


def norm(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def fingerprint(title, source_ids):
    # Python port of DoradoDevs narrativeFingerprint (MIT, vendor/).
    text = norm(title) + '::' + '|'.join(sorted(source_ids))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def entities(title):
    """Deliberately modest entity rules; no claim of semantic/AI understanding."""
    words = [m.group(1) or m.group(0).lstrip('$') for m in re.finditer(r'\$[A-Za-z]{3,16}\b|\b[A-Z][A-Za-z0-9-]{2,24}\b|[“「]([^”」]{2,12})[”」]', title)]
    return list(dict.fromkeys(norm(w) for w in words if norm(w) not in STOP))[:6]


def matches(entity, pair):
    token = pair.get('baseToken', {})
    # Exact name/symbol or whole word; no substring match such as CAT in SCAT.
    texts = [norm(str(token.get(k, ''))) for k in ('name', 'symbol')]
    return any(t == entity or bool(re.search(r'(?<!\w)' + re.escape(entity) + r'(?!\w)', t)) for t in texts)


def risk_gate(report):
    if not all(report.get('sources', {}).get(s, {}).get('status') == 'ok' for s in ('GoPlus', 'RugCheck')):
        return False, '安全数据源未全部返回'
    checks = {c['id']: c for c in report.get('checks', [])}
    if any(c.get('state') == 'high' for c in checks.values()):
        return False, '发现高危风险'
    if any(checks.get(k, {}).get('state') != 'ok' for k in CRITICAL):
        return False, '关键权限或交易限制尚未通过'
    # Metadata/report-age may stay unknown. Expose it; never label token safe.
    if not any(k == 'rug' or k.startswith('rug_') for k in checks):
        return False, '缺少风险报告'
    if any(c.get('state') != 'ok' for k, c in checks.items() if k == 'rug' or k.startswith('rug_')):
        return False, '第三方风险报告尚有风险或未知项'
    return True, '通过模拟入场初筛；不保证安全或可成交'


def quote_amount(q, mint_in, mint_out, amount, now):
    if q.get('inputMint') != mint_in or q.get('outputMint') != mint_out or str(q.get('inAmount')) != str(amount):
        raise ValueError('报价币种或数量不匹配')
    raw = str(q.get('outAmount', ''))
    if not raw.isdigit() or int(raw) <= 0 or not 0 <= now - q.get('_at', 0) <= 15:
        raise ValueError('报价无效或已过期')
    fee = D(str(q.get('feeBps', 'NaN')))
    if not fee.is_finite() or fee < 0 or fee > 100:
        raise ValueError('平台费用未知或超过百分之一')
    return int(raw)


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, title TEXT, url TEXT, origin TEXT, published REAL, seen REAL, entities TEXT);
        CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, entity TEXT, created REAL, evidence TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS attempts (topic TEXT, mint TEXT, at REAL, status TEXT, detail TEXT, PRIMARY KEY(topic,mint));
        CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, topic TEXT, mint TEXT UNIQUE, symbol TEXT, raw TEXT, cost TEXT, fee TEXT, opened REAL, closed REAL, proceeds TEXT, pnl TEXT, reason TEXT, note TEXT);
        INSERT OR IGNORE INTO kv VALUES ('cash','1000');
        INSERT OR IGNORE INTO kv VALUES ('enabled','true');
        ''')

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    def get(self, key):
        return self.rows('SELECT value FROM kv WHERE key=?', (key,))[0]['value']

    def set(self, key, value):
        self.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, str(value)))


class Radar:
    def __init__(self, store, api, clock=time.time):
        self.store, self.api, self.clock = store, api, clock
        self.cycle_lock = threading.Lock()
        self.last = {'state': '等待首轮扫描', 'at': None, 'error': None}

    def ingest(self, items):
        now = self.clock()
        for item in items:
            at = item.get('published', 0)
            if not now - 1800 <= at <= now + 60:
                continue
            title, url = str(item['title'])[:500], item['url']
            origin = urlsplit(item.get('source_url') or url).hostname
            if not origin:
                continue
            # Cross-feed identical headlines count once, not twice.
            sid = fingerprint(title, [])
            self.store.execute('INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?,?)',
                               (sid, title, url, origin, at, now, json.dumps(entities(title))))
        recent = self.store.rows('SELECT * FROM signals WHERE published>=? ORDER BY seen', (now - 1800,))
        groups = {}
        for s in recent:
            for entity in json.loads(s['entities']):
                groups.setdefault(entity, []).append(s)
        for entity, group in groups.items():
            if len({s['origin'] for s in group}) < 2:
                continue
            # One entity per UTC day, stable across restarts and repeated polling.
            tid = fingerprint(entity, [time.strftime('%Y-%m-%d', time.gmtime(now))])
            evidence = [{k: s[k] for k in ('title', 'url', 'origin', 'published')} for s in group[:8]]
            self.store.execute('INSERT OR IGNORE INTO topics VALUES (?,?,?,?,?)', (tid, entity, now, json.dumps(evidence), '热点已确认'))
        self.store.execute('DELETE FROM signals WHERE published<?', (now - 86400,))

    def attempt(self, topic, pair, fx):
        now = self.clock()
        mint = pair.get('baseToken', {}).get('address')
        created = pair.get('pairCreatedAt', 0) / 1000
        if pair.get('chainId') != 'solana' or not mint or not matches(topic['entity'], pair):
            return
        if not 0 <= now - created <= 86400:
            return
        prior = self.store.rows('SELECT * FROM attempts WHERE topic=? AND mint=?', (topic['id'], mint))
        if prior and now - prior[0]['at'] < 300:
            return
        report = self.api.check('sol', mint)
        passed, reason = risk_gate(report)
        self.store.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?,?,?)', (topic['id'], mint, now, '待报价' if passed else '拦截', reason))
        if not passed:
            return
        raw_usdc = int((D('100') / fx * D(10**6)).to_integral_value(rounding=ROUND_DOWN))
        quote = self.api.quote(USDC, mint, raw_usdc)
        out = quote_amount(quote, USDC, mint, raw_usdc, self.clock())
        # Reverse quote demonstrates current route availability, not sell simulation.
        reverse = self.api.quote(mint, USDC, out)
        quote_amount(reverse, mint, USDC, out, self.clock())
        qty = str(out * 9950 // 10000)  # 0.5% paper slippage; integer token units.
        cost, fee = D(raw_usdc) / D(10**6), D('0.03')
        if int(qty) <= 0:
            raise ValueError('模拟成交量不足')
        with self.store.lock:
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                if self.store.get('enabled') != 'true':
                    raise ValueError('模拟入场已暂停')
                cash = D(self.store.get('cash'))
                count = self.store.rows('SELECT COUNT(*) AS n FROM positions WHERE closed IS NULL')[0]['n']
                if count >= 5 or cash < cost + fee or self.store.rows('SELECT id FROM positions WHERE mint=?', (mint,)):
                    raise ValueError('已有记录、持仓已满或模拟余额不足')
                note = json.dumps({'report': report, 'quote': {k: quote.get(k) for k in ('router','feeBps','outAmount')}, 'fx': str(fx), 'warnings': '报价记账模拟；含每边0.03 USDC网络费用假设；未验证实际链上成交'}, ensure_ascii=False)
                self.store.execute('INSERT INTO positions (topic,mint,symbol,raw,cost,fee,opened,note) VALUES (?,?,?,?,?,?,?,?)',
                                   (topic['id'], mint, str(pair['baseToken'].get('symbol', ''))[:24], qty, str(cost), str(fee), now, note))
                self.store.set('cash', cash - cost - fee)
                self.store.execute('UPDATE attempts SET status=?,detail=? WHERE topic=? AND mint=?', ('模拟买入', '已记账，无链上交易', topic['id'], mint))
                self.store.db.execute('COMMIT')
            except Exception:
                self.store.db.execute('ROLLBACK')
                raise

    def monitor(self):
        for p in self.store.rows('SELECT * FROM positions WHERE closed IS NULL'):
            try:
                q = self.api.quote(p['mint'], USDC, int(p['raw']))
                out = quote_amount(q, p['mint'], USDC, int(p['raw']), self.clock())
                proceeds = D(out * 9950 // 10000) / D(10**6) - D('0.03')
                cost = D(p['cost']) + D(p['fee'])
                pnl = proceeds - cost
                report = self.api.check('sol', p['mint'])
                danger = any(c['state'] == 'high' for c in report.get('checks', []))
                reason = '风险异常' if danger else '止盈' if pnl / cost >= D('.20') else '止损' if pnl / cost <= D('-.10') else None
                if reason:
                    with self.store.lock:
                        self.store.db.execute('BEGIN IMMEDIATE')
                        try:
                            cur = self.store.execute('UPDATE positions SET closed=?,proceeds=?,pnl=?,reason=? WHERE id=? AND closed IS NULL', (self.clock(), str(proceeds), str(pnl), reason, p['id']))
                            if cur.rowcount:
                                self.store.set('cash', D(self.store.get('cash')) + proceeds)
                            self.store.db.execute('COMMIT')
                        except Exception:
                            self.store.db.execute('ROLLBACK')
                            raise
            except Exception:
                self.store.execute('UPDATE positions SET reason=? WHERE id=? AND closed IS NULL', ('退出数据不可用，未伪造成交', p['id']))

    def cycle(self):
        if not self.cycle_lock.acquire(blocking=False):
            return
        try:
            self.monitor()  # Pausing entry never pauses position monitoring.
            self.ingest(self.api.news())
            if self.store.get('enabled') == 'true':
                fx = self.api.fx()
                topics = self.store.rows('SELECT * FROM topics WHERE created>=? ORDER BY created DESC LIMIT 8', (self.clock() - 1800,))
                for topic in topics:
                    for pair in self.api.search(topic['entity'])[:10]:
                        try:
                            self.attempt(topic, pair, fx)
                        except Exception:
                            # A failed candidate must not starve later candidates.
                            self.last['candidate_error'] = '候选数据不完整或接口异常，本次未入场'
                            mint = pair.get('baseToken', {}).get('address', '')
                            self.store.execute('UPDATE attempts SET status=?,detail=? WHERE topic=? AND mint=?', ('未入场', '报价、费用或余额校验未通过', topic['id'], mint))
            self.last.update(state='运行中', at=self.clock(), error=None)
        except Exception:
            self.last.update(state='等待接口恢复', at=self.clock(), error='行情、热点或汇率接口不可用；没有使用伪造数据')
        finally:
            self.cycle_lock.release()

    def snapshot(self):
        with self.store.lock:
            positions = self.store.rows('SELECT * FROM positions ORDER BY id DESC LIMIT 100')
            for p in positions:
                p['evidence'] = json.loads(p.pop('note'))
            return {'mode': '模拟交易', 'live_available': False, 'enabled': self.store.get('enabled') == 'true', 'cash_usdc': self.store.get('cash'),
                    'budget_cny': 100, 'last': dict(self.last), 'health': dict(getattr(self.api, 'health', {})),
                    'counts': {'news': self.store.rows('SELECT COUNT(*) AS n FROM signals')[0]['n'],
                               'topics': self.store.rows('SELECT COUNT(*) AS n FROM topics')[0]['n'],
                               'attempts': self.store.rows('SELECT COUNT(*) AS n FROM attempts')[0]['n'],
                               'open_positions': self.store.rows('SELECT COUNT(*) AS n FROM positions WHERE closed IS NULL')[0]['n']},
                    'news': [{k: s[k] for k in ('title', 'url', 'origin', 'published')} for s in self.store.rows('SELECT * FROM signals ORDER BY published DESC LIMIT 20')],
                    'topics': [{**t, 'evidence': json.loads(t['evidence'])} for t in self.store.rows('SELECT * FROM topics ORDER BY created DESC LIMIT 50')],
                    'attempts': self.store.rows('SELECT * FROM attempts ORDER BY at DESC LIMIT 100'), 'positions': positions}
