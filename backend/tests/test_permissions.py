import runpy
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, text

from app.api import app
from app.domain import now
from app.media import media_path
from app.models import Audit, Chat, Job, User
from app.permissions import DEFAULT_OPERATOR_PERMISSIONS, PERMISSIONS, Permission, effective_permissions
from tests.test_integration import intake_photo, setup_chat, setup_district


def sign_in(client, login="operator"):
    result = client.post("/api/auth/login", json={"login": login, "password": "test-password-123"})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = client.cookies["csrf"]
    return result.json()


def restrict(db, permissions):
    operator = db.scalar(select(User).where(User.login == "operator"))
    operator.permissions = permissions
    db.commit()
    return operator


@pytest.fixture
def photo(db):
    setup_chat(db)
    record = intake_photo(db)
    record.analyzed_at = now()
    record.status = "NEEDS_REVIEW"
    record.yandex_disk_path = "disk:/MAX_PHOTOS/test.jpg"
    record.storage_status = "SYNCED"
    db.commit()
    db.refresh(record)
    Image.new("RGB", (20, 20)).save(media_path(record.id, preview=True), format="JPEG")
    return record


def test_existing_operator_and_admin_defaults(admin, db):
    assert set(admin.get("/api/auth/me").json()["permissions"]) == set(PERMISSIONS)
    operator = db.scalar(select(User).where(User.login == "operator"))
    assert operator.permissions == DEFAULT_OPERATOR_PERMISSIONS
    assert set(effective_permissions(operator)) == {
        "reports_view",
        "photos_view",
        "originals_view",
        "photos_edit",
        "spam_view",
        "reports_export",
        "previews_remove",
        "districts_view",
    }
    operator.role = "ADMIN_OPERATOR"
    operator.permissions = []
    assert set(effective_permissions(operator)) == set(PERMISSIONS)


def test_create_and_edit_custom_operator_rights(admin, db):
    body = {
        "login": "reader",
        "name": "Просмотр",
        "password": "a-test-password",
        "permissions": ["photos_view"],
    }
    response = admin.post("/api/users", json=body)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["permissions"] == ["photos_view"]
    assert "password_hash" not in record
    updated = admin.patch(f"/api/users/{record['id']}", json={"permissions": []})
    assert updated.status_code == 200 and updated.json()["permissions"] == []
    history = list(db.scalars(select(Audit).where(Audit.object_type == "user").order_by(Audit.id)))
    assert history[-1].old_value["permissions"] == ["photos_view"]
    assert history[-1].new_value["permissions"] == []
    assert all("password_hash" not in (item.new_value or {}) for item in history)
    # Clients using the old API keep the legacy operator defaults when the field is omitted.
    body.update(login="legacy")
    body.pop("permissions")
    assert admin.post("/api/users", json=body).json()["permissions"] == DEFAULT_OPERATOR_PERMISSIONS


@pytest.mark.parametrize(
    "permissions",
    [
        ["unknown"],
        None,
        ["photos_edit"],
        ["originals_view"],
        ["reports_export", "photos_view"],
        ["districts_edit"],
    ],
)
def test_invalid_or_incomplete_permission_sets_rejected(admin, db, permissions):
    body = {"login": "reader", "name": "Test", "password": "a-test-password", "permissions": permissions}
    assert admin.post("/api/users", json=body).status_code == 422
    operator = db.scalar(select(User).where(User.login == "operator"))
    assert admin.patch(f"/api/users/{operator.id}", json={"permissions": permissions}).status_code == 422
    db.refresh(operator)
    assert operator.permissions == DEFAULT_OPERATOR_PERMISSIONS


def test_no_permissions_leaves_only_account_and_denies_all_function_endpoints(client, users, db, photo):
    restrict(db, [])
    assert sign_in(client)["permissions"] == []
    assert client.get("/api/auth/me").status_code == 200
    meta = client.get("/api/meta").json()
    assert meta["chats"] == meta["districts"] == meta["operators"] == []
    assert len(meta["permission_catalog"]) == len(PERMISSIONS)
    assert meta["yandex_maps_api_key"] == ""
    polygon = {"type": "Polygon", "coordinates": [[[72, 61], [73, 61], [73, 62], [72, 61]]]}
    routes = [
        ("GET", "/api/reports", None),
        ("GET", "/api/photos", None),
        ("GET", f"/api/photos/{photo.id}", None),
        ("GET", f"/api/photos/{photo.id}/preview", None),
        ("GET", f"/api/photos/{photo.id}/original", None),
        ("PATCH", f"/api/photos/{photo.id}", {"version": photo.version, "photo_date": "2026-10-15"}),
        ("POST", f"/api/photos/{photo.id}/retry", None),
        ("POST", f"/api/photos/{photo.id}/remove-missing-preview", {"version": photo.version}),
        ("GET", "/api/export.xlsx", None),
        ("GET", "/api/districts", None),
        ("POST", "/api/districts", {"name": "Test", "geometry": polygon}),
        ("PUT", "/api/districts/1", {"name": "Test", "geometry": polygon}),
        ("GET", "/api/chats", None),
        ("GET", "/api/chats/discovered", None),
        ("POST", "/api/chats", {"name": "Test", "max_chat_id": "456"}),
        ("PUT", "/api/chats/1", {"name": "Test", "max_chat_id": "123"}),
        ("GET", "/api/max/status", None),
        ("GET", "/api/users", None),
        ("GET", "/api/audit", None),
        ("GET", "/api/jobs", None),
        ("POST", "/api/jobs/1/retry", None),
        ("GET", "/api/ml", None),
        ("POST", "/api/ml/train", None),
        ("GET", "/api/exchange", None),
        ("PUT", "/api/exchange/mode", {"cohort": "test"}),
        ("POST", "/api/exchange/publish", {"cohort": "test"}),
        ("POST", "/api/exchange/organize", None),
    ]
    for method, path, body in routes:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, (method, path, response.text)
    assert client.post("/api/auth/logout").status_code == 200


