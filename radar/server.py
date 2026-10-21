"""Authenticated local HTTP service; put behind HTTPS (deploy/Caddyfile)."""
import argparse
import hmac
import json
import os
from pathlib import Path
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from radar.api import API
from radar.core import Radar, Store
from radar.observe_read import read_snapshot

WEB = Path(__file__).parent / 'web'


def make_handler(radar, token, observe_only=False, snapshot_path='/var/lib/chainshield-observe/snapshot.json'):
    manual_api = API() if observe_only else None
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            pass  # Never log auth headers or contract query strings.

        def send(self, status, data, mime='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict,list)) else data
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def auth(self):
            return hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer ' + token)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path in ('/', '/index.html', '/app.css', '/app.js'):
                name = url.path.lstrip('/') or 'index.html'
                mime = 'text/css' if name.endswith('.css') else 'text/javascript' if name.endswith('.js') else 'text/html'
                return self.send(200, (WEB / name).read_bytes(), mime + '; charset=utf-8')
            if not self.auth():
                return self.send(401, {'error': '服务器访问密钥无效'})
            if url.path == '/api/radar/state':
                try:
                    return self.send(200, read_snapshot(snapshot_path))
                except (OSError, ValueError, TypeError):
                    return self.send(503, {'error': '真实观察快照尚未接通，请等待后台接入或恢复'})
            if url.path == '/api/state':
                if observe_only:
                    return self.send(200, {'mode': '只读观察', 'enabled': False, 'live_available': False})
                return self.send(200, radar.snapshot())
            if url.path == '/api/check':
                try:
                    params = parse_qs(url.query)
                    result = (manual_api if observe_only else radar.api).check(params.get('chain',[''])[0], params.get('address',[''])[0])
                    return self.send(200, result)
                except ValueError as exc:
                    return self.send(400, {'error': str(exc)})
                except Exception:
                    return self.send(502, {'error': '检测接口不可用'})
            return self.send(404, {'error': '接口不存在'})

        def do_POST(self):
            if observe_only:
                self.close_connection = True
                return self.send(403, {'error': '只读观察模式不允许写入或模拟入场'})
            if not self.auth():
                self.close_connection = True
                return self.send(401, {'error': '服务器访问密钥无效'})
            if self.headers.get('Transfer-Encoding'):
                self.close_connection = True
                return self.send(400, {'error': '请求格式不支持'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= (60000 if self.path == '/api/social/import' else 1024):
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                if self.path == '/api/social/import':
                    try:
                        return self.send(200, radar.ingest_social(body.get('messages')))
                    except ValueError as exc:
                        return self.send(400, {'error': str(exc)})
                if self.path != '/api/entry' or type(body.get('enabled')) is not bool:
                    raise ValueError()
                radar.store.set('enabled', str(body['enabled']).lower())
                return self.send(200, {'enabled': body['enabled']})
            except (ValueError, TypeError, AttributeError):
                self.close_connection = True
                return self.send(400, {'error': '只支持暂停或继续模拟入场；实盘未开放'})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='radar-data/radar.sqlite3')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    token = os.getenv('RADAR_TOKEN', '')
    if len(token) < 32 or not token.isascii():
        raise SystemExit('请先设置至少32位ASCII服务器访问密钥 RADAR_TOKEN')
    if os.getenv('TRADING_MODE', 'paper') != 'paper':
        raise SystemExit('此版本只开放模拟交易，没有实盘签名器')
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    observe_only = os.getenv('RADAR_OBSERVE_ONLY', '0') == '1'
    radar = None if observe_only else Radar(Store(args.db), API())
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            radar.cycle()
            stop.wait(60)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 16
        def get_request(self):
            sock, addr = super().get_request()
            sock.settimeout(20)
            return sock, addr

    server = Server(('127.0.0.1', args.port), make_handler(radar, token, observe_only=observe_only))
    if not observe_only:
        threading.Thread(target=worker, daemon=True).start()
    def shutdown(*_):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print('链盾热点雷达已启动：' + ('只读观察，无自动交易循环' if observe_only else '原有模拟模式'), flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
