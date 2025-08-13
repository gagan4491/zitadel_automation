import requests, json, configparser

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

# 1) Project details (v1)
proj_url = f"{DOMAIN}/management/v1/projects/{PROJECT_ID}"
proj_res = requests.get(proj_url, headers=HEADERS, timeout=30)
proj_res.raise_for_status()
proj_json = proj_res.json()
project = proj_json.get("project", proj_json)  # be tolerant of shapes

# 2) Apps under the project (v1)
apps_url = f"{DOMAIN}/management/v1/projects/{PROJECT_ID}/apps/_search"
apps = []
offset = 0
limit = 200
while True:
    payload = {"limit": limit, "offset": offset, "asc": True, "queries": []}
    r = requests.post(apps_url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    page = r.json()
    chunk = page.get("result") or page.get("apps") or []
    apps.extend(chunk)
    if len(chunk) < limit:
        break
    offset += len(chunk)

# Optional: enrich each app with a convenient clientId + type
def pick_client_id(a):
    return (
        a.get("clientId")
        or (a.get("oidcConfig") or {}).get("clientId")
        or (a.get("apiConfig") or {}).get("clientId")
        or "-"
    )

for a in apps:
    a["resolvedType"] = a.get("appType") or a.get("type")
    a["resolvedClientId"] = pick_client_id(a)

# 3) Print combined
out = {
    "project": project,
    "apps": apps,
}
print(json.dumps(out, indent=2))
