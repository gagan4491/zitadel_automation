#!/usr/bin/env python3
import requests, json, configparser, sys

TARGET_CLIENT_ID = "301926079046713354"  # compare as string

cfg = configparser.ConfigParser()
cfg.read("zitadel.conf")

DOMAIN       = cfg.get("zitadel", "domain").rstrip("/")
ACCESS_TOKEN = cfg.get("zitadel", "access_token")
ORG_ID       = cfg.get("zitadel", "org_id")
PROJECT_ID   = cfg.get("zitadel", "project_id")

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "x-zitadel-orgid": ORG_ID,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def list_apps():
    url = f"{DOMAIN}/management/v1/projects/{PROJECT_ID}/apps/_search"
    apps, offset, limit = [], 0, 200
    while True:
        r = requests.post(url, headers=HEADERS, json={"limit": limit, "offset": offset, "asc": True, "queries": []}, timeout=30)
        r.raise_for_status()
        page = r.json()
        chunk = page.get("result") or page.get("apps") or []
        apps.extend(chunk)
        if len(chunk) < limit:
            return apps
        offset += len(chunk)

def pick_client_id(app):
    return (
        (app.get("oidcConfig") or {}).get("clientId")
        or (app.get("apiConfig") or {}).get("clientId")
        or app.get("clientId")
        or ""
    )

apps = list_apps()
target_app = next((a for a in apps if str(pick_client_id(a)) == TARGET_CLIENT_ID), None)
if not target_app:
    print(f"No app found with clientId={TARGET_CLIENT_ID}", file=sys.stderr)
    sys.exit(1)

app_id = target_app.get("id")
app_type = (target_app.get("appType") or target_app.get("type") or "").upper()
is_oidc = "oidcConfig" in target_app or app_type == "OIDC"

if is_oidc:
    regen_url = f"{DOMAIN}/management/v1/projects/{PROJECT_ID}/apps/{app_id}/oidc_config/_generate_client_secret"
else:
    regen_url = f"{DOMAIN}/management/v1/projects/{PROJECT_ID}/apps/{app_id}/api_config/_generate_client_secret"

resp = requests.post(regen_url, headers=HEADERS, json={}, timeout=30)
resp.raise_for_status()
data = resp.json()

# Secret can be under different keys depending on build
NEW_SECRET = data.get("clientSecret") or data.get("secret") or data.get("value")
if not NEW_SECRET:
    print(f"Secret not found in response: {json.dumps(data)}", file=sys.stderr)
    sys.exit(2)

print(NEW_SECRET)
