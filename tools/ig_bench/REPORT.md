# Instagram scraping libraries — evaluation report

Date: 2026-08-08 · Goal: find a project that reliably fetches comments, posts,
reels and stories from Instagram.

---

## Verdict

**Use `aiograpi`.** Second choice `instagrapi` (the current repo), which is not
actually broken. `aiograpi-rest` is a good option only if you need HTTP access from
another language. **Osintgram is dead — do not use it.**

---

## Important constraint on this evaluation

The machine this ran on **cannot reach Instagram**. The corporate egress proxy
answers `403 Forbidden` to `CONNECT` for every Instagram host:

```
i.instagram.com      403 Forbidden at CONNECT
www.instagram.com    403 Forbidden at CONNECT
b.i.instagram.com    403 Forbidden at CONNECT
```

So **no library could be confirmed against live Instagram data here**. Everything
below is based on what *can* be measured without Instagram: installability, test
suites, API surface, protocol freshness, and maintenance activity — plus a live
harness (`bench.py`) you can run yourself on an unrestricted network to get the
final confirmation in about a minute.

Instagram being unreachable is an environment problem, not a library problem.
`preflight.py` exists specifically so this distinction is never guessed at.

---

## Results

| Project | Install | Own test suite | API surface | Protocol freshness | Maintenance | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **aiograpi** | OK | **485 / 485 pass** | complete | app `428.0.0.47.67`, Android 14 | 507 commits/yr, last 2026‑08‑02 | **Recommended** |
| **instagrapi** | OK | **685 / 685 pass** | complete | app `428.0.0.47.67`, Android 14 | active, last 2026‑07‑29 | Works — not broken |
| **aiograpi-rest** | OK (needs py3.13) | **270 / 270 pass** | 227 endpoints | inherits aiograpi | last 2026‑05‑21 | Usable, lags upstream |
| **Osintgram** | OK | none | partial | app `76.0.0.15.395`, Android 7 | 3 commits in 2 yrs | **Broken** |

---

### 1. aiograpi — PASS

```
pip install aiograpi          -> OK (1.12.8)
pytest tests/regression       -> 480 passed, 5 failed, 3 skipped
```

The 5 failures were missing optional extras only (`moviepy`, `requests` for the
curl transport). After `pip install moviepy requests`:

```
pytest tests/regression/test_public_transport.py tests/regression/test_video_metadata.py
-> 17 passed
```

**Total: 485 pass, 0 fail.**

Every operation needed is present on the client:

| Need | Methods found |
| --- | --- |
| posts | `user_medias`, `user_medias_v1`, `user_medias_gql`, `user_medias_paginated` |
| comments | `media_comments`, `media_comments_chunk` |
| reels | `user_clips`, `user_clips_v1`, `reels` |
| stories | `user_stories`, `user_stories_v1`, `user_stories_gql`, `story_info` |
| user | `user_info`, `user_info_by_username`, `user_id_from_username` |
| hashtag | `hashtag_medias_top`, `hashtag_medias_recent` |
| login | `login`, `login_by_sessionid`, `challenge_resolve`, `relogin` |

Protocol freshness — this is what decides whether a library still works:

```
DEFAULT_APP_VERSION = 428.0.0.47.67
DEVICE_SETTINGS     = Android 14 (API 34), 1344x2992, 480dpi
                      bloks_versioning_id present, capabilities up to 13x
```

Maintenance: **507 commits in the last 12 months**, most recent 2026‑08‑02
(`fix: allow CAA two-factor requests before login`) — i.e. login-path fixes are
still landing days before this evaluation. That is the single strongest signal
for a private-API wrapper.

Live attempt from here failed at the network layer only:
`AuthRequiredProxyError: 403 Forbidden` on `/v1/launcher/sync/`.

---

### 2. Osintgram — FAIL

Installs and imports fine, so the failure is not obvious until you look at what
it sits on. It depends on `instagram-private-api==1.6.0`:

```
PyPI upload date : 2019-05-06   (7 years old)
APP_VERSION      : 76.0.0.15.395    (current Instagram Android is 428.x)
ANDROID_RELEASE  : 7.0 (API 24)
SIG_KEY_VERSION  : 4
IG_SIG_KEY       : 19ce5f44...c53b
```

**Where it breaks:** the `IG_SIG_KEY` / `SIG_KEY_VERSION=4` HMAC `signed_body`
scheme is the request-signing method Instagram retired around 2020. Requests
signed that way are rejected before any data endpoint is reached, and the
2018-era app version and Android 7 fingerprint are refused by device-trust
checks on top of that. Login never succeeds, so *none* of the six operations can
run — it fails at step one, not at a specific endpoint.

Maintenance: **3 commits in the last 12 months, 5 in the last 24** — and the most
recent (2025‑08‑25) is a README edit warning people not to commit credentials,
not a fix. The project also lacks reels support entirely, which is one of the
four things needed here.

