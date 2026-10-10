#!/usr/bin/env bash
#
# Verify a running CatSight API — S7's gate.
#
#   ./scripts/smoke_test.sh                              # local, :8080
#   ./scripts/smoke_test.sh https://catsight-api-x.run.app
#
# Checks behaviour, not just status codes. A 200 that returns the wrong number
# is worse than a 500, because nobody investigates it.

set -uo pipefail

BASE="${1:-http://localhost:8080}"
PASS=0
FAIL=0

ok()   { printf '  \033[32m[PASS]\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m[FAIL]\033[0m %s\n' "$1"; [[ -n "${2:-}" ]] && printf '         %s\n' "$2"; FAIL=$((FAIL+1)); }

echo
echo "CatSight smoke test against ${BASE}"
echo "======================================================================"

# -- API-1 ------------------------------------------------------------------ #
echo
echo "1. Health"
HEALTH="$(curl -fsS --max-time 30 "${BASE}/healthz" 2>/dev/null)" || HEALTH=""
if [[ -z "${HEALTH}" ]]; then
  bad "GET /healthz" "no response - is the service up?"
  echo; echo "Cannot continue."; exit 1
fi
grep -q '"status":"ok"' <<<"${HEALTH}" && ok "GET /healthz" || bad "GET /healthz" "${HEALTH:0:200}"

if grep -q '"configured":true' <<<"${HEALTH}"; then
  ok "project configured"
else
  bad "project configured" "GOOGLE_CLOUD_PROJECT is unset in the deployed service"
fi

# C-2: gemini-2.5-* retires 2026-10-20 and must never be deployed.
if grep -q 'gemini-2\.5' <<<"${HEALTH}"; then
  bad "no retired model" "a gemini-2.5-* model is configured"
else
  ok "no retired model configured"
fi

# -- API-2 ------------------------------------------------------------------ #
echo
echo "2. Replay catalogue"
EVENTS="$(curl -fsS --max-time 30 "${BASE}/api/events" 2>/dev/null)" || EVENTS=""
grep -q '"jebi-2018"' <<<"${EVENTS}" && ok "GET /api/events includes the hero event" \
  || bad "GET /api/events" "${EVENTS:0:200}"

# -- API-3 ------------------------------------------------------------------ #
echo
echo "3. Treaties"
TREATIES="$(curl -fsS --max-time 30 "${BASE}/api/treaties" 2>/dev/null)" || TREATIES=""
grep -q '"T-001"' <<<"${TREATIES}" && ok "GET /api/treaties includes T-001" \
  || bad "GET /api/treaties" "${TREATIES:0:200}"

DETAIL="$(curl -fsS --max-time 30 "${BASE}/api/treaties/T-001" 2>/dev/null)" || DETAIL=""
grep -q 'Sakura' <<<"${DETAIL}" && ok "GET /api/treaties/T-001" \
  || bad "GET /api/treaties/T-001" "${DETAIL:0:200}"

MISSING="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "${BASE}/api/treaties/T-999")"
[[ "${MISSING}" == "404" ]] && ok "an unknown treaty is a 404" || bad "unknown treaty" "got ${MISSING}"

# -- API-4 ------------------------------------------------------------------ #
echo
echo "4. Analysis stream (the demo path)"
STREAM="$(curl -fsS --max-time 120 -X POST "${BASE}/api/analyses" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"replay","event_id":"jebi-2018"}' 2>/dev/null)" || STREAM=""

if [[ -z "${STREAM}" ]]; then
  bad "POST /api/analyses" "no stream"
else
  grep -q '"type":"done"' <<<"${STREAM}" && ok "the stream completes" \
    || bad "the stream completes" "no done frame"
  grep -q '"type":"error"' <<<"${STREAM}" && bad "no error frames" "an error frame was streamed" \
    || ok "no error frames"
  grep -q '"key":"impact"' <<<"${STREAM}" && ok "an impact result is streamed" \
    || bad "impact result" "missing"

  # The money moment. The whole demo rests on Sakura's programme burning
  # partially: L1 exhausted, L2 part-burnt, L3 untouched. If the calibration
  # drifts, every layer exhausts and the hours-clause split shows nothing.
  if grep -q '"treaty_id":"T-001"' <<<"${STREAM}"; then
    ok "the hero treaty T-001 responds"
  else
    bad "T-001 responds" "the hero treaty did not match - check as_if and the period"
  fi
  if grep -qE '"our_net":"6\.(7|8)[0-9]' <<<"${STREAM}"; then
    ok "T-001 our_net is near the documented 6.82"
  else
    bad "T-001 our_net" "expected ~6.81; the calibration may have drifted"
  fi
fi

# -- API-5 ------------------------------------------------------------------ #
echo
echo "5. Analysis document"
DOC="$(curl -fsS --max-time 60 "${BASE}/api/analyses/replay-jebi-2018" 2>/dev/null)" || DOC=""
grep -q '"treaties_matched":13' <<<"${DOC}" && ok "GET /api/analyses/replay-jebi-2018" \
  || bad "GET /api/analyses/replay-jebi-2018" "${DOC:0:200}"

# -- FR-GUARD --------------------------------------------------------------- #
echo
echo "6. Guardrails"
LONG="$(printf 'x%.0s' {1..301})"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST "${BASE}/api/analyses" \
  -H 'Content-Type: application/json' -d "{\"mode\":\"live\",\"event_query\":\"${LONG}\"}")"
[[ "${CODE}" == "422" ]] && ok "an over-long live query is refused" || bad "query length guard" "got ${CODE}"

echo
echo "======================================================================"
echo "PASS ${PASS}   FAIL ${FAIL}"
[[ "${FAIL}" -eq 0 ]] || exit 1
echo "Smoke test green."
