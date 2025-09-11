#!/usr/bin/env python3
import requests, json, configparser, sys, csv, os

# ================== Targets / Output ==================
TARGET_CLIENT_ID = "301926079046713354"        # rotate if matches app client_id or service user's username/userId
TARGET_SERVICE_USER_ID = "304678892734545930"  # also rotate this specific service user ID ("" to disable)
OUTPUT_CSV = os.environ.get("ZITADEL_OUT", "zitadel_clients.csv")
TIMEOUT = 30
# ======================================================

# --------- Config from zitadel.conf ---------
cfg = configparser.ConfigParser()
cfg.read("zitadel.conf")

DOMAIN       = cfg.get("zitadel", "domain").rstrip("/")
ACCESS_TOKEN = cfg.get("zitadel", "access_token")
ORG_ID       = cfg.get("zitadel", "org_id")

BASE_HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
# Use ORG_ID by default for list/search; rotation will detect resourceOwner automatically
HEADERS = dict(BASE_HEADERS)
HEADERS["x-zitadel-orgid"] = ORG_ID

# ----------------- Utility -----------------
def http_post(url, payload, headers=HEADERS):
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def http_put(url, payload, headers=HEADERS):
    r = requests.put(url, headers=headers, json=payload, timeout=TIMEOUT)
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
            if isinstance(d, dict) and k in d:
                return d[k]
    return None

def _h(org_id=None):
    h = dict(BASE_HEADERS)
    if org_id:
        h["x-zitadel-orgid"] = org_id
    return h

# ------------- Projects & Apps -------------
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
    t = (app.get("appType") or app.get("type") or "").upper()
    if "OIDC" in t: return "OIDC"
    if "API"  in t: return "API"
    if "oidcConfig" in app: return "OIDC"
    if "apiConfig"  in app: return "API"
    return t or "UNKNOWN"

def rotate_app_secret(project_id, app):
    app_id = app.get("id")
    t = app_type_label(app)
    if t == "OIDC":
        url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/oidc_config/_generate_client_secret"
    else:
        url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/api_config/_generate_client_secret"
    data = http_post(url, {}, headers=HEADERS)
    return extract(data, "clientSecret", "secret", "value")

# ------------- Service Users (v2) -------------
# def list_service_users():
#     """
#     POST /v2/users with TypeQuery(TYPE_MACHINE)
#     """
#     url = f"{DOMAIN}/v2/users"
#     users = []
#     body = {"limit": 200, "queries": [{"typeQuery": {"type": "TYPE_MACHINE"}}]}
#     next_keys = ("nextPageToken", "next_page_token", "pageToken")
#     while True:
#         data = http_post(url, body, headers=HEADERS)
#         chunk = data.get("users") or data.get("result") or []
#         # print(chunk)
#         #
#         # filtered = [
#         #     u for u in chunk
#         #     if (u.get("details", {}) or u.get("user", {}).get("details", {})).get("resourceOwner") == ORG_ID
#         # ]
#         # print(filtered)
#
#
#         next_token = next((data[k] for k in next_keys if k in data and data[k]), None)
#
#         if next_token:
#             body["nextPageToken"] = next_token
#             body["pageToken"] = next_token
#         else:
#             break
#     return users

def service_user_fields(u):
    user_id = extract(u, "userId", "user_id", "id") or ""
    username = extract(u, "username", "userName") or ""
    display = (
        extract(u, "displayName") or
        extract(u, ["profile","displayName"]) or
        username or user_id
    )
    client_id = username or user_id
    return user_id, username, display, client_id

# ------ ResourceOwner-aware secret rotation for service users ------
def _extract_user(payload):
    # v2 may return flat or wrapped under "user"
    return payload.get("user", payload)

def _is_machine(u):
    t = (u.get("type") or u.get("userType") or "").upper()
    return ("MACHINE" in t) or ("machine" in u)

