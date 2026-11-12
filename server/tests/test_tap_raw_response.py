"""Trace Raw views retain captured bytes even when JSON parsing succeeds."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from server import db
from server.services import tap


class TapRawResponseTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(db.SCHEMA)
        self.db_patch = patch.object(db, '_conn', self.conn)
        self.db_patch.start()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.db_patch.stop)
        tap.save_settings({'enabled': True})

    def capture(self, protocol, raw, client=None, stream=False):
        turn_id = tap.capture(
            body={'model': 'test', 'messages': [{'role': 'user', 'content': 'ping'}]},
            headers=[], key=None, ua='fixture', path='/v1/chat/completions',
            protocol=protocol, status=200, stream=stream,
            text=raw, client_response=client,
        )
        self.assertIsNotNone(turn_id)
        return tap.turn_view(turn_id)

    def test_nonstream_chat_preserves_raw_json_for_both_views(self):
        raw = '{ "choices" : [{"message":{"content":"OK"}}] }\n'
        view = self.capture('chat', raw)
        self.assertTrue(view['response_ok'])
        self.assertEqual(view['response_raw'], raw)
        self.assertEqual(view['client_response_raw'], raw)
        self.assertEqual(view['response'], json.loads(raw))

    def test_stream_chat_reuses_upstream_raw_for_client_view(self):
        raw = 'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
        view = self.capture('chat', raw, stream=True)
        self.assertEqual(view['response_raw'], raw)
        self.assertEqual(view['client_response_raw'], raw)

    def test_translated_protocols_preserve_distinct_raw_json(self):
        upstream = '{ "choices": [{"message":{"content":"OK"}}] }\n'
        for protocol, client in (
            ('responses', '{ "output":[], "status":"completed" }\n'),
            ('anthropic', '{ "content":[{"type":"text","text":"OK"}] }\n'),
        ):
            with self.subTest(protocol=protocol):
                view = self.capture(protocol, upstream, client)
                self.assertEqual(view['response_raw'], upstream)
                self.assertEqual(view['client_response_raw'], client)
                self.assertTrue(view['client_response_ok'])

    def test_missing_translated_capture_stays_missing(self):
        view = self.capture('responses', '{"choices":[]}')
        self.assertIsNone(view['client_response_raw'])
        self.assertFalse(view['client_response_ok'])
