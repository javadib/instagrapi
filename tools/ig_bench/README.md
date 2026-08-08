# ig_bench — Instagram library comparison harness

Runs the same six data-fetch operations against several Instagram libraries and
prints a PASS/FAIL matrix, so a failure can be pinned to a specific library and
a specific operation instead of "it doesn't work".

Operations: `user_info`, `posts`, `comments`, `reels`, `stories`, `hashtag`.

Backends: `instagrapi` (sync), `aiograpi` (async), `aiograpi-rest` (HTTP service),
`osintgram` (legacy, via `instagram-private-api`).

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tools/ig_bench/requirements.txt
```

`aiograpi-rest` is a separate service — clone and run it if you want that row:

```bash
git clone https://github.com/subzeroid/aiograpi-rest.git
cd aiograpi-rest && pip install .          # needs Python >= 3.13
uvicorn aiograpi_rest.main:app --port 8000
```

## Check connectivity first

```bash
python tools/ig_bench/preflight.py
```

If this fails, every library will fail for the same reason and the result says
nothing about the libraries. Fix the network before drawing conclusions.

## Check the harness itself

```bash
python tools/ig_bench/selftest.py
```

Runs every operation against stubbed clients — no network. It verifies the
harness calls methods that actually exist on the installed libraries, so a
renamed upstream method shows up here rather than being misread as a block.

## Run the comparison

```bash
export IG_SESSIONID='...'                  # preferred
# or: export IG_USERNAME=... IG_PASSWORD=... [IG_OTP=123456]

python tools/ig_bench/bench.py --target instagram --json report.json
```

Useful flags:

| Flag | Meaning |
| --- | --- |
| `--target USERNAME` | public account to read (default `instagram`) |
| `--backends a,b` | subset to run |
| `--amount N` | items per operation (default 5) |
| `--delay S` | pause between operations, keeps rate limits calm (default 2) |
| `--rest-url URL` | where aiograpi-rest is listening (default `http://127.0.0.1:8000`) |
| `--traceback` | full tracebacks |
| `--skip-preflight` | run even when Instagram looks unreachable |

## Reading the output

- `PASS` on login but `FAIL` on one operation → that endpoint changed, or the
  target account restricts it (stories on a non-followed private account, for
  instance).
- `FAIL` on login across every backend → account, session, proxy, or network.
  Not a library bug. Check preflight and try a residential proxy.
- `SKIP` → the library or service isn't installed/running.

Use a throwaway account. Instagram rate-limits and challenges accounts that make
unusual API traffic.
