"""Trace Raw, privacy-view and responsive regression using mocked APIs only.

Build web/out and serve it at localhost:7961, then generate the fixture using
dev/make_tap_ui_fixture.py. Run with Playwright installed. Optional variables:
WB_BASE, WB_CHROMIUM, WB_TAP_FIXTURE, WB_SHOTS. All API calls are intercepted;
toggling capture in this test never changes a live server.
"""
import json, os, tempfile
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
root=Path(os.environ.get('WB_SHOTS', str(Path(tempfile.gettempdir())/'workbuddy-tap-ui')))
root.mkdir(parents=True,exist_ok=True)
fixture=json.loads(Path(os.environ.get('WB_TAP_FIXTURE', '/tmp/workbuddy-tap-fixture.json')).read_text())
mutations=[]
state={'enabled':False}
def api(route):
 path=urlparse(route.request.url).path
 if path=='/api/me': data={'username':'fixture-admin','role':'admin'}
 elif path=='/api/tap/config':
  if route.request.method=='PUT':
   body=route.request.post_data_json;mutations.append(body);state.update(body)
  data={**fixture['config'],'config':{**fixture['config']['config'],**state}}
 elif path=='/api/tap/sessions':data=fixture['sessions'] if state['enabled'] else {'total':0,'items':[]}
 elif path=='/api/tap/sessions/1':data=fixture['session']
 elif path.startswith('/api/tap/turns/'): data=fixture['turns'][path.rsplit('/',1)[-1]]
 elif path=='/api/tap/diff':data=fixture['diff']
 elif path=='/api/tap/sessions/1/export':
  route.fulfill(status=200,content_type='text/html',headers={'Content-Disposition':'attachment; filename="fixture.html"'},body=fixture['export']);return
 else:data={}
 route.fulfill(status=200,content_type='application/json',body=json.dumps(data,ensure_ascii=False))
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
 for name,width,height in [('desktop',1440,1000),('mobile',390,844)]:
  state['enabled']=False
  ctx=browser.new_context(viewport={'width':width,'height':height},locale='zh-CN')
  ctx.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN');localStorage.setItem('wb.realm','global')")
  ctx.route('**/api/**',api);page=ctx.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(os.environ.get('WB_BASE','http://127.0.0.1:7961').rstrip('/')+'/traces/',wait_until='networkidle')
  expect(page.get_by_text('尚未开启调用抓包',exact=True)).to_be_visible()
  expect(page.locator('#tap-enabled')).to_have_attribute('aria-checked','false')
  page.screenshot(path=str(root/f'{name}-off.png'),full_page=True)
  page.locator('#tap-enabled').click()
  expect(page.get_by_role('button',name='#2',exact=True)).to_be_visible()
  page.get_by_role('button',name='请求',exact=True).click()
  page.get_by_role('button',name='Raw',exact=True).click()
  expect(page.get_by_role('heading',name='请求体',exact=True)).to_be_visible()
  expect(page.locator('pre').filter(has_text='"store": true')).to_be_visible()
  page.get_by_role('button',name='网关',exact=True).click()
  expect(page.locator('pre').filter(has_text='"store": false')).to_be_visible()
  page.screenshot(path=str(root/f'{name}-request.png'),full_page=True)
  page.get_by_role('button',name='响应',exact=True).click()
  expect(page.locator('pre').filter(has_text='这是第 2 轮模拟回复。')).to_be_visible()
  page.get_by_role('button',name='与上一轮对比',exact=True).click()
  expect(page.get_by_text('消息 1 → 3 条',exact=True)).to_be_visible()
  page.screenshot(path=str(root/f'{name}-diff.png'),full_page=True)
  if page.evaluate('document.documentElement.scrollWidth > innerWidth+1'):
   print(page.evaluate("Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})).slice(0,22)"),flush=True)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),name+' overflow'
  assert not errors,(name, errors)
  ctx.close()
 browser.close()
assert mutations and all(x=={'enabled':True} for x in mutations),mutations
print('PASS: desktop/mobile disabled default, fixture-only toggle, latest turn, client true/gateway false, response, diff, no horizontal overflow or page errors')
