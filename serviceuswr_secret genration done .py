import requests, json

DOMAIN = "https://app241dev-zitadel.int.capoptix.com"
ACCESS_TOKEN = "7wl7afoRxv7ltT1tADlCU_WYAp9S-1gzYBfSU9PzyGiylEazX0rGZa8HxSQRdOt8hCqTdZI"            # must have user.write on the user's org
ORG_ID_HINT = "301926074198032394"  # what you're currently using; we’ll override with resourceOwner
USER_ID = "304678892734545930"
TIMEOUT = 30

BASE_HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def _h(org_id=None):
    h = dict(BASE_HEADERS)
    if org_id:
        h["x-zitadel-orgid"] = org_id
    return h

def _extract_user(payload):
    # responses can be flat or nested under "user"
    return payload.get("user", payload)

def _is_machine(u):
    t = (u.get("type") or u.get("userType") or "").upper()
    return ("MACHINE" in t) or ("machine" in u)

def _resource_owner(payload):
    # prefer details.resourceOwner; try both flat and nested shapes
    details = payload.get("details") or payload.get("user", {}).get("details") or {}
    return details.get("resourceOwner") or payload.get("resourceOwner")

def rotate_service_user_secret():
    # 1) Read user (first with hint, then without)
    for org in (ORG_ID_HINT, None):
        r = requests.get(f"{DOMAIN}/v2/users/{USER_ID}", headers=_h(org), timeout=TIMEOUT)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        payload = r.json()
        user = _extract_user(payload)
        owner = _resource_owner(payload) or org
        if not _is_machine(user):
            raise RuntimeError("User is not a MACHINE (service) user; only machine users can have secrets.")
        username = user.get("username") or user.get("userName") or ""
        print(f"Resolved org={owner}  username={username}")

        # 2) Rotate on v2 using the owning org, then fallback without org header
        for try_org in (owner, None):
            rr = requests.post(f"{DOMAIN}/v2/users/{USER_ID}/secret", headers=_h(try_org), json={}, timeout=TIMEOUT)
            if rr.status_code == 404:
                continue
            if rr.status_code == 403:
                raise RuntimeError("403 Forbidden: the token lacks user.write for this org.")
            rr.raise_for_status()
            data = rr.json()
            secret = data.get("clientSecret") or data.get("secret") or data.get("value")
            if not secret:
                raise RuntimeError(f"No secret in response: {json.dumps(data)}")
            return secret

        # 3) Last resort: mgmt v1 (deprecated but often enabled)
        rr = requests.put(f"{DOMAIN}/management/v1/users/{USER_ID}/secret",
                          headers=_h(owner), json={}, timeout=TIMEOUT)
        if rr.status_code == 404:
            raise RuntimeError("Not found via v1 either: org mismatch or deleted user.")
        if rr.status_code == 403:
            raise RuntimeError("Forbidden via v1: need user.write on this org.")
        rr.raise_for_status()
        data = rr.json()
        secret = data.get("clientSecret") or data.get("secret") or data.get("value")
        if not secret:
            raise RuntimeError(f"No secret in mgmt v1 response: {json.dumps(data)}")
        return secret

    raise RuntimeError(f"user_id '{USER_ID}' not found in any visible org (check ID or token scope).")

if __name__ == "__main__":
    print("NEW SERVICE USER SECRET:", rotate_service_user_secret())
