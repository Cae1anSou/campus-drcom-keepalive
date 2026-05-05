import json
import os
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

import campus_keepalive as ck


class FakeResponse:
    def __init__(self, text):
        self._text = text.encode("utf-8")

    def read(self):
        return self._text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def open(self, url, timeout=10):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("no fake response left")
        return FakeResponse(self.responses.pop(0))


class CampusKeepaliveTests(unittest.TestCase):
    def test_parse_jsonp_response(self):
        payload = ck.parse_jsonp('dr1002({"result":1,"uid":"test-user"});')
        self.assertEqual(payload, {"result": 1, "uid": "test-user"})

    def test_status_uses_chkstatus_and_reports_online(self):
        opener = FakeOpener(['dr1002({"result":1,"uid":"test-user"});'])
        client = ck.DrcomClient("http://10.1.60.100", opener=opener)

        status = client.status()

        self.assertTrue(client.is_online(status, "test-user"))
        self.assertIn("/drcom/chkstatus?", opener.urls[0])

    def test_login_builds_drcom_login_request(self):
        opener = FakeOpener(['dr1003({"result":1,"uid":"test-user"});'])
        client = ck.DrcomClient("http://10.1.60.100", opener=opener)

        result = client.login("test-user", "secret")

        self.assertEqual(result["result"], 1)
        parsed = urlparse(opener.urls[0])
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/drcom/login")
        self.assertEqual(params["DDDDD"], ["test-user"])
        self.assertEqual(params["upass"], ["secret"])
        self.assertEqual(params["0MKKey"], ["123456"])
        self.assertEqual(params["terminal_type"], ["1"])

    def test_ensure_online_skips_login_when_already_online(self):
        opener = FakeOpener(['dr1002({"result":1,"uid":"test-user"});'])
        client = ck.DrcomClient("http://10.1.60.100", opener=opener)

        result = ck.ensure_online(client, "test-user", "secret")

        self.assertEqual(result["action"], "already_online")
        self.assertEqual(len(opener.urls), 1)

    def test_ensure_online_logs_in_when_offline(self):
        opener = FakeOpener(
            [
                'dr1002({"result":0});',
                'dr1003({"result":1,"uid":"test-user"});',
            ]
        )
        client = ck.DrcomClient("http://10.1.60.100", opener=opener)

        result = ck.ensure_online(client, "test-user", "secret")

        self.assertEqual(result["action"], "login")
        self.assertEqual(result["login"]["result"], 1)
        self.assertEqual(len(opener.urls), 2)

    def test_load_env_file_ignores_comments_and_preserves_existing_env(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fp:
            fp.write("# comment\n")
            fp.write("CAMPUS_USERNAME=test-user\n")
            fp.write("CAMPUS_PASSWORD='secret value'\n")
            fp.write("CAMPUS_INTERVAL=30 # inline comment\n")
            path = fp.name

        old_username = os.environ.get("CAMPUS_USERNAME")
        old_password = os.environ.get("CAMPUS_PASSWORD")
        old_interval = os.environ.get("CAMPUS_INTERVAL")
        try:
            os.environ["CAMPUS_USERNAME"] = "already-set"
            os.environ.pop("CAMPUS_PASSWORD", None)
            os.environ.pop("CAMPUS_INTERVAL", None)

            loaded = ck.load_env_file(path)

            self.assertEqual(loaded["CAMPUS_USERNAME"], "test-user")
            self.assertEqual(loaded["CAMPUS_PASSWORD"], "secret value")
            self.assertEqual(loaded["CAMPUS_INTERVAL"], "30")
            self.assertEqual(os.environ["CAMPUS_USERNAME"], "already-set")
            self.assertEqual(os.environ["CAMPUS_PASSWORD"], "secret value")
            self.assertEqual(os.environ["CAMPUS_INTERVAL"], "30")
        finally:
            os.unlink(path)
            for key, old_value in [
                ("CAMPUS_USERNAME", old_username),
                ("CAMPUS_PASSWORD", old_password),
                ("CAMPUS_INTERVAL", old_interval),
            ]:
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value


if __name__ == "__main__":
    unittest.main()
