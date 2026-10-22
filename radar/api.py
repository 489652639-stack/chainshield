"""Read-only external adapters. Real HTTP, bounded response size and timeout."""
import datetime
import email.utils
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal
import engine

DEFAULT_FEEDS = ['https://feeds.bbci.co.uk/news/world/rss.xml', 'https://www.theguardian.com/world/rss']


class API:
    def __init__(self):
        self.health = {}
        self.lock = threading.Lock()
        self.last = {}
        self.feeds = [x.strip() for x in os.getenv('RADAR_FEEDS', ','.join(DEFAULT_FEEDS)).split(',') if x.strip()]
        for url in self.feeds:
            if urllib.parse.urlsplit(url).scheme != 'https':
                raise ValueError('热点源必须使用 HTTPS')

    def fetch(self, url, headers=None):
        host = urllib.parse.urlsplit(url).hostname
        # 0.5 RPS ceiling for keyless Jupiter; serial requests, no bursts.
        with self.lock:
            wait = self.last.get(host, 0) + 2.1 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ChainShieldRadar/0.1', **(headers or {})})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = r.read(3_000_001)
            if len(data) > 3_000_000:
                raise ValueError('响应过大')
            self.health[host] = {'state': '可连接', 'at': time.time()}
            return data
        except Exception:
            self.health[host] = {'state': '连接或授权异常', 'at': time.time()}
            raise

    def json(self, url, headers=None):
        return json.loads(self.fetch(url, headers))

    def news(self):
        items, successes = [], 0
        for feed in self.feeds:
            try:
                root = ET.fromstring(self.fetch(feed))
                successes += 1
                for node in root.findall('.//item')[:100]:
                    try:
                        date = email.utils.parsedate_to_datetime(node.findtext('pubDate', ''))
                        if date.tzinfo is None:
                            continue
                        url = node.findtext('link', '')
                        if urllib.parse.urlsplit(url).scheme != 'https':
                            continue
                        source = node.find('source')
                        items.append({'title': node.findtext('title', ''), 'url': url, 'published': date.timestamp(),
                                      'source_url': source.get('url') if source is not None else url})
                    except (ValueError, TypeError, AttributeError):
                        continue
            except Exception:
                continue
        if not successes:
            raise ValueError('所有热点源不可用')
        return items

    def fx(self):
        data = self.json('https://api.frankfurter.app/latest?from=USD&to=CNY')
        day = datetime.date.fromisoformat(data['date'])
        if not 0 <= (datetime.datetime.now(datetime.timezone.utc).date() - day).days <= 4:
            raise ValueError('汇率已过期')
        rate = Decimal(str(data['rates']['CNY']))
        if not rate.is_finite() or rate <= 0:
            raise ValueError('汇率无效')
        self.health['汇率'] = {'state': '参考美元兑人民币；按USDC等值1美元估算', 'date': data['date'], 'rate': str(rate)}
        return rate

    def search(self, entity):
        data = self.json('https://api.dexscreener.com/latest/dex/search?' + urllib.parse.urlencode({'q': entity}))
        if not isinstance(data.get('pairs'), list):
            raise ValueError('新币搜索响应异常')
        return data['pairs']

    def quote(self, mint_in, mint_out, amount):
        headers = {}
        key = os.getenv('JUPITER_API_KEY', '').strip()
        if key:
            headers['x-api-key'] = key
        params = urllib.parse.urlencode({'inputMint': mint_in, 'outputMint': mint_out, 'amount': str(amount)})
        data = self.json('https://api.jup.ag/swap/v2/order?' + params, headers)
        data['_at'] = time.time()
        return data

    def check(self, chain, address):
        result = engine.check_token(chain, address)
        for name, state in result['sources'].items():
            self.health[name] = {'state': '已返回数据' if state['status'] == 'ok' else '接口不可用', 'at': time.time()}
        return result
