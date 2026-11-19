"""Daily quota form and model-picker wheel scrolling; isolated mocked APIs only."""
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
shots = Path(os.environ.get('WB_SHOTS', str(Path(tempfile.gettempdir())/'wb-daily-quota')))
shots.mkdir(parents=True, exist_ok=True)
saved = []


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


server = ThreadingHTTPServer(('127.0.0.1', 7965), functools.partial(Quiet, directory=str(root/'web/out')))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
        context = browser.new_context(viewport={'width':1280, 'height':900}, locale='zh-CN')
        context.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN');localStorage.setItem('theme','dark');localStorage.setItem('workbuddy-manager:dock-tip-dismissed','true')")

        def api(route):
            path = urlparse(route.request.url).path
            data = {}
            if path == '/api/me': data = dict(username='fixture', role='admin')
            elif path == '/api/upstreams': data = dict(items=[])
            elif path == '/api/keys':
                if route.request.method == 'POST':
                    saved.append(route.request.post_data_json)
                    data = dict(id=1)  # No credential is created or displayed.
                else: data = []
            elif path == '/api/accounts': data = dict(accounts=[dict(realm='cn')])
            elif path == '/api/model-catalog':
                data = dict(models=[dict(id=f'model-{i:02}', tags=[]) for i in range(40)]+[dict(id='hy4flash-free',tags=[])])
            elif path == '/api/keys/check-models': data = dict(checked=True, unknown=[])
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))

        context.route('**/api/**', api)
        page = context.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:7965/keys', wait_until='networkidle')
        page.get_by_role('button',name='新建密钥',exact=True).first.click()
        dialog = page.get_by_role('dialog',name='新建密钥')
        dialog.get_by_placeholder('例如：客服组').fill('每日额度验收')
        daily = dialog.locator('label').filter(has_text='每日 Token 限额').locator('..').locator('input')
        expect(daily).to_have_value('0')
        daily.fill('1500')
        daily.scroll_into_view_if_needed()
        page.screenshot(path=str(shots/'daily-quota-desktop.png'))
        dialog.get_by_role('button',name='从清单选择',exact=True).click()
        popup = page.locator('[data-slot="popover-content"]')
        expect(popup).to_be_visible()
        assert popup.evaluate("e => !!e.closest('[data-slot=dialog-content]')")
        bounds=popup.bounding_box(); modal=dialog.bounding_box()
        assert bounds['y'] >= modal['y'] and bounds['y']+bounds['height'] <= modal['y']+modal['height'], 'model picker clipped by modal'
        popup.get_by_role('button',name='只看限时免费',exact=True).click()
        expect(popup.get_by_role('checkbox',name='hy4flash-free 免费',exact=True)).to_be_visible()
        expect(popup.get_by_role('checkbox',name='model-00',exact=True)).to_have_count(0)
        popup.get_by_role('button',name='只看限时免费',exact=True).click()
        scroll = popup.locator('.overflow-y-auto')
        scroll.hover(); page.mouse.wheel(0,650)
        page.wait_for_function("document.querySelector('[data-slot=popover-content] .overflow-y-auto').scrollTop > 100")
        popup.get_by_role('checkbox',name='model-30',exact=True).click()
        page.screenshot(path=str(shots/'model-picker-wheel.png'))
        page.keyboard.press('Escape')
        dialog.get_by_role('button',name='创建',exact=True).click()
        expect(dialog).to_be_hidden()
        assert saved[-1]['daily_quota'] == 1500 and saved[-1]['models'] == ['model-30'], saved
        page.set_viewport_size({'width':390,'height':900})
        page.get_by_role('button',name='新建密钥',exact=True).first.click()
        expect(dialog).to_be_visible()
        expect(daily).to_have_value('0')
        daily.scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(shots/'daily-quota-mobile.png'))
        assert not errors, errors
        context.close(); browser.close()
    print('PASS: daily quota default=0, save=1500, model whitelist wheel works inside modal, selection saved, modal collision bounds and free suffix filter verified, 390px form has no overflow, no page errors; mocked APIs only')
finally:
    server.shutdown(); server.server_close()
