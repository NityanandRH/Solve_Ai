"""
User.py — Identity layer for Azure App Service SSO.

In production (Azure): App Service Easy Auth validates the AAD token and injects
identity headers before the request reaches FastAPI. We just read those headers.

In local dev: Set LOCAL_DEV=true in .env and the app uses a mock user so you
can run without Easy Auth.

Headers injected by App Service Easy Auth on every authenticated request:
  X-MS-CLIENT-PRINCIPAL-ID    → AAD Object ID (stable unique user ID)
  X-MS-CLIENT-PRINCIPAL-NAME  → UPN / email (e.g. alice@yourorg.com)
  X-MS-CLIENT-PRINCIPAL       → base64-encoded JSON of all AAD claims
"""

import os
import json
import base64
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Comma-separated list of UPNs/emails that should get admin role.
# Set in Azure App Service → Configuration → Application Settings.
# Example: ADMIN_USERS=alice@yourorg.com,bob@yourorg.com
ADMIN_USERS_RAW = os.getenv("ADMIN_USERS", "")
ADMIN_UPNS: set = {u.strip().lower() for u in ADMIN_USERS_RAW.split(",") if u.strip()}

# Local dev fallback — set LOCAL_DEV=true in .env for development without Easy Auth
LOCAL_DEV = os.getenv("LOCAL_DEV", "false").lower() == "true"
LOCAL_DEV_EMAIL = os.getenv("LOCAL_DEV_EMAIL", "dev@localhost")
LOCAL_DEV_NAME = os.getenv("LOCAL_DEV_NAME", "Dev User")
LOCAL_DEV_OID = os.getenv("LOCAL_DEV_OID", "00000000-0000-0000-0000-000000000001")


# ── Pydantic models (kept compatible with all existing endpoint signatures) ───

class UserOut(BaseModel):
    id: str           # internal DB UUID
    username: str     # UPN / email (used as display key)
    email: str        # UPN / email from AAD
    role: str         # 'admin' | 'user'
    display_name: str # friendly name from AAD claims


class TokenData(BaseModel):
    """
    Used as the 'current_user' dependency throughout app.py.
    Replaces the old JWT-based TokenData — same fields, populated from SSO headers.
    """
    username: Optional[str] = None    # UPN / email
    user_id: Optional[str] = None     # internal DB UUID
    role: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    aad_oid: Optional[str] = None     # AAD Object ID


# ── SSO header parsing ────────────────────────────────────────────────────────

def _decode_principal_header(header_value: str) -> dict:
    """Decode the X-MS-CLIENT-PRINCIPAL base64 header into a claims dict."""
    try:
        padded = header_value + "=" * (4 - len(header_value) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
        data = json.loads(decoded)
        claims = {c["typ"]: c["val"] for c in data.get("claims", [])}
        return claims
    except Exception:
        return {}


def extract_sso_identity(headers: dict) -> Optional[dict]:
    """
    Extract user identity from App Service Easy Auth headers.
    Returns dict with: oid, upn, display_name, role
    Returns None if not authenticated.
    """
    # ── Local dev mode ────────────────────────────────────────────────────────
    if LOCAL_DEV:
        role = "admin" if LOCAL_DEV_EMAIL.lower() in ADMIN_UPNS else "user"
        if not ADMIN_UPNS:
            role = "admin"   # no admins configured → dev user gets admin
        return {
            "oid": LOCAL_DEV_OID,
            "upn": LOCAL_DEV_EMAIL,
            "display_name": LOCAL_DEV_NAME,
            "role": role,
        }

    # ── Production: read App Service injected headers ─────────────────────────
    oid = headers.get("x-ms-client-principal-id", "").strip()
    upn = headers.get("x-ms-client-principal-name", "").strip()

    if not oid or not upn:
        return None

    # Get display name from the full claims blob
    display_name = upn
    principal_header = headers.get("x-ms-client-principal", "")
    if principal_header:
        claims = _decode_principal_header(principal_header)
        display_name = (
            claims.get("name")
            or claims.get("preferred_username")
            or upn
        )

    role = "admin" if upn.lower() in ADMIN_UPNS else "user"

    return {
        "oid": oid,
        "upn": upn,
        "display_name": display_name,
        "role": role,
    }


def is_admin_upn(upn: str) -> bool:
    return upn.lower() in ADMIN_UPNS
