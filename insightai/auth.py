"""Sessions.

A session token says who the user is (AD_User_ID) and which role they chose (AD_Role_ID).
It is signed by this service, so the browser cannot alter it. Client and organisations are
never taken from the browser: they are looked up from ADempiere's access tables on every request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import db
from .config import get_settings

COOKIE = "insightai_session"


@dataclass(frozen=True)
class Session:
    user_id: int
    role_id: int
    client_id: int
    user_name: str
    role_name: str
    client_name: str
    currency: str
    org_ids: tuple[int, ...]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: str) -> str:
    key = get_settings().secret_key.encode()
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


def issue_token(user_id: int, role_id: int, ttl_seconds: int) -> str:
    payload = _b64(json.dumps({"uid": user_id, "rid": role_id, "exp": int(time.time()) + ttl_seconds}).encode())
    return f"{payload}.{_signature(payload)}"


def read_token(token: str) -> tuple[int, int] | None:
    """Return (user_id, role_id) for a valid, unexpired token, otherwise None."""
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _signature(payload)):
            return None
        claims = json.loads(_unb64(payload))
        if int(claims["exp"]) < time.time():
            return None
        return int(claims["uid"]), int(claims["rid"])
    except (ValueError, KeyError, TypeError):
        return None


def load_session(user_id: int, role_id: int) -> Session | None:
    """Build the session from ADempiere's own access tables. None if the user does not hold the role."""
    who = db.query_one(
        "SELECT user_name, role_name, ad_client_id, client_name, base_currency "
        "FROM v_user_role WHERE ad_user_id = %(u)s AND ad_role_id = %(r)s",
        {"u": user_id, "r": role_id},
    )
    if not who:
        return None
    orgs = db.query(
        "SELECT ad_org_id FROM v_user_role_org WHERE ad_user_id = %(u)s AND ad_role_id = %(r)s ORDER BY ad_org_id",
        {"u": user_id, "r": role_id},
    )
    return Session(
        user_id=user_id,
        role_id=role_id,
        client_id=int(who["ad_client_id"]),
        user_name=who["user_name"],
        role_name=who["role_name"],
        client_name=who["client_name"],
        currency=who["base_currency"] or "",
        org_ids=tuple(int(o["ad_org_id"]) for o in orgs),
    )


def require_session(request: Request) -> Session:
    """FastAPI dependency: every /api route goes through this."""
    token = request.cookies.get(COOKIE)
    ids = read_token(token) if token else None
    if ids is None:
        raise HTTPException(status_code=401, detail="Not signed in. Open InsightAI from the ADempiere menu.")
    session = load_session(*ids)
    if session is None:
        raise HTTPException(status_code=403, detail="This user no longer holds this role in ADempiere.")
    if not session.org_ids:
        raise HTTPException(status_code=403, detail="This role has no organisation access in ADempiere.")
    return session
