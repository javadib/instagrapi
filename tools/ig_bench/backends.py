"""Backend adapters.

Every adapter exposes the same six operations so the results are comparable:

    user_info, posts, comments, reels, stories, hashtag

Each operation returns a short human-readable summary string, or raises. The
runner turns that into PASS/FAIL. Adapters import their library lazily so a
missing dependency is reported as SKIP rather than crashing the whole run.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Dict, List, Optional

OPERATIONS = ["user_info", "posts", "comments", "reels", "stories", "hashtag"]


class BackendUnavailable(RuntimeError):
    """Raised when the backend's library or service is not installed/running."""


class Backend:
    name = "base"
    kind = "library"

    def __init__(self, target: str, hashtag: str, amount: int) -> None:
        self.target = target
        self.hashtag = hashtag
        self.amount = amount

    def login(self, username: str, password: str, sessionid: str, otp: str) -> str:
        raise NotImplementedError

    def operations(self) -> Dict[str, Callable[[], str]]:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# instagrapi (sync)
# --------------------------------------------------------------------------- #
class InstagrapiBackend(Backend):
    name = "instagrapi"
    kind = "sync library"

    def __init__(self, target: str, hashtag: str, amount: int) -> None:
        super().__init__(target, hashtag, amount)
        try:
            from instagrapi import Client
        except ImportError as exc:
            raise BackendUnavailable(f"pip install instagrapi ({exc})") from exc
        self.cl = Client()
        self.uid: Optional[str] = None
        self.media_id: Optional[str] = None

    def login(self, username: str, password: str, sessionid: str, otp: str) -> str:
        if sessionid:
            self.cl.login_by_sessionid(sessionid)
            return "logged in via sessionid"
        self.cl.login(username, password, verification_code=otp or "")
        return f"logged in as {username}"

    def operations(self) -> Dict[str, Callable[[], str]]:
        return {
            "user_info": self._user_info,
            "posts": self._posts,
            "comments": self._comments,
            "reels": self._reels,
            "stories": self._stories,
            "hashtag": self._hashtag,
        }

    def _user_info(self) -> str:
        user = self.cl.user_info_by_username(self.target)
        self.uid = str(user.pk)
        return f"pk={user.pk} followers={user.follower_count} private={user.is_private}"

    def _posts(self) -> str:
        medias = self.cl.user_medias(self.uid, amount=self.amount)
        if medias:
            self.media_id = str(medias[0].pk)
        return f"{len(medias)} posts, newest={self.media_id}"

    def _comments(self) -> str:
        if not self.media_id:
            raise RuntimeError("no media id from the posts step")
        comments = self.cl.media_comments(self.media_id, amount=self.amount)
        return f"{len(comments)} comments on {self.media_id}"

    def _reels(self) -> str:
        clips = self.cl.user_clips(self.uid, amount=self.amount)
        return f"{len(clips)} reels"

    def _stories(self) -> str:
        stories = self.cl.user_stories(self.uid, amount=self.amount)
        return f"{len(stories)} active stories"

    def _hashtag(self) -> str:
        medias = self.cl.hashtag_medias_top(self.hashtag, amount=self.amount)
        return f"{len(medias)} top posts for #{self.hashtag}"


