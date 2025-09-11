#!/usr/bin/env bash
set -euo pipefail

# Load secrets from .env
ENV_FILE="${ENV_FILE:-secrets.env}"
[[ -r "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
set -a; source "$ENV_FILE"; set +a

# Optional: fail if missing
: "${P9_BACKEND_CLIENT_SECRET:?P9_BACKEND_CLIENT_SECRET not set in secrets.env}"
: "${P9_SERVICE_DEV_A_CLIENT_SECRET:?P9_SERVICE_DEV_A_CLIENT_SECRET not set in secrets.env}"

PG_USER="postgres"
TARGET_DB="p9"

HOST_IP=$(hostname -I | awk '{print $1}')
LAST_OCTET=$(echo "$HOST_IP" | awk -F '.' '{print $4}')
NEW_DOMAIN="app${LAST_OCTET}dev.int.capoptix.com"
ZITADEL_DOMAIN="app${LAST_OCTET}dev-zitadel.int.capoptix.com"

# If you worry secrets might contain single quotes:
SAFE_BACKEND_SECRET=${P9_BACKEND_CLIENT_SECRET//\'/\'\'}
SAFE_BACKEND_ADMIN_SECRET=${P9_SERVICE_DEV_A_CLIENT_SECRET//\'/\'\'}

sudo -u "$PG_USER" psql -d "$TARGET_DB" <<EOF

-- Replace old domains
UPDATE ts_config
SET config_value = REPLACE(config_value, 'ad.capoptix.com', '$NEW_DOMAIN')
WHERE config_value ILIKE '%ad.capoptix.com%';

-- Update specific config values
UPDATE ts_config
SET config_value = CASE config_key
  WHEN 'zitadel.organization.id' THEN '301926074198032394'
  WHEN 'oidc.frontend.resource_id' THEN '301926077821911050'
  WHEN 'oidc.frontend.client_id' THEN '301926077821976586'
  WHEN 'oidc.backend.client_id' THEN '301926079046713354'
  WHEN 'oidc.backend-admin.client_secret' THEN '${SAFE_BACKEND_ADMIN_SECRET}'
  WHEN 'oidc.backend.grant_type' THEN 'client_credentials'
  WHEN 'oidc.backend.service_user.token' THEN 's7YaZhDO2lBQPihQTJgIH1fBFd3bB2yTRGdzlSEZwUHop5mPFcKQBGjGbAgIKy04'
  WHEN 'unleash.api.key' THEN 'default:production.e616042305afd48f203f60f6bfdf3e6fcafb39fe559e747ffa404645'
  WHEN 'unleash.api.frontend_key' THEN 'default:production.f882ccb2501df9ba4fd0329ea8f790ccdab35ae4bd9526ae557f2387'
  WHEN 'oidc.backend.client_secret' THEN '${SAFE_BACKEND_SECRET}'
  WHEN 'oidc.backend-admin.client_id' THEN 'p9-service-dev-a'
  WHEN 'oidc.frontend.post_logout_redirect_uri' THEN 'https://${NEW_DOMAIN}/app-web/'
  WHEN 'oidc.frontend.redirect_uri' THEN 'https://${NEW_DOMAIN}/app-web/auth-callback'
  WHEN 'unleash.api.url.public' THEN 'https://${NEW_DOMAIN}/unleash/api/frontend'
  WHEN 'unleash.api.public_url' THEN 'https://${NEW_DOMAIN}/unleash/api/frontend'
  WHEN 'zitadel.api.url' THEN 'https://${ZITADEL_DOMAIN}'
  WHEN 'oidc.discovery_url' THEN 'https://${ZITADEL_DOMAIN}/.well-known/openid-configuration'
  WHEN 'unleash.api.url' THEN 'http://unleash:4242/unleash/api'
  WHEN 'oidc.backend.scope' THEN 'openid profile urn:zitadel:iam:org:project:id:zitadel:aud'
END
WHERE config_key IN (
  'zitadel.organization.id',
  'oidc.frontend.resource_id',
  'oidc.frontend.client_id',
  'oidc.backend.client_id',
  'oidc.backend-admin.client_secret',
  'oidc.backend.grant_type',
  'oidc.backend.service_user.token',
  'unleash.api.key',
  'unleash.api.frontend_key',
  'oidc.backend.client_secret',
  'oidc.backend-admin.client_id',
  'oidc.frontend.post_logout_redirect_uri',
  'oidc.frontend.redirect_uri',
  'unleash.api.url.public',
  'unleash.api.public_url',
  'zitadel.api.url',
  'oidc.discovery_url',
  'unleash.api.url',
  'oidc.backend.scope'
);
EOF

echo "Update completed with NEW_DOMAIN=${NEW_DOMAIN}, ZITADEL_DOMAIN=${ZITADEL_DOMAIN}"
