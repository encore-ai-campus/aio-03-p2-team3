import json
import unittest
from urllib.error import HTTPError

from Quotation_KEKOREA.agent.counterparties import load_company_profiles, upsert_company_profile
from Quotation_KEKOREA.tests.test_counterparties import PROFILE


class Response:
    def __init__(self, value): self.value = value
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.value).encode()


class CounterpartyApiTests(unittest.TestCase):
    env = {'SUPABASE_URL': 'https://test.supabase.co', 'SUPABASE_SECRET_KEY': 'test-server-secret'}

    def test_loads_server_only_directory_and_does_not_put_key_in_url(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return Response([PROFILE])
        self.assertEqual(load_company_profiles(self.env, opener=opener), [PROFILE])
        self.assertEqual(requests[0].get_header('Apikey'), 'test-server-secret')
        self.assertNotIn('test-server-secret', requests[0].full_url)
        self.assertIn('/kekorea_counterparties?', requests[0].full_url)

    def test_upsert_preserves_existing_unspecified_phone_and_verifies_written_fields(self):
        existing = {**PROFILE, 'phone': 'Test known phone', 'email': 'test@example.invalid'}
        writes = []
        def opener(request, timeout):
            if request.get_method() == 'GET': return Response([existing])
            payload = json.loads(request.data)
            writes.append(payload)
            return Response([payload])
        result = upsert_company_profile(self.env, {**PROFILE, 'contact': 'Changed Contact'}, opener=opener)
        self.assertEqual(result['phone'], 'Test known phone')
        self.assertEqual(result['contact'], 'Changed Contact')
        self.assertEqual(writes[0]['company_key'], 'DEAR_GLOW')

    def test_http_errors_do_not_echo_keys_or_personal_record_contents(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 403, 'private error details', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403') as ctx:
            load_company_profiles(self.env, opener=opener)
        self.assertNotIn('test-server-secret', str(ctx.exception))
        self.assertNotIn('private error details', str(ctx.exception))
