#!/usr/bin/env python3
"""Fetch reels and their comments from a public Instagram account with aiograpi.

Credentials are read from the environment — never hardcode them, and never
commit them:

    export CRAWLER_INSTAGRAM_USERNAME='your_account'
    export CRAWLER_INSTAGRAM_PASSWORD='your_password'
    export CRAWLER_INSTAGRAM_PROXY='http://user:pass@host:port'   # recommended
    export CRAWLER_INSTAGRAM_OTP='123456'                         # only if 2FA asks

    python fetch_comments_reels.py --target nasa --reels 5 --comments 20

The session is saved to --session (default ./ig_session.json) and reused on the
next run. That matters: logging in with a password on every run is the fastest
way to get an account challenged. Delete the file only if login starts failing.

Output goes to --out as JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from aiograpi import Client
from aiograpi.exceptions import (
    BadPassword,
    ChallengeRequired,
    ClientError,
    LoginRequired,
    MediaNotFound,
    PleaseWaitFewMinutes,
    PrivateAccount,
    TwoFactorRequired,
    UserNotFound,
)


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #
async def login(session_path: Path, proxy: str) -> Client:
    """Return a logged-in client, reusing a saved session when possible."""
    username = os.getenv("CRAWLER_INSTAGRAM_USERNAME", "")
    password = os.getenv("CRAWLER_INSTAGRAM_PASSWORD", "")
    otp = os.getenv("CRAWLER_INSTAGRAM_OTP", "")

    if not username or not password:
        sys.exit(
            "Set CRAWLER_INSTAGRAM_USERNAME and CRAWLER_INSTAGRAM_PASSWORD "
            "in the environment."
        )

    cl = Client()
    # Random pause between requests. Instagram flags accounts that fire
    # requests at machine speed far more readily than slow ones.
    cl.delay_range = [1, 3]

    if proxy:
        cl.set_proxy(proxy)

    # 1. Try the saved session first.
    if session_path.exists():
        try:
            cl.load_settings(session_path)
            await cl.login(username, password)
            await cl.get_timeline_feed()  # cheap call that proves the session is live
            print(f"[login] reused session from {session_path}")
            return cl
        except (LoginRequired, ClientError) as exc:
            print(f"[login] saved session rejected ({type(exc).__name__}), logging in fresh")
            cl = Client()
            cl.delay_range = [1, 3]
            if proxy:
                cl.set_proxy(proxy)

    # 2. Fresh password login.
    try:
        await cl.login(username, password, verification_code=otp)
    except TwoFactorRequired:
        sys.exit(
            "Two-factor authentication required. Put the code in "
            "CRAWLER_INSTAGRAM_OTP and run again within its validity window."
        )
    except BadPassword:
        sys.exit("Instagram rejected the password. Check the credentials.")
    except ChallengeRequired:
        sys.exit(
            "Instagram raised a challenge for this account. Open the Instagram "
            "app, confirm it was you, then run again. A residential proxy via "
            "CRAWLER_INSTAGRAM_PROXY makes this much less frequent."
        )
    except PleaseWaitFewMinutes:
        sys.exit("Rate limited at login. Wait a few minutes and retry.")

    cl.dump_settings(session_path)
    print(f"[login] logged in as {username}, session saved to {session_path}")
    return cl


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #
def comment_to_dict(comment) -> Dict[str, Any]:
    return {
        "pk": str(comment.pk),
        "text": comment.text,
        "created_at": comment.created_at_utc.isoformat() if comment.created_at_utc else None,
        "like_count": comment.like_count,
        "replied_to_comment_id": (
            str(comment.replied_to_comment_id) if comment.replied_to_comment_id else None
        ),
        "user": {
            "pk": str(comment.user.pk),
            "username": comment.user.username,
            "full_name": comment.user.full_name,
        },
    }


def reel_to_dict(media) -> Dict[str, Any]:
    return {
        "pk": str(media.pk),
        "code": media.code,
        "url": f"https://www.instagram.com/reel/{media.code}/",
        "taken_at": media.taken_at.isoformat() if media.taken_at else None,
        "caption": media.caption_text,
        "duration": media.video_duration,
        "video_url": str(media.video_url) if media.video_url else None,
        "thumbnail_url": str(media.thumbnail_url) if media.thumbnail_url else None,
        "play_count": media.play_count,
        "view_count": media.view_count,
        "like_count": media.like_count,
        "comment_count": media.comment_count,
        "comments_disabled": media.comments_disabled,
    }


async def fetch_comments(cl: Client, media, amount: int) -> List[Dict[str, Any]]:
    """Comments for one reel. Returns [] rather than raising on per-media errors,
    so one bad reel does not abort the whole run."""
    if media.comments_disabled:
        print(f"  [{media.code}] comments are disabled")
        return []
    try:
        comments = await cl.media_comments(str(media.pk), amount=amount)
    except MediaNotFound:
        print(f"  [{media.code}] media no longer available")
        return []
    except PleaseWaitFewMinutes:
        print(f"  [{media.code}] rate limited, backing off 60s")
        await asyncio.sleep(60)
        comments = await cl.media_comments(str(media.pk), amount=amount)
    except ClientError as exc:
        print(f"  [{media.code}] failed: {type(exc).__name__}: {exc}")
        return []

    print(f"  [{media.code}] {len(comments)} comments")
    return [comment_to_dict(c) for c in comments]


async def run(args: argparse.Namespace) -> int:
    cl = await login(Path(args.session), os.getenv("CRAWLER_INSTAGRAM_PROXY", ""))

    try:
        user = await cl.user_info_by_username(args.target)
    except UserNotFound:
        sys.exit(f"No such account: {args.target}")

    print(f"[user] {user.username} pk={user.pk} followers={user.follower_count} private={user.is_private}")
    if user.is_private:
        print("[user] account is private — you will only get data if you follow it")

    try:
        reels = await cl.user_clips(user.pk, amount=args.reels)
    except PrivateAccount:
        sys.exit("Account is private and you do not follow it.")

    print(f"[reels] fetched {len(reels)}")

    # Bounded concurrency. This is the reason for using aiograpi over instagrapi:
    # comments for N reels are fetched in parallel instead of one after another.
    # Keep the limit low — Instagram rate-limits aggressive clients.
    semaphore = asyncio.Semaphore(args.concurrency)

    async def bounded(media):
        async with semaphore:
            return await fetch_comments(cl, media, args.comments)

    comment_lists = await asyncio.gather(*(bounded(m) for m in reels))

    result = {
        "target": user.username,
        "user_pk": str(user.pk),
        "follower_count": user.follower_count,
        "reels": [
            {**reel_to_dict(media), "comments": comments}
            for media, comments in zip(reels, comment_lists)
        ],
    }
    result["total_comments"] = sum(len(r["comments"]) for r in result["reels"])

    Path(args.out).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"\n[done] {len(result['reels'])} reels, "
        f"{result['total_comments']} comments -> {args.out}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", required=True, help="username to read (no '@')")
    parser.add_argument("--reels", type=int, default=5, help="how many reels")
    parser.add_argument("--comments", type=int, default=20, help="comments per reel")
    parser.add_argument("--concurrency", type=int, default=3, help="parallel comment fetches")
    parser.add_argument("--session", default="ig_session.json", help="session file path")
    parser.add_argument("--out", default="reels_comments.json", help="output JSON path")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