# --------------------------------------------------------------------------- #
# aiograpi (async)
# --------------------------------------------------------------------------- #
class AiograpiBackend(Backend):
    name = "aiograpi"
    kind = "async library"

    def __init__(self, target: str, hashtag: str, amount: int) -> None:
        super().__init__(target, hashtag, amount)
        try:
            from aiograpi import Client
        except ImportError as exc:
            raise BackendUnavailable(f"pip install aiograpi ({exc})") from exc
        self.cl = Client()
        self.uid: Optional[str] = None
        self.media_id: Optional[str] = None
        self.loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def login(self, username: str, password: str, sessionid: str, otp: str) -> str:
        if sessionid:
            self._run(self.cl.login_by_sessionid(sessionid))
            return "logged in via sessionid"
        self._run(self.cl.login(username, password, verification_code=otp or ""))
        return f"logged in as {username}"

    def operations(self) -> Dict[str, Callable[[], str]]:
        return {
            "user_info": self._user_info,
            "posts": self._posts,
            "comments": self._comments,
            "reels": self._reels,
            "stories": self._stories,
            "hashtag": self._hashtag,
        }

    def _user_info(self) -> str:
        user = self._run(self.cl.user_info_by_username(self.target))
        self.uid = str(user.pk)
        return f"pk={user.pk} followers={user.follower_count} private={user.is_private}"

    def _posts(self) -> str:
        medias = self._run(self.cl.user_medias(self.uid, amount=self.amount))
        if medias:
            self.media_id = str(medias[0].pk)
        return f"{len(medias)} posts, newest={self.media_id}"

    def _comments(self) -> str:
        if not self.media_id:
            raise RuntimeError("no media id from the posts step")
        comments = self._run(self.cl.media_comments(self.media_id, amount=self.amount))
        return f"{len(comments)} comments on {self.media_id}"

    def _reels(self) -> str:
        clips = self._run(self.cl.user_clips(self.uid, amount=self.amount))
        return f"{len(clips)} reels"

    def _stories(self) -> str:
        stories = self._run(self.cl.user_stories(self.uid, amount=self.amount))
        return f"{len(stories)} active stories"

    def _hashtag(self) -> str:
        medias = self._run(self.cl.hashtag_medias_top(self.hashtag, amount=self.amount))
        return f"{len(medias)} top posts for #{self.hashtag}"

    def close(self) -> None:
        try:
            self.loop.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


