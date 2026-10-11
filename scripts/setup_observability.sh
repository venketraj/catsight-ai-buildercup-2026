#!/usr/bin/env bash
#
# Turn CatSight's structured logs into Cloud Monitoring metrics and a dashboard.
# Run once in Cloud Shell. Safe to re-run: existing metrics are updated, the
# dashboard is replaced. Creates monitoring resources only; the service is not
# touched.
#
#   PROJECT_ID=techno-crackers-catsight ./scripts/setup_observability.sh
#   # optional budget alert (INR, for the trial credit):
#   PROJECT_ID=... BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX BUDGET_INR=5000 ./scripts/setup_observability.sh
#
# The service already writes one JSON log line per event (backend/app/logs.py)
# and ADK spans to Cloud Trace; this script only charts them.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
SERVICE="${SERVICE:-catsight-api}"
[[ -n "${PROJECT_ID}" ]] || { echo "PROJECT_ID is not set." >&2; exit 1; }

BASE="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE}\""
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

# --------------------------------------------------------------- metrics -- #

# name | event | description | extra filter
COUNTERS=(
  "catsight_analyses|analysis_done|Analyses completed, by mode (live, replay, cap_replay)|"
  "catsight_analysis_errors|analysis_error|Analyses that ended in an error|"
  "catsight_citations_verified|citation_verified|Wording flags whose citation verified|"
  "catsight_citations_withheld|citation_withheld|Wording flags withheld (citation did not check out)|"
  "catsight_unsupported_figures|unsupported_figures|AI text that stated a figure not in the engine output|"
  "catsight_courtroom_done|courtroom_done|Clause Courtroom runs completed|"
  "catsight_courtroom_skipped|courtroom_skipped|Courtroom requests with no qualifying flag|"
  "catsight_counsel_dropped|counsel_dropped|Courtroom counsel dropped for an unsupported quote|"
  "catsight_limit_refused|limit_refused|Requests refused by the per-visitor limit or daily cap|"
)

upsert_metric() {  # name, yaml file
  if gcloud logging metrics describe "$1" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud logging metrics update "$1" --project "${PROJECT_ID}" --config-from-file "$2" >/dev/null
    echo "  updated  $1"
  else
    gcloud logging metrics create "$1" --project "${PROJECT_ID}" --config-from-file "$2" >/dev/null
    echo "  created  $1"
  fi
}

echo "Log-based metrics:"
for row in "${COUNTERS[@]}"; do
  IFS='|' read -r name event desc extra <<<"${row}"
  label_block=""
  if [[ "${event}" == "analysis_done" ]]; then
    label_block='  labels:
  - key: mode
    valueType: STRING
labelExtractors:
  mode: EXTRACT(jsonPayload.mode)'
  fi
  cat >"${TMP}/${name}.yaml" <<EOF
description: "${desc}"
filter: '${BASE} AND jsonPayload.event="${event}"${extra}'
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
${label_block}
EOF
  upsert_metric "${name}" "${TMP}/${name}.yaml"
done

# Distributions from analysis_done on live runs: seconds and model cost.
cat >"${TMP}/catsight_live_seconds.yaml" <<EOF
description: "End-to-end seconds of a live analysis"
filter: '${BASE} AND jsonPayload.event="analysis_done" AND jsonPayload.mode="live"'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: "s"
valueExtractor: EXTRACT(jsonPayload.seconds)
bucketOptions:
  explicitBuckets:
    bounds: [2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180]
EOF
upsert_metric catsight_live_seconds "${TMP}/catsight_live_seconds.yaml"

cat >"${TMP}/catsight_live_cost_usd.yaml" <<EOF
description: "Model cost in USD of a live analysis"
filter: '${BASE} AND jsonPayload.event="analysis_done" AND jsonPayload.mode="live" AND jsonPayload.cost_usd:*'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: "USD"
valueExtractor: REGEXP_EXTRACT(jsonPayload.cost_usd, "([0-9.]+)")
bucketOptions:
  explicitBuckets:
    bounds: [0.002, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02, 0.03, 0.05, 0.1]
EOF
upsert_metric catsight_live_cost_usd "${TMP}/catsight_live_cost_usd.yaml"

# ------------------------------------------------------------- dashboard -- #

user() { echo "logging.googleapis.com/user/$1"; }

line_tile() {  # title, metric filter, aligner, reducer, groupBy-json
  cat <<EOF
{"title": "$1", "xyChart": {"dataSets": [{"plotType": "LINE", "timeSeriesQuery": {"timeSeriesFilter": {
  "filter": "$2",
  "aggregation": {"alignmentPeriod": "3600s", "perSeriesAligner": "$3",
                  "crossSeriesReducer": "$4", "groupByFields": $5}}}}]}}
EOF
}

