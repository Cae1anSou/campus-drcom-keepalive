#!/usr/bin/env python3
"""Prefer one interface as default route when healthy; fail over to backup interface."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime


def _log(message: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def _run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def _ipv4_info(interface: str) -> tuple[str, int]:
    result = _run(["ip", "-4", "-o", "addr", "show", "dev", interface])
    match = re.search(r"\binet\s+([0-9]{1,3}(?:\.[0-9]{1,3}){3})/([0-9]{1,2})", result.stdout)
    if not match:
        raise RuntimeError(f"interface {interface!r} has no IPv4 address")
    return match.group(1), int(match.group(2))


def _default_gateway(interface: str) -> str | None:
    result = _run(["ip", "-4", "route", "show", "default", "dev", interface], check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    match = re.search(r"\bvia\s+([0-9]{1,3}(?:\.[0-9]{1,3}){3})\b", result.stdout)
    if not match:
        return None
    return match.group(1)


def _operstate(interface: str) -> str:
    path = f"/sys/class/net/{interface}/operstate"
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return fp.read().strip().lower()
    except OSError:
        return "unknown"


def _ping(target: str, source_ip: str, timeout_sec: int) -> bool:
    result = _run(
        [
            "ping",
            "-4",
            "-c",
            "1",
            "-W",
            str(max(timeout_sec, 1)),
            "-I",
            source_ip,
            target,
        ],
        check=False,
    )
    return result.returncode == 0


@dataclass
class InterfaceState:
    interface: str
    source_ip: str
    prefix: int
    gateway: str | None
    network: str


@dataclass
class ProbeDecision:
    healthy: bool
    reason: str


class RouteManager:
    def __init__(self, preferred: str, backup: str, preferred_metric: int, backup_metric: int) -> None:
        self.preferred = preferred
        self.backup = backup
        self.preferred_metric = preferred_metric
        self.backup_metric = backup_metric

    @staticmethod
    def _resolve(interface: str) -> InterfaceState:
        ip, prefix = _ipv4_info(interface)
        network = str(ipaddress.ip_interface(f"{ip}/{prefix}").network)
        gateway = _default_gateway(interface)
        return InterfaceState(interface=interface, source_ip=ip, prefix=prefix, gateway=gateway, network=network)

    @staticmethod
    def _replace_default(state: InterfaceState, metric: int) -> None:
        if state.gateway:
            command = [
                "ip",
                "-4",
                "route",
                "replace",
                "default",
                "via",
                state.gateway,
                "dev",
                state.interface,
                "metric",
                str(metric),
            ]
        else:
            command = [
                "ip",
                "-4",
                "route",
                "replace",
                "default",
                "dev",
                state.interface,
                "metric",
                str(metric),
            ]
        _run(command)

    def apply_preferred_active(self) -> tuple[InterfaceState, InterfaceState]:
        preferred_state = self._resolve(self.preferred)
        backup_state = self._resolve(self.backup)
        self._replace_default(preferred_state, self.preferred_metric)
        self._replace_default(backup_state, self.backup_metric)
        return preferred_state, backup_state

    def apply_backup_active(self) -> tuple[InterfaceState, InterfaceState]:
        preferred_state = self._resolve(self.preferred)
        backup_state = self._resolve(self.backup)
        self._replace_default(preferred_state, self.backup_metric)
        self._replace_default(backup_state, self.preferred_metric)
        return preferred_state, backup_state


def evaluate_preferred_health(preferred: str, probe_targets: list[str], timeout_sec: int) -> ProbeDecision:
    state = _operstate(preferred)
    if state not in ("up", "unknown"):
        return ProbeDecision(False, f"operstate={state}")

    try:
        source_ip, _prefix = _ipv4_info(preferred)
    except Exception as exc:
        return ProbeDecision(False, f"no-ipv4: {exc}")

    if not probe_targets:
        return ProbeDecision(True, "link-only")

    for target in probe_targets:
        if _ping(target, source_ip, timeout_sec):
            return ProbeDecision(True, f"probe-ok:{target}")
    return ProbeDecision(False, f"probe-failed:{','.join(probe_targets)}")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _env_targets() -> list[str]:
    raw = os.getenv("NPM_PROBE_TARGETS", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interface-aware default route manager")
    parser.add_argument("--preferred-interface", default=os.getenv("NPM_PREFERRED_INTERFACE", "enp7s0"))
    parser.add_argument("--backup-interface", default=os.getenv("NPM_BACKUP_INTERFACE", "wlp0s20f3"))
    parser.add_argument("--probe-target", action="append", dest="probe_targets")
    parser.add_argument("--probe-timeout", type=int, default=_env_int("NPM_PROBE_TIMEOUT", 1))
    parser.add_argument("--interval", type=int, default=_env_int("NPM_INTERVAL", 10))
    parser.add_argument("--preferred-metric", type=int, default=_env_int("NPM_PREFERRED_METRIC", 100))
    parser.add_argument("--backup-metric", type=int, default=_env_int("NPM_BACKUP_METRIC", 30000))
    parser.add_argument("--fail-threshold", type=int, default=_env_int("NPM_FAIL_THRESHOLD", 3))
    parser.add_argument("--recover-threshold", type=int, default=_env_int("NPM_RECOVER_THRESHOLD", 2))
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.preferred_interface == args.backup_interface:
        print("preferred and backup interface must be different", file=sys.stderr)
        return 2

    targets = args.probe_targets if args.probe_targets else _env_targets()
    manager = RouteManager(
        preferred=args.preferred_interface,
        backup=args.backup_interface,
        preferred_metric=args.preferred_metric,
        backup_metric=args.backup_metric,
    )

    mode = "preferred"
    fail_count = 0
    recover_count = 0
    last_log = ""

    while True:
        try:
            decision = evaluate_preferred_health(args.preferred_interface, targets, args.probe_timeout)
            if decision.healthy:
                fail_count = 0
                recover_count += 1
                if mode == "backup" and recover_count >= max(args.recover_threshold, 1):
                    pref_state, bak_state = manager.apply_preferred_active()
                    mode = "preferred"
                    recover_count = 0
                    message = (
                        f"switch->preferred reason={decision.reason} "
                        f"preferred={pref_state.interface}:{pref_state.source_ip} gw={pref_state.gateway} metric={args.preferred_metric} "
                        f"backup={bak_state.interface}:{bak_state.source_ip} gw={bak_state.gateway} metric={args.backup_metric}"
                    )
                    _log(message)
                    last_log = message
                elif mode == "preferred":
                    pref_state, bak_state = manager.apply_preferred_active()
                    message = (
                        f"stay-preferred reason={decision.reason} "
                        f"preferred={pref_state.interface}:{pref_state.source_ip} backup={bak_state.interface}:{bak_state.source_ip}"
                    )
                    if message != last_log:
                        _log(message)
                        last_log = message
            else:
                recover_count = 0
                fail_count += 1
                if mode == "preferred" and fail_count >= max(args.fail_threshold, 1):
                    pref_state, bak_state = manager.apply_backup_active()
                    mode = "backup"
                    fail_count = 0
                    message = (
                        f"switch->backup reason={decision.reason} "
                        f"preferred={pref_state.interface}:{pref_state.source_ip} gw={pref_state.gateway} metric={args.backup_metric} "
                        f"backup={bak_state.interface}:{bak_state.source_ip} gw={bak_state.gateway} metric={args.preferred_metric}"
                    )
                    _log(message)
                    last_log = message
                elif mode == "backup":
                    pref_state, bak_state = manager.apply_backup_active()
                    message = (
                        f"stay-backup reason={decision.reason} "
                        f"preferred={pref_state.interface}:{pref_state.source_ip} backup={bak_state.interface}:{bak_state.source_ip}"
                    )
                    if message != last_log:
                        _log(message)
                        last_log = message

        except Exception as exc:
            _log(f"error: {exc}")

        if args.once:
            return 0
        time.sleep(max(args.interval, 3))


if __name__ == "__main__":
    raise SystemExit(main())
