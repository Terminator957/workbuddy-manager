"""CORS form browser acceptance against a static export and isolated API fixtures."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
shots = Path(os.environ.get('WB_SHOTS', str(Path(tempfile.gettempdir())/'wb-gateway-cors')))
shots.mkdir(parents=True, exist_ok=True)
locale = json.loads((root/'web/lib/i18n/locales/zh-CN.json').read_text())
def t(key): return locale['gatewayCors'][key]
state = dict(enabled=False, origins=[], max_age=600, max_origins=64,
             prefixes=['/v1','/v2'], admin_origins=['https://admin.example.com'])
saved = []
fail_load = False

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(root/'web/out')))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
        context = browser.new_context(viewport={'width':1280,'height':1000}, locale='zh-CN')
        context.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN');localStorage.setItem('theme','light');localStorage.setItem('workbuddy-manager:dock-tip-dismissed','true')")
        def api(route):
            path = urlparse(route.request.url).path
            data, status = {}, 200
            if path == '/api/me': data = dict(username='fixture',role='admin')
            elif path == '/api/upstreams': data = dict(items=[])
            elif path == '/api/accounts': data = dict(accounts=[])
            elif path == '/api/users': data = []
            elif path == '/api/settings/gateway-cors':
                if route.request.method == 'PUT':
                    body = route.request.post_data_json
                    if 'invalid' in body['origins']:
                        status, data = 400, dict(detail='来源格式不对：invalid')
                    else:
                        state.update(body);state['origins']=[s.rstrip('/') for s in body['origins']]
                        saved.append(dict(state));data=state
                elif fail_load: status, data = 503, dict(detail='fixture unavailable')
                else: data = state
            elif path.startswith('/api/system/') or path in ('/api/settings/auto-update','/api/settings/github-mirror'):
                # Update-service controls are outside this fixture; exercise their existing error view.
                status, data = 503, dict(detail='fixture: update service unavailable')
            route.fulfill(status=status,content_type='application/json',body=json.dumps(data))
        context.route('**/api/**',api)
        page=context.new_page();errors=[];phase="initial"
        page.on('pageerror',lambda e:errors.append((phase,str(e))))
        page.on('console',lambda m: print('browser_error',m.text) if m.type=='error' and 'Failed to load resource' not in m.text else None)
        page.goto(f'http://127.0.0.1:{server.server_port}/settings/system/',wait_until='networkidle')
        title=page.get_by_text(t('title'),exact=True)
        expect(title).to_be_visible()
        toggle=page.get_by_role('switch',name=t('enable'),exact=True)
        origins=page.get_by_role('textbox',name=t('originPlaceholder'),exact=True)
        save=toggle.locator('..').locator('..').get_by_role('button',name=t('save'),exact=True)
        dirty=page.get_by_text(t('unsaved'),exact=True)
        expect(toggle).not_to_be_checked()
        toggle.click();origins.first.fill('https://app.example.com/')
        page.get_by_role('spinbutton',name=t('maxAge'),exact=True).fill('900')
        expect(dirty).to_be_visible();save.click();expect(dirty).to_be_hidden()
        expect(origins.first).to_have_value('https://app.example.com')
        assert saved[-1]['enabled'] and saved[-1]['max_age']==900
        phase='desktop_reload';page.reload(wait_until='networkidle')
        expect(toggle).to_be_checked();expect(origins.first).to_have_value('https://app.example.com')
        expect(dirty).to_be_hidden()
        page.get_by_role('button',name=t('addOrigin'),exact=True).click()
        origins.nth(1).fill('invalid');save.click()
        expect(page.get_by_text('来源格式不对：invalid',exact=True)).to_be_visible()
        expect(origins.nth(1)).to_have_value('invalid');expect(dirty).to_be_visible()
        origins.nth(1).fill('*');expect(page.get_by_text(t('wildcardWarn'),exact=True)).to_be_visible()
        expect(page.get_by_text('https://admin.example.com',exact=True)).to_be_visible()
        title.evaluate('e => window.scrollTo(0,window.scrollY + e.getBoundingClientRect().top - 80)')
        page.screenshot(path=str(shots/'gateway-cors-desktop.png'))
        page.set_viewport_size({'width':390,'height':1000})
        age=page.get_by_role('spinbutton',name=t('maxAge'),exact=True)
        age.fill('7200')
        assert age.bounding_box()['width'] >= 100, 'mobile cache input must show all four digits'
        age.scroll_into_view_if_needed()
        page.get_by_text('来源格式不对：invalid',exact=True).wait_for(state='hidden')
        page.screenshot(path=str(shots/'gateway-cors-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        phase='mobile_reload';fail_load=True;page.reload(wait_until='networkidle')
        failed=page.get_by_text(t('loadFailed'),exact=True)
        expect(failed).to_be_visible();fail_load=False
        failed.locator('..').get_by_role('button').click();expect(title).to_be_visible()
        assert not errors,errors
        context.close();browser.close()
    print('PASS: CORS default off, enable/origin/max-age save and reload, dirty state, validation error retention, wildcard warning, read-only admin list, retry, desktop/mobile no overflow or page errors; isolated API fixtures only')
finally:
    server.shutdown();server.server_close()
