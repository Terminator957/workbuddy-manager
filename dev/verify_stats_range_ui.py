"""Browser regression for historical custom usage ranges (mocked APIs only)."""
import functools
import json
import os
from pathlib import Path
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
shots = Path(os.environ.get('WB_SHOTS', str(Path(tempfile.gettempdir())/'wb-stats-range')))
shots.mkdir(parents=True, exist_ok=True)
seen = []

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

server = ThreadingHTTPServer(('127.0.0.1', 7965), functools.partial(Quiet, directory=str(root/'web/out')))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
        ctx = browser.new_context(viewport={'width':1440,'height':1000}, locale='zh-CN', timezone_id='Asia/Shanghai')
        ctx.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN');localStorage.setItem('theme','dark');localStorage.setItem('workbuddy-manager:dock-tip-dismissed','true')")
        def api(route):
            u = urlparse(route.request.url); path = u.path; q = parse_qs(u.query)
            seen.append((path,q))
            data = {}
            point = dict(day='2020-10-02', requests=3, prompt_tokens=150, completion_tokens=50, credit=1, failed=1, success=2)
            row = dict(account='历史测试号(12345678)', nickname='历史测试号', uid8='12345678', requests=3, tokens=200, credit=1, cost=None)
            if path == '/api/me': data = dict(username='fixture',role='admin')
            elif path == '/api/upstreams': data = dict(items=[dict(id=1,name='默认分组',auth_dir='/auths',enabled=True,is_default=True)])
            elif path == '/api/stats/daily': data = [point]
            elif path == '/api/stats/hourly': data = [dict(point,day=q.get('day',['2020-10-02'])[0],hour=13)]
            elif path in ('/api/stats/by-model','/api/stats/by-key'): data = []
            elif path == '/api/stats/by-account': data = dict(items=[dict(row,day='2020-10-02')])
            elif path == '/api/stats/by-account-model': data = dict(items=[dict(row,model='deepseek-v4.1-flash')])
            elif path == '/api/stats/upstream': data = dict(available=False)
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        ctx.route('**/api/**',api)
        page = ctx.new_page(); errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:7965/stats',wait_until='networkidle')
        expect(page.get_by_role('combobox',name='时间范围')).to_contain_text('今日')
        assert any(p=='/api/stats/hourly' for p,q in seen)
        page.get_by_role('combobox',name='时间范围').click()
        page.get_by_role('option',name='自定义',exact=True).click()
        page.get_by_label('开始日期',exact=True).fill('2020-10-01')
        page.get_by_label('结束日期',exact=True).fill('2020-10-03')
        page.wait_for_load_state('networkidle')
        axis = page.locator('.recharts-xAxis')
        expect(axis).to_contain_text('10-01')
        expect(axis).to_contain_text('10-03')
        for endpoint in ('daily','by-model','by-key','by-account','by-account-model'):
            assert any(p=='/api/stats/'+endpoint and q.get('start')==['2020-10-01'] and q.get('end')==['2020-10-03'] for p,q in seen),endpoint
        expect(page.locator('tbody tr').filter(has_text='历史测试号')).to_have_count(2)
        page.wait_for_function("[...document.querySelectorAll('.recharts-bar-rectangle path')].some(p => p.getBBox().height >= 220)")
        page.screenshot(path=str(shots/'custom-multiday-desktop.png'),full_page=True)
        page.get_by_label('开始日期',exact=True).fill('2020-10-02')
        page.get_by_label('结束日期',exact=True).fill('2020-10-02')
        page.wait_for_load_state('networkidle')
        assert any(p=='/api/stats/hourly' and q.get('day')==['2020-10-02'] for p,q in seen), 'historical single day must fetch its hourly data'
        expect(axis).to_contain_text('00:00')
        expect(page.locator('.recharts-bar-rectangle path').first).to_be_visible()
        page.wait_for_function("[...document.querySelectorAll('.recharts-bar-rectangle path')].some(p => p.getBBox().height >= 220)")
        page.screenshot(path=str(shots/'custom-singleday-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile horizontal overflow'
        page.wait_for_function("[...document.querySelectorAll('.recharts-bar-rectangle path')].some(p => p.getBBox().height >= 220)")
        page.screenshot(path=str(shots/'custom-range-mobile.png'),full_page=True)
        page.get_by_role('combobox',name='时间范围').click()
        page.get_by_role('option',name='今日',exact=True).click()
        expect(page.get_by_label('开始日期',exact=True)).to_have_count(0)
        assert not errors,errors
        browser.close()
    print('PASS: default today, historical multi-day axis and five query ranges, account tables, historical hourly fetch, mobile layout, return to today; mocked APIs')
finally:
    server.shutdown();server.server_close()