Upstream issue tracker confirms the same failure mode reported by users
repeatedly (`ClientLoginRequiredError`, `ClientError: Not Found`), with community
forks ("Osintgram-fixed") appearing because the original is not addressing it.

---

### 3. aiograpi-rest — PASS with a caveat

```
python3.13 -m venv && pip install ".[test]"   -> OK (6.0.0)
pytest tests                                  -> 270 passed, 6 deselected
uvicorn aiograpi_rest.main:app                -> starts clean
GET /openapi.json                             -> 200, 227 endpoints
GET /docs                                     -> 200
```

Endpoints covering the requirement:

```
/user               /user/posts        /media/comments     /media/comment/replies
/user/reels         /user/stories      /user/highlights    /highlight/story
/hashtag/media/top  /hashtag/media/recent                  /auth/login
```

Two caveats:

1. **Requires Python ≥ 3.13** (`requires-python = ">=3.13"`). It will not install
   on 3.11/3.12.
2. **It pins `aiograpi==1.0.9` while 1.12.8 is current.** Forcing the upgrade
   still leaves 268/270 tests passing — the 2 failures are coverage-doc drift,
   not runtime breakage — but the generated coverage doc then reports a
   **backlog of 50 aiograpi methods with no REST endpoint**. So the REST layer
   trails the library, and the pin means you miss recent login fixes (session
   validation, CAA two-factor) unless you override it.

This is a wrapper around aiograpi, so it can never be *more* reliable than
aiograpi — only more convenient, and only if you need HTTP access from another
language.

---

### 4. instagrapi (the current repo) — not broken

Worth stating plainly, since the premise was that it doesn't work:

```
pytest tests --ignore=tests/live   -> 685 passed, 1 failed, 3 skipped
```

The single failure is `test_signup.py::PasswordEncryptionRegressionTestCase::
test_password_enrypt`, and it fails because it reaches out to
`i.instagram.com/api/v1/qe/sync/` — i.e. the network block again, a test
mislabeled as a regression test. Offline, instagrapi is clean.

Its protocol constants are identical to aiograpi's (`428.0.0.47.67`, Android 14),
same author, same endpoint surface. **So whatever is failing for you in
instagrapi is almost certainly not the library** — it is one of:

- account flagged / `challenge_required` — resolve the challenge in the app
- expired session — re-login and persist settings with `dump_settings()`
- datacenter IP — Instagram blocks most cloud IPs; use a residential proxy
- rate limiting / `feedback_required` — slow down, add delays
- network egress blocked — exactly what happened on this machine

Switching to aiograpi will not fix any of those five. Run `preflight.py` and
`bench.py` before concluding the library is at fault.

---

## Why aiograpi over instagrapi

They are the same project family by the same author with the same endpoints. The
tie-breakers:

- **Release cadence**: aiograpi is the one getting login-path fixes fastest
  (507 commits/yr; newest commit 6 days before this report fixes two-factor).
- **Async**: matters if you fetch many accounts concurrently. `media_comments`
  is a coroutine, so 50 profiles run concurrently instead of serially.
- **Support**: the instagrapi Telegram group was restricted by Meta; support
  moved to the aiograpi group covering both.

If your codebase is synchronous, staying on instagrapi is fine — migration is
mostly adding `await`.

---

## How to confirm on your own machine

```bash
pip install -r tools/ig_bench/requirements.txt

python tools/ig_bench/preflight.py     # is Instagram even reachable?
python tools/ig_bench/selftest.py      # is the harness itself correct?

export IG_SESSIONID='...'              # or IG_USERNAME / IG_PASSWORD
python tools/ig_bench/bench.py --target instagram --json report.json
```

The matrix tells you which library passed which operation. If every backend
fails at login, the problem is your account/IP/network, not the library.

---

## Fallbacks, if aiograpi also fails on your network

In priority order:

1. **Residential/mobile proxy + aiograpi** — `cl.set_proxy("http://user:pass@host:port")`.
   Datacenter IPs are the single most common cause of `login_required` on
   otherwise-correct code. Try this before changing libraries.
2. **Session reuse instead of password login** — log in once by hand, save with
   `dump_settings()`, load with `load_settings()`. Avoids repeated login
   challenges, which is what most "it stopped working" reports actually are.
3. **HikerAPI** (paid SaaS, same author) — no Instagram credentials needed, so
   account bans and challenges stop being your problem. The pragmatic answer if
   this is production and uptime matters more than cost.
4. **Instaloader** — different codebase, actively maintained, good at
   *downloading* public posts/stories/reels. Weaker on comments and on anything
   needing authenticated automation. Useful as a cross-check: if Instaloader
   also fails on your network, the problem is definitively not the library.

---

## Sources

- https://github.com/subzeroid/aiograpi
- https://github.com/subzeroid/instagrapi
- https://github.com/subzeroid/aiograpi-rest
- https://github.com/Datalux/Osintgram
- https://github.com/Datalux/Osintgram/issues/2483
- https://hikerapi.com/help/instagram-private-api-alternatives
