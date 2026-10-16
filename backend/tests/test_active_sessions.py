import runpy
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api import app
from app.auth import digest
from app.db import engine
from app.domain import now
from app.models import Audit, LoginSession, User
from app.session_details import client_address, client_description, record_session_activity

MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.2 Safari/605.1.15"
PHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 Version/18.2 Mobile Safari/604.1"


def sign_in(client, login="operator", ua=MAC_UA):
    result = client.post(
        "/api/auth/login", json={"login": login, "password": "test-password-123"}, headers={"User-Agent": ua}
    )
    assert result.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["csrf"]
    return result.json()


def test_only_own_unexpired_sessions_are_returned_without_credentials(client, users, db):
    with TestClient(app) as phone, TestClient(app) as foreign:
        sign_in(client)
        sign_in(phone, ua=PHONE_UA)
        sign_in(foreign, login="admin")
        user = db.scalar(select(User).where(User.login == "operator"))
        expired = LoginSession(
            token_hash="e" * 64, csrf_hash="f" * 64, user_id=user.id, expires_at=now() - timedelta(seconds=1)
        )
        db.add(expired)
        db.commit()
        response = client.get("/api/auth/sessions")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["session_hours"] == 12
        assert len(payload["items"]) == 2
        current, other = payload["items"]
        assert current["current"] and current["device"] == "Mac" and current["browser"] == "Safari 18.2"
        assert not other["current"] and other["device"] == "iPhone"
        assert current["created_at"] and current["last_seen_at"]
        assert all(UUID(item["id"]) for item in payload["items"])
        assert set(current) == {
            "id",
            "current",
            "created_at",
            "last_seen_at",
            "expires_at",
            "ip_address",
            "device",
            "device_type",
            "os",
            "browser",
        }
        assert expired.id not in {item["id"] for item in payload["items"]}
        assert foreign.get("/api/auth/sessions").json()["items"][0]["id"] not in {
            item["id"] for item in payload["items"]
        }


def test_individual_revocation_ends_other_login_but_keeps_current(client, users, db):
    with TestClient(app) as other:
        sign_in(client)
        sign_in(other, ua=PHONE_UA)
        target = other.get("/api/auth/sessions").json()["items"][0]["id"]
        assert client.delete(f"/api/auth/sessions/{target}").status_code == 200
        assert other.get("/api/auth/me").status_code == 401
        assert other.get("/api/photos").status_code == 401
        assert client.get("/api/auth/me").status_code == 200
        assert client.delete(f"/api/auth/sessions/{target}").status_code == 404
        log = db.scalar(select(Audit).where(Audit.action == "SESSION_REVOKED"))
        assert log.new_value == {"session_id": target}


def test_bulk_revocation_keeps_current_and_other_users(client, users, db):
    with TestClient(app) as second, TestClient(app) as third, TestClient(app) as foreign:
        sign_in(client)
        sign_in(second)
        sign_in(third)
        sign_in(foreign, login="admin")
        assert client.post("/api/auth/sessions/revoke-others").json() == {"revoked": 2}
        assert client.get("/api/auth/me").status_code == 200
        assert foreign.get("/api/auth/me").status_code == 200
        assert second.get("/api/auth/me").status_code == third.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/sessions/revoke-others").json() == {"revoked": 0}
        assert (
            db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "OTHER_SESSIONS_REVOKED"))
            == 1
        )


def test_cannot_revoke_current_or_foreign_session_even_as_admin(client, users):
    with TestClient(app) as operator:
        sign_in(client, login="admin")
        sign_in(operator)
        current = client.get("/api/auth/sessions").json()["items"][0]["id"]
        foreign = operator.get("/api/auth/sessions").json()["items"][0]["id"]
        assert client.delete(f"/api/auth/sessions/{current}").status_code == 409
        assert client.delete(f"/api/auth/sessions/{foreign}").status_code == 404
        assert client.delete(f"/api/auth/sessions/{uuid4()}").status_code == 404
        assert operator.get("/api/auth/me").status_code == 200


def test_session_management_requires_auth_csrf_and_origin(client, users):
    assert client.get("/api/auth/sessions").status_code == 401
    assert client.post("/api/auth/sessions/revoke-others").status_code == 401
    sign_in(client)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/auth/sessions/revoke-others").status_code == 403
    assert client.delete(f"/api/auth/sessions/{uuid4()}").status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.post(
            "/api/auth/sessions/revoke-others", headers={"Origin": "https://foreign.invalid"}
        ).status_code
        == 403
    )


def test_operator_without_function_permissions_can_manage_own_sessions(client, users, db):
    operator = db.scalar(select(User).where(User.login == "operator"))
    operator.permissions = []
    db.commit()
    sign_in(client)
    assert client.get("/api/auth/sessions").status_code == 200
    assert client.post("/api/auth/sessions/revoke-others").status_code == 200
    assert client.get("/api/photos").status_code == 403


