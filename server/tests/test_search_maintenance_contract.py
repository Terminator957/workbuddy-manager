"""Search must retain key realm isolation and reject non-object JSON locally."""
import asyncio
import contextlib
import json
import unittest
from unittest import mock

from server.routers import gateway
from server.tests.test_gateway_tools_search import _request


class SearchMaintenanceContract(unittest.TestCase):
    def call(self, body, realm=''):
        posted = []

        @contextlib.asynccontextmanager
        async def client(*args, **kwargs):
            async def post(url, **kwargs):
                posted.append(kwargs['json'])
                return mock.Mock(status_code=200, json=lambda: {'code': 0}, text='{}')
            yield mock.Mock(post=post)

        with mock.patch.object(gateway, '_authorize', return_value=({'realm': realm}, '1.2.3.4', None)), \
             mock.patch.object(gateway, '_upstream_for', return_value=({'base_url': 'http://test', 'api_key': ''}, None)), \
             mock.patch.object(gateway, '_record'), \
             mock.patch.object(gateway.iputil, 'client_ip', return_value='1.2.3.4'), \
             mock.patch.object(gateway, 'tap_svc') as tap, \
             mock.patch.object(gateway.config, 'http_client', client):
            tap.enabled.return_value = False
            response = asyncio.run(gateway.tools_search(_request(json.dumps(body).encode())))
        return response, posted

    def test_non_object_json_is_400_without_upstream(self):
        for body in (None, [], [1], 'x', 1, True):
            with self.subTest(body=body):
                response, posted = self.call(body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(posted, [])

    def test_key_realm_overrides_client_search_realm(self):
        for key_realm, client_realm in (('global', 'cn'), ('cn', 'global')):
            with self.subTest(realm=key_realm):
                response, posted = self.call({'query': 'q', 'realm': client_realm}, key_realm)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(posted[0]['realm'], key_realm)

    def test_unscoped_key_keeps_optional_realm(self):
        response, posted = self.call({'query': 'q', 'realm': 'global'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(posted[0]['realm'], 'global')
