#!/usr/bin/env python3
"""Keep a Dr.COM campus network session online.

The script only calls the login endpoint after chkstatus reports the host is
offline. Credentials are read from environment variables or CLI flags.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import build_opener


DEFAULT_BASE_URL = "http://10.1.60.100"
DEFAULT_JS_VERSION = "4.2.1"


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    for index, char in enumerate(value):
        if char in ("'", '"'):
            quote = char if quote is None else None if quote == char else quote
        elif char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env_file(path: str, override: bool = False) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path or not os.path.exists(path):
        return loaded

    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = _unquote(_strip_inline_comment(value.strip()))
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            loaded[key] = value
            if override or key not in os.environ:
                os.environ[key] = value
    return loaded


def parse_jsonp(text: str) -> dict[str, Any]:
    match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", text.strip(), re.S)
    if not match:
        raise ValueError(f"not a JSONP response: {text[:120]!r}")
    return json.loads(match.group(1))


def _callback() -> str:
    return f"dr{random.randint(1000, 9999)}"


@dataclass
class DrcomClient:
    base_url: str = DEFAULT_BASE_URL
    timeout: int = 10
    js_version: str = DEFAULT_JS_VERSION
    opener: Any | None = None

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if self.opener is None:
            self.opener = build_opener()

    def _get_jsonp(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query: dict[str, Any] = {
            "callback": _callback(),
            "jsVersion": self.js_version,
            "v": random.randint(500, 10499),
            "lang": "zh",
        }
        if params:
            query.update(params)
        url = f"{self.base_url}{path}?{urlencode(query)}"
        with self.opener.open(url, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return parse_jsonp(raw)

    def status(self) -> dict[str, Any]:
        return self._get_jsonp("/drcom/chkstatus")

    def login(self, username: str, password: str, service: str = "") -> dict[str, Any]:
        params = {
            "DDDDD": f"{username}{service}",
            "upass": password,
            "0MKKey": "123456",
            "R1": "",
            "R2": "",
            "R3": "",
            "R6": "0",
            "para": "",
            "v6ip": "",
            "terminal_type": "1",
        }
        return self._get_jsonp("/drcom/login", params)

    @staticmethod
    def is_online(status: dict[str, Any], username: str | None = None) -> bool:
        if status.get("result") != 1:
            return False
        if username and status.get("uid") and str(status["uid"]) != username:
            return False
        return True


def ensure_online(
    client: DrcomClient,
    username: str,
    password: str,
    service: str = "",
) -> dict[str, Any]:
    status_error = ""
    try:
        status = client.status()
    except ValueError as exc:
        status = {"result": 0}
        status_error = str(exc)
    else:
        if client.is_online(status, username):
            return {"action": "already_online", "status": status}

    login_result = client.login(username, password, service)
    result = {"action": "login", "status": status, "login": login_result}
    if status_error:
        result["status_error"] = status_error
    return result


def _log(message: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dr.COM campus network auto connect and keepalive")
    parser.add_argument("--env-file", default=os.getenv("CAMPUS_ENV_FILE", ".env"))
    parser.add_argument("--base-url", default=os.getenv("CAMPUS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--username", default=os.getenv("CAMPUS_USERNAME"))
    parser.add_argument("--password", default=os.getenv("CAMPUS_PASSWORD"))
    parser.add_argument(
        "--service",
        default=os.getenv("CAMPUS_SERVICE", ""),
        help="optional account suffix such as @dx or @lt; leave empty for campus user",
    )
    parser.add_argument("--interval", type=int, default=int(os.getenv("CAMPUS_INTERVAL", "60")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("CAMPUS_TIMEOUT", "10")))
    parser.add_argument("--once", action="store_true", help="check once and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", default=os.getenv("CAMPUS_ENV_FILE", ".env"))
    pre_args, _ = pre_parser.parse_known_args(argv)
    load_env_file(pre_args.env_file)

    args = _build_parser().parse_args(argv)
    if not args.username or not args.password:
        print(
            "missing credentials: set CAMPUS_USERNAME and CAMPUS_PASSWORD or pass --username/--password",
            file=sys.stderr,
        )
        return 2

    client = DrcomClient(args.base_url, timeout=args.timeout)
    while True:
        try:
            result = ensure_online(client, args.username, args.password, args.service)
            if result["action"] == "already_online":
                status = result["status"]
                _log(f"online uid={status.get('uid', '')} ip={status.get('v46ip') or status.get('v4ip', '')}")
            else:
                login_result = result["login"]
                _log(f"login attempted result={login_result.get('result')} msg={login_result.get('msg', '')}")
        except Exception as exc:
            _log(f"error: {exc}")
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    raise SystemExit(main())
