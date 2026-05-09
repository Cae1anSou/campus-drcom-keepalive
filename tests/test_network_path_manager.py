import unittest
from unittest import mock

import network_path_manager as npm


class NetworkPathManagerTests(unittest.TestCase):
    def test_evaluate_preferred_health_link_down(self):
        with mock.patch.object(npm, "_operstate", return_value="down"):
            decision = npm.evaluate_preferred_health("enp7s0", ["1.1.1.1"], 1)
        self.assertFalse(decision.healthy)
        self.assertIn("operstate=down", decision.reason)

    def test_evaluate_preferred_health_probe_success(self):
        with mock.patch.object(npm, "_operstate", return_value="up"), mock.patch.object(
            npm, "_ipv4_info", return_value=("10.3.20.57", 24)
        ), mock.patch.object(npm, "_ping", side_effect=[False, True]):
            decision = npm.evaluate_preferred_health("enp7s0", ["8.8.8.8", "1.1.1.1"], 1)
        self.assertTrue(decision.healthy)
        self.assertEqual(decision.reason, "probe-ok:1.1.1.1")

    def test_route_manager_apply_preferred(self):
        manager = npm.RouteManager("enp7s0", "wlp0s20f3", 100, 30000)
        with mock.patch.object(
            npm.RouteManager,
            "_resolve",
            side_effect=[
                npm.InterfaceState("enp7s0", "10.3.20.57", 24, "10.3.20.1", "10.3.20.0/24"),
                npm.InterfaceState("wlp0s20f3", "10.110.243.199", 19, "10.110.224.1", "10.110.224.0/19"),
            ],
        ), mock.patch.object(npm.RouteManager, "_replace_default") as replace:
            manager.apply_preferred_active()
        self.assertEqual(replace.call_count, 2)
        first_call = replace.call_args_list[0]
        second_call = replace.call_args_list[1]
        self.assertEqual(first_call.args[0].interface, "enp7s0")
        self.assertEqual(first_call.args[1], 100)
        self.assertEqual(second_call.args[0].interface, "wlp0s20f3")
        self.assertEqual(second_call.args[1], 30000)

    def test_route_manager_apply_backup(self):
        manager = npm.RouteManager("enp7s0", "wlp0s20f3", 100, 30000)
        with mock.patch.object(
            npm.RouteManager,
            "_resolve",
            side_effect=[
                npm.InterfaceState("enp7s0", "10.3.20.57", 24, "10.3.20.1", "10.3.20.0/24"),
                npm.InterfaceState("wlp0s20f3", "10.110.243.199", 19, "10.110.224.1", "10.110.224.0/19"),
            ],
        ), mock.patch.object(npm.RouteManager, "_replace_default") as replace:
            manager.apply_backup_active()
        self.assertEqual(replace.call_count, 2)
        first_call = replace.call_args_list[0]
        second_call = replace.call_args_list[1]
        self.assertEqual(first_call.args[0].interface, "enp7s0")
        self.assertEqual(first_call.args[1], 30000)
        self.assertEqual(second_call.args[0].interface, "wlp0s20f3")
        self.assertEqual(second_call.args[1], 100)


if __name__ == "__main__":
    unittest.main()
