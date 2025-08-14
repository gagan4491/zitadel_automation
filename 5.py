#!/usr/bin/env python3
import requests, json, configparser, sys, csv, os

# ============ Config ============
TARGET_CLIENT_ID = "301926079046713354"  # rotate this one if found
OUTPUT_CSV       = os.environ.get("ZITADEL_OUT", "zitadel_clients.csv")

cfg = configparser.ConfigParser()
cfg.read("zitadel.conf")

DOMAIN       = cfg.get("zitadel", "domain").rstrip("/")
ACCESS_TOKEN = cfg.get("zitadel", "access_token")
ORG_ID       = cfg.get("zitadel", "org_id")

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "x-zitadel-orgid": ORG_ID,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# ============ Helpers ============
def http_post(url, payload):
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def http_put(url, payload):
    r = requests.put(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def extract(d, *keys):
    for k in keys:
        if isinstance(k, (list, tuple)):
            cur = d
            ok = True
            for part in k:
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok:
                return cur
        else:
            if k in d:
                return d[k]
    return None

# ============ Projects & Apps (OIDC/API) ============
def list_projects():
    url = f"{DOMAIN}/management/v1/projects/_search"
    projects, offset, limit = [], 0, 200
    while True:
        page = http_post(url, {"limit": limit, "offset": offset, "asc": True, "queries": []})
        chunk = page.get("result") or page.get("projects") or []
        projects.extend(chunk)
        if len(chunk) < limit:
            return projects
        offset += len(chunk)

def list_apps(project_id):
    url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/_search"
    apps, offset, limit = [], 0, 200
    while True:
        page = http_post(url, {"limit": limit, "offset": offset, "asc": True, "queries": []})
        chunk = page.get("result") or page.get("apps") or []
        apps.extend(chunk)
        if len(chunk) < limit:
            return apps
        offset += len(chunk)

def pick_client_id_from_app(app):
    return (
        extract(app, ["oidcConfig","clientId"]) or
        extract(app, ["apiConfig","clientId"]) or
        extract(app, "clientId") or
        ""
    )

def app_type_label(app):
    # normalize type across API variants
    t = (app.get("appType") or app.get("type") or "").upper()
    if "OIDC" in t: return "OIDC"
    if "API"  in t: return "API"
    # fallback based on presence of config keys
    if "oidcConfig" in app: return "OIDC"
    if "apiConfig"  in app: return "API"
    return t or "UNKNOWN"

# ============ Service Users (machine users) ============
def list_service_users():
    """
    Uses User Service v2: POST /v2/users with a TypeQuery(TYPE_MACHINE).
    The v2 APIs often use lowerCamelCase; be liberal in parsing the response.
    """
    url = f"{DOMAIN}/v2/users"
    users = []
    # request with a sane page size; bump if you have tons of service users
    body = {
        "limit": 200,
        "queries": [
            {"typeQuery": {"type": "TYPE_MACHINE"}}
        ]
    }

    # Try token-based pagination if available; otherwise rely on limit.
    next_token_key_candidates = ("nextPageToken", "next_page_token", "pageToken")
    while True:
        data = http_post(url, body)
        chunk = data.get("users") or data.get("result") or []
        users.extend(chunk)

        next_token = None
        for k in next_token_key_candidates:
            if k in data and data[k]:
                next_token = data[k]
                break

        if next_token:
            # carry forward token using a few common names
            body["nextPageToken"] = next_token
            body["pageToken"] = next_token
        else:
            # if no token, assume we’re done (or raise limit if needed)
            break

    return users

def service_user_fields(u):
    user_id = extract(u, "userId", "user_id", "id") or ""
    username = extract(u, "username", "userName") or ""
    # Display-friendly name (if present)
    display = (
        extract(u, "displayName") or
        extract(u, ["profile","displayName"]) or
        username or user_id
    )
    # In ZITADEL v2 AddSecret: client_id == username for machine users
    client_id = username or user_id
    return user_id, username, display, client_id

# ============ Secret rotation ============
def rotate_app_secret(project_id, app):
    app_id = app.get("id")
    t = app_type_label(app)
    if t == "OIDC":
        url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/oidc_config/_generate_client_secret"
    else:
        url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/api_config/_generate_client_secret"
    data = http_post(url, {})
    # secret field name differs by build; check multiple keys
    return extract(data, "clientSecret", "secret", "value")

def rotate_service_user_secret(user_id):
    # v2 endpoint
    url = f"{DOMAIN}/v2/users/{user_id}/secret"
    data = requests.post(url, headers=HEADERS, json={}, timeout=30)
    data.raise_for_status()
    payload = data.json()
    return extract(payload, "clientSecret", "secret", "value")

# ============ Main ============
rows = []
new_secret_value = None

# 1) Projects + Apps
projects = list_projects()
for p in projects:
    pid = p.get("id") or p.get("projectId") or ""
    pname = p.get("name") or ""
    apps = list_apps(pid)
    for app in apps:
        app_id = app.get("id") or ""
        atype  = app_type_label(app)
        client_id = pick_client_id_from_app(app) or ""
        # rotate secret ONLY for target
        rotated = ""
        if str(client_id) == str(TARGET_CLIENT_ID):
            try:
                rotated = rotate_app_secret(pid, app) or ""
                new_secret_value = rotated or new_secret_value
            except Exception as e:
                rotated = f"ERROR: {e}"
        rows.append({
            "scope": "APP",
            "project_id": pid,
            "project_name": pname,
            "resource_id": app_id,     # the app ID
            "name": app.get("name") or "",
            "type": atype,
            "client_id": str(client_id),
            "new_secret_if_target": rotated,
        })

# 2) Service Users (machine)
try:
    svc_users = list_service_users()
    for u in svc_users:
        user_id, username, display, client_id = service_user_fields(u)
        rotated = ""
        if str(client_id) == str(TARGET_CLIENT_ID) or str(user_id) == str(TARGET_CLIENT_ID):
            try:
                rotated = rotate_service_user_secret(user_id) or ""
                new_secret_value = rotated or new_secret_value
            except Exception as e:
                rotated = f"ERROR: {e}"
        rows.append({
            "scope": "SERVICE_USER",
            "project_id": "",          # not tied to a single project
            "project_name": "",
            "resource_id": user_id,    # the user ID
            "name": display,
            "type": "SERVICE_USER",
            "client_id": str(client_id),
            "new_secret_if_target": rotated,
        })
except Exception as e:
    print(f"WARNING: Failed to list service users: {e}", file=sys.stderr)

# 3) Output: CSV file + screen
fieldnames = ["scope","project_id","project_name","resource_id","name","type","client_id","new_secret_if_target"]

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)

# print a compact table on screen
print(",".join(fieldnames))
for r in rows:
    print(",".join((r.get(k,"") or "").replace("\n"," ").replace(","," ") for k in fieldnames))

# If we rotated a secret, also print it clearly at the end
if new_secret_value:
    print("\nNEW SECRET for TARGET_CLIENT_ID:")
    print(new_secret_value)
else:
    print("\nNo secret rotated (TARGET_CLIENT_ID not found among apps or service users).")
print(f"\nWrote {len(rows)} rows to: {OUTPUT_CSV}")
