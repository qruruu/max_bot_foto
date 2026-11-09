from fastapi.testclient import TestClient

from app.api import app


def test_staff_presence_is_authorized_and_survives_logout(admin):
    with TestClient(app) as operator:
        assert operator.post("/api/auth/presence").status_code == 401
        assert operator.post("/api/auth/login", json={
            "login": "operator", "password": "test-password-123",
        }).status_code == 200
        assert operator.post("/api/auth/presence").status_code == 403
        operator.headers["X-CSRF-Token"] = operator.cookies["csrf"]
        assert operator.post("/api/auth/presence").status_code == 200
        initial = operator.get("/api/auth/me").json()["last_seen_at"]
        assert initial
        assert operator.post("/api/auth/presence").status_code == 200
        assert operator.get("/api/auth/me").json()["last_seen_at"] == initial
        assert operator.post("/api/auth/logout").status_code == 200
    contact = next(peer for peer in admin.get("/api/operator-chats").json()["items"] if peer["role"] == "OPERATOR")
    assert contact["last_seen_at"] == initial
