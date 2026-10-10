#!/usr/bin/env bash
#
# Deploy the CatSight API to Cloud Run.
#
# Takes the project from the environment, never from a literal in this file -
# the rule stated in backend/.env.example. Run `scripts/check_access.ps1`
# first; this script assumes the APIs are enabled and you are authenticated.
#
#   PROJECT_ID=techno-crackers-catsight ./scripts/deploy.sh
#
# Cost guards are applied here rather than left to the console (C-12), so a
# redeploy cannot quietly drop them.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-catsight-api}"
# The dedicated runtime identity (least privilege: Vertex AI user, Firestore
# user, Storage, log writer, trace agent) - never the default compute account,
# which holds Editor on the whole project.
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-catsight-run@${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}.iam.gserviceaccount.com}"
# Gemini 3.x is not served from us-central1, so the model location stays
# global while the service itself runs in the region with the data.
MODEL_LOCATION="${MODEL_LOCATION:-global}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is not set." >&2
  echo "  PROJECT_ID=techno-crackers-catsight ./scripts/deploy.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/backend"

BUCKET="${GCS_BUCKET:-${PROJECT_ID}-docs}"
ORIGINS="${ALLOWED_ORIGINS:-http://localhost:5173,https://${PROJECT_ID}.web.app,https://${PROJECT_ID}.firebaseapp.com}"
BUILD_LABEL="${BUILD_LABEL:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)}"

echo "project ${PROJECT_ID} | region ${REGION} | service ${SERVICE} | build ${BUILD_LABEL}"

# Build the SPA and stage it inside the Docker build context. Docker cannot
# COPY from outside the context, so frontend/dist is copied to backend/static
# rather than referenced in place.
if [[ "${SKIP_FRONTEND:-0}" != "1" ]]; then
  echo
  echo "building the frontend ..."
  ( cd "${REPO_ROOT}/frontend" && npm ci --no-fund --no-audit && npm run build )
  rm -rf "${REPO_ROOT}/backend/static"
  cp -r "${REPO_ROOT}/frontend/dist" "${REPO_ROOT}/backend/static"
  echo "staged $(find "${REPO_ROOT}/backend/static" -type f | wc -l) files into backend/static"
else
  mkdir -p "${REPO_ROOT}/backend/static"
fi

# --min-instances 0 by default so an idle demo costs nothing (C-12). During the
# judging window, run with MIN_INSTANCES=1 to keep one instance warm: no cold
# start for the first judge, at a small always-on cost from the trial credit.
#   MIN_INSTANCES=1 ./scripts/deploy.sh      # judging window
#   ./scripts/deploy.sh                      # back to scale-to-zero afterwards
# --max-instances 3 so a popular link cannot run up a bill. --timeout 300
# because an analysis streams for longer than the 60s default, and a truncated
# SSE stream looks to a judge like a broken product.
MIN_INSTANCES="${MIN_INSTANCES:-0}"
case "${MIN_INSTANCES}" in
  0|1) ;;
  *) echo "MIN_INSTANCES must be 0 or 1 (got ${MIN_INSTANCES})" >&2; exit 1 ;;
esac
echo "min-instances: ${MIN_INSTANCES}"

gcloud run deploy "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source . \
  --allow-unauthenticated \
  --service-account "${SERVICE_ACCOUNT}" \
  --min-instances "${MIN_INSTANCES}" \
  --max-instances 3 \
  --timeout 300 \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 20 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-env-vars "GOOGLE_CLOUD_LOCATION=${MODEL_LOCATION}" \
  --set-env-vars "GOOGLE_GENAI_USE_ENTERPRISE=true" \
  --set-env-vars "GCS_BUCKET=${BUCKET}" \
  --set-env-vars "DATA_BACKEND=firestore" \
  --set-env-vars "ENABLE_CLOUD_TRACE=true" \
  --set-env-vars "^|^ALLOWED_ORIGINS=${ORIGINS}" \
  --set-env-vars "BUILD_LABEL=${BUILD_LABEL}"

URL="$(gcloud run services describe "${SERVICE}" \
  --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')"

echo
echo "Service URL: ${URL}"
echo
echo "The UI and the API are the SAME origin, so there is nothing to configure:"
echo "  open ${URL}"
echo
echo "Verify: ./scripts/smoke_test.sh ${URL}"
echo
echo "ALLOWED_ORIGINS is still set, but only matters if the UI is ever served"
echo "from a different origin (e.g. Firebase Hosting). Served from this"
echo "service there is no cross-origin request to allow."
