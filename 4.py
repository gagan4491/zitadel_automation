#!/usr/bin/env python3
import requests, json, configparser, sys, csv

# ====== USER INPUT ======
TARGET_CLIENT_ID = "301926079046713354"   # the clientId whose secret you want to regenerate
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "zitadel_apps.csv"
# ========================

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

def _page(endpoint, payload_key_result_candidates=("result",), limit=200):
    """Generic pager for Zitadel management search endpoints."""
    offset = 0
    while True:
        payload = {"limit": limit, "offset": offset, "asc": True, "queries": []}
        r = requests.post(endpoint, headers=HEADERS, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        # Try common keys ("result", or a plural like "projects"/"apps")
        chunk = None
        for k in payload_key_result_candidates:
            if k in data:
                chunk = data[k]
                break
        if chunk is None:
            # try plural fallbacks by endpoint guess
            if "projects" in data:
                chunk = data["projects"]
            elif "apps" in data:
                chunk = data["apps"]
            else:
                chunk = []
        if not chunk:
            return
        for item in chunk:
            yield item
        if len(chunk) < limit:
            return
        offset += len(chunk)

def list_projects():
    url = f"{DOMAIN}/management/v1/projects/_search"
    return list(_page(url, payload_key_result_candidates=("result","projects")))

def list_apps(project_id):
    url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/_search"
    return list(_page(url, payload_key_result_candidates=("result","apps")))

def pick_client_id(app):
    return (
        (app.get("oidcConfig") or {}).get("clientId")
        or (app.get("apiConfig") or {}).get("clientId")
        or app.get("clientId")
        or ""
    )

def pick_app_name(app):
    # Common fields that might carry a display name
    return (
        app.get("name")
        or app.get("appName")
        or (app.get("oidcConfig") or {}).get("appName")
        or (app.get("apiConfig") or {}).get("appName")
        or ""
    )

def pick_app_type(app):
    return (app.get("appType") or app.get("type") or "").upper()

def is_oidc_app(app):
    t = pick_app_type(app)
    return "oidcConfig" in app or t == "OIDC"

def generate_secret(project_id, app_id, oidc=True):
    if oidc:
        regen_url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/oidc_config/_generate_client_secret"
    else:
        regen_url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/api_config/_generate_client_secret"
    r = requests.post(regen_url, headers=HEADERS, json={}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("clientSecret") or data.get("secret") or data.get("value")

def main():
    projects = list_projects()
    if not projects:
        print("No projects found in organization.", file=sys.stderr)
        sys.exit(1)

    rows = []
    header = ["org_id","project_id","project_name","app_id","app_name","app_type","client_id","new_secret"]

    print(",".join(header))
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for p in projects:
            project_id = p.get("id") or ""
            project_name = p.get("name") or ""
            try:
                apps = list_apps(project_id)
            except requests.HTTPError as e:
                print(f"# error listing apps for project {project_id}: {e}", file=sys.stderr)
                continue

            for app in apps:
                app_id = app.get("id") or ""
                app_name = pick_app_name(app)
                app_type = pick_app_type(app)
                client_id = str(pick_client_id(app))
                new_secret = ""

                if client_id and client_id == str(TARGET_CLIENT_ID):
                    try:
                        new_secret = generate_secret(project_id, app_id, oidc=is_oidc_app(app))
                    except requests.HTTPError as e:
                        print(f"# error generating secret for app {app_id} ({client_id}): {e}", file=sys.stderr)

                row = [ORG_ID, project_id, project_name, app_id, app_name,client_id, new_secret]
                rows.append(row)
                # print to screen
                print(",".join(item if item is not None else "" for item in row))
                # write to file
                writer.writerow(row)

    print(f"\nWrote {len(rows)} rows to {OUTPUT_FILE}")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        msg = getattr(e.response, "text", str(e))
        print(f"HTTP error: {msg}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(3)