def _resource_owner(payload):
    details = payload.get("details") or payload.get("user", {}).get("details") or {}
    return details.get("resourceOwner") or payload.get("resourceOwner")

def _get_user(user_id, org_hint=None):
    # Try with org hint then without
    for org in (org_hint, None):
        r = requests.get(f"{DOMAIN}/v2/users/{user_id}", headers=_h(org), timeout=TIMEOUT)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"user_id '{user_id}' not found in visible orgs")

def rotate_service_user_secret(user_id, org_hint=ORG_ID):
    """
    Robust rotation:
      - GET /v2/users/{id} to find resourceOwner (owning org)
      - POST /v2/users/{id}/secret with owning org header, fallback w/o header
      - Fallback to PUT /management/v1/users/{id}/secret with owning org header
    """
    # Resolve user + owner
    payload = _get_user(user_id, org_hint)
    u = _extract_user(payload)
    owner = _resource_owner(payload) or org_hint

    if not _is_machine(u):
        kind = (u.get("type") or u.get("userType") or "UNKNOWN")
        state = u.get("state") or "UNKNOWN"
        raise RuntimeError(f"user '{user_id}' is not MACHINE (type={kind}, state={state})")

    # Try v2 with owner, then without org header
    url = f"{DOMAIN}/v2/users/{user_id}/secret"
    for try_org in (owner, None):
        r = requests.post(url, headers=_h(try_org), json={}, timeout=TIMEOUT)
        if r.status_code == 404:
            # org-mismatch or masked lack of write; try next variant
            continue
        if r.status_code == 403:
            raise RuntimeError("403 Forbidden: token lacks 'user.write' in this org.")
        r.raise_for_status()
        data = r.json()
        secret = data.get("clientSecret") or data.get("secret") or data.get("value")
        if not secret:
            raise RuntimeError(f"No secret in response: {json.dumps(data)}")
        return secret

    # Fallback: mgmt v1 (often enabled)
    r = requests.put(f"{DOMAIN}/management/v1/users/{user_id}/secret",
                     headers=_h(owner), json={}, timeout=TIMEOUT)
    if r.status_code == 404:
        raise RuntimeError("Not found via v1 either: org mismatch or deleted user.")
    if r.status_code == 403:
        raise RuntimeError("Forbidden via v1: need 'user.write' on this org.")
    r.raise_for_status()
    data = r.json()
    secret = data.get("clientSecret") or data.get("secret") or data.get("value")
    if not secret:
        raise RuntimeError(f"No secret in mgmt v1 response: {json.dumps(data)}")
    return secret

