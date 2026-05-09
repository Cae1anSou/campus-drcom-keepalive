import json
import os
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

import campus_keepalive as ck


class FakeResponse:
    def __init__(self, text, url="http://example.com/"):
        self._text = text.encode("utf-8")
        self._url = url

    def read(self, *_args):
        return self._text

    def geturl(self):
        return self._url

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
        current = self.responses.pop(0)
        if isinstance(current, FakeResponse):
            return current
        return FakeResponse(current)


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

    def test_login_places_credentials_before_trailing_common_params(self):
        opener = FakeOpener(['dr1003({"result":1,"uid":"test-user"});'])
        client = ck.DrcomClient("http://10.1.60.100", opener=opener)

        client.login("test-user", "secret")

        query_keys = [part.split("=", 1)[0] for part in urlparse(opener.urls[0]).query.split("&")]
        self.assertLess(query_keys.index("DDDDD"), query_keys.index("jsVersion"))
        self.assertLess(query_keys.index("upass"), query_keys.index("jsVersion"))
        self.assertLess(query_keys.index("terminal_type"), query_keys.index("jsVersion"))

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

    def test_ensure_online_logs_in_when_status_returns_html_error(self):
        opener = FakeOpener(
            [
                "<html><body>\r\nError code: 203 Bad request(2)\r\n</body></html>",
                'dr1003({"result":1,"uid":"test-user"});',
            ]
        )
        client = ck.DrcomClient("http://10.1.60.100", opener=opener)

        result = ck.ensure_online(client, "test-user", "secret")

        self.assertEqual(result["action"], "login")
        self.assertIn("not a JSONP response", result["status_error"])
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

    def test_discover_gateway_base_url_from_redirected_final_url(self):
        opener = FakeOpener(
            [
                FakeResponse(
                    "<html>portal</html>",
                    url="http://10.99.253.230/chkuser?url=example.com/",
                )
            ]
        )
        discovered = ck.discover_gateway_base_url("http://example.com/", opener=opener)
        self.assertEqual(discovered, "http://10.99.253.230")

    def test_discover_gateway_base_url_from_portal_html(self):
        opener = FakeOpener(
            [
                FakeResponse(
                    "v4serip='10.1.60.100'; v46ip='10.3.20.57';",
                    url="http://example.com/",
                )
            ]
        )
        discovered = ck.discover_gateway_base_url("http://example.com/", opener=opener)
        self.assertEqual(discovered, "http://10.1.60.100")

    def test_gateway_cache_roundtrip(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fp:
            path = fp.name
        try:
            ck.save_cached_gateway(path, "http://10.99.253.230/")
            cached = ck.load_cached_gateway(path)
            self.assertEqual(cached, "http://10.99.253.230")
        finally:
            os.unlink(path)

    def test_ensure_online_with_fallback_tries_next_gateway(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fp:
            cache_path = fp.name
        try:
            with mock.patch.object(
                ck,
                "_build_gateway_candidates",
                return_value=["http://10.1.60.100", "http://10.99.253.230"],
            ):
                with mock.patch.object(ck, "save_cached_gateway"):
                    def fake_ensure_online(client, username, password, service):
                        if client.base_url == "http://10.1.60.100":
                            return {"action": "login", "login": {"result": 0, "msg": "bad gateway"}, "status": {"result": 0}}
                        return {"action": "already_online", "status": {"result": 1, "uid": username}}

                    with mock.patch.object(ck, "ensure_online", side_effect=fake_ensure_online):
                        result = ck.ensure_online_with_fallback(
                            base_url="http://10.1.60.100",
                            username="test-user",
                            password="secret",
                            timeout=5,
                            cache_file=cache_path,
                            auto_discover_gateway=False,
                        )

            self.assertEqual(result["base_url"], "http://10.99.253.230")
            self.assertEqual(result["attempted_base_urls"], ["http://10.1.60.100", "http://10.99.253.230"])
        finally:
            os.unlink(cache_path)

    def test_ensure_online_with_fallback_passes_source_ip_to_client(self):
        created = []

        class RecordingClient:
            def __init__(self, base_url, timeout=10, source_ip=None):
                self.base_url = base_url
                self.timeout = timeout
                self.source_ip = source_ip
                created.append(self)

        with tempfile.NamedTemporaryFile("w", delete=False) as fp:
            cache_path = fp.name
        try:
            with mock.patch.object(ck, "_build_gateway_candidates", return_value=["http://10.99.253.230"]):
                with mock.patch.object(ck, "DrcomClient", RecordingClient):
                    with mock.patch.object(ck, "save_cached_gateway"):
                        with mock.patch.object(
                            ck,
                            "ensure_online",
                            return_value={"action": "already_online", "status": {"result": 1, "uid": "test-user"}},
                        ):
                            result = ck.ensure_online_with_fallback(
                                base_url="http://10.1.60.100",
                                username="test-user",
                                password="secret",
                                timeout=5,
                                cache_file=cache_path,
                                auto_discover_gateway=False,
                                source_ip="10.3.20.57",
                            )

            self.assertEqual(result["base_url"], "http://10.99.253.230")
            self.assertEqual(created[0].source_ip, "10.3.20.57")
        finally:
            os.unlink(cache_path)

    def test_parser_accepts_source_ip_and_interface_from_environment(self):
        old_source_ip = os.environ.get("CAMPUS_SOURCE_IP")
        old_interface = os.environ.get("CAMPUS_INTERFACE")
        try:
            os.environ["CAMPUS_SOURCE_IP"] = "10.3.20.57"
            os.environ["CAMPUS_INTERFACE"] = "enp7s0"

            args = ck._build_parser().parse_args([])

            self.assertEqual(args.source_ip, "10.3.20.57")
            self.assertEqual(args.interface, "enp7s0")
        finally:
            for key, old_value in [
                ("CAMPUS_SOURCE_IP", old_source_ip),
                ("CAMPUS_INTERFACE", old_interface),
            ]:
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value

    def test_interface_ipv4_info_parses_ip_and_prefix(self):
        with mock.patch.object(
            ck.subprocess,
            "check_output",
            return_value="2: enp7s0    inet 10.3.20.57/24 brd 10.3.20.255 scope global dynamic noprefixroute enp7s0\n",
        ):
            ip, prefix = ck.interface_ipv4_info("enp7s0")
        self.assertEqual(ip, "10.3.20.57")
        self.assertEqual(prefix, 24)

    def test_ensure_interface_policy_routing_applies_expected_commands(self):
        with mock.patch.object(
            ck,
            "interface_ipv4_info",
            return_value=("10.3.20.57", 24),
        ), mock.patch.object(
            ck,
            "interface_default_gateway",
            return_value="10.3.20.1",
        ), mock.patch.object(
            ck.subprocess,
            "run",
        ) as run_mock:
            run_mock.return_value = mock.Mock(returncode=0)
            state = ck.ensure_interface_policy_routing(
                interface="enp7s0",
                source_ip="10.3.20.57",
                table_id=103,
                rule_priority=100,
            )

        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertIn(
            ["ip", "-4", "route", "replace", "10.3.20.0/24", "dev", "enp7s0", "src", "10.3.20.57", "table", "103"],
            commands,
        )
        self.assertIn(
            ["ip", "-4", "route", "replace", "default", "via", "10.3.20.1", "dev", "enp7s0", "table", "103"],
            commands,
        )
        self.assertIn(
            ["ip", "-4", "rule", "add", "pref", "100", "from", "10.3.20.57/32", "table", "103"],
            commands,
        )
        self.assertEqual(state["network"], "10.3.20.0/24")
        self.assertEqual(state["gateway"], "10.3.20.1")

    def test_parser_accepts_policy_routing_env_overrides(self):
        old_values = {
            "CAMPUS_ENSURE_POLICY_ROUTING": os.environ.get("CAMPUS_ENSURE_POLICY_ROUTING"),
            "CAMPUS_POLICY_ROUTE_TABLE": os.environ.get("CAMPUS_POLICY_ROUTE_TABLE"),
            "CAMPUS_POLICY_RULE_PRIORITY": os.environ.get("CAMPUS_POLICY_RULE_PRIORITY"),
        }
        try:
            os.environ["CAMPUS_ENSURE_POLICY_ROUTING"] = "true"
            os.environ["CAMPUS_POLICY_ROUTE_TABLE"] = "103"
            os.environ["CAMPUS_POLICY_RULE_PRIORITY"] = "100"
            args = ck._build_parser().parse_args([])
            self.assertTrue(args.ensure_policy_routing)
            self.assertEqual(args.policy_route_table, 103)
            self.assertEqual(args.policy_rule_priority, 100)
        finally:
            for key, old_value in old_values.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value


if __name__ == "__main__":
    unittest.main()
