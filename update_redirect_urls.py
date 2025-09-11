#!/usr/bin/env python3
import requests, json, configparser, sys, os, socket

def get_primary_ipv4() -> str:
    for target in ("8.8.8.8", "1.1.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        for fam, stype, proto, canon, sockaddr in infos:
            ip = sockaddr[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"

last_octet = os.environ.get("ZITADEL_APP_LAST_OCTET")
if not last_octet:
    ip = get_primary_ipv4()
    last_octet = ip.split(".")[-1] if "." in ip else "1"

# ================== Config / Targets ==================
APP_ID = "301926077821911050"   # your OIDC app id
REDIRECT_URIS = [f"https://app{last_octet}dev.int.capoptix.com/auth/callback"]

POST_LOGOUT_URIS = [f"https://app{last_octet}dev.int.capoptix.com/app-web/"]
TIMEOUT = 30

cfg = configparser.ConfigParser()
cfg.read("zitadel.conf")

try:
    DOMAIN       = cfg.get("zitadel", "domain").rstrip("/")
    ACCESS_TOKEN = cfg.get("zitadel", "access_token")
    ORG_ID       = cfg.get("zitadel", "org_id")
except Exception as e:
    print(f"Missing zitadel.conf keys: {e}", file=sys.stderr)
    sys.exit(2)

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "x-zitadel-orgid": ORG_ID,
}

def http_post(url, payload):
    r = requests.post(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def http_put(url, payload):
    r = requests.put(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def list_projects(limit=200):
    url = f"{DOMAIN}/management/v1/projects/_search"
    projects, offset = [], 0
    while True:
        page = http_post(url, {"limit": limit, "offset": offset, "asc": True, "queries": []})
        chunk = page.get("result") or page.get("projects") or []
        projects.extend(chunk)
        if len(chunk) < limit:
            return projects
        offset += len(chunk)

def list_apps(project_id, limit=200):
    url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/_search"
    apps, offset = [], 0
    while True:
        page = http_post(url, {"limit": limit, "offset": offset, "asc": True, "queries": []})
        chunk = page.get("result") or page.get("apps") or []
        apps.extend(chunk)
        if len(chunk) < limit:
            return apps
        offset += len(chunk)

def find_project_for_app(app_id):
    for p in list_projects():
        pid = p.get("id") or p.get("projectId")
        if not pid:
            continue
        try:
            for app in list_apps(pid):
                if (app.get("id") or "") == app_id:
                    return pid
        except Exception as e:
            print(f"# warn: listing apps failed for project {pid}: {e}", file=sys.stderr)
    return None

# ---- Update ----
def update_redirects(project_id, app_id, redirects, post_logout):
    url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/oidc_config"
    payload = {
        "redirectUris": redirects,
        "postLogoutRedirectUris": post_logout,
    }
    resp = http_put(url, payload)
    return resp

# ---- Main ----
def main():
    print(f"# Looking up project for app_id={APP_ID} ...")
    project_id = find_project_for_app(APP_ID)
    if not project_id:
        print("ERROR: App not found in any project.", file=sys.stderr)
        sys.exit(4)

    print(f"# Found project_id={project_id}")
    print("# Updating redirect URIs...")

    try:
        resp = update_redirects(project_id, APP_ID, REDIRECT_URIS, POST_LOGOUT_URIS)
    except requests.HTTPError as e:
        print("HTTP error:", getattr(e.response, "text", str(e)), file=sys.stderr)
        sys.exit(3)

    print("Redirect URIs updated successfully.")
    print(json.dumps({
        "project_id": project_id,
        "app_id": APP_ID,
        "redirectUris": REDIRECT_URIS,
        "postLogoutRedirectUris": POST_LOGOUT_URIS
    }, indent=2))

if __name__ == "__main__":
    main()