# -------------------- Main --------------------
def main():
    rows = []
    rotated_any = False
    rotated_targets = []

    # 1) Projects + Apps
    try:
        projects = list_projects()
    except Exception as e:
        print(f"ERROR listing projects: {e}", file=sys.stderr)
        projects = []

    for p in projects:
        pid = p.get("id") or p.get("projectId") or ""
        pname = p.get("name") or ""
        try:
            apps = list_apps(pid)
        except Exception as e:
            print(f"# error listing apps for project {pid}: {e}", file=sys.stderr)
            apps = []

        for app in apps:
            app_id = app.get("id") or ""
            atype  = app_type_label(app)
            client_id = str(pick_client_id_from_app(app) or "")
            rotated = ""
            if TARGET_CLIENT_ID and client_id == str(TARGET_CLIENT_ID):
                try:
                    rotated = rotate_app_secret(pid, app) or ""
                    rotated_any = rotated_any or bool(rotated)
                    rotated_targets.append(("APP", app_id))
                except Exception as e:
                    rotated = f"ERROR: {e}"
            rows.append({
                "scope": "APP",
                "project_id": pid,
                "project_name": pname,
                "resource_id": app_id,
                "name": app.get("name") or "",
                "type": atype,
                "client_id": client_id,
                "new_secret_if_target": rotated,
            })

    # # 2) Service Users (list & maybe rotate)
    # try:
    #     svc_users = list_service_users()
    #     print("svc_users:", svc_users)
    # except Exception as e:
    #     print(f"WARNING: Failed to list service users: {e}", file=sys.stderr)
    #     svc_users = []
    #
    # # track if we saw the explicit target ID
    # saw_explicit_su = False

    # for u in svc_users:
    #     user_id, username, display, client_id = service_user_fields(u)
    #     rotated = ""
    #     should_rotate = False
    #
    #     if TARGET_CLIENT_ID:
    #         if str(client_id) == str(TARGET_CLIENT_ID) or str(user_id) == str(TARGET_CLIENT_ID):
    #             should_rotate = True
    #
    #     if TARGET_SERVICE_USER_ID:
    #         if str(user_id) == str(TARGET_SERVICE_USER_ID):
    #             should_rotate = True
    #             saw_explicit_su = True
    #
    #     if should_rotate:
    #         try:
    #             rotated = rotate_service_user_secret(user_id) or ""
    #             rotated_any = rotated_any or bool(rotated)
    #             rotated_targets.append(("SERVICE_USER", user_id))
    #         except Exception as e:
    #             rotated = f"ERROR: {e}"
    #
    #     rows.append({
    #         "scope": "SERVICE_USER",
    #         "project_id": "",
    #         "project_name": "",
    #         "resource_id": user_id,
    #         "name": display,
    #         "type": "SERVICE_USER",
    #         "client_id": str(client_id),
    #         "new_secret_if_target": rotated,
    #     })

    # 2b) If explicit target ID wasn't in the list (e.g., pagination/filter), still try rotation directly
    # Fetch user details
    user_payload = _get_user(TARGET_SERVICE_USER_ID)
    user_obj = _extract_user(user_payload)
    display_name = (
            extract(user_obj, "displayName") or
            extract(user_obj, ["profile", "displayName"]) or
            extract(user_obj, "username", "userName") or
            extract(user_obj, "userId", "id") or
            ""
    )

    # rows.append({
    #     "scope": "SERVICE_USER",
    #     "project_id": "",
    #     "project_name": "",
    #     "resource_id": TARGET_SERVICE_USER_ID,
    #     "name": display_name,
    #     "type": "SERVICE_USER",
    #     "client_id": "",
    #     "new_secret_if_target": rotated,
    # })
    if TARGET_SERVICE_USER_ID :
        try:
            rotated = rotate_service_user_secret(TARGET_SERVICE_USER_ID) or ""
            rotated_any = rotated_any or bool(rotated)
            rotated_targets.append(("SERVICE_USER", TARGET_SERVICE_USER_ID))
            rows.append({
                "scope": "SERVICE_USER",
                "project_id": "",
                "project_name": "",
                "resource_id": TARGET_SERVICE_USER_ID,
                "name": display_name,
                "type": "SERVICE_USER",
                "client_id": "",
                "new_secret_if_target": rotated,
            })
        except Exception as e:
            rows.append({
                "scope": "SERVICE_USER",
                "project_id": "",
                "project_name": "",
                "resource_id": TARGET_SERVICE_USER_ID,
                "name": "",
                "type": "SERVICE_USER",
                "client_id": "",
                "new_secret_if_target": f"ERROR: {e}",
            })

    # 3) Output CSV + screen
    fieldnames = ["scope", "project_id", "project_name", "resource_id", "name", "type", "client_id",
                  "new_secret_if_target"]

    # Write CSV (kept as-is)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Print ONLY name and secret for items that actually got a new secret
    # (skip errors/empty secrets)
    for r in rows:
        secret = (r.get("new_secret_if_target") or "").strip()
        if secret and not secret.startswith("ERROR"):
            # prefer a readable name; fall back to client_id or resource_id
            name = (r.get("name") or r.get("client_id") or r.get("resource_id") or "").strip()
            # print exactly: name,secret
            print(f"{name},{secret}")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print("HTTP error:", getattr(e.response, "text", str(e)), file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(3)
