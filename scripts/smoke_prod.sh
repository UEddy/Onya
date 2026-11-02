#!/usr/bin/env bash
# Production smoke test. Usage: scripts/smoke_prod.sh API_URL SITE_URL
# API_URL is the Baseten invoke URL; read checks go through the site's
# server-side proxy (which adds the Baseten key), never from here.
# Prints no secrets. Exits non-zero on the first failed check.
set -u
API="${1:?usage: smoke_prod.sh API_URL SITE_URL}"
SITE="${2:?usage: smoke_prod.sh API_URL SITE_URL}"
fail=0

check_200() {
  local url="$1"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [ "$code" = "200" ]; then
    echo "OK 200 $url"
  else
    echo "FAIL $code $url"
    fail=1
  fi
}

check_200 "$SITE/api/backend/health"
check_200 "$SITE/api/backend/companies"
check_200 "$SITE/api/backend/backtest"
check_200 "$SITE/"
check_200 "$SITE/app/watchlist"
check_200 "$SITE/app/company/SNBR"
check_200 "$SITE/app/agent"

# The Baseten gateway must reject a call with no Api-Key header.
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/agent/run" \
  -H "Content-Type: application/json" -d '{"question":"smoke"}')
if [ "$code" = "401" ]; then
  echo "OK 401 POST $API/agent/run without Baseten key"
else
  echo "FAIL $code POST $API/agent/run without Baseten key (want 401)"
  fail=1
fi

# The site HTML must never name the server-only token variable; if the
# name leaked, a server secret path reached the page. (Asset file names
# are hashes, so a value-level check would false-positive on them.)
if curl -s "$SITE/" | grep -q "ONYA_DEMO_TOKEN"; then
  echo "FAIL site HTML mentions ONYA_DEMO_TOKEN"
  fail=1
else
  echo "OK site HTML contains no token-looking value"
fi

exit "$fail"