def test_photo_read_permission_does_not_grant_edits_originals_or_exports(client, users, db, photo):
    restrict(db, ["photos_view"])
    sign_in(client)
    assert client.get("/api/photos").json()["total"] == 1
    assert client.get(f"/api/photos/{photo.id}").status_code == 200
    assert client.get(f"/api/photos/{photo.id}/preview").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/photos/{photo.id}/original").status_code == 403
    assert client.get("/api/export.xlsx").status_code == 403
    assert client.get("/api/reports").status_code == 403
    assert (
        client.patch(f"/api/photos/{photo.id}", json={"version": 1, "photo_date": "2026-10-15"}).status_code
        == 403
    )
    assert client.post(f"/api/photos/{photo.id}/retry").status_code == 403
    assert (
        client.post(f"/api/photos/{photo.id}/remove-missing-preview", json={"version": 1}).status_code == 403
    )


def test_original_access_is_explicit(client, users, db, photo, monkeypatch):
    restrict(db, ["photos_view", "originals_view"])
    sign_in(client)
    # URL policy is still checked; permission tests must not depend on live DNS.
    monkeypatch.setattr("app.integrations.socket.getaddrinfo",
                        lambda *_args, **_kwargs: [(2, 1, 6, "", ("1.1.1.1", 443))])
    monkeypatch.setattr(
        "app.api.YandexDisk.request",
        lambda *a, **kw: httpx.Response(
            200,
            json={"href": "https://downloader.disk.yandex.ru/test.jpg"},
            request=httpx.Request("GET", "https://cloud-api.yandex.net"),
        ),
    )
    response = client.get(f"/api/photos/{photo.id}/original", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://downloader.disk.yandex.ru/test.jpg"


def test_spam_permission_cannot_be_bypassed_with_id_filter_or_retry(client, users, db, photo):
    permissions = [p for p in DEFAULT_OPERATOR_PERMISSIONS if p != "spam_view"] + ["jobs_manage"]
    restrict(db, permissions)
    sign_in(client)
    response = client.patch(f"/api/photos/{photo.id}", json={"version": photo.version, "is_spam": True})
    assert response.status_code == 403, response.text
    photo.is_spam, photo.status = True, "SPAM"
    photo.processing_error, photo.storage_status = "ORIGINAL_MISSING", "ERROR"
    db.add(Job(kind="SYNC", object_id=photo.id, dedupe_key="spam-sync", status="BLOCKED"))
    db.commit()
    assert client.get("/api/photos").json()["total"] == 0
    assert client.get("/api/reports").json()["total"] == 0
    for path in [
        "/api/photos?status=SPAM",
        "/api/reports?status=SPAM",
        "/api/export.xlsx?status=SPAM",
        f"/api/photos/{photo.id}",
        f"/api/photos/{photo.id}/preview",
        f"/api/photos/{photo.id}/original",
    ]:
        assert client.get(path).status_code == 403, path
    assert client.patch(f"/api/photos/{photo.id}", json={"version": 1, "is_spam": False}).status_code == 403
    assert client.post(f"/api/photos/{photo.id}/retry").status_code == 403
    assert (
        client.post(f"/api/photos/{photo.id}/remove-missing-preview", json={"version": 1}).status_code == 403
    )
    job_id = db.scalar(select(Job.id).where(Job.dedupe_key == "spam-sync"))
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 403


@pytest.mark.parametrize(
    ("permissions", "path"),
    [
        (["reports_view"], "/api/reports"),
        (["districts_view"], "/api/districts"),
        (["chats_manage"], "/api/chats"),
        (["chats_manage"], "/api/chats/discovered"),
        (["chats_manage"], "/api/max/status"),
        (["audit_view"], "/api/audit"),
        (["jobs_manage"], "/api/jobs"),
        (["exchange_manage"], "/api/exchange"),
        (["learning_manage"], "/api/ml"),
    ],
)
def test_explicit_section_grants(client, users, db, permissions, path):
    restrict(db, permissions)
    sign_in(client)
    assert client.get(path).status_code == 200
    assert client.get("/api/users").status_code == 403


def test_delegated_actions_and_admin_only_user_management(client, users, db):
    operator = restrict(db, list(map(str, PERMISSIONS)))
    sign_in(client)
    assert (
        client.post(
            "/api/users", json={"login": "extra", "name": "extra", "password": "a-test-password"}
        ).status_code
        == 403
    )
    assert client.patch(f"/api/users/{operator.id}", json={"role": "ADMIN_OPERATOR"}).status_code == 403
    assert client.post("/api/chats", json={"max_chat_id": "456", "name": "Delegated"}).status_code == 201
    assert db.scalar(select(Chat).where(Chat.max_chat_id == 456)) is not None
    assert client.put("/api/exchange/mode", json={"cohort": "production"}).status_code == 200
    assert client.post("/api/exchange/publish", json={"cohort": "production"}).status_code == 202
    assert client.post("/api/exchange/organize").status_code == 202
    district = setup_district(db)
    data = client.get("/api/districts").json()["features"][0]
    assert (
        client.put(
            f"/api/districts/{district.id}", json={"name": "New name", "geometry": data["geometry"]}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("kind", "required"),
    [
        ("PUBLISH", ["exchange_manage"]),
        ("EXCHANGE_GC", ["exchange_manage"]),
        ("ARCHIVE_ORGANIZE", ["exchange_manage"]),
        ("TRAIN", ["learning_manage"]),
        ("REGEO", ["districts_view", "districts_edit"]),
        ("SYNC", ["photos_view", "photos_edit"]),
        ("BATCH", ["photos_view", "photos_edit"]),
        ("REPLY", ["photos_view", "photos_edit"]),
        ("REMOVE_PREVIEW", ["photos_view", "previews_remove"]),
    ],
)
def test_job_retry_does_not_bypass_function_permissions(client, users, db, kind, required):
    restrict(db, ["jobs_manage"])
    job = Job(kind=kind, object_id=99, dedupe_key="test-retry", last_error="Test")
    db.add(job)
    db.commit()
    sign_in(client)
    assert not client.get("/api/jobs").json()[0]["can_retry"]
    assert client.post(f"/api/jobs/{job.id}/retry").status_code == 403
    db.refresh(job)
    assert job.last_error == "Test"
    restrict(db, ["jobs_manage", *required])
    assert client.get("/api/jobs").json()[0]["can_retry"]
    assert client.post(f"/api/jobs/{job.id}/retry").status_code == 200


def test_permission_change_revokes_existing_session(admin, db):
    with TestClient(app) as operator_client:
        sign_in(operator_client)
        operator = db.scalar(select(User).where(User.login == "operator"))
        assert (
            admin.patch(f"/api/users/{operator.id}", json={"permissions": ["photos_view"]}).status_code == 200
        )
        assert operator_client.get("/api/photos").status_code == 401
        assert sign_in(operator_client)["permissions"] == ["photos_view"]
        assert operator_client.get("/api/photos").status_code == 200
        assert operator_client.get("/api/reports").status_code == 403


def test_only_account_permissions_can_still_change_password(client, users, db):
    restrict(db, [])
    sign_in(client)
    response = client.post(
        "/api/auth/password",
        json={"current_password": "test-password-123", "new_password": "new-password-1234"},
    )
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_permission_migration_preserves_existing_users_and_guards_downgrade(db):
    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0013_operator_permissions.py")
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        migration["downgrade"]()
        db.execute(
            text("""INSERT INTO users(login,name,password_hash,role,active)
            VALUES ('legacy','Legacy','unused','OPERATOR',true), ('admin','Admin','unused','ADMIN_OPERATOR',true)""")
        )
        migration["upgrade"]()
        legacy = db.scalar(select(User).where(User.login == "legacy"))
        assert legacy.permissions == DEFAULT_OPERATOR_PERMISSIONS
        admin = db.scalar(select(User).where(User.login == "admin"))
        assert set(effective_permissions(admin)) == set(PERMISSIONS)
        legacy.permissions = ["photos_view"]
        db.flush()
        with pytest.raises(RuntimeError, match="Restricted operators"):
            migration["downgrade"]()
        # No column was dropped and the restricted record remains restricted.
        assert db.scalar(text("SELECT permissions FROM users WHERE login='legacy'")) == ["photos_view"]
    db.commit()


def test_malformed_stored_prerequisites_fail_closed():
    user = User(role="OPERATOR", permissions=["photos_edit", "reports_export", "originals_view", "unknown"])
    assert effective_permissions(user) == []
    assert Permission.PHOTOS_VIEW in PERMISSIONS


def test_resaving_same_permissions_keeps_existing_session(admin, db):
    with TestClient(app) as operator_client:
        sign_in(operator_client)
        operator = db.scalar(select(User).where(User.login == "operator"))
        response = admin.patch(
            f"/api/users/{operator.id}", json={"name": "Renamed", "permissions": operator.permissions}
        )
        assert response.status_code == 200
        assert operator_client.get("/api/auth/me").status_code == 200
        assert operator_client.get("/api/auth/me").json()["name"] == "Renamed"
