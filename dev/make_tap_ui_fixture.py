"""Generate only synthetic Trace Tap data in a disposable database.

From the repository's Python runtime:
    python dev/make_tap_ui_fixture.py > /tmp/workbuddy-tap-fixture.json
Then run dev/verify_tap_raw_ui.py against the static export.
No existing database, credentials or upstream connection is used.
"""
import os, tempfile, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as tmp:
 for name in list(os.environ):
  if name.startswith(('WB_','WB2API_','WORKBUDDY_')): os.environ.pop(name)
 os.environ.update(WB_DATA_DIR=tmp, WB_AUTH_DIR=tmp+'/auths', WB_DB=tmp+'/fixture.db')
 from server import db
 from server.services import tap
 assert tap.settings()['enabled'] is False
 tap.save_settings({'enabled': True})
 ids=[]
 messages=[{'role':'user','content':'说明维护验证流程'}]
 for seq in (1,2):
  if seq==2: messages += [{'role':'assistant','content':'先检查，再验证。'},{'role':'user','content':'第二步是什么？'}]
  body={'model':'global:deepseek-v4.1-flash','messages':list(messages),'store':True}
  payload={'choices':[{'message':{'role':'assistant','content':'这是第 %s 轮模拟回复。'%seq},'finish_reason':'stop'}]}
  turn=tap.capture(body=body,headers=[],key=None,ua='deepseek-harness/0.2.2',path='/v1/chat/completions',protocol='chat',status=200,latency_ms=300,stream=False,payload=payload,usage={'prompt_tokens':30,'completion_tokens':10},upstream_body={**body,'model':'deepseek-v4.1-flash','store':False},client_response=payload)
  assert turn
  ids.append(turn)
 sessions=tap.list_sessions();sid=sessions['items'][0]['id']
 out={'config':{'config':tap.settings(),'stats':tap.stats()},'sessions':sessions,'session':tap.session(sid),'turns':{str(i):tap.turn_view(i) for i in ids},'diff':tap.diff(*ids),'export':tap.export_html(sid)}
 assert out['session']['turns']==2
 db._conn.close();db._conn=None
 print(json.dumps(out,ensure_ascii=False))