UF="resource.type=\\\"cloud_run_revision\\\" AND resource.labels.service_name=\\\"${SERVICE}\\\""
TILES=(
  "$(line_tile 'Analyses per hour, by mode' "metric.type=\\\"$(user catsight_analyses)\\\"" ALIGN_SUM REDUCE_SUM '["metric.label.mode"]')"
  "$(line_tile 'Live analysis seconds (p50)' "metric.type=\\\"$(user catsight_live_seconds)\\\"" ALIGN_PERCENTILE_50 REDUCE_MEAN '[]')"
  "$(line_tile 'Live analysis model cost, USD (p50)' "metric.type=\\\"$(user catsight_live_cost_usd)\\\"" ALIGN_PERCENTILE_50 REDUCE_MEAN '[]')"
  "$(line_tile 'Citations verified per hour' "metric.type=\\\"$(user catsight_citations_verified)\\\"" ALIGN_SUM REDUCE_SUM '[]')"
  "$(line_tile 'Citations withheld per hour' "metric.type=\\\"$(user catsight_citations_withheld)\\\"" ALIGN_SUM REDUCE_SUM '[]')"
  "$(line_tile 'Courtroom: done / skipped / counsel dropped' "metric.type=one_of(\\\"$(user catsight_courtroom_done)\\\",\\\"$(user catsight_courtroom_skipped)\\\",\\\"$(user catsight_counsel_dropped)\\\")" ALIGN_SUM REDUCE_SUM '["metric.type"]')"
  "$(line_tile 'Guardrail trips: unsupported figures, limits, errors' "metric.type=one_of(\\\"$(user catsight_unsupported_figures)\\\",\\\"$(user catsight_limit_refused)\\\",\\\"$(user catsight_analysis_errors)\\\")" ALIGN_SUM REDUCE_SUM '["metric.type"]')"
  "$(line_tile 'Cloud Run requests per hour, by status' "metric.type=\\\"run.googleapis.com/request_count\\\" AND ${UF}" ALIGN_SUM REDUCE_SUM '["metric.label.response_code_class"]')"
  "$(line_tile 'Cloud Run request latency p95 (ms)' "metric.type=\\\"run.googleapis.com/request_latencies\\\" AND ${UF}" ALIGN_PERCENTILE_95 REDUCE_MEAN '[]')"
  "$(line_tile 'Cloud Run instances' "metric.type=\\\"run.googleapis.com/container/instance_count\\\" AND ${UF}" ALIGN_MAX REDUCE_SUM '["metric.label.state"]')"
)

{
  echo '{"displayName": "CatSight - live service", "mosaicLayout": {"columns": 12, "tiles": ['
  i=0
  for tile in "${TILES[@]}"; do
    x=$(( (i % 2) * 6 )); y=$(( (i / 2) * 4 ))
    [[ $i -gt 0 ]] && echo ","
    echo "{\"xPos\": ${x}, \"yPos\": ${y}, \"width\": 6, \"height\": 4, \"widget\": ${tile}}"
    i=$((i + 1))
  done
  echo ']}}'
} >"${TMP}/dashboard.json"

echo
echo "Dashboard:"
for old in $(gcloud monitoring dashboards list --project "${PROJECT_ID}" \
               --filter='displayName="CatSight - live service"' --format='value(name)'); do
  gcloud monitoring dashboards delete "${old}" --project "${PROJECT_ID}" --quiet >/dev/null
done
gcloud monitoring dashboards create --project "${PROJECT_ID}" --config-from-file "${TMP}/dashboard.json" >/dev/null
echo "  created  CatSight - live service"

# ---------------------------------------------------------- budget alert -- #

if [[ -n "${BILLING_ACCOUNT:-}" && -n "${BUDGET_INR:-}" ]]; then
  echo
  echo "Budget alert:"
  gcloud billing budgets create --billing-account "${BILLING_ACCOUNT}" \
    --display-name "CatSight ${PROJECT_ID}" \
    --budget-amount "${BUDGET_INR}INR" \
    --filter-projects "projects/${PROJECT_ID}" \
    --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0 >/dev/null
  echo "  created  ${BUDGET_INR} INR with alerts at 50/90/100% (emails go to billing admins)"
fi

cat <<EOF

Open:
  Dashboard  https://console.cloud.google.com/monitoring/dashboards?project=${PROJECT_ID}
  Traces     https://console.cloud.google.com/traces/list?project=${PROJECT_ID}
  Logs       https://console.cloud.google.com/logs/query;query=jsonPayload.event%3D%22analysis_done%22?project=${PROJECT_ID}

Log-based metrics count from now on; earlier log lines are not back-filled.
EOF
