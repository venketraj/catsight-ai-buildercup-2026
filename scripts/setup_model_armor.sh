#!/usr/bin/env bash
#
# Set up Google Cloud Model Armor for CatSight's follow-up questions.
# Run once in Cloud Shell before deploy.sh. Safe to re-run: an existing
# template is left as it is, and the role grant is idempotent.
#
#   PROJECT_ID=techno-crackers-catsight ./scripts/setup_model_armor.sh
#
# What it does:
#   1. enables modelarmor.googleapis.com;
#   2. creates the template the service screens with (prompt injection and
#      jailbreak, malicious URLs, harassment and hate speech);
#   3. lets the catsight-run service account call it (roles/modelarmor.user).
#
# deploy.sh then sets MODEL_ARMOR_TEMPLATE and MODEL_ARMOR_LOCATION on the
# service; /health reports "question_screening": "local+model-armor".

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
LOCATION="${MODEL_ARMOR_LOCATION:-us-central1}"
TEMPLATE="${MODEL_ARMOR_TEMPLATE:-catsight-ask}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-catsight-run@${PROJECT_ID}.iam.gserviceaccount.com}"
[[ -n "${PROJECT_ID}" ]] || { echo "PROJECT_ID is not set." >&2; exit 1; }

echo "project ${PROJECT_ID} | location ${LOCATION} | template ${TEMPLATE}"

gcloud services enable modelarmor.googleapis.com --project "${PROJECT_ID}"

# Model Armor is regional: template commands go to the regional endpoint.
gcloud config set api_endpoint_overrides/modelarmor \
  "https://modelarmor.${LOCATION}.rep.googleapis.com/" >/dev/null

if gcloud model-armor templates describe "${TEMPLATE}" \
     --project "${PROJECT_ID}" --location "${LOCATION}" >/dev/null 2>&1; then
  echo "template ${TEMPLATE} exists - left unchanged"
else
  gcloud model-armor templates create "${TEMPLATE}" \
    --project "${PROJECT_ID}" \
    --location "${LOCATION}" \
    --pi-and-jailbreak-filter-settings-enforcement=enabled \
    --pi-and-jailbreak-filter-settings-confidence-level=MEDIUM_AND_ABOVE \
    --malicious-uri-filter-settings-enforcement=enabled \
    --rai-settings-filters='[{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"}]'
  echo "template ${TEMPLATE} created"
fi

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:${SERVICE_ACCOUNT}" \
  --role roles/modelarmor.user \
  --condition None >/dev/null
echo "roles/modelarmor.user granted to ${SERVICE_ACCOUNT}"

# Leave gcloud as it was for other commands in this shell.
gcloud config unset api_endpoint_overrides/modelarmor >/dev/null 2>&1 || true

echo
echo "Done. Deploy with ./scripts/deploy.sh, then check /health for question_screening."
