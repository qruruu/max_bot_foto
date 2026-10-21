"""Real independent PostgreSQL databases, identities, files and MAX routing."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date

import pytest
from fastapi.testclient import TestClient
from psycopg import connect, sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_integration import event

from app import ml
from app.auth import hasher
from app.config import settings
from app.db import database_engine, engine
from app.domain import now
from app.media import media_path
from app.models import (
    Inbox,
    MaxReceiverState,
    ModelVersion,
    Organization,
    OrganizationEvent,
    Photo,
    PlatformMaxReceiverState,
    User,
    WorkType,
)
from app.organization_context import current_organization, organization_scope
from app.organization_intake import dispatch_once, ingest_event
from app.organization_registry import bootstrap, control_session, scope_for

pytestmark = pytest.mark.integration
PASSWORD = "test-password-123"


@pytest.fixture
def companies(db, users, monkeypatch):
    from app.api import app

    assert make_url(settings().database_url).database.endswith("_test")
    bootstrap("admin", "Существующая компания", "legacy")
    monkeypatch.setenv("ORGANIZATIONS_ENABLED", "true")
    settings.cache_clear()
    records = []
    try:
        with ExitStack() as stack:
            owner = stack.enter_context(TestClient(app))
            login = owner.post("/api/auth/login", json={"login": "admin", "password": PASSWORD})
            assert login.status_code == 200 and login.json()["is_platform_owner"]
            owner.headers["X-CSRF-Token"] = owner.cookies["platform_csrf"]
            for slug in ("alpha", "beta"):
                response = owner.post("/api/platform/organizations", json={"name": slug.title(), "slug": slug})
                assert response.status_code == 201, response.text
                with control_session() as control:
                    record = control.get(Organization, response.json()["id"])
                    records.append(record)
                assert response.json()["status"] == "ACTIVE", response.text
            scopes = [scope_for(record) for record in records]
            clients = [stack.enter_context(TestClient(app)) for _ in scopes]
            for index, scope in enumerate(scopes):
                with organization_scope(scope), Session(engine()) as tenant:
                    assert tenant.scalar(select(func.count()).select_from(WorkType)) == 0
                    assert ml.active_model(tenant) is None
                    tenant.add(User(login="same-login", name=f"Operator {index}", role="OPERATOR", active=True,
                                    password_hash=hasher.hash(PASSWORD)))
                    tenant.commit()
                from app.signin_directory import sync_directory
                sync_directory(scope)
                response = clients[index].post("/api/auth/login", json={"login": "same-login", "password": PASSWORD})
                assert response.status_code == 200, response.text
                if response.json().get("requires_organization"):
                    response = clients[index].post("/api/auth/choose-organization", json={"organization_id": scope.id},
                        headers={"X-CSRF-Token": clients[index].cookies["login_choice_csrf"]})
                    assert response.status_code == 200, response.text
                clients[index].headers["X-CSRF-Token"] = clients[index].cookies["workspace_csrf"]
            yield owner, scopes, clients
    finally:
        # Only generated databases recorded by this disposable fixture may be dropped.
        root_url = make_url(settings().database_url)
        with connect(root_url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True) as root:
            for record in records:
                assert record.database_name == record.database_role == "org_" + record.id.replace("-", "")
                if record.owner_user_id:
                    database_engine(scope_for(record).database_url).dispose()
                root.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(record.database_name)))
                root.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(record.database_role)))


def bind(owner, scope, chat_id):
    response = owner.post(f"/api/platform/organizations/{scope.id}/chats",
                          json={"max_chat_id": str(chat_id), "name": "Chat " + str(chat_id)})
    assert response.status_code == 201, response.text


def test_databases_files_accounts_and_company_urls_are_isolated(companies):
    owner, scopes, clients = companies
    from app.api import app

    for i, scope in enumerate(scopes):
        bind(owner, scope, 100 + i)
        with organization_scope(scope), Session(engine()) as tenant:
            from app.intake import ingest
            inbox_id = ingest(tenant, event(chat_id=100 + i))
            tenant.flush()
            photo = tenant.scalar(select(Photo).where(Photo.inbox_id == inbox_id))
            photo.photo_date, photo.status, photo.analyzed_at = date(2026, 10, 16), "NEEDS_REVIEW", now()
            photo.sha256 = str(i) * 64
            path = media_path(photo.id, True)
            path.write_bytes(f"private image {i}".encode())
            tenant.commit()
        response = clients[i].get(scope.prefix + "/api/photos/1")
        assert response.status_code == 200, response.text
        assert response.json()["chat_name"] == "Chat " + str(100 + i)
        assert response.json()["preview_url"].startswith(scope.prefix + "/api/")
        assert clients[i].get(scope.prefix + "/api/photos/1/preview").content == f"private image {i}".encode()
        assert owner.get(scope.prefix + "/api/photos/1").status_code == 200
    assert scopes[0].data_dir != scopes[1].data_dir
    assert clients[0].get(scopes[1].prefix + "/api/photos/1").status_code == 401
    assert clients[0].get("/api/platform/organizations").status_code == 401
    assert clients[0].get("/api/photos/1").status_code == 409
    assert clients[0].get(scopes[0].prefix + "/api/platform/organizations").status_code == 404
    assert clients[0].post(scopes[0].prefix + "/api/webhooks/max", json={}).status_code == 404
    with TestClient(app) as anonymous:
        assert anonymous.get(scopes[0].prefix + "/api/photos/1").status_code == 401
    # A tenant SQL credential also cannot bypass the API and connect to another company's database.
    first = make_url(scopes[0].database_url)
    for database in (make_url(scopes[1].database_url).database, make_url(settings().database_url).database):
        other = database_engine(first.set(database=database).render_as_string(hide_password=False))
        with pytest.raises(OperationalError), other.connect():
            pass
        other.dispose()


def test_one_max_queue_routes_retries_and_preserves_unassigned_and_paused_messages(companies):
    owner, scopes, clients = companies
    bind(owner, scopes[0], 101)
    bind(owner, scopes[1], 202)
    with control_session() as db:
        ids = [ingest_event(db, event(chat_id=chat_id)) for chat_id in (101, 202, 303)]
        assert ingest_event(db, event(chat_id=101)) is None
        db.commit()
    assert dispatch_once() and dispatch_once() and not dispatch_once()
    for scope in scopes:
        with organization_scope(scope), Session(engine()) as db:
            assert db.scalar(select(func.count()).select_from(Photo)) == 1
            assert db.scalar(select(func.count()).select_from(Inbox)) == 1
    # Simulate an acknowledgement lost after a successful tenant commit.
    with control_session() as db:
        first = db.get(OrganizationEvent, ids[0])
        first.status, first.payload = "PENDING", event(chat_id=101)
        db.commit()
    assert dispatch_once() and not dispatch_once()
    bind(owner, scopes[1], 303)
    assert dispatch_once()
    conflict = owner.post(f"/api/platform/organizations/{scopes[1].id}/chats",
                          json={"max_chat_id": "101", "name": "Wrong company"})
    assert conflict.status_code == 409
    pause = owner.patch(f"/api/platform/organizations/{scopes[0].id}", json={"name": "Alpha", "status": "PAUSED"})
    assert pause.status_code == 200
    assert clients[0].get(scopes[0].prefix + "/api/auth/me").status_code == 404
    assert owner.get(scopes[0].prefix + "/api/meta").status_code == 200
    with control_session() as db:
        ingest_event(db, event(mid="while-paused", chat_id=101))
        db.commit()
    assert not dispatch_once()
    owner.patch(f"/api/platform/organizations/{scopes[0].id}", json={"name": "Alpha", "status": "ACTIVE"})
    assert dispatch_once()
    for scope in scopes:
        with organization_scope(scope), Session(engine()) as db:
            assert db.scalar(select(func.count()).select_from(Photo)) == 2
    with control_session() as db:
        assert all(row.status == "DELIVERED" and not row.payload for row in db.scalars(select(OrganizationEvent)))


def test_learning_and_concurrent_contexts_do_not_share_data(companies):
    owner, scopes, _ = companies
    bind(owner, scopes[0], 101)
    with organization_scope(scopes[0]), Session(engine()) as db:
        from app.intake import ingest
        db.add(WorkType(code="PRIVATE", name="Только Alpha", filename_label="Alpha", model_index=0, sort_order=1))
        inbox_id = ingest(db, event(chat_id=101))
        db.flush()
        photo = db.scalar(select(Photo).where(Photo.inbox_id == inbox_id))
        photo.work_type, photo.work_type_source, photo.reviewed_by = "PRIVATE", "OPERATOR", scopes[0].owner_user_id
        photo.sha256, photo.analyzed_at, photo.status = "a" * 64, now(), "ACCEPTED"
        media_path(photo.id, True).write_bytes(b"private training example")
        db.commit()
        assert len(ml.collect_examples(db)[0]) == 1
    def inspect(scope):
        with organization_scope(scope), Session(engine()) as db:
            return current_organization().id, settings().data_dir, len(ml.collect_examples(db)[0])
    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(inspect, scopes))
    assert [result[0] for result in results] == [scope.id for scope in scopes]
    assert [result[2] for result in results] == [1, 0]
    assert current_organization() is None
    with organization_scope(scopes[1]), Session(engine()) as db:
        assert db.scalar(select(func.count()).select_from(ModelVersion)) == 0
        response = ml.LocalClassifier().classify(media_path(1, True))
        assert response.raw["reason"] == "MODEL_NOT_TRAINED"
    listed = owner.get("/api/platform/organizations").json()
    assert [item["stats"]["work_types"] for item in listed if not item["legacy"]] == [1, 0]


def test_company_administrators_cannot_take_over_owner_or_other_companies(companies):
    owner, scopes, clients = companies
    local = clients[0]
    with organization_scope(scopes[0]), Session(engine()) as db:
        user = db.scalar(select(User).where(User.login == "same-login"))
        user.role = "ADMIN_OPERATOR"
        db.commit()
    assert local.get("/api/platform/organizations").status_code == 401
    assert local.patch(scopes[0].prefix + f"/api/users/{scopes[0].owner_user_id}",
                       json={"password": "unauthorized-owner-password"}).status_code == 403
    assert local.post(scopes[0].prefix + "/api/chats", json={"max_chat_id": "999", "name": "Unclaimed"}).status_code == 409
    assert local.get(scopes[1].prefix + "/api/users").status_code == 401
    bad_csrf = local.post(scopes[0].prefix + "/api/users", headers={"X-CSRF-Token": "wrong"},
                          json={"login": "third", "name": "Third", "password": PASSWORD})
    assert bad_csrf.status_code == 403
    assert owner.post("/api/platform/organizations", headers={"X-CSRF-Token": "wrong"},
                      json={"slug": "forbidden", "name": "Forbidden"}).status_code == 403
    order = ["/photos", "/"]
    assert owner.put(scopes[0].prefix + "/api/auth/sidebar-order", json={"sidebar_order": order}).status_code == 200
    me = owner.get(scopes[0].prefix + "/api/auth/me").json()
    assert me["sidebar_order"] == order and me["id"] == scopes[0].owner_user_id
    assert me["name"] == "admin" and me["is_platform_owner"]


def test_global_receiver_checkpoint_does_not_change_legacy_company_counters(companies):
    from test_receiver import MaxPage

    from app.receiver import poll_once

    owner, scopes, _ = companies
    bind(owner, scopes[0], 101)
    assert poll_once(MaxPage([event(chat_id=101)]))
    with control_session() as db:
        assert db.get(PlatformMaxReceiverState, 1).marker == 42
        assert db.get(MaxReceiverState, 1) is None
        assert db.scalar(select(func.count()).select_from(Photo)) == 0
    assert dispatch_once()
    with organization_scope(scopes[0]), Session(engine()) as db:
        assert db.get(MaxReceiverState, 1).inbox_received == 1


def test_worker_continues_after_an_unavailable_company(monkeypatch, tmp_path):
    from app import organization_registry, worker
    from app.organization_context import OrganizationScope

    monkeypatch.setenv("ORGANIZATIONS_ENABLED", "true")
    settings.cache_clear()
    scopes = [OrganizationScope(str(i), str(i), "postgresql://unused", tmp_path / str(i), 1) for i in (1, 2)]
    monkeypatch.setattr(organization_registry, "scopes", lambda: scopes)
    visited = []
    def run_once(kinds):
        visited.append(current_organization().id)
        if current_organization().id == "1":
            raise RuntimeError("one company unavailable")
        return True
    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker, "stop", False)
    assert worker.run_workspaces_once(["REPLY"])
    assert visited == ["1", "2"] and current_organization() is None


def test_existing_company_import_preserves_photo_ids_labels_files_and_model(companies):
    import hashlib
    from dataclasses import asdict

    from app.disk_folders import company_roots
    from app.models import Chat, DiskFolderSettings, ExchangeState, LoginSession, OrganizationChat
    from app.organization_import import finish, prepare

    owner, scopes, _ = companies
    scope = scopes[0]
    owner.patch(f"/api/platform/organizations/{scope.id}", json={"name": "Imported", "status": "PAUSED"})
    # Refuse to erase even a newly created operator; source/working companies stay untouched.
    with pytest.raises(ValueError, match="операторы"):
        prepare(scope.id)
    with organization_scope(scope), Session(engine()) as db:
        for session in db.scalars(select(LoginSession)):
            db.delete(session)
        db.flush()
        db.delete(db.scalar(select(User).where(User.login == "same-login")))
        db.commit()
    prepare(scope.id)
    assert owner.get(scope.prefix + "/api/meta").status_code == 404
    weights = b"original trained weights"
    with organization_scope(scope), Session(engine()) as db:
        # These are the business rows a data-only PostgreSQL restore supplies.
        operator = User(login="original", name="Original", role="OPERATOR", active=True,
                        password_hash=hasher.hash(PASSWORD))
        db.add(operator)
        db.flush()
        db.add_all([ExchangeState(id=1, instance_id=scope.id, intake_cohort="test", source_timezone="Asia/Yekaterinburg"),
                    DiskFolderSettings(id=1, version=1, folder_sets=[]),
                    Chat(max_chat_id=777, name="Original chat", active=True),
                    WorkType(code="ORIGINAL", name="Original label", filename_label="Original", model_index=0, sort_order=1)])
        db.flush()
        from app.intake import ingest
        inbox_id = ingest(db, event(chat_id=777))
        db.flush()
        photo = db.scalar(select(Photo).where(Photo.inbox_id == inbox_id))
        photo.work_type, photo.work_type_source, photo.reviewed_by = "ORIGINAL", "OPERATOR", operator.id
        photo.sha256, photo.status, photo.analyzed_at = "a" * 64, "ACCEPTED", now()
        media_path(photo.id, True).write_bytes(b"original preview")
        version = ModelVersion(status="ACTIVE", dataset_fingerprint="b" * 64, sample_count=50,
                               labels_snapshot={str(photo.id): "ORIGINAL"}, supported_classes=["ORIGINAL"],
                               model_path="/old/data/models/version-1/weights.pt",
                               model_sha256=hashlib.sha256(weights).hexdigest())
        db.add(version)
        db.commit()
        target = scope.data_dir / "models/version-1/weights.pt"
        target.parent.mkdir(parents=True)
        target.write_bytes(weights)
    finish(scope.id, old_data_dir="/old/data", roots=asdict(company_roots("IMPORTED_COMPANY")))
    with organization_scope(scope), Session(engine()) as db:
        photo = db.get(Photo, 1)
        assert photo.work_type == "ORIGINAL" and photo.status == "ACCEPTED"
        assert media_path(1, True).read_bytes() == b"original preview"
        assert db.get(ModelVersion, 1).model_path == str(target)
        assert target.read_bytes() == weights and len(ml.collect_examples(db)[0]) == 1
        assert db.get(DiskFolderSettings, 1).folder_sets[0]["photo_root"] == "IMPORTED_COMPANY"
    with control_session() as db:
        assert db.get(Organization, scope.id).status == "PAUSED"
        assert db.get(OrganizationChat, 777).organization_id == scope.id
    assert owner.get(scope.prefix + "/api/photos/1").status_code == 200


def test_common_entry_resolves_owner_operator_and_revoked_session(companies):
    from app.auth import digest
    from app.models import LoginSession

    owner, scopes, clients = companies
    assert owner.get("/api/auth/entry").json()["user"]["is_platform_owner"]
    operator = clients[0]
    entry = operator.get("/api/auth/entry").json()["user"]
    assert entry["organization"]["id"] == scopes[0].id and not entry["is_platform_owner"]
    assert operator.get(scopes[1].prefix + "/api/auth/me").status_code == 401
    with organization_scope(scopes[0]), Session(engine()) as tenant:
        tenant.delete(tenant.get(LoginSession, digest(operator.cookies["workspace_session"])))
        tenant.commit()
    assert operator.get("/api/auth/entry").json() == {"user": None}
    assert operator.get(scopes[0].prefix + "/api/auth/me").status_code == 401


def test_common_login_filters_matching_passwords_and_clears_owner_authority(companies):
    owner, scopes, _ = companies
    other_password = "different-company-password"
    with organization_scope(scopes[1]), Session(engine()) as tenant:
        user = tenant.scalar(select(User).where(User.login == "same-login"))
        user.password_hash = hasher.hash(other_password)
        tenant.commit()
    # Starting from an owner browser must not retain owner cookies after operator sign-in.
    response = owner.post("/api/auth/login", json={"login": "same-login", "password": other_password})
    assert response.status_code == 200 and "choices" not in response.json()
    assert response.json()["organization"]["id"] == scopes[1].id
    assert "platform_session" not in owner.cookies
    assert owner.get("/api/platform/organizations").status_code == 401
    owner.headers["X-CSRF-Token"] = owner.cookies["workspace_csrf"]
    assert owner.post(scopes[1].prefix + "/api/auth/logout").status_code == 200
    assert owner.get("/api/auth/entry").json() == {"user": None}
    assert owner.post("/api/auth/login", json={"login": "same-login", "password": "wrong"}).status_code == 401


def test_common_login_choice_is_verified_csrf_protected_and_single_use(companies):
    from app.api import app
    from app.auth import digest
    from app.models import LoginChoice

    owner, scopes, _ = companies
    with TestClient(app) as browser:
        response = browser.post("/api/auth/login", json={"login": "same-login", "password": PASSWORD})
        assert response.status_code == 200
        assert {item["id"] for item in response.json()["choices"]} == {scope.id for scope in scopes}
        assert "workspace_session" not in browser.cookies
        choice_token = browser.cookies["login_choice"]
        csrf = browser.cookies["login_choice_csrf"]
        assert PASSWORD not in response.text
        with control_session() as db:
            grant = db.get(LoginChoice, digest(choice_token))
            assert PASSWORD not in str(grant.candidates)
            legacy = db.scalar(select(Organization).where(Organization.legacy))
            forbidden_id = legacy.id
        assert browser.post("/api/auth/choose-organization", json={"organization_id": scopes[0].id}).status_code == 403
        browser.headers["X-CSRF-Token"] = csrf
        assert browser.post("/api/auth/choose-organization", json={"organization_id": forbidden_id}).status_code == 403
        chosen = browser.post("/api/auth/choose-organization", json={"organization_id": scopes[0].id})
        assert chosen.status_code == 200 and chosen.json()["organization"]["id"] == scopes[0].id
        browser.cookies.set("login_choice", choice_token)
        assert browser.post("/api/auth/choose-organization", json={"organization_id": scopes[1].id}).status_code == 401


def test_login_choice_cannot_outlive_password_or_expiry(companies):
    from datetime import timedelta

    from app.api import app
    from app.auth import digest
    from app.models import LoginChoice

    _, scopes, _ = companies
    with TestClient(app) as browser:
        response = browser.post("/api/auth/login", json={"login": "same-login", "password": PASSWORD})
        assert response.json()["requires_organization"]
        browser.headers["X-CSRF-Token"] = browser.cookies["login_choice_csrf"]
        with organization_scope(scopes[0]), Session(engine()) as tenant:
            tenant.scalar(select(User).where(User.login == "same-login")).password_hash = hasher.hash("new-password-123")
            tenant.commit()
        assert browser.post("/api/auth/choose-organization", json={"organization_id": scopes[0].id}).status_code == 401
        # Password changes invalidate the saved verification, including a consumed failed grant.
        response = browser.post("/api/auth/login", json={"login": "same-login", "password": PASSWORD})
        assert response.json()["organization"]["id"] == scopes[1].id
        with organization_scope(scopes[0]), Session(engine()) as tenant:
            tenant.scalar(select(User).where(User.login == "same-login")).password_hash = hasher.hash(PASSWORD)
            tenant.commit()
        assert browser.post("/api/auth/login", json={"login": "same-login", "password": PASSWORD}).json()["requires_organization"]
        browser.headers["X-CSRF-Token"] = browser.cookies["login_choice_csrf"]
        with control_session() as control:
            grant = control.get(LoginChoice, digest(browser.cookies["login_choice"]))
            grant.expires_at = now() - timedelta(seconds=1)
            control.commit()
        assert browser.post("/api/auth/choose-organization", json={"organization_id": scopes[1].id}).status_code == 401


def test_created_operator_can_use_common_login_and_modes_are_company_specific(companies):
    from app.api import app
    from app.models import ExchangeState

    owner, scopes, _ = companies
    response = owner.post(scopes[0].prefix + "/api/users", json={"login": "fresh-user", "name": "Fresh",
                                                                    "password": PASSWORD})
    assert response.status_code == 201, response.text
    with TestClient(app) as browser:
        response = browser.post("/api/auth/login", json={"login": "fresh-user", "password": PASSWORD})
        assert response.status_code == 200 and response.json()["organization"]["id"] == scopes[0].id
    with organization_scope(scopes[0]), Session(engine()) as tenant:
        state = tenant.get(ExchangeState, 1)
        if state:
            state.intake_cohort = "production"
        else:
            tenant.add(ExchangeState(id=1, instance_id=scopes[0].id, source_timezone="Asia/Yekaterinburg", intake_cohort="production"))
        tenant.commit()
    listed = {item["id"]: item for item in owner.get("/api/platform/organizations").json()}
    assert listed[scopes[0].id]["stats"]["intake_cohort"] == "production"
    assert listed[scopes[1].id]["stats"]["intake_cohort"] == "test"


def test_reusable_disk_accounts_are_private_separate_folders_and_preserve_originals(companies):
    import httpx
    import respx

    from app.disk_accounts import account_token, token_path
    from app.integrations import YandexDisk
    from app.models import Audit, DiskFolderSettings

    owner, scopes, clients = companies
    with respx.mock:
        identify = respx.get("https://cloud-api.yandex.net/v1/disk/").mock(
            return_value=httpx.Response(200, json={"user": {"uid": "123456", "login": "my-archive"}}))
        response = owner.post("/api/platform/disk-accounts", json={"name": "Мой архив", "token": "synthetic-token-one"})
        assert response.status_code == 201, response.text
        account = response.json()
        assert set(account) == {"id", "name", "login"} and account["login"] == "my-archive"
        assert identify.calls[0].request.headers["Authorization"] == "OAuth synthetic-token-one"
        assert account_token(account["id"]) == "synthetic-token-one"
        assert token_path(account["id"]).stat().st_mode & 0o777 == 0o600
        roots = []
        for scope in scopes:
            denied = owner.patch("/api/platform/organizations/" + scope.id, json={
                "name": scope.name, "status": "ACTIVE", "disk_account_id": account["id"]})
            assert denied.status_code == 409  # Pause first to drain incoming deliveries.
            assert owner.patch("/api/platform/organizations/" + scope.id, json={"name": scope.name, "status": "PAUSED"}).status_code == 200
            saved = owner.patch("/api/platform/organizations/" + scope.id, json={
                "name": scope.name, "status": "ACTIVE", "disk_account_id": account["id"]})
            assert saved.status_code == 200 and saved.json()["disk_account_id"] == account["id"]
            with organization_scope(scope), Session(engine()) as tenant:
                roots.append(tenant.get(DiskFolderSettings, 1).folder_sets[0]["photo_root"])
                route = respx.get(YandexDisk.API + "/resources").mock(return_value=httpx.Response(404))
                assert YandexDisk().metadata("disk:/example.jpg") is None
                assert route.calls[-1].request.headers["Authorization"] == "OAuth synthetic-token-one"
        assert roots[0] != roots[1]
        # A reconnect of this physical account rotates the token for all its companies.
        again = owner.post("/api/platform/disk-accounts", json={"name": "Мой архив", "token": "synthetic-token-rotated"})
        assert again.status_code == 201 and again.json()["id"] == account["id"]
        with organization_scope(scopes[0]):
            YandexDisk().metadata("disk:/example.jpg")
            assert route.calls[-1].request.headers["Authorization"] == "OAuth synthetic-token-rotated"
        identify.mock(return_value=httpx.Response(200, json={"user": {"uid": "654321", "login": "another"}}))
        different = owner.post("/api/platform/disk-accounts", json={"name": "Другой", "token": "synthetic-other-token"}).json()
        bind(owner, scopes[0], 101)
        with organization_scope(scopes[0]), Session(engine()) as tenant:
            from app.intake import ingest
            ingest(tenant, event(chat_id=101))
            tenant.commit()
        blocked = owner.patch("/api/platform/organizations/" + scopes[0].id, json={
            "name": scopes[0].name, "status": "ACTIVE", "disk_account_id": different["id"]})
        assert blocked.status_code == 409 and "перенос" in blocked.text
        assert "synthetic-" not in owner.get("/api/platform/disk-accounts").text
        with control_session() as control:
            assert "synthetic-" not in str(list(control.scalars(select(Audit.new_value))))
        assert clients[0].get("/api/platform/disk-accounts").status_code == 401
        assert clients[0].post("/api/platform/disk-accounts", json={"name": "No", "token": "synthetic-forbidden"}).status_code == 401


def test_invalid_disk_token_is_not_saved_or_echoed(companies):
    import httpx
    import respx

    from app.models import DiskAccount

    owner, _, _ = companies
    with respx.mock:
        respx.get("https://cloud-api.yandex.net/v1/disk/").mock(return_value=httpx.Response(401, text="synthetic-invalid-secret"))
        response = owner.post("/api/platform/disk-accounts", json={"name": "Invalid", "token": "synthetic-invalid-secret"})
        assert response.status_code == 422 and "synthetic-invalid-secret" not in response.text
    with control_session() as control:
        assert control.scalar(select(func.count()).select_from(DiskAccount)) == 0
