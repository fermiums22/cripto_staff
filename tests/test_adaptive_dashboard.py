import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
import agent
import dashboard


class AdaptiveDashboardTests(unittest.TestCase):
    def test_read_only_allowlist_and_partial_startup(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(agent,'ARTIFACTS',Path(temp)):
            server=dashboard.ThreadingHTTPServer(('127.0.0.1',0),dashboard.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with urllib.request.urlopen(base+'/api/adaptive') as response:
                    self.assertEqual(json.load(response)['live'],None)
                    self.assertIn("script-src 'self'",response.headers['Content-Security-Policy'])
                for path in ('/adaptive','/adaptive.js','/adaptive.css','/'):
                    with urllib.request.urlopen(base+path) as response:self.assertEqual(response.status,200)
                for path in ('/secrets/bybit.key','/../data/adaptive.sqlite3','/adaptive_protocol.json'):
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+path)
                    self.assertEqual(error.exception.code,404)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/adaptive',data=b'{}',method='POST'))
                self.assertEqual(error.exception.code,501)
            finally:
                server.shutdown();server.server_close();thread.join()
