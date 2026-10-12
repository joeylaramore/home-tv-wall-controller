import base64
import http.client
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import server


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        self.original = b'{"tvs": []}\n'
        self.path.write_bytes(self.original)
        patch = mock.patch.object(server, "CONFIG_PATH", self.path)
        patch.start()
        self.addCleanup(patch.stop)
        server.TVS[:] = []
        self.config = {"tvs": [
            {"name": "Left", "device_id": "id-a", "mac": "", "ip": "192.168.1.20"},
            {"name": "Right", "device_id": "", "mac": "aa:bb:cc:dd:ee:ff", "ip": ""},
        ]}

    def test_restore_preserves_previous_file_and_order(self):
        backup = server.save_config(self.config)
        self.assertEqual((self.path.parent / "config-backups" / backup).read_bytes(), self.original)
        self.assertEqual(json.loads(self.path.read_text()), self.config)
        self.assertEqual(server.TVS, self.config["tvs"])
        second = server.save_config({"tvs": []})
        self.assertEqual(json.loads((self.path.parent / "config-backups" / second).read_text()), self.config)

    def test_invalid_configs_do_not_modify_disk_or_memory(self):
        invalid = [None, [], {"tvs": {}}, {"tvs": [None]}, {"tvs": [{"name": "No identity"}]},
                   {"tvs": [{"name": "Public", "device_id": "a", "ip": "8.8.8.8"}]},
                   {"tvs": [{"name": "Bad address", "device_id": "a", "ip": "not-an-ip"}]},
                   {"tvs": [{"name": "a", "device_id": "same"}, {"name": "b", "device_id": "same"}]},
                   {"tvs": [{"name": "Bad MAC", "mac": "nope"}]},
                   {"tvs": [{"name": 42, "device_id": "a"}]}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                server.save_config(payload)
            self.assertEqual(self.path.read_bytes(), self.original)
            self.assertEqual(server.TVS, [])

    def test_failed_backup_or_replace_keeps_previous_configuration(self):
        real_write = server.atomic_write
        for failing_target in ("backup", "config"):
            def write(path, data):
                if (path == self.path) == (failing_target == "config"):
                    raise OSError("simulated disk failure")
                real_write(path, data)
            with self.subTest(failing_target=failing_target), mock.patch.object(server, "atomic_write", side_effect=write):
                with self.assertRaises(OSError):
                    server.save_config(self.config)
            self.assertEqual(self.path.read_bytes(), self.original)
            self.assertEqual(server.TVS, [])

    def test_network_listener_refuses_missing_password_or_tls(self):
        env = {**os.environ, "ROKU_CONFIG_PATH": str(self.path), "ROKU_WALL_PASSWORD": "", "ROKU_ALLOWED_CIDRS": ""}
        result = subprocess.run([sys.executable, str(server.ROOT / "server.py"), "--host", "0.0.0.0"], env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ROKU_WALL_PASSWORD", result.stderr)
        env["ROKU_WALL_PASSWORD"] = "test-secret"
        result = subprocess.run([sys.executable, str(server.ROOT / "server.py"), "--host", "0.0.0.0"], env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --cert and --key", result.stderr)

    def test_http_validation_backup_and_live_restore(self):
        httpd = server.http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.allowed_networks = server.LOCAL_NETWORKS
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def request(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
            try:
                conn.request(method, path, body, headers or {})
                response = conn.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                conn.close()

        with mock.patch.dict(os.environ, {"ROKU_WALL_PASSWORD": "test-secret"}):
            auth = {"Authorization": "Basic " + base64.b64encode(b"roku:test-secret").decode(), "Content-Type": "application/json"}
            self.assertEqual(request("GET", "/api/backup")[0], 401)
            self.assertEqual(request("HEAD", "/index.html")[0], 401)
            self.assertEqual(request("POST", "/api/restore", json.dumps(self.config), {**auth, "Origin": "https://evil.example"})[0], 403)
            self.assertEqual(request("POST", "/api/configure", json.dumps(self.config), {**auth, "Sec-Fetch-Site": "cross-site"})[0], 403)
            self.assertEqual(request("POST", "/api/restore", "{broken", auth)[0], 400)
            self.assertEqual(request("POST", "/api/restore", "{}", {**auth, "Content-Length": "invalid"})[0], 400)
            self.assertEqual(request("POST", "/api/restore", "{}", {**auth, "Content-Length": "262145"})[0], 400)
            self.assertEqual(request("POST", "/api/restore", "{}", {**auth, "Content-Type": "text/plain"})[0], 415)
            self.assertEqual(self.path.read_bytes(), self.original)
            status, _, body = request("POST", "/api/restore", json.dumps(self.config), auth)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["previous_backup"])
            status, headers, body = request("GET", "/api/backup", headers=auth)
            self.assertEqual(status, 200)
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertEqual(json.loads(body), self.config)
            self.assertEqual(json.loads(request("GET", "/api/tvs", headers=auth)[2])[1]["mac"], "aa:bb:cc:dd:ee:ff")

    def test_peer_filter_and_network_password_requirement(self):
        handler = object.__new__(server.Handler)
        handler.server = mock.Mock(allowed_networks=server.LOCAL_NETWORKS)
        handler.reply = mock.Mock()
        handler.headers = {}
        for address, allowed in (("192.168.1.5", True), ("10.8.0.2", True), ("8.8.8.8", False)):
            handler.client_address = (address, 1234)
            self.assertEqual(handler.allowed_client(), allowed)
        handler.client_address = ("100.64.1.2", 1234)
        self.assertFalse(handler.allowed_client())
        handler.server.allowed_networks += (server.ipaddress.ip_network("100.64.1.0/24"),)
        self.assertTrue(handler.allowed_client())
        with mock.patch.dict(os.environ, {"ROKU_WALL_PASSWORD": ""}):
            self.assertFalse(handler.authorized())
            handler.client_address = ("127.0.0.1", 1234)
            self.assertTrue(handler.authorized())


if __name__ == "__main__":
    unittest.main()
