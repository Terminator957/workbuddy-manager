"""Realtime stats polling, range isolation and failure feedback on the static export.

All API traffic is mocked; no credentials or production requests are used.
"""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
shots = Path(os.environ.get('WB_SHOTS', str(Path(tempfile.gettempdir())/'wb-realtime-stats')))
shots.mkdir(parents=True, exist_ok=True)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


server = ThreadingHTTPServer(('127.0.0.1', 7966), functools.partial(Quiet, directory=str(root/'web/out')))
threading.Thread(target=server.serve_forever, daemon=True).start()
state = dict(mode='ok', requests=0)
held = []


def realtime(days=1):
    return dict(available=state['mode'] != 'unavailable', days=days, updated_at=int(time.time())-90,
                inflight=3, client_inflight=5, capacity=11, rpm_60=12, rpm_3m=8, rpm_5m=9,
                peaks=dict(concurrency=7 if days == 1 else 9, rpm=20),
                series=dict(start=int(time.time())-180, step=5,
                            concurrency=[i % 5 for i in range(36)], rpm=[i % 15 for i in range(36)]))


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
        context = browser.new_context(viewport={'width':1280, 'height':900}, locale='zh-CN')
        context.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN');localStorage.setItem('theme','dark');localStorage.setItem('workbuddy-manager:dock-tip-dismissed','true')")

        def api(route):
            url = urlparse(route.request.url)
            path = url.path
            data = {}
            if path == '/api/me': data = dict(username='fixture', role='admin', admin=True)
            elif path == '/api/stats/realtime':
                state['requests'] += 1
                if state['mode'] == 'hold':
                    held.append(route)
                    return
                if state['mode'] == 'failure':
                    route.fulfill(status=503, json=dict(detail='fixture temporarily unavailable'))
                    return
                data = realtime(int(parse_qs(url.query).get('days', ['1'])[0]))
            elif path == '/api/stats/summary':
                data = {f'{span}_{field}':0 for span in ('today','week','total')
                        for field in ('requests','tokens','credit','cost','unpriced')}
                data.update(active_keys=1, top_model=None, cost_currency='CNY')
            elif path in ('/api/stats/daily','/api/stats/hourly','/api/stats/by-model','/api/stats/by-key'):
                data = []
            elif path in ('/api/stats/by-account','/api/stats/by-account-model'): data = dict(items=[])
            elif path == '/api/stats/upstream': data = dict(available=False)
            elif path == '/api/account-risk': data = dict(warnings=[], paused_count=0)
            elif path == '/api/announcements': data = dict(items=[])
            route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

        context.route('**/api/**', api)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:7966/stats/')
        strip = page.locator('section').filter(has=page.get_by_text('当前并发', exact=True))
        expect(strip).to_contain_text('客户端在途 5 · 峰值 7 · 上限 11')
        expect(strip).to_contain_text('3 分钟均 8')
        first = state['requests']
        page.wait_for_timeout(1300)
        assert state['requests'] > first, 'one-second polling did not refresh'

        # Hold an old poll while changing range; releasing it must not overwrite the new peak.
        state['mode'] = 'hold'
        page.wait_for_timeout(1200)
        assert held, 'old poll was not held'
        state['mode'] = 'ok'
        page.get_by_role('combobox', name='时间范围').click()
        page.get_by_role('option', name='近 7 天', exact=True).click()
        expect(strip).to_contain_text('客户端在途 5 · 峰值 9 · 上限 11')
        for route in held:
            route.fulfill(status=200, json=realtime(1))
        page.wait_for_timeout(250)
        expect(strip).to_contain_text('峰值 9 · 上限 11')
        for width in (1280, 390):
            page.set_viewport_size(dict(width=width, height=900))
            page.wait_for_timeout(400)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(shots/f'realtime-{width}.png'), full_page=True)

        state['mode'] = 'failure'
        expect(strip).to_contain_text('分钟前', timeout=5000)
        expect(strip).to_contain_text('峰值 9 · 上限 11')
        state['mode'] = 'unavailable'
        expect(strip).to_contain_text('上游不可达', timeout=5000)
        expect(strip).to_contain_text('3 分钟均 8')
        assert '上限 11' not in strip.inner_text(), 'unknown capacity must not look current'
        assert not errors, errors
        context.close()
        browser.close()
        print('PASS: one-second polling, range response isolation, desktop/mobile render, stale and unavailable states, no page errors')
finally:
    server.shutdown()
