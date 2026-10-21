"""Only invalid gateway credentials should trigger the credential-ban signal."""
import unittest
from server.routers import gateway, anthropic


class CredentialFailureHeaderTest(unittest.TestCase):
    def test_openai_invalid_key_only(self):
        self.assertEqual(gateway._oai_error('invalid', 401, code='invalid_api_key').headers.get('X-Credential-Failure'), '1')
        self.assertNotIn('X-Credential-Failure', gateway._oai_error('upstream unauthorized', 401).headers)
        self.assertNotIn('X-Credential-Failure', gateway._oai_error('forbidden', 403, code='invalid_api_key').headers)

    def test_anthropic_invalid_key_only(self):
        self.assertEqual(anthropic._err('API Key 无效', 401).headers.get('X-Credential-Failure'), '1')
        self.assertNotIn('X-Credential-Failure', anthropic._err('upstream unauthorized', 401).headers)
        self.assertNotIn('X-Credential-Failure', anthropic._err('API Key 无效', 403).headers)
