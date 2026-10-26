"""All public chat protocols must disable upstream conversation storage."""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
from starlette.requests import Request
from server import config
from server.routers import gateway, responses, anthropic


class ForceNoStoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_forwarding_overrides_client_store(self):
        for path in ('/v1/chat/completions', '/v2/chat/completions'):
            for supplied in (None, True, False):
                with self.subTest(path=path, store=supplied):
                    body = {'model': 'deepseek-v4.1-flash', 'messages': [{'role': 'user', 'content': 'ping'}]}
                    if supplied is not None:
                        body['store'] = supplied
                    client = AsyncMock()
                    client.post.return_value = httpx.Response(200, json={'choices': [], 'usage': {}})
                    @asynccontextmanager
                    async def http_client(*args, **kwargs):
                        yield client
                    with patch.object(gateway, '_read_json_body', AsyncMock(return_value=(body, None))), \
                         patch.object(gateway, '_authorize', return_value=({'id': 1}, '127.0.0.1', None)), \
                         patch.object(gateway, '_map_model', return_value='deepseek-v4.1-flash'), \
                         patch.object(gateway, '_upstream_for', return_value=({'base_url': 'http://test'}, None)), \
                         patch.object(gateway, '_upstream_headers', return_value={}), \
                         patch.object(gateway, '_record'), \
                         patch.object(config, 'http_client', http_client):
                        result = await gateway._chat(Request({'type': 'http', 'headers': []}), path)
                    self.assertEqual(result.status_code, 200)
                    self.assertIs(client.post.call_args.kwargs['json'].get('store'), False)

    async def test_converters_force_no_store(self):
        for supplied in (None, True, False):
            for converter, body in (
                (responses.to_chat_request, {'model': 'test', 'input': 'ping'}),
                (anthropic.to_openai_request, {'model': 'test', 'messages': [{'role': 'user', 'content': 'ping'}]}),
            ):
                with self.subTest(converter=converter.__name__, store=supplied):
                    if supplied is not None:
                        body['store'] = supplied
                    self.assertIs(converter(body).get('store'), False)
