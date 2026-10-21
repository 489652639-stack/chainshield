"""Bounded read-only DB adapter; writes only a separate atomic JSON snapshot.

Never imports the shadow worker, opens image caches, or changes source DBs.
"""
import argparse,json,math,os,pathlib,sqlite3,subprocess,time

SOURCE='/var/lib/chainshield-source-test/audit.sqlite3'
SHADOW='/var/lib/chainshield-shadow/shadow.sqlite3'
OUTPUT='/var/lib/chainshield-observe/snapshot.json'
SERVICES=('chainshield-source-test','chainshield-xfree-test','chainshield-shadow','chainshield-radar','caddy')

def connect(path):
 c=sqlite3.connect(pathlib.Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
 c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
 deadline=time.monotonic()+4
 c.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
 return c

def scalar(c,sql,args=()):return c.execute(sql,args).fetchone()[0]
def text(v,limit=4000):return str(v or '')[:limit]
def post(v):
 return {'post_id':text(v.get('post_id') or v.get('tweet_id'),40),'actor':text(v.get('actor') or v.get('author'),80),'content':text(v.get('content')),'url':text(v.get('url'),512),'published':v.get('published'),'received':v.get('received'),'expires':v.get('expires'),'time_basis':text(v.get('source_time_basis') or v.get('time_basis'),180)}
def coin(v):
 verified=v.get('chain_creation_verified') is True
 return {'mint':text(v.get('mint'),44),'name':text(v.get('name'),160),'symbol':text(v.get('symbol'),40),'event_received':v.get('event_received') or v.get('received'),'chain_created':v.get('chain_created') if verified else None}
def pair(v,audit=False):
 # Field whitelist prevents leaking cached URI, image data, raw events or secrets.
 out={k:v.get(k) for k in ('generated','evaluated','phase','delay_seconds','rule_version','human_status','group_id')}
 out.update(coin=coin(v.get('coin',{})),post=post(v.get('post',{})),grade='证据不足' if audit else text(v.get('grade'),20))
 t=v.get('text',{});out['text']={k:t[k] for k in ('reason','shared','specific','anchors','literal_anchors','eligible') if k in t}
 if isinstance(v.get('anchors'),list):out['anchors']=v['anchors'][:12]
 return out
def latencies(rows):
 out={}
 for phase in ('live','catchup','late_hotspot'):
  ds=sorted(v['delay_seconds'] for v in rows if v.get('phase')==phase and type(v.get('delay_seconds')) in (int,float) and math.isfinite(v['delay_seconds']))
  n=len(ds);out[phase]={'n':n,'median':(ds[n//2]+ds[(n-1)//2])/2 if n else None,'p95':ds[math.ceil(.95*n)-1] if n else None,'max':ds[-1] if n else None,'over10':sum(d>10 for d in ds)}
 return out
def service_status():
 result={}
 for name in SERVICES:
  try:
   raw=subprocess.check_output(['systemctl','show',name,'--property=ActiveState','--property=SubState','--property=MainPID','--property=NRestarts'],text=True,timeout=2)
   d=dict(line.split('=',1) for line in raw.splitlines() if '=' in line);result[name]={'active':d.get('ActiveState'),'sub':d.get('SubState'),'pid':d.get('MainPID'),'restarts':d.get('NRestarts')}
  except (OSError,subprocess.SubprocessError):result[name]={'active':'unknown'}
 return result

def build_snapshot(source=SOURCE,shadow=SHADOW,now=None,services=None):
 now=time.time() if now is None else now;day=math.floor((now+8*3600)/86400)*86400-8*3600
 s=connect(source);r=connect(shadow)
 try:
  cut_raw=scalar(r,"SELECT value FROM state WHERE key='v4_text_cutover'")
  cut=json.loads(cut_raw) if cut_raw is not None else None
  pred="json_extract(payload,'$.rule_version')='V4-text'";v4where=pred+' AND generated>=?';cut_arg=cut if type(cut) in (int,float) else now+1
  cs=[json.loads(x[0]) for x in r.execute('SELECT payload FROM candidates WHERE '+v4where+' ORDER BY generated DESC LIMIT 60',(cut_arg,))]
  audits=[json.loads(x[0]) for x in r.execute('SELECT payload FROM text_audit WHERE evaluated>=? ORDER BY evaluated DESC LIMIT 20',(cut_arg,))]
  posts=[post(dict(x)) for x in s.execute('SELECT tweet_id,author,content,url,published,received,expires,time_basis FROM tweets WHERE synthetic=0 AND content IS NOT NULL ORDER BY rowid DESC LIMIT 80')]
  counts={x['post_id']:scalar(r,'SELECT COUNT(DISTINCT mint) FROM candidates WHERE post_id=? AND '+v4where,(x['post_id'],cut_arg)) for x in posts}
  for p in posts:p['candidate_mints']=counts[p['post_id']]
  mints=[{'mint':x['mint'],'name':text(x['name'],160),'symbol':text(x['symbol'],40),'received':x['received'],'chain_created':None} for x in s.execute('SELECT mint,name,symbol,received FROM tokens WHERE synthetic=0 ORDER BY rowid DESC LIMIT 60')]
  accounts=[{'actor':x['author'],'received':x['received'],'published':x['published'],'count':x['n']} for x in s.execute('SELECT author,MAX(received) AS received,MAX(published) AS published,COUNT(*) AS n FROM tweets WHERE synthetic=0 GROUP BY author')]
  overview={'today_mints':scalar(s,'SELECT COUNT(*) FROM tokens WHERE synthetic=0 AND received>=?',(day,)),'total_source_mints':scalar(s,'SELECT COUNT(*) FROM tokens WHERE synthetic=0'),'evaluated':scalar(r,'SELECT COUNT(*) FROM coins WHERE evaluated=1'),'pending':scalar(r,'SELECT COUNT(*) FROM coins WHERE evaluated=0'),'errors':scalar(r,'SELECT COUNT(*) FROM errors'),'last_mint_received':mints[0]['received'] if mints else None,'v4_candidate_pairs':scalar(r,'SELECT COUNT(*) FROM candidates WHERE '+v4where,(cut_arg,)),'v4_candidate_mints':scalar(r,'SELECT COUNT(DISTINCT mint) FROM candidates WHERE '+v4where,(cut_arg,)),'v3_candidate_pairs':scalar(r,"SELECT COUNT(*) FROM candidates WHERE COALESCE(json_extract(payload,'$.rule_version'),'V3')!='V4-text'"),'weak_pairs':scalar(r,'SELECT COUNT(*) FROM text_audit WHERE evaluated>=?',(cut_arg,))}
  out={'schema_version':1,'generated_at':now,'v4_cutover':cut,'source':'现有X及PumpPortal监听 / V4-text；非人工真值','mode':'只读观察','trading_available':False,'overview':overview,'services':services if services is not None else service_status(),'accounts':accounts,'hotspots':posts,'mints':mints,'candidates':[pair(v) for v in cs],'audits':[pair(v,True) for v in audits],'latency_window':{'basis':'最近最多60条V4候选配对；接收至候选，不是链上创建至发现','phases':latencies(cs)},'limits':{'hotspots':80,'mints':60,'candidate_pairs':60,'audit_pairs':20},'human_precision':None,'human_recall':None}
  return out
 finally:s.close();r.close()

def write_snapshot(data,path=OUTPUT):
 raw=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
 if len(raw)>1_500_000:raise ValueError('snapshot exceeds size limit')
 p=pathlib.Path(path);tmp=p.with_suffix('.tmp')
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o640)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)

def main():
 p=argparse.ArgumentParser();p.add_argument('--stdout',action='store_true');args=p.parse_args();data=build_snapshot()
 if args.stdout:print(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')))
 else:write_snapshot(data)
if __name__=='__main__':main()