def test_activity_is_persisted_at_most_once_per_minute_and_logout_never_restores_session(client, users, db):
    sign_in(client)
    token_hash = digest(client.cookies["session"])
    session = db.get(LoginSession, token_hash)
    session.last_seen_at = now() - timedelta(minutes=2)
    db.commit()
    previous = session.last_seen_at
    assert client.get("/api/auth/me").status_code == 200
    db.refresh(session)
    observed = session.last_seen_at
    assert observed > previous + timedelta(minutes=1)
    assert client.get("/api/auth/me").status_code == 200
    db.refresh(session)
    assert session.last_seen_at == observed
    session.last_seen_at = now() - timedelta(minutes=2)
    db.commit()
    assert client.post("/api/auth/logout").status_code == 200
    assert db.scalar(select(func.count()).select_from(LoginSession)) == 0


def test_activity_does_not_commit_unfinished_business_work_or_restore_deleted_rows(client, users, db):
    sign_in(client)
    token_hash = digest(client.cookies["session"])
    user = db.scalar(select(User).where(User.login == "operator"))
    original_name = user.name
    user.name = "uncommitted name"
    db.info["session_activity"] = {"token_hash": token_hash, "at": now() + timedelta(minutes=2)}
    record_session_activity(db)
    db.refresh(user)
    assert user.name == original_name
    session = db.get(LoginSession, token_hash)
    db.delete(session)
    db.commit()
    db.info["session_activity"] = {"token_hash": token_hash, "at": now() + timedelta(minutes=3)}
    record_session_activity(db)
    assert db.scalar(select(func.count()).select_from(LoginSession)) == 0


def test_login_records_reported_client_and_ignores_untrusted_forwarded_headers(users):
    with TestClient(app, client=("203.0.113.7", 50000)) as client:
        client.headers["X-Forwarded-For"] = "198.51.100.9"
        sign_in(client, ua=PHONE_UA + "x" * 600)
        session = client.get("/api/auth/sessions").json()["items"][0]
        assert session["ip_address"] == "203.0.113.7" and session["device_type"] == "phone"
        with Session(engine()) as db:
            assert len(db.get(LoginSession, digest(client.cookies["session"])).user_agent) == 512


def test_migration_keeps_existing_login_and_unknown_historical_metadata(client, users, db):
    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0015_login_session_details.py")
    )
    user = db.scalar(select(User).where(User.login == "operator"))
    user_id = user.id
    db.commit()
    with Operations.context(MigrationContext.configure(db.connection())):
        migration["downgrade"]()
        db.execute(
            text(
                "INSERT INTO login_sessions(token_hash,csrf_hash,user_id,expires_at) VALUES (:token,:csrf,:user,now()+interval '1 hour')"
            ),
            {"token": digest("legacy-test-token"), "csrf": digest("legacy-csrf"), "user": user_id},
        )
        migration["upgrade"]()
    db.commit()
    client.cookies.set("session", "legacy-test-token")
    client.cookies.set("csrf", "legacy-csrf")
    payload = client.get("/api/auth/sessions").json()
    assert len(payload["items"]) == 1
    current = payload["items"][0]
    assert current["current"] and UUID(current["id"])
    assert current["created_at"] is None and current["ip_address"] is None
    assert current["last_seen_at"] is not None and current["device"] == "Устройство не определено"
    assert client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize(
    "ua,device,browser",
    [
        (MAC_UA, "Mac", "Safari 18.2"),
        (PHONE_UA, "iPhone", "Safari 18.2"),
        ("Mozilla/5.0 (iPad; CPU OS 18_2 like Mac OS X) CriOS/130.0 Mobile", "iPad", "Chrome 130.0"),
        ("Mozilla/5.0 (Linux; Android 15; Phone) Chrome/130.0 Mobile", "Устройство Android", "Chrome 130.0"),
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Edg/130.1", "Компьютер Windows", "Edge 130.1"),
        (
            "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 YaBrowser/24.10",
            "Компьютер Windows",
            "Яндекс Браузер 24.10",
        ),
        ("Mozilla/5.0 (Linux x86_64) Firefox/132.0", "Компьютер Linux", "Firefox 132.0"),
        (None, "Устройство не определено", "Браузер не определён"),
        ("<script>not a real browser</script>", "Устройство не определено", "Браузер не определён"),
    ],
)
def test_client_metadata_is_display_only_and_unknown_values_stay_unknown(ua, device, browser):
    assert client_description(ua)["device"] == device
    assert client_description(ua)["browser"] == browser


def test_client_address_handles_ipv6_and_missing_address():
    assert client_address(Request({"type": "http", "client": ("2001:db8::1", 1234)})) == "2001:db8::1"
    assert client_address(Request({"type": "http", "client": None})) is None
    assert client_address(Request({"type": "http", "client": ("not-an-ip", 1234)})) is None
