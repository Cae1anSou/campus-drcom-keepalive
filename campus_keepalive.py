#!/usr/bin/env python3
"""Keep a Dr.COM campus network session online.

The script only calls the login endpoint after chkstatus reports the host is
offline. Credentials are read from environment variables or CLI flags.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import random
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlencode
from urllib.request import HTTPHandler, HTTPSHandler, build_opener


DEFAULT_BASE_URL = "http://10.1.60.100"
DEFAULT_JS_VERSION = "4.2.1"
DEFAULT_PROBE_URL = "http://example.com/"
DEFAULT_GATEWAY_CACHE_FILE = ".campus_gateway_cache"


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


class SourceBoundHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, source_ip: str, **kwargs: Any) -> None:
        super().__init__(*args, source_address=(source_ip, 0), **kwargs)


class SourceBoundHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, source_ip: str, **kwargs: Any) -> None:
        super().__init__(*args, source_address=(source_ip, 0), **kwargs)


class SourceBoundHTTPHandler(HTTPHandler):
    def __init__(self, source_ip: str) -> None:
        super().__init__()
        self.source_ip = source_ip

    def http_open(self, req: Any) -> Any:
        return self.do_open(
            lambda host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT: SourceBoundHTTPConnection(
                host,
                timeout=timeout,
                source_ip=self.source_ip,
            ),
            req,
        )


class SourceBoundHTTPSHandler(HTTPSHandler):
    def __init__(self, source_ip: str) -> None:
        super().__init__()
        self.source_ip = source_ip

    def https_open(self, req: Any) -> Any:
        return self.do_open(
            lambda host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs: SourceBoundHTTPSConnection(
                host,
                timeout=timeout,
                source_ip=self.source_ip,
                **kwargs,
            ),
            req,
        )


def build_source_bound_opener(source_ip: str) -> Any:
    return build_opener(SourceBoundHTTPHandler(source_ip), SourceBoundHTTPSHandler(source_ip))


def interface_ipv4_address(interface: str) -> str:
    command = ["ip", "-4", "-o", "addr", "show", "dev", interface]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"cannot resolve IPv4 address for interface {interface!r}") from exc

    match = re.search(r"\binet\s+([0-9]{1,3}(?:\.[0-9]{1,3}){3})/", output)
    if not match:
        raise RuntimeError(f"interface {interface!r} has no IPv4 address")
    return match.group(1)


def resolve_source_ip(source_ip: str | None = None, interface: str | None = None) -> str | None:
    if source_ip and interface:
        raise ValueError("use either source_ip or interface, not both")
    if source_ip:
        return source_ip
    if interface:
        return interface_ipv4_address(interface)
    return None


def _normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _is_private_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _base_url_from_candidate_url(candidate_url: str, probe_url: str) -> str | None:
    parsed = urlparse(candidate_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    probe_host = urlparse(probe_url).hostname or ""
    host = parsed.hostname or ""
    lower_path = parsed.path.lower()
    has_portal_hint = "drcom" in lower_path or "chkuser" in lower_path or "drcom" in parsed.query.lower()

    if host and host != probe_host and (_is_private_ip(host) or has_portal_hint):
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return None


def _gateway_from_portal_html(html: str) -> str | None:
    patterns = [
        r"v4serip=['\"]([0-9]{1,3}(?:\.[0-9]{1,3}){3})['\"]",
        r"v46ip=['\"]([0-9]{1,3}(?:\.[0-9]{1,3}){3})['\"]",
        r"http://([0-9]{1,3}(?:\.[0-9]{1,3}){3})/chkuser",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match and _is_private_ip(match.group(1)):
            return f"http://{match.group(1)}"
    return None


def discover_gateway_base_url(
    probe_url: str = DEFAULT_PROBE_URL,
    timeout: int = 10,
    source_ip: str | None = None,
    opener: Any | None = None,
) -> str | None:
    if opener is None:
        opener = build_source_bound_opener(source_ip) if source_ip else build_opener()

    try:
        with opener.open(probe_url, timeout=timeout) as response:
            final_url = response.geturl()
            html = response.read(8192).decode("utf-8", errors="replace")
    except Exception:
        return None

    by_url = _base_url_from_candidate_url(final_url, probe_url)
    if by_url:
        return by_url
    return _gateway_from_portal_html(html)


def load_cached_gateway(path: str) -> str | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            cached = fp.read().strip()
    except OSError:
        return None

    if not cached:
        return None
    parsed = urlparse(cached)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return _normalize_base_url(cached)


def save_cached_gateway(path: str, base_url: str) -> None:
    if not path:
        return
    normalized = _normalize_base_url(base_url)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(normalized + "\n")


@dataclass
class DrcomClient:
    base_url: str = DEFAULT_BASE_URL
    timeout: int = 10
    js_version: str = DEFAULT_JS_VERSION
    source_ip: str | None = None
    opener: Any | None = None

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if self.opener is None:
            self.opener = build_source_bound_opener(self.source_ip) if self.source_ip else build_opener()

    def _get_jsonp(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query: dict[str, Any] = {"callback": _callback()}
        if params:
            query.update(params)
        query["jsVersion"] = self.js_version
        query["v"] = random.randint(500, 10499)
        query["lang"] = "zh"
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


def _login_succeeded(result: dict[str, Any]) -> bool:
    if result.get("action") == "already_online":
        return True
    if result.get("action") != "login":
        return False
    login_result = result.get("login", {})
    return str(login_result.get("result")) == "1"


def _build_gateway_candidates(
    base_url: str,
    cache_file: str,
    auto_discover_gateway: bool,
    probe_url: str,
    timeout: int,
    source_ip: str | None = None,
) -> list[str]:
    candidates = [_normalize_base_url(base_url)]
    cached = load_cached_gateway(cache_file)
    discovered = discover_gateway_base_url(probe_url, timeout=timeout, source_ip=source_ip) if auto_discover_gateway else None
    for candidate in (cached, discovered):
        if candidate:
            normalized = _normalize_base_url(candidate)
            if normalized not in candidates:
                candidates.append(normalized)
    return candidates


def ensure_online_with_fallback(
    base_url: str,
    username: str,
    password: str,
    service: str = "",
    timeout: int = 10,
    cache_file: str = DEFAULT_GATEWAY_CACHE_FILE,
    auto_discover_gateway: bool = True,
    probe_url: str = DEFAULT_PROBE_URL,
    source_ip: str | None = None,
) -> dict[str, Any]:
    candidates = _build_gateway_candidates(base_url, cache_file, auto_discover_gateway, probe_url, timeout, source_ip)
    errors: list[str] = []

    for candidate in candidates:
        client = DrcomClient(candidate, timeout=timeout, source_ip=source_ip)
        try:
            result = ensure_online(client, username, password, service)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        if _login_succeeded(result):
            result["base_url"] = candidate
            result["attempted_base_urls"] = candidates
            save_cached_gateway(cache_file, candidate)
            return result

        login = result.get("login", {})
        errors.append(f"{candidate}: login result={login.get('result')} msg={login.get('msg', '')}")

    error_text = "; ".join(errors) if errors else "all gateway attempts failed"
    raise RuntimeError(error_text)


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
    parser.add_argument(
        "--probe-url",
        default=os.getenv("CAMPUS_PROBE_URL", DEFAULT_PROBE_URL),
        help="URL used for portal detection when gateway changes",
    )
    parser.add_argument(
        "--gateway-cache-file",
        default=os.getenv("CAMPUS_GATEWAY_CACHE_FILE", DEFAULT_GATEWAY_CACHE_FILE),
        help="cache file for last successful gateway base URL",
    )
    parser.add_argument(
        "--source-ip",
        default=os.getenv("CAMPUS_SOURCE_IP"),
        help="bind HTTP requests to this local IPv4 address",
    )
    parser.add_argument(
        "--interface",
        default=os.getenv("CAMPUS_INTERFACE"),
        help="bind HTTP requests to this network interface by using its IPv4 address",
    )
    parser.add_argument(
        "--no-auto-discover-gateway",
        action="store_true",
        help="disable gateway discovery fallback",
    )
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
    try:
        source_ip = resolve_source_ip(args.source_ip, args.interface)
    except Exception as exc:
        print(f"invalid network binding: {exc}", file=sys.stderr)
        return 2

    while True:
        try:
            result = ensure_online_with_fallback(
                base_url=args.base_url,
                username=args.username,
                password=args.password,
                service=args.service,
                timeout=args.timeout,
                cache_file=args.gateway_cache_file,
                auto_discover_gateway=not args.no_auto_discover_gateway,
                probe_url=args.probe_url,
                source_ip=source_ip,
            )
            gateway = result.get("base_url", args.base_url)
            if result["action"] == "already_online":
                status = result["status"]
                _log(
                    "online "
                    f"uid={status.get('uid', '')} "
                    f"ip={status.get('v46ip') or status.get('v4ip', '')} "
                    f"gateway={gateway}"
                )
            else:
                login_result = result["login"]
                _log(
                    "login attempted "
                    f"result={login_result.get('result')} "
                    f"msg={login_result.get('msg', '')} "
                    f"gateway={gateway}"
                )
        except Exception as exc:
            _log(f"error: {exc}")
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    raise SystemExit(main())
