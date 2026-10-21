"""Isolated Android UI fixture. No production DB, wallets or external adapters."""
import json,time,ssl
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  now=time.time();mint='So11111111111111111111111111111111111111112'
  p={'post_id':'1','actor':'elonmusk','content':'CI测试热点，非真实热点信号','published':now-60,'received':now-58,'url':'https://x.com/elonmusk/status/2112781998624555086','expires':now+3600}
  m={'mint':mint,'name':'CI测试币','symbol':'TEST','received':now-2,'event_received':now-2,'chain_created':None}
  r={'coin':m,'post':p,'text':{'reason':'test_fixture','anchors':['CI测试热点']},'grade':'疑似相关','rule_version':'V4-text','human_status':'未人工确认','generated':now-1.2,'delay_seconds':.8,'phase':'live'}
  data={'schema_version':1,'generated_at':now,'v4_cutover':now-600,'overview':{'today_mints':1,'v4_candidate_mints':1,'v4_candidate_pairs':1,'v3_candidate_pairs':0,'weak_pairs':1,'pending':0,'errors':0,'last_mint_received':now-2},'services':{'测试数据源':{'active':'active'}},'mints':[m],'hotspots':[p],'candidates':[r],'audits':[{**r,'grade':'证据不足'}],'accounts':[{'actor':'elonmusk','count':1,'received':now-58}]}
  status=200
  if self.headers.get('Authorization')!='Bearer radar-ci-readonly-test-token-0000000000':status=401;data={'error':'密钥无效'}
  elif self.path!='/api/radar/state':status=404;data={'error':'接口不存在'}
  body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=='__main__':
 s=ThreadingHTTPServer(('0.0.0.0',9443),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain('/tmp/radar-ci.crt','/tmp/radar-ci.key');s.socket=ctx.wrap_socket(s.socket,server_side=True);s.serve_forever()
