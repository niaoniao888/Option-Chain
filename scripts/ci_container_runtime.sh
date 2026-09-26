#!/bin/sh
set -eu

[ "$(uname -m)" = "x86_64" ] || { echo "CI requires Linux x86_64" >&2; exit 1; }
export COMPOSE_PROJECT_NAME=options-panel-ci
cleanup() { docker compose down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
wait_health() {
  attempts=0
  until docker compose exec -T options-panel python -c "import os,urllib.request; from options_panel.config import normalize_base_path; p=normalize_base_path(os.environ.get('OPTIONS_BASE_PATH','')); urllib.request.urlopen('http://127.0.0.1:8780'+p+'/healthz',timeout=5).read()" >/dev/null 2>&1; do
    attempts=$((attempts + 1)); [ "$attempts" -lt 40 ] || { echo "healthz timeout" >&2; return 1; }
    sleep 2
  done
}

cat > .env <<'EOF'
OPTIONS_PORT=8780
OPTIONS_BASE_PATH=/options
OPTIONS_ALLOWED_HOSTS=127.0.0.1,localhost
OPTIONS_COLLECTOR_ENABLED=false
OPTIONS_BITCOIN_COLLECTOR_ENABLED=false
OPTIONS_US_COLLECTOR_ENABLED=false
OPTIONS_BITCOIN_PROVIDER=binance
OPTIONS_US_EQUITIES_PROVIDER=alpaca
ALPACA_API_KEY=
ALPACA_API_SECRET=
EOF

./scripts/options-panel.sh check
./scripts/options-panel.sh start
./scripts/options-panel.sh status

python3 - <<'PY'
import json, urllib.error, urllib.request
base = "http://127.0.0.1:8780/options"
for path in ("/", "/bitcoin/desktop/", "/bitcoin/mobile/", "/us-equities/desktop/", "/us-equities/mobile/", "/bitcoin/desktop/styles.css", "/api/v1/status", "/api/v1/modules"):
    with urllib.request.urlopen(base + path, timeout=10) as response:
        assert response.status == 200, (path, response.status)
request = urllib.request.Request(base + "/api/v1/us-equities/watchlist", method="POST", data=b"{}", headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(request, timeout=10)
except urllib.error.HTTPError as exc:
    assert exc.code == 405, exc.code
else:
    raise AssertionError("public write unexpectedly accepted")
with urllib.request.urlopen(base + "/api/v1/us-equities/health", timeout=10) as response:
    body = json.load(response)
    assert body["status"] == "configuration_required", body
    assert body["configured"] is False, body
    assert body["collector_running"] is False, body
PY

[ "$(docker compose exec -T options-panel id -u)" = 10001 ]
if docker compose exec -T options-panel sh -c 'touch /app/rootfs-write-test' 2>/dev/null; then
  echo "read-only root filesystem accepted a write" >&2; exit 1
fi

revision=$(docker compose exec -T options-panel python -m options_panel.manage watchlist revision)
docker compose exec -T options-panel python -m options_panel.manage watchlist add AAPL --revision "$revision" >/dev/null
./scripts/options-panel.sh stop
[ "$(docker inspect --format '{{.State.ExitCode}}' "$(docker compose ps --all -q options-panel)")" = 0 ]
docker compose up -d --build --force-recreate options-panel
wait_health
./scripts/options-panel.sh status
docker compose exec -T options-panel python -m options_panel.manage watchlist list | grep -q 'AAPL'
./scripts/options-panel.sh stop
./scripts/options-panel.sh backup
backup=$(find backups -maxdepth 1 -name 'options-panel-data-*.tar.gz' -type f | sort | tail -1)
revision=$(docker compose run --rm --no-deps -T options-panel python -m options_panel.manage watchlist revision)
docker compose run --rm --no-deps -T options-panel python -m options_panel.manage watchlist remove AAPL --revision "$revision" >/dev/null
./scripts/options-panel.sh restore "$backup"
docker compose run --rm --no-deps -T options-panel python -m options_panel.manage watchlist list | grep -q 'AAPL'

# Two real containers sharing the named volume must not own the same process lock.
docker compose run --rm --no-deps -T options-panel python -c \
  'from pathlib import Path; import time; from options_panel.runtime.refresher import ProcessLock; lock=ProcessLock(Path("/app/runtime/ci-singleton.lock")); lock.acquire(); Path("/app/runtime/ci-lock-ready").write_text("ready"); time.sleep(8)' &
lock_owner=$!
attempts=0
until docker compose run --rm --no-deps -T options-panel test -f /app/runtime/ci-lock-ready >/dev/null 2>&1; do
  attempts=$((attempts + 1)); [ "$attempts" -lt 10 ] || { echo "lock owner readiness timeout" >&2; exit 1; }
  sleep 1
done
if contender=$(docker compose run --rm --no-deps -T options-panel python -c \
  'from pathlib import Path; from options_panel.runtime.refresher import ProcessLock; ProcessLock(Path("/app/runtime/ci-singleton.lock")).acquire()' 2>&1); then
  echo "second container acquired singleton lock" >&2; exit 1
fi
printf '%s' "$contender" | grep -q 'already active'
wait "$lock_owner"

# Empty base path is a real root-mode deployment, not an alias for /options.
python3 - <<'PY'
from pathlib import Path
p=Path('.env'); p.write_text(p.read_text().replace('OPTIONS_BASE_PATH=/options', 'OPTIONS_BASE_PATH='))
PY
./scripts/options-panel.sh start
python3 - <<'PY'
import urllib.request
for path in ("/", "/bitcoin/desktop/", "/bitcoin/mobile/", "/us-equities/desktop/", "/us-equities/mobile/", "/api/v1/status"):
    with urllib.request.urlopen("http://127.0.0.1:8780" + path, timeout=10) as response:
        assert response.status == 200
PY
./scripts/options-panel.sh stop
