"""Read a fixed bounded handoff file. No direct access to production SQLite."""
import json,pathlib,time
def read_snapshot(path='/var/lib/chainshield-observe/snapshot.json',now=None):
 p=pathlib.Path(path)
 with p.open('rb') as f:raw=f.read(1_500_001)
 if len(raw)>1_500_000:raise ValueError('snapshot size')
 v=json.loads(raw)
 if not isinstance(v,dict) or v.get('schema_version')!=1 or type(v.get('generated_at')) not in (int,float):raise ValueError('snapshot schema')
 age=(time.time() if now is None else now)-v['generated_at']
 if age< -60:raise ValueError('snapshot future timestamp')
 v['stale']=age>90;v['server_response_at']=time.time() if now is None else now
 return v
