"""Verify exported login safety before hydration and normal form behavior.

Uses an isolated browser and synthetic credentials; never contacts production.
Run after web's build:export, with WB_CHROMIUM set if Chromium is not bundled.
"""
import functools
import os
from pathlib import Path
import re
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
shots = Path(os.environ.get('WB_SHOTS', str(Path(tempfile.gettempdir()) / 'wb-login-safety')))
shots.mkdir(parents=True, exist_ok=True)
credentials = {'username': 'fixture-user', 'password': 'fixture-not-real'}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(root / 'web/out')))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
        # Without JS, the real exported HTML must still prevent GET submission.
        static = browser.new_context(java_script_enabled=False)
        page = static.new_page()
        native_posts = []

        def native(route):
            if route.request.method == 'POST':
                native_posts.append(route.request)
                route.fulfill(status=200, content_type='text/html', body='<p>fixture POST received</p>')
            else:
                route.continue_()

        static.route('**/login/**', native)
        page.goto(base + '/login/')
        expect(page.locator('form')).to_have_attribute('method', 'post')
        expect(page.locator('button[type=submit]')).to_be_disabled()
        page.locator('#username').fill(credentials['username'])
        page.locator('#password').fill(credentials['password'])
        page.locator('#password').press('Enter')
        assert not native_posts, 'Enter before hydration must not submit the disabled form'
        # Explicit native submission exercises the POST fallback independently.
        with page.expect_request(lambda r: r.method == 'POST'):
            page.locator('form').evaluate('(form) => form.submit()')
        expect(page.get_by_text('fixture POST received', exact=True)).to_be_visible()
        assert len(native_posts) == 1
        assert not urlparse(native_posts[0].url).query
        assert 'password=fixture-not-real' in native_posts[0].post_data
        static.close()

        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='zh-CN')
        ctx.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN')")
        seen = []

        def api(route):
            path = urlparse(route.request.url).path
            if path == '/api/login':
                assert route.request.method == 'POST'
                assert not urlparse(route.request.url).query
                seen.append(route.request.post_data_json)
                if len(seen) == 1:
                    route.fulfill(status=401, json={'detail': '用户名或密码错误'})
                else:
                    route.fulfill(status=200, json={'ok': True, 'username': 'fixture-user', 'role': 'admin'})
            elif path == '/api/me':
                if len(seen) >= 2:
                    route.fulfill(status=200, json={'username': 'fixture-user', 'role': 'admin'})
                else:
                    route.fulfill(status=401, json={'detail': '未登录'})
            else:
                route.fulfill(status=200, json={})

        ctx.route('**/api/**', api)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto(base + '/login/')
        button = page.get_by_role('button', name='登录', exact=True)
        expect(button).to_be_enabled()
        page.wait_for_function("getComputedStyle(document.querySelector('form').parentElement).opacity === '1'")
        page.screenshot(path=str(shots / 'login-desktop.png'), full_page=True)
        # Simulate password-manager filling: DOM values, without React change events.
        page.locator('#username').evaluate('(el, value) => el.value = value', credentials['username'])
        page.locator('#password').evaluate('(el, value) => el.value = value', credentials['password'])
        button.click()
        expect(page.get_by_text('用户名或密码错误', exact=True)).to_be_visible()
        expect(button).to_be_enabled()
        assert seen == [credentials]
        assert not urlparse(page.url).query
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(shots / 'login-mobile-error.png'), full_page=True)
        assert not errors, errors
        page.locator('#username').fill(credentials['username'])
        page.locator('#password').fill(credentials['password'])
        button.click()
        expect(page).to_have_url(re.compile(r'/dashboard/?$'))
        assert seen == [credentials, credentials]
        ctx.close()
        browser.close()
    print('PASS: pre-hydration disabled/Enter, native POST fallback, hydrated JSON POST, DOM autofill, error/retry, success redirect and mobile layout; synthetic credentials only')
finally:
    server.shutdown()
    server.server_close()
