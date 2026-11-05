"""Exercise current/future pricing and overrides against isolated mocked APIs."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
shots = Path(os.environ.get('WB_SHOTS', '/tmp/wb-pricing-ui'))
shots.mkdir(parents=True, exist_ok=True)
base = json.loads((root / 'server/services/pricing.json').read_text())
active = base['versions'][-1]
info = dict(currency='CNY', money_unit='元', versions=[active], active=active,
            is_peak_now=True, override=None, has_override=False,
            missing_holiday_years=[], stale_after_days=90, aliases={}, priced_models=[])
future = copy.deepcopy(active)
future.update(effective_from='2099-01-01', models={'future-only-model': active['models']['deepseek-flash']})
writes = []


def api(route):
    path = urlparse(route.request.url).path
    data = {}
    if path == '/api/me':
        data = dict(username='fixture', role='admin')
    elif path == '/api/upstreams':
        data = dict(items=[dict(id=1, name='测试分组', enabled=True, is_default=True)])
    elif path in ('/api/users', '/api/accounts'):
        data = [] if path.endswith('users') else dict(accounts=[], total=0)
    elif path == '/api/models':
        data = dict(models=[])
    elif path == '/api/settings/pricing':
        if route.request.method == 'PUT':
            body = route.request.post_data_json
            writes.append(body)
            info.update(override=body, has_override=bool(body),
                        versions=[active, future] if body else [active])
        data = info
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data))


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=os.environ.get('WB_CHROMIUM'))
    page = browser.new_page(viewport={'width': 1440, 'height': 1100}, locale='zh-CN')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("localStorage.setItem('workbuddy-manager:locale','zh-CN');localStorage.setItem('workbuddy-manager:dock-tip-dismissed','true')")
    page.route('**/api/**', api)
    page.goto(os.environ.get('WB_BASE', 'http://127.0.0.1:7960') + '/settings/models/', wait_until='networkidle')
    panel = page.get_by_text('计费价格（DeepSeek 官方价）', exact=True).locator('../../..')
    expect(panel.get_by_text(active['effective_from'], exact=True)).to_be_visible()
    override = panel.locator('textarea')
    override.fill('{invalid')
    panel.get_by_role('button', name='保存', exact=True).click()
    expect(page.get_by_text('价目不是合法的 JSON', exact=True)).to_be_visible()
    assert writes == []
    override.fill(json.dumps({'versions': [future]}))
    panel.get_by_role('button', name='保存', exact=True).click()
    expect(page.get_by_text('价目已保存', exact=True)).to_be_visible()
    expect(panel.get_by_text(active['effective_from'], exact=True)).to_be_visible()
    expect(panel.locator('table')).not_to_contain_text('future-only-model')
    assert len(writes) == 1 and writes[0]['versions'][0]['effective_from'] == '2099-01-01'
    page.screenshot(path=str(shots / 'pricing-future-desktop.png'))
    page.reload(wait_until='networkidle')
    expect(panel.get_by_text(active['effective_from'], exact=True)).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 1000})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(shots / 'pricing-mobile.png'))
    panel.get_by_role('button', name='恢复默认价目', exact=True).click()
    expect(override).to_have_value('')
    assert writes == [{'versions': [future]}, None]
    assert not errors, errors
    browser.close()
print('PASS: current pricing, invalid JSON, future override, reload, reset and mobile layout; mocked APIs only')
