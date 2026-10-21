import hashlib,json,pathlib,sqlite3,tempfile,threading,time,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from radar.observe_export import build_snapshot,connect,write_snapshot
from radar.observe_read import read_snapshot
from radar.server import make_handler

MINT='So11111111111111111111111111111111111111112'
class ObserveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.source=self.root/'source.db';self.shadow=self.root/'shadow.db';self.now=1792572420
  s=sqlite3.connect(self.source);s.executescript('CREATE TABLE tweets(tweet_id TEXT,author TEXT,content TEXT,url TEXT,published REAL,received REAL,expires REAL,time_basis TEXT,synthetic INTEGER);CREATE TABLE tokens(mint TEXT,name TEXT,symbol TEXT,received REAL,synthetic INTEGER);')
  s.execute('INSERT INTO tweets VALUES(?,?,?,?,?,?,?,?,?)',('p','elonmusk','special phrase','https://x.com/elonmusk/status/1',self.now-60,self.now-58,self.now+3600,'source record',0));s.execute('INSERT INTO tokens VALUES(?,?,?,?,?)',(MINT,'special phrase','TEST',self.now-2,0));s.commit();s.close()
  r=sqlite3.connect(self.shadow);r.executescript('CREATE TABLE state(key TEXT,value TEXT);CREATE TABLE coins(mint TEXT,evaluated INTEGER);CREATE TABLE errors(at REAL);CREATE TABLE candidates(post_id TEXT,mint TEXT,generated REAL,payload TEXT);CREATE TABLE text_audit(evaluated REAL,payload TEXT);')
  r.execute('INSERT INTO state VALUES(?,?)',('v4_text_cutover',json.dumps(self.now-600)));r.execute('INSERT INTO coins VALUES(?,1)',(MINT,))
  self.pair={'post':{'post_id':'p','actor':'elonmusk','content':'special phrase','images':'must not export'},'coin':{'mint':MINT,'name':'special phrase','symbol':'TEST','event_received':self.now-2,'chain_created':123,'chain_creation_verified':False,'uri':'must not export'},'generated':self.now-1,'phase':'live','delay_seconds':1,'rule_version':'V4-text','grade':'疑似相关','text':{'reason':'phrase','literal_anchors':[{'anchor':'special phrase'}]},'image':{'should':'never read'}}
  r.execute('INSERT INTO candidates VALUES(?,?,?,?)',('p',MINT,self.now-1,json.dumps(self.pair)));r.execute('INSERT INTO candidates VALUES(?,?,?,?)',('old',MINT,self.now-1000,json.dumps({**self.pair,'rule_version':'V3'})));r.execute('INSERT INTO text_audit VALUES(?,?)',(self.now-1,json.dumps(self.pair)));r.commit();r.close()
 def tearDown(self):self.tmp.cleanup()
 def snapshot(self):return build_snapshot(self.source,self.shadow,self.now,services={})
 def test_readonly_preserves_source_and_history(self):
  before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in [self.source,self.shadow]];v=self.snapshot();self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in [self.source,self.shadow]]);self.assertEqual(v['overview']['v3_candidate_pairs'],1);self.assertEqual(v['overview']['v4_candidate_pairs'],1)
 def test_readonly_sql_refuses_write(self):
  c=connect(self.source)
  with self.assertRaises(sqlite3.OperationalError):c.execute('DELETE FROM tokens')
  c.close()
 def test_unknown_created_no_images_and_separate_audit(self):
  v=self.snapshot();self.assertIsNone(v['candidates'][0]['coin']['chain_created']);self.assertNotIn('images',json.dumps(v));self.assertNotIn('must not export',json.dumps(v));self.assertEqual(v['audits'][0]['grade'],'证据不足');self.assertEqual(v['latency_window']['phases']['live']['n'],1)
 def test_atomic_bounded_snapshot_and_staleness(self):
  p=self.root/'snapshot.json';write_snapshot(self.snapshot(),p);self.assertEqual(p.stat().st_mode&0o777,0o640);self.assertFalse(read_snapshot(p,self.now)['stale']);self.assertTrue(read_snapshot(p,self.now+100)['stale']);p.write_bytes(b' '*1500001)
  with self.assertRaises(ValueError):read_snapshot(p,self.now)
 def test_authenticated_route_and_writes_denied(self):
  p=self.root/'snapshot.json';write_snapshot(self.snapshot(),p)
  class OfflineAPI:
   def check(self,*a):raise AssertionError('external request not expected')
  with patch('radar.server.API',OfflineAPI):handler=make_handler(None,'x'*32,observe_only=True,snapshot_path=str(p))
  server=ThreadingHTTPServer(('127.0.0.1',0),handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start();base='http://127.0.0.1:'+str(server.server_port)
  try:
   with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(base+'/api/radar/state')
   self.assertEqual(cm.exception.code,401)
   req=urllib.request.Request(base+'/api/radar/state',headers={'Authorization':'Bearer '+'x'*32});self.assertEqual(json.load(urllib.request.urlopen(req))['schema_version'],1)
   req=urllib.request.Request(base+'/api/entry',data=b'{"enabled":true}',headers={'Authorization':'Bearer '+'x'*32})
   with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(req)
   self.assertEqual(cm.exception.code,403)
  finally:server.shutdown();server.server_close();t.join()

if __name__=='__main__':unittest.main()
