"""Network reachability checks for Instagram endpoints.

Run this before any backend test. If preflight fails, every backend will fail
for the same reason, and the failure says nothing about the libraries.
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

HOSTS = [
    ("i.instagram.com", "private API (app endpoints)"),
    ("www.instagram.com", "web/GraphQL endpoints"),
    ("b.i.instagram.com", "login / bloks endpoints"),
]

TIMEOUT = 15


@dataclass
class HostResult:
    host: str
    purpose: str
    ok: bool
    detail: str

    @property
    def line(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        return f"  [{mark}] {self.host:<20} {self.purpose:<32} {self.detail}"


def _check(host: str, purpose: str) -> HostResult:
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror as exc:
        return HostResult(host, purpose, False, f"DNS resolution failed: {exc}")

    try:
        req = Request(f"https://{host}/", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            return HostResult(host, purpose, True, f"HTTP {resp.status}")
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        hint = ""
        if "403" in str(reason) or "407" in str(reason):
            hint = "  <- blocked by an HTTP proxy / egress policy, not by Instagram"
        elif isinstance(reason, (socket.timeout, TimeoutError)):
            hint = "  <- connection timed out (firewall or ISP-level block)"
        return HostResult(host, purpose, False, f"{type(reason).__name__}: {reason}{hint}")
    except ssl.SSLError as exc:
        return HostResult(host, purpose, False, f"TLS error: {exc}")
    except Exception as exc:  # noqa: BLE001 - report anything that goes wrong
        # An HTTP error status still proves the host is reachable.
        status = getattr(exc, "code", None)
        if status is not None:
            return HostResult(host, purpose, True, f"HTTP {status} (host reachable)")
        return HostResult(host, purpose, False, f"{type(exc).__name__}: {exc}")


def run(verbose: bool = True) -> bool:
    """Return True when every Instagram host is reachable."""
    if verbose:
        print("Preflight: Instagram network reachability")
    results = [_check(host, purpose) for host, purpose in HOSTS]
    if verbose:
        for result in results:
            print(result.line)

    ok = all(result.ok for result in results)
    if verbose and not ok:
        print(
            "\n  Instagram is not reachable from this machine. Every library below "
            "will fail\n  for that reason alone. Fix connectivity (VPN, proxy, or a "
            "different network)\n  and re-run before judging any library."
        )
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 2)
