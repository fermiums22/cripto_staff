import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check_api


class CredentialTests(unittest.TestCase):
    def run_check(self, response):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'key'
            path.write_text('label\nTEST_KEY_ONLY\nTEST_SECRET_ONLY', encoding='utf-8')
            stream = io.BytesIO(json.dumps(response).encode())
            output = io.StringIO()
            with patch('check_api.urllib.request.build_opener') as opener, contextlib.redirect_stdout(output):
                opener.return_value.open.return_value = stream
                result = check_api.check(path)
            self.assertNotIn('TEST_KEY_ONLY', output.getvalue())
            self.assertNotIn('TEST_SECRET_ONLY', output.getvalue())
            return result, json.loads(output.getvalue())

    def test_write_key_does_not_enable_trading(self):
        result, output = self.run_check({'retCode': 0, 'result': {'readOnly': 0, 'ips': []}})
        self.assertEqual(result, 0)
        self.assertFalse(output['read_only'])
        self.assertFalse(output['real_trading_enabled'])

    def test_signing_error_does_not_leak_response(self):
        result, output = self.run_check({'retCode': 10004, 'retMsg': 'TEST_KEY_ONLY TEST_SECRET_ONLY'})
        self.assertEqual(result, 1)
        self.assertEqual(output, {'ok': False, 'code': 10004})
