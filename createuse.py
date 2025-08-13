#!/usr/bin/env python3
import sys, json, requests, configparser

cfg = configparser.ConfigParser()
cfg.read("zitadel.conf")

DOMAIN       = cfg.get("zitadel", "domain").rstrip("/")
ACCESS_TOKEN = cfg.get("zitadel", "access_token")
ORG_ID       = cfg.get("zitadel", "org_id")
#
# USERNAME    = cfg.get("new_user", "username",    fallback="newadmin123")
# GIVEN_NAME  = cfg.get("new_user", "given_name",  fallback="Admin12334")
# FAMILY_NAME = cfg.get("new_user", "family_name", fallback="User")
# EMAIL       = cfg.get("new_user", "email",       fallback="admin12366@example.com")
# PASSWORD    = cfg.get("new_user", "password",    fallback="SecretPass123!")
# ORG_ROLES   = json.loads(cfg.get("new_user", "org_roles", fallback='["ORG_OWNER"]'))

USERNAME    = "newadmin123dd"
GIVEN_NAME  = "Admin12334d"
FAMILY_NAME = "User"
EMAIL       = "admin12366fdf@example.com"
PASSWORD    = "SecretPass123!"
ORG_ROLES   = ["ORG_OWNER"]
H = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "x-zitadel-orgid": ORG_ID,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def create_user_v2_human():
    """Create a human user via v2 /users/human (works on your setup)."""
    url = f"{DOMAIN}/v2/users/human"
    payload = {
        "userName": USERNAME,
        "profile": {"givenName": GIVEN_NAME, "familyName": FAMILY_NAME},
        "email":   {"email": EMAIL, "isVerified": True},
        "password": {"password": PASSWORD, "changeRequired": False},
    }
    r = requests.post(url, headers=H, json=payload, timeout=30)
    r.raise_for_status()
    j = r.json()
    user_id = j.get("userId") or j.get("id") or j.get("user", {}).get("id")
    if not user_id:
        raise RuntimeError(f"Could not parse userId from response: {j}")
    return user_id

def add_org_member(user_id: str):
    """Grant roles to the user on the org (v1 members)."""
    url = f"{DOMAIN}/management/v1/orgs/me/members"
    r = requests.post(url, headers=H, json={"userId": user_id, "roles": ORG_ROLES}, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    if not all([DOMAIN, ACCESS_TOKEN, ORG_ID]):
        sys.exit("Set domain, access_token, org_id in zitadel.conf")
    uid = create_user_v2_human()
    add_org_member(uid)
    print(json.dumps({
        "userId": uid,
        "username": USERNAME,
        "email": EMAIL,
        "rolesGranted": ORG_ROLES,
        "orgId": ORG_ID
    }, indent=2))

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        body = e.response.text if getattr(e, "response", None) else ""
        print(f"HTTP error: {e}\n{body}", file=sys.stderr); sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(3)
