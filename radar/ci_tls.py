"""CI-only TLS reverse proxy for emulator connectivity validation."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ssl,urllib.request,urllib.error
class Proxy(BaseHTTPRequestHandler):
    def do_GET(self):self.forward()
    def do_POST(self):self.forward()
    def log_message(self,*args):pass
    def forward(self):
        body=self.rfile.read(int(self.headers.get('Content-Length',0)))if self.command=='POST'else None
        req=urllib.request.Request('http://127.0.0.1:8787'+self.path,data=body,headers={'Authorization':self.headers.get('Authorization',''),'Content-Type':'application/json'})
        try:r=urllib.request.urlopen(req,timeout=45)
        except urllib.error.HTTPError as e:r=e
        data=r.read();self.send_response(r.code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
s=ThreadingHTTPServer(('0.0.0.0',9443),Proxy);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain('/tmp/radar-ci.crt','/tmp/radar-ci.key');s.socket=ctx.wrap_socket(s.socket,server_side=True);s.serve_forever()
