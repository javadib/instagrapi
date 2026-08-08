#!/usr/bin/env python3
"""Compare Instagram scraping libraries on the same six operations.

Runs preflight connectivity checks, then logs in with each requested backend and
fetches profile info, posts, comments, reels, stories and hashtag results.
Prints a PASS/FAIL matrix so a failure can be attributed to a specific library
and a specific operation.

    python tools/ig_bench/bench.py --target instagram

Credentials come from the environment:

    IG_USERNAME, IG_PASSWORD      username/password login
    IG_SESSIONID                  reuse an existing session (preferred)
    IG_OTP                        2FA / TOTP code, when prompted

Never run this against your main account.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backends as backends_mod  # noqa: E402
import preflight  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _short(exc: BaseException, limit: int = 160) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


def run_backend(name: str, args: argparse.Namespace) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "backend": name,
        "login": {"status": SKIP, "detail": ""},
        "operations": {},
    }

    print(f"\n=== {name} " + "=" * (60 - len(name)))
    try:
        backend = backends_mod.build(
            name, args.target, args.hashtag, args.amount, args.rest_url
        )
    except backends_mod.BackendUnavailable as exc:
        print(f"  SKIP  not available: {exc}")
        report["login"] = {"status": SKIP, "detail": str(exc)}
        for op in backends_mod.OPERATIONS:
            report["operations"][op] = {"status": SKIP, "detail": "backend unavailable"}
        return report
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  could not construct backend: {_short(exc)}")
        report["login"] = {"status": FAIL, "detail": _short(exc)}
        for op in backends_mod.OPERATIONS:
            report["operations"][op] = {"status": SKIP, "detail": "backend not constructed"}
        return report

    report["kind"] = backend.kind

    started = time.time()
    try:
        detail = backend.login(
            os.getenv("IG_USERNAME", ""),
            os.getenv("IG_PASSWORD", ""),
            os.getenv("IG_SESSIONID", ""),
            os.getenv("IG_OTP", ""),
        )
        elapsed = time.time() - started
        print(f"  PASS  login  ({elapsed:.1f}s)  {detail}")
        report["login"] = {"status": PASS, "detail": detail, "seconds": round(elapsed, 1)}
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - started
        print(f"  FAIL  login  ({elapsed:.1f}s)  {_short(exc)}")
        if args.traceback:
            traceback.print_exc()
        report["login"] = {"status": FAIL, "detail": _short(exc), "seconds": round(elapsed, 1)}
        for op in backends_mod.OPERATIONS:
            report["operations"][op] = {"status": SKIP, "detail": "login failed"}
        backend.close()
        return report

    for op_name, op in backend.operations().items():
        started = time.time()
        try:
            detail = op()
            elapsed = time.time() - started
            print(f"  PASS  {op_name:<10} ({elapsed:5.1f}s)  {detail}")
            report["operations"][op_name] = {
                "status": PASS,
                "detail": detail,
                "seconds": round(elapsed, 1),
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started
            print(f"  FAIL  {op_name:<10} ({elapsed:5.1f}s)  {_short(exc)}")
            if args.traceback:
                traceback.print_exc()
            report["operations"][op_name] = {
                "status": FAIL,
                "detail": _short(exc),
                "seconds": round(elapsed, 1),
            }
        time.sleep(args.delay)

    backend.close()
    return report


def print_matrix(reports: List[Dict[str, Any]]) -> None:
    ops = backends_mod.OPERATIONS
    width = max(len(r["backend"]) for r in reports) + 2
    header = "backend".ljust(width) + "login".ljust(8) + "".join(o[:9].ljust(10) for o in ops)
    print("\n" + "=" * len(header))
    print("RESULT MATRIX")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for report in reports:
        row = report["backend"].ljust(width) + report["login"]["status"].ljust(8)
        row += "".join(
            report["operations"].get(op, {}).get("status", SKIP).ljust(10) for op in ops
        )
        print(row)
    print("=" * len(header))

    working = [
        r["backend"]
        for r in reports
        if r["login"]["status"] == PASS
        and all(r["operations"].get(op, {}).get("status") == PASS for op in ops)
    ]
    partial = [
        r["backend"]
        for r in reports
        if r["login"]["status"] == PASS and r["backend"] not in working
    ]
    print(f"\nfully working : {', '.join(working) if working else 'none'}")
    print(f"partial       : {', '.join(partial) if partial else 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", default="instagram", help="public username to read")
    parser.add_argument("--hashtag", default="python", help="hashtag to query (no '#')")
    parser.add_argument("--amount", type=int, default=5, help="items per operation")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between operations")
    parser.add_argument(
        "--backends",
        default=",".join(backends_mod.ALL_BACKENDS),
        help="comma-separated subset: " + ",".join(backends_mod.ALL_BACKENDS),
    )
    parser.add_argument(
        "--rest-url", default="http://127.0.0.1:8000", help="base URL of a running aiograpi-rest"
    )
    parser.add_argument("--json", help="write the full report to this path")
    parser.add_argument("--traceback", action="store_true", help="print full tracebacks")
    parser.add_argument(
        "--skip-preflight", action="store_true", help="run even if Instagram looks unreachable"
    )
    args = parser.parse_args()

    reachable = preflight.run()
    if not reachable and not args.skip_preflight:
        print("\nAborting. Re-run with --skip-preflight to test anyway.")
        return 2

    if not (os.getenv("IG_SESSIONID") or (os.getenv("IG_USERNAME") and os.getenv("IG_PASSWORD"))):
        print(
            "\nNo credentials found. Set IG_SESSIONID, or IG_USERNAME and IG_PASSWORD.\n"
            "Every backend below needs a logged-in session — Instagram no longer serves\n"
            "these endpoints anonymously."
        )
        return 2

    reports = [run_backend(name.strip(), args) for name in args.backends.split(",") if name.strip()]
    print_matrix(reports)

    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"\nfull report written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
