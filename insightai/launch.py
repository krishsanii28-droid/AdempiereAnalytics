"""Hand-off from the ADempiere menu to a browser session.

The launcher process inside ADempiere knows who is logged in and with which role. It signs that
with a key shared between this service and the ADempiere installation and asks for a launch URL.
The URL carries a random code that works once, for one minute; opening it sets the session cookie.
The browser never sees the shared key and cannot choose its own user, role, client or organisation.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from . import auth, db
from .config import get_settings

PROCESS_VALUE = "InsightAI_Launch"     # AD_Process.Value of the menu entry's process
MAX_SKEW_SECONDS = 60
CODE_TTL_SECONDS = 60

_lock = threading.Lock()
_seen_nonces: dict[str, float] = {}                 # nonce -> expiry, to refuse a replayed request
_codes: dict[str, tuple[int, int, float]] = {}      # code -> (user_id, role_id, expiry)


class LaunchRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def sign(key: str, user_id: int, role_id: int, timestamp: int, nonce: str) -> str:
    message = f"{user_id}:{role_id}:{timestamp}:{nonce}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def _purge(now: float) -> None:
    for store in (_seen_nonces, _codes):
        for key in [k for k, v in store.items() if (v if isinstance(v, float) else v[2]) < now]:
            del store[key]


def issue_code(user_id: int, role_id: int, timestamp: int, nonce: str, signature: str) -> str:
    """Check a launcher request and return a one-time code for /launch."""
    key = get_settings().launch_key
    if not key:
        raise LaunchRefused(503, "InsightAI has no launch key configured. Run scripts\\adempiere_install.ps1.")
    if not (8 <= len(nonce) <= 64) or not hmac.compare_digest(signature, sign(key, user_id, role_id, timestamp, nonce)):
        raise LaunchRefused(401, "The launch request was not signed with this installation's key.")
    now = time.time()
    if abs(now - timestamp) > MAX_SKEW_SECONDS:
        raise LaunchRefused(401, "The launch request has expired. Check the clocks and try again.")
    with _lock:
        _purge(now)
        if nonce in _seen_nonces:
            raise LaunchRefused(401, "This launch request was already used.")
        _seen_nonces[nonce] = now + 2 * MAX_SKEW_SECONDS

    if auth.load_session(user_id, role_id) is None:
        raise LaunchRefused(403, "That user does not hold that role in ADempiere.")
    allowed = db.query_one("SELECT 1 AS ok FROM v_role_process WHERE ad_role_id = %(r)s AND process_value = %(p)s",
                           {"r": role_id, "p": PROCESS_VALUE})
    if not allowed:
        raise LaunchRefused(403, "This role has not been granted access to InsightAI in ADempiere.")

    code = secrets.token_urlsafe(32)
    with _lock:
        _codes[code] = (user_id, role_id, now + CODE_TTL_SECONDS)
    return code


def redeem_code(code: str) -> tuple[int, int] | None:
    """Exchange a code for (user_id, role_id). Works once."""
    with _lock:
        _purge(time.time())
        entry = _codes.pop(code, None)
    return (entry[0], entry[1]) if entry else None
