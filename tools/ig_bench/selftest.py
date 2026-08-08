#!/usr/bin/env python3
"""Offline self-test for the bench harness.

Replaces each backend's underlying client with a stub so every operation runs
without touching the network. This proves the harness calls real, existing
methods with the right arguments — if a library renames a method, this fails
here instead of being misread as "Instagram blocked us".

    python tools/ig_bench/selftest.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backends as backends_mod  # noqa: E402

FAKE_USER = SimpleNamespace(pk=25025320, follower_count=690_000_000, is_private=False)
FAKE_MEDIA = [SimpleNamespace(pk=f"3212{i}") for i in range(5)]
FAKE_COMMENTS = [SimpleNamespace(pk=f"c{i}") for i in range(5)]


def _check_methods_exist(client, names: list[str], label: str) -> list[str]:
    missing = [n for n in names if not hasattr(client, n)]
    if missing:
        print(f"  FAIL  {label}: missing methods {missing}")
    else:
        print(f"  PASS  {label}: all {len(names)} methods exist on the real client")
    return missing


def test_instagrapi() -> bool:
    print("\n=== instagrapi ===")
    try:
        from instagrapi import Client
    except ImportError as exc:
        print(f"  SKIP  not installed ({exc})")
        return True

    needed = [
        "login", "login_by_sessionid", "user_info_by_username", "user_medias",
        "media_comments", "user_clips", "user_stories", "hashtag_medias_top",
    ]
    missing = _check_methods_exist(Client(), needed, "instagrapi.Client")
    if missing:
        return False

    backend = backends_mod.InstagrapiBackend("instagram", "python", 5)
    backend.cl = SimpleNamespace(
        user_info_by_username=lambda u: FAKE_USER,
        user_medias=lambda uid, amount: FAKE_MEDIA,
        media_comments=lambda mid, amount: FAKE_COMMENTS,
        user_clips=lambda uid, amount: FAKE_MEDIA[:3],
        user_stories=lambda uid, amount: FAKE_MEDIA[:2],
        hashtag_medias_top=lambda name, amount: FAKE_MEDIA,
    )
    return _run_ops(backend)


def test_aiograpi() -> bool:
    print("\n=== aiograpi ===")
    try:
        from aiograpi import Client
    except ImportError as exc:
        print(f"  SKIP  not installed ({exc})")
        return True

    needed = [
        "login", "login_by_sessionid", "user_info_by_username", "user_medias",
        "media_comments", "user_clips", "user_stories", "hashtag_medias_top",
    ]
    missing = _check_methods_exist(Client(), needed, "aiograpi.Client")
    if missing:
        return False

    backend = backends_mod.AiograpiBackend("instagram", "python", 5)

    async def _user_info(u):
        return FAKE_USER

    async def _medias(uid, amount):
        return FAKE_MEDIA

    async def _comments(mid, amount):
        return FAKE_COMMENTS

    async def _clips(uid, amount):
        return FAKE_MEDIA[:3]

    async def _stories(uid, amount):
        return FAKE_MEDIA[:2]

    async def _hashtag(name, amount):
        return FAKE_MEDIA

    backend.cl = SimpleNamespace(
        user_info_by_username=_user_info,
        user_medias=_medias,
        media_comments=_comments,
        user_clips=_clips,
        user_stories=_stories,
        hashtag_medias_top=_hashtag,
    )
    ok = _run_ops(backend)
    backend.close()
    return ok


def test_osintgram() -> bool:
    print("\n=== Osintgram (instagram-private-api) ===")
    try:
        from instagram_private_api import Client  # noqa: F401
        import instagram_private_api.constants as constants
    except ImportError as exc:
        print(f"  SKIP  not installed ({exc})")
        return True

    app_version = constants.Constants.APP_VERSION
    sig_version = getattr(constants.Constants, "SIG_KEY_VERSION", None)
    print(f"  INFO  impersonates Instagram Android app {app_version}")
    print(f"  INFO  request signing scheme SIG_KEY_VERSION={sig_version}")
    if app_version.split(".")[0].isdigit() and int(app_version.split(".")[0]) < 200:
        print(
            "  FAIL  app version is far behind the current Instagram Android client; "
            "login is rejected server-side"
        )
        return False
    return True


def _run_ops(backend) -> bool:
    ok = True
    for name, op in backend.operations().items():
        try:
            detail = op()
            print(f"  PASS  {name:<10} -> {detail}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {name:<10} -> {type(exc).__name__}: {exc}")
            ok = False
    return ok


def main() -> int:
    print("Bench harness self-test (no network required)")

    # Harness correctness: do the adapters call methods that really exist?
    harness = {
        "instagrapi": test_instagrapi(),
        "aiograpi": test_aiograpi(),
    }
    # Diagnostic only: Osintgram has no methods for the harness to verify, its
    # protocol constants are the finding. Does not affect the exit code.
    osintgram_current = test_osintgram()

    print("\n" + "=" * 60)
    print("harness correctness")
    for name, ok in harness.items():
        print(f"  {name:<14} {'OK' if ok else 'PROBLEM'}")
    print("diagnostic")
    print(f"  {'osintgram':<14} {'current' if osintgram_current else 'protocol is obsolete'}")
    print("=" * 60)
    return 0 if all(harness.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
