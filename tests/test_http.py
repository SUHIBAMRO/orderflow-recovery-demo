"""Real HTTP integration against the dependency-free verification runner."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port, cls.provider_port = free_port(), free_port()
        cls.tokens = {r: "integration-only-" + r + "-0123456789abcdef" for r in ("operator", "supervisor", "viewer")}
        env = dict(os.environ, **{r.upper()+"_TOKEN": t for r, t in cls.tokens.items()})
        cls.proc = subprocess.Popen([sys.executable, "-m", "orderflow.local", "--port", str(cls.port),
            "--provider-port", str(cls.provider_port), "--data", cls.tmp.name], env=env, stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/healthz", timeout=.2).close()
                return
            except OSError:
                time.sleep(.05)
        raise RuntimeError("Verification server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.tmp.cleanup()

    def call(self, path, payload=None, role="operator", key="http-create"):
        headers = {"Content-Type": "application/json", "Idempotency-Key": key}
        if role:
            headers["Authorization"] = "Bearer " + self.tokens[role]
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}"+path,
              data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def wait_status(self, ident, status):
        for _ in range(100):
            _, data = self.call('/api/orders/'+ident)
            if data['order']['status'] == status:
                return data['order']
            time.sleep(.1)
        self.fail(f"Did not reach {status}")

    def test_requires_authentication(self):
        self.assertEqual(self.call('/api/orders', role=None)[0], 401)

    def test_viewer_cannot_create(self):
        self.assertEqual(self.call('/api/orders', {'scenario':'success'}, role='viewer')[0], 403)

    def test_full_http_correction_workflow(self):
        code, created = self.call('/api/orders', {'scenario':'owner_mismatch'}, key='http-correction')
        self.assertEqual(code, 201)
        order = self.wait_status(created['id'], 'WAITING_CORRECTION')
        code, _ = self.call(f"/api/orders/{order['id']}/actions/correct_owner",
             {'note':'Verified synthetic correction', 'expected_version':order['version'], 'owner_last4':'5678'}, key='http-correct')
        self.assertEqual(code, 200)
        final = self.wait_status(order['id'], 'COMPLETED')
        self.assertEqual(final['policy_ref'], order['policy_ref'])

    def test_http_refund_role_gate(self):
        _, created = self.call('/api/orders', {'scenario':'blacklist'}, key='http-blacklist')
        order = self.wait_status(created['id'], 'REFUND_REQUIRED')
        path = f"/api/orders/{order['id']}/actions/approve_refund"
        payload = {'note':'Approved synthetic roadtax-only refund','expected_version':order['version']}
        self.assertEqual(self.call(path, payload, key='http-refund')[0], 403)
        self.assertEqual(self.call(path, payload, role='supervisor', key='http-refund')[0], 200)
        self.wait_status(order['id'], 'ROADTAX_REFUNDED')

    def test_static_assets_and_content_security_policy(self):
        for path in ['/', '/assets/app.js', '/assets/styles.css', '/assets/readability.css', '/assets/favicon.svg']:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}"+path) as r:
                self.assertEqual(r.status, 200)
                self.assertIn("default-src 'self'", r.headers['Content-Security-Policy'])
                self.assertGreater(len(r.read()), 50)


if __name__ == '__main__':
    unittest.main()
