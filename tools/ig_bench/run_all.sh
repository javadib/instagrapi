#!/usr/bin/env bash
# One-shot: install every backend and test all of them against Instagram.
#
#   export CRAWLER_INSTAGRAM_USERNAME='your_account'
#   export CRAWLER_INSTAGRAM_PASSWORD='your_password'
#   bash tools/ig_bench/run_all.sh [target_username]
#
# Optional:
#   CRAWLER_INSTAGRAM_PROXY='http://user:pass@host:port'   strongly recommended
#   CRAWLER_INSTAGRAM_OTP='123456'                         if 2FA is on
#
# Writes ig_bench_report.json next to wherever you run it.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-instagram}"
WORK="${IG_BENCH_WORKDIR:-$PWD/.ig_bench}"

: "${CRAWLER_INSTAGRAM_USERNAME:?set CRAWLER_INSTAGRAM_USERNAME}"
: "${CRAWLER_INSTAGRAM_PASSWORD:?set CRAWLER_INSTAGRAM_PASSWORD}"

# bench.py reads IG_*; map the CRAWLER_* names onto them.
export IG_USERNAME="$CRAWLER_INSTAGRAM_USERNAME"
export IG_PASSWORD="$CRAWLER_INSTAGRAM_PASSWORD"
export IG_OTP="${CRAWLER_INSTAGRAM_OTP:-}"

echo "==> workdir: $WORK"
mkdir -p "$WORK"

# ---------------------------------------------------------------- 1. backends
if [ ! -d "$WORK/venv" ]; then
    echo "==> creating venv"
    python3 -m venv "$WORK/venv"
fi
"$WORK/venv/bin/pip" install -q -U pip
echo "==> installing instagrapi, aiograpi, instagram-private-api"
"$WORK/venv/bin/pip" install -q -r "$HERE/requirements.txt" || {
    echo "!! backend install failed"; exit 1;
}

# ------------------------------------------------------- 2. aiograpi-rest svc
REST_URL="http://127.0.0.1:8000"
REST_PID=""
PY313="$(command -v python3.13 || true)"

if [ -n "$PY313" ]; then
    if [ ! -d "$WORK/aiograpi-rest" ]; then
        echo "==> cloning aiograpi-rest"
        git clone -q --depth 1 https://github.com/subzeroid/aiograpi-rest.git "$WORK/aiograpi-rest"
    fi
    if [ ! -d "$WORK/venv-rest" ]; then
        "$PY313" -m venv "$WORK/venv-rest"
        "$WORK/venv-rest/bin/pip" install -q -U pip
        echo "==> installing aiograpi-rest"
        "$WORK/venv-rest/bin/pip" install -q "$WORK/aiograpi-rest"
    fi
    echo "==> starting aiograpi-rest on $REST_URL"
    ( cd "$WORK/aiograpi-rest" && "$WORK/venv-rest/bin/python" -m uvicorn \
        aiograpi_rest.main:app --host 127.0.0.1 --port 8000 > "$WORK/rest.log" 2>&1 ) &
    REST_PID=$!
    sleep 8
    curl -sf -o /dev/null "$REST_URL/openapi.json" \
        && echo "==> aiograpi-rest is up" \
        || echo "!! aiograpi-rest did not start, see $WORK/rest.log"
else
    echo "!! python3.13 not found — skipping aiograpi-rest (it requires >= 3.13)"
fi

cleanup() { [ -n "$REST_PID" ] && kill "$REST_PID" 2>/dev/null; }
trap cleanup EXIT

# ---------------------------------------------------------------- 3. preflight
echo
"$WORK/venv/bin/python" "$HERE/preflight.py"
PREFLIGHT=$?

echo
"$WORK/venv/bin/python" "$HERE/selftest.py" || echo "!! harness self-test reported a problem"

# -------------------------------------------------------------------- 4. bench
echo
EXTRA=""
[ $PREFLIGHT -ne 0 ] && EXTRA="--skip-preflight"

"$WORK/venv/bin/python" "$HERE/bench.py" \
    --target "$TARGET" \
    --rest-url "$REST_URL" \
    --json ig_bench_report.json \
    $EXTRA

echo
echo "==> full report: ig_bench_report.json"
