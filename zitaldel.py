#!/usr/bin/env python3
import csv
import os
import sys
import time
import requests
from typing import Dict, List, Optional

DOMAIN = os.getenv("ZITADEL_DOMAIN", "https://app241dev-zitadel.int.capoptix.com")
ACCESS_TOKEN = os.getenv("ZITADEL_ACCESS_TOKEN", "7wl7afoRxv7ltT1tADlCU_WYAp9S-1gzYBfSU9PzyGiylEazX0rGZa8HxSQRdOt8hCqTdZI")
ORG_ID = os.getenv("ZITADEL_ORG_ID", "301926074198032394")
PAGE_SIZE = 100
OUT = "zitadel_new_secrets.csv"

if ACCESS_TOKEN == "REPLACE_ME" or not ACCESS_TOKEN.strip():
    sys.exit("ERROR: Provide a valid ZITADEL_ACCESS_TOKEN.")

def session_with_headers() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-zitadel-orgid": ORG_ID,
    })
    return session

def safe_get(data: Dict, path: str, default=None):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data

def fetch_paginated_data(session: requests.Session, url: str) -> List[Dict]:
    results = []
    next_token = ""
    while True:
        full_url = f"{url}&pageToken={next_token}" if next_token else url
        response = session.post(full_url, json={"queries": []})
        response.raise_for_status()
        data = response.json()
        results.extend(data.get("result", []))
        next_token = safe_get(data, "details.nextPageToken", "")
        if not next_token:
            break
    return results

def regenerate_secret(session: requests.Session, project_id: str, app_id: str, app_type: str) -> Optional[str]:
    v2_url = f"{DOMAIN}/zitadel.app.v2beta.AppService/RegenerateClientSecret"
    v1_url = f"{DOMAIN}/management/v1/projects/{project_id}/apps/{app_id}/" + \
             ("oidc_config/_generate_client_secret" if app_type == "OIDC" else "api_config/_generate_client_secret")
    headers = {"Connect-Protocol-Version": "1"}
    for url, extra_headers in [(v2_url, headers), (v1_url, None)]:
        try:
            response = session.post(url, json={"projectId": project_id, "appId": app_id}, headers=extra_headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("clientSecret") or data.get("secret") or safe_get(data, "value", "-")
        except requests.RequestException:
            continue
    return None

def main():
    session = session_with_headers()
    projects_url = f"{DOMAIN}/management/v1/projects/_search?pageSize={PAGE_SIZE}"
    apps_url_template = f"{DOMAIN}/management/v1/projects/{{}}/apps/_search?pageSize={PAGE_SIZE}"

    with open(OUT, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["org_id", "project_id", "project_name", "app_id", "app_name", "app_type", "client_id", "new_secret"])

        for project in fetch_paginated_data(session, projects_url):
            project_id = project.get("id", "-")
            project_name = project.get("name", "-")
            print(f"\nProject: {project_id} | {project_name}")

            for app in fetch_paginated_data(session, apps_url_template.format(project_id)):
                app_id = app.get("id", "-")
                app_name = app.get("name", "-")
                app_type = app.get("appType") or app.get("type", "-")
                client_id = safe_get(app, "oidcConfig.clientId") or safe_get(app, "apiConfig.clientId") or app.get("clientId", "-")

                if app_type not in ("OIDC", "API"):
                    print(f"  Skip (no secret): {app_id} | {app_name} | {app_type}")
                    writer.writerow([ORG_ID, project_id, project_name, app_id, app_name, app_type, client_id, "-"])
                    continue

                new_secret = regenerate_secret(session, project_id, app_id, app_type) or "-"
                writer.writerow([ORG_ID, project_id, project_name, app_id, app_name, app_type, client_id, new_secret])
                if new_secret != "-":
                    print(f"  Rotated: {app_id} | {app_name} | New secret captured")
                time.sleep(0.05)

    print(f"\nSaved new secrets to: {OUT}")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        sys.exit(f"HTTP error: {e} | Response: {getattr(e.response, 'text', '')}")
    except Exception as e:
        sys.exit(f"Unexpected error: {e}")