# --------------------------------------------------------------------------- #
# aiograpi-rest (HTTP service)
# --------------------------------------------------------------------------- #
class AiograpiRestBackend(Backend):
    name = "aiograpi-rest"
    kind = "REST service"

    def __init__(self, target: str, hashtag: str, amount: int, base_url: str) -> None:
        super().__init__(target, hashtag, amount)
        try:
            import requests
        except ImportError as exc:
            raise BackendUnavailable(f"pip install requests ({exc})") from exc
        self.requests = requests
        self.base = base_url.rstrip("/")
        self.session_token: Optional[str] = None
        self.uid: Optional[str] = None
        self.media_id: Optional[str] = None

        try:
            resp = requests.get(f"{self.base}/openapi.json", timeout=10)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(
                f"service not reachable at {self.base} — start it with "
                f"`uvicorn aiograpi_rest.main:app` ({exc})"
            ) from exc

    def _get(self, path: str, params: dict) -> object:
        headers = {"X-Session-ID": self.session_token} if self.session_token else {}
        resp = self.requests.get(
            f"{self.base}{path}", params=params, headers=headers, timeout=90
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def login(self, username: str, password: str, sessionid: str, otp: str) -> str:
        if sessionid:
            resp = self.requests.post(
                f"{self.base}/auth/login/by/sessionid",
                data={"sessionid": sessionid},
                timeout=90,
            )
        else:
            payload = {"username": username, "password": password}
            if otp:
                payload["verification_code"] = otp
            resp = self.requests.post(f"{self.base}/auth/login", data=payload, timeout=120)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        self.session_token = resp.json()
        return "logged in, session token issued"

    def operations(self) -> Dict[str, Callable[[], str]]:
        return {
            "user_info": self._user_info,
            "posts": self._posts,
            "comments": self._comments,
            "reels": self._reels,
            "stories": self._stories,
            "hashtag": self._hashtag,
        }

    def _user_info(self) -> str:
        user = self._get("/user", {"username": self.target})
        self.uid = str(user["pk"])
        return f"pk={user['pk']} followers={user.get('follower_count')}"

    def _posts(self) -> str:
        data = self._get("/user/posts", {"user_id": self.uid, "amount": self.amount})
        items = data.get("items", data) if isinstance(data, dict) else data
        if items:
            self.media_id = str(items[0]["pk"])
        return f"{len(items)} posts, newest={self.media_id}"

    def _comments(self) -> str:
        if not self.media_id:
            raise RuntimeError("no media id from the posts step")
        data = self._get(
            "/media/comments", {"media_id": self.media_id, "amount": self.amount}
        )
        items = data.get("items", data) if isinstance(data, dict) else data
        return f"{len(items)} comments on {self.media_id}"

    def _reels(self) -> str:
        data = self._get("/user/reels", {"user_id": self.uid, "amount": self.amount})
        items = data.get("items", data) if isinstance(data, dict) else data
        return f"{len(items)} reels"

    def _stories(self) -> str:
        data = self._get("/user/stories", {"user_id": self.uid, "amount": self.amount})
        items = data.get("items", data) if isinstance(data, dict) else data
        return f"{len(items)} active stories"

    def _hashtag(self) -> str:
        data = self._get(
            "/hashtag/media/top", {"name": self.hashtag, "amount": self.amount}
        )
        items = data.get("items", data) if isinstance(data, dict) else data
        return f"{len(items)} top posts for #{self.hashtag}"


# --------------------------------------------------------------------------- #
# Osintgram (legacy, kept so the comparison is complete)
# --------------------------------------------------------------------------- #
class OsintgramBackend(Backend):
    """Osintgram sits on instagram-private-api 1.6.0.0 (PyPI release 2019-05-06).

    That library signs requests with the retired IG_SIG_KEY/SIG_KEY_VERSION=4
    scheme and impersonates Instagram Android 76.0.0.15.395 on Android 7.0.
    Instagram dropped both years ago, so login fails before any data operation
    can run. The adapter still attempts a real login so the failure is measured
    rather than assumed.
    """

    name = "Osintgram"
    kind = "legacy CLI"

    def __init__(self, target: str, hashtag: str, amount: int) -> None:
        super().__init__(target, hashtag, amount)
        try:
            from instagram_private_api import Client  # noqa: F401
        except ImportError as exc:
            raise BackendUnavailable(
                f"pip install instagram-private-api==1.6.0 ({exc})"
            ) from exc
        self.api = None

    def login(self, username: str, password: str, sessionid: str, otp: str) -> str:
        from instagram_private_api import Client

        if not username or not password:
            raise RuntimeError("Osintgram needs username+password (no sessionid support)")
        self.api = Client(username, password)
        return f"logged in as {username}"

    def operations(self) -> Dict[str, Callable[[], str]]:
        return {
            "user_info": self._user_info,
            "posts": self._posts,
            "comments": self._comments,
            "reels": self._unsupported("reels"),
            "stories": self._stories,
            "hashtag": self._hashtag,
        }

    def _unsupported(self, what: str) -> Callable[[], str]:
        def raise_it() -> str:
            raise RuntimeError(f"{what} is not implemented by instagram-private-api 1.6.0")

        return raise_it

    def _user_info(self) -> str:
        info = self.api.username_info(self.target)
        self.uid = str(info["user"]["pk"])
        return f"pk={self.uid} followers={info['user'].get('follower_count')}"

    def _posts(self) -> str:
        feed = self.api.user_feed(self.uid, )
        items = feed.get("items", [])
        if items:
            self.media_id = str(items[0]["pk"])
        return f"{len(items)} posts"

    def _comments(self) -> str:
        data = self.api.media_comments(self.media_id)
        return f"{len(data.get('comments', []))} comments"

    def _stories(self) -> str:
        data = self.api.user_reel_media(self.uid)
        return f"{len(data.get('items', []))} active stories"

    def _hashtag(self) -> str:
        data = self.api.feed_tag(self.hashtag, self.api.generate_uuid())
        return f"{len(data.get('items', []))} posts for #{self.hashtag}"


def build(name: str, target: str, hashtag: str, amount: int, rest_url: str) -> Backend:
    if name == "instagrapi":
        return InstagrapiBackend(target, hashtag, amount)
    if name == "aiograpi":
        return AiograpiBackend(target, hashtag, amount)
    if name == "aiograpi-rest":
        return AiograpiRestBackend(target, hashtag, amount, rest_url)
    if name == "osintgram":
        return OsintgramBackend(target, hashtag, amount)
    raise ValueError(f"unknown backend: {name}")


ALL_BACKENDS: List[str] = ["aiograpi", "osintgram", "aiograpi-rest", "instagrapi"]
