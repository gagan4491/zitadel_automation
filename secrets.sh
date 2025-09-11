#!/usr/bin/env bash
set -euo pipefail

# --- fill these ---
DOMAIN="https://app241dev-zitadel.int.capoptix.com"
TOKEN="NIJmsMJlrMy8HHNPZAVJyndbdwq3ifpO8rTJI4bOczi0cqlMk5pT0ZXAjKeUerDi"
ORG_ID="301926074198032394"           # the org that owns both resources

# Backend app (project + app)
PROJECT_ID="301926076681060362"       # e.g. your P9 project
APP_ID="301926079046647818"           # e.g. p9-backend app id
APP_KIND="api"                        # set to "api" (backend) or "oidc"

# Service user
USER_ID="304678892734545930"          # e.g. p9-service-dev-a

# --- backend app secret ---
APP_PATH="oidc_config"; [ "$APP_KIND" = "api" ] && APP_PATH="api_config"
BACKEND_SECRET=$(
  curl -sS -X POST "$DOMAIN/management/v1/projects/$PROJECT_ID/apps/$APP_ID/${APP_PATH}/_generate_client_secret" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-zitadel-orgid: $ORG_ID" \
    -H "Accept: application/json" -H "Content-Type: application/json" \
    -d '{}' | jq -r '.clientSecret // .secret // .value'
)

# --- service user secret ---
SERVICE_USER_SECRET=$(
  curl -sS -X POST "$DOMAIN/v2/users/$USER_ID/secret" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-zitadel-orgid: $ORG_ID" \
    -H "Accept: application/json" -H "Content-Type: application/json" \
    -d '{}' | jq -r '.clientSecret // .secret // .value'
)

echo "BACKEND_APP_SECRET=$BACKEND_SECRET"
echo "SERVICE_USER_SECRET=$SERVICE_USER_SECRET"
