"""Hand-off from ADempiere: what the service accepts from the launcher process and what it refuses.

These call the service the way the Java launcher does. The Java side itself is exercised by
scripts\\test_launcher.ps1, which needs a JDK and the ADempiere installation.
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from insightai import db, launch
from insightai.config import get_settings
from insightai.main import app


def _ids(user: str, role: str) -> tuple[int, int]:
    row = db.query_one("SELECT u.ad_user_id::int AS uid, r.ad_role_id::int AS rid FROM "
                       "(SELECT DISTINCT ad_user_id FROM v_user_role WHERE user_name = %(u)s) u, "
                       "(SELECT DISTINCT ad_role_id FROM v_user_role WHERE role_name = %(r)s) r", {"u": user, "r": role})
    if not row:
        pytest.skip(f"{user} or {role} not present")
    return row["uid"], row["rid"]


@pytest.fixture(scope="module")
def key() -> str:
    key = get_settings().launch_key
    if not key:
        pytest.skip("no INSIGHTAI_LAUNCH_KEY; run scripts\\adempiere_install.ps1")
    if not db.query_one("SELECT 1 AS ok FROM v_role_process WHERE process_value = %(p)s", {"p": launch.PROCESS_VALUE}):
        pytest.skip("InsightAI dictionary records are not installed")
    return key


def _request(key: str, user_id: int, role_id: int, *, timestamp: int | None = None, nonce: str | None = None,
             signing_key: str | None = None) -> dict:
    timestamp = int(time.time()) if timestamp is None else timestamp
    nonce = nonce or uuid.uuid4().hex
    return {"user_id": user_id, "role_id": role_id, "timestamp": timestamp, "nonce": nonce,
            "signature": launch.sign(signing_key or key, user_id, role_id, timestamp, nonce)}


def test_granted_role_gets_a_one_time_link_that_opens_a_session(key):
    user_id, role_id = _ids("GardenAdmin", "GardenWorld Admin")
    client = TestClient(app, follow_redirects=False)
    response = client.post("/auth/launch-token", json=_request(key, user_id, role_id))
    assert response.status_code == 200
    url = response.json()["url"]
    assert url.startswith(get_settings().public_url + "/launch?code=")

    path = url[len(get_settings().public_url):]
    assert client.get(path).status_code == 303                 # sets the cookie and redirects to the dashboard
    me = client.get("/api/me").json()
    assert (me["user"], me["role"]) == ("GardenAdmin", "GardenWorld Admin")
    assert TestClient(app, follow_redirects=False).get(path).status_code == 401      # the code works once


def test_restricted_role_session_is_limited_to_its_organisations(key):
    user_id, role_id = _ids("test_salerep", "SalesRep(Restricted)")
    client = TestClient(app, follow_redirects=False)
    url = client.post("/auth/launch-token", json=_request(key, user_id, role_id)).json()["url"]
    client.get(url[len(get_settings().public_url):])
    orgs = client.get("/api/me").json()["filters"]["orgs"]
    allowed = {r["ad_org_id"] for r in db.query("SELECT ad_org_id::int AS ad_org_id FROM v_user_role_org "
                                                "WHERE ad_user_id = %(u)s AND ad_role_id = %(r)s", {"u": user_id, "r": role_id})}
    assert {o["id"] for o in orgs} == allowed and len(allowed) == 1


def test_role_without_the_menu_entry_is_refused(key):
    user_id, role_id = _ids("GardenUser", "GardenWorld User")
    if db.query_one("SELECT 1 AS ok FROM v_role_process WHERE ad_role_id = %(r)s AND process_value = %(p)s",
                    {"r": role_id, "p": launch.PROCESS_VALUE}):
        pytest.skip("GardenWorld User has been granted InsightAI in this database")
    response = TestClient(app).post("/auth/launch-token", json=_request(key, user_id, role_id))
    assert response.status_code == 403 and "not been granted access" in response.json()["detail"]


def test_user_cannot_claim_a_role_they_do_not_hold(key):
    user_id, _ = _ids("test_salerep", "SalesRep(Restricted)")
    _, admin_role = _ids("GardenAdmin", "GardenWorld Admin")
    response = TestClient(app).post("/auth/launch-token", json=_request(key, user_id, admin_role))
    assert response.status_code == 403 and "does not hold that role" in response.json()["detail"]


def test_wrong_key_stale_and_replayed_requests_are_refused(key):
    user_id, role_id = _ids("GardenAdmin", "GardenWorld Admin")
    client = TestClient(app)
    assert client.post("/auth/launch-token", json=_request(key, user_id, role_id, signing_key="not-the-key")).status_code == 401
    assert client.post("/auth/launch-token", json=_request(key, user_id, role_id, timestamp=int(time.time()) - 600)).status_code == 401

    tampered = _request(key, user_id, role_id)
    tampered["role_id"] = role_id + 1                           # signature no longer matches the body
    assert client.post("/auth/launch-token", json=tampered).status_code == 401

    once = _request(key, user_id, role_id)
    assert client.post("/auth/launch-token", json=once).status_code == 200
    assert client.post("/auth/launch-token", json=once).status_code == 401       # same nonce again


def test_unknown_or_missing_code_does_not_open_a_session():
    client = TestClient(app, follow_redirects=False)
    assert client.get("/launch", params={"code": "made-up"}).status_code == 401
    assert client.get("/launch").status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.post("/auth/launch-token", json={"user_id": 1}).status_code == 422
