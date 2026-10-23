"""Real owner authentication, per-organization isolation and durable original transfers."""

import hashlib
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_integration import event, intake_photo, setup_chat
from test_missing_original import Storage
from test_organizations import bind
from test_organizations import companies as companies

from app.config import settings
from app.db import engine
from app.domain import audit, now, storage_path
from app.intake import ingest
from app.media import media_path
from app.models import Audit, DayClosure, DayPhotoReview, ExchangeState, Job, Photo, User
from app.organization_context import organization_scope
from app.processing import sync_photo

pytestmark = pytest.mark.integration


def seed(scope, *, content=b"original photo", cohort="test", mid="photo", current="production"):
    with organization_scope(scope), Session(engine(), expire_on_commit=False) as db:
        db.get(ExchangeState, 1).intake_cohort = cohort
        inbox_id = ingest(db, event(mid=mid, chat_id=101))
        db.flush()
        photo = db.scalar(select(Photo).where(Photo.inbox_id == inbox_id))
        photo.sha256, photo.analyzed_at, photo.status = hashlib.sha256(content).hexdigest(), now(), "ACCEPTED"
        photo.extension, photo.photo_date = ".jpg", date(2026, 10, 16)
        photo.latitude, photo.longitude = 61.1, 72.6
        photo.work_type, photo.work_type_source = "PRIVATE", "AI"
        photo.review_reason = []
        from app.disk_folders import current_disk_roots
        photo.yandex_disk_path = storage_path(photo, None, {"PRIVATE": ("Работа", "Работа")}, current_disk_roots(db))
        photo.storage_status = "SYNCED"
        media_path(photo.id, True).write_bytes(b"preview")
        db.get(ExchangeState, 1).intake_cohort = current
        for job in db.scalars(select(Job)):
            job.status = "DONE"
        db.commit()
        db.refresh(photo)
        return photo


def prepare(owner, scope):
    bind(owner, scope, 101)
    with organization_scope(scope), Session(engine()) as db:
        from app.models import WorkType
        db.add(WorkType(code="PRIVATE", name="Работа", filename_label="Работа", model_index=0, sort_order=1))
        db.commit()


def test_only_real_platform_owner_can_open_test_photo_in_production_and_promote(companies):
    from app.api import app
    owner, scopes, clients = companies
    scope = scopes[0]
    prepare(owner, scope)
    photo = seed(scope)
    path = scope.prefix + f"/api/photos/{photo.id}"
    assert owner.get(path).json()["cohort"] == "test"
    assert owner.get(path + "/preview").content == b"preview"
    assert clients[0].get(path).status_code == 404
    assert clients[0].post(path + "/promote", json={"version": photo.version}).status_code == 403
    # A tenant administrator is still not the service owner, even with every permission.
    with organization_scope(scope), Session(engine()) as db:
        db.scalar(select(User).where(User.login == "same-login")).role = "ADMIN_OPERATOR"
        db.commit()
    assert clients[0].get(path).status_code == 404
    assert clients[0].post(path + "/promote", json={"version": photo.version}).status_code == 403
    assert clients[1].post(path + "/promote", json={"version": photo.version}).status_code == 401
    with TestClient(app) as anonymous:
        assert anonymous.post(path + "/promote", json={"version": photo.version}).status_code == 401
    assert owner.post(path + "/promote", json={"version": photo.version}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert owner.post(path + "/promote", json={"version": photo.version + 1}).status_code == 409
    assert owner.post(path + "/promote", json={"version": photo.version, "cohort": "test"}).status_code == 422
    response = owner.post(path + "/promote", json={"version": photo.version})
    assert response.status_code == 200, response.text
    assert response.json()["cohort"] == "production"
    assert clients[0].get(path).status_code == 200
    assert clients[1].get(path).status_code == 401
    with organization_scope(scope), Session(engine()) as db:
        assert db.get(ExchangeState, 1).intake_cohort == "production"
        assert db.get(Photo, photo.id).work_type_source == "AI"
        assert db.get(Photo, photo.id).reviewed_by is None
        assert db.scalar(select(Audit).where(Audit.action == "PHOTO_PROMOTED_TO_PRODUCTION")).user_id == scope.owner_user_id


@pytest.mark.parametrize("already_at_destination", [False, True])
def test_promotion_synchronizes_verified_original_and_reuses_blocked_job(companies, monkeypatch, already_at_destination):
    owner, scopes, _ = companies
    scope = scopes[0]
    prepare(owner, scope)
    content = b"exact original bytes"
    photo = seed(scope, content=content, current="test")
    disk = Storage()
    with organization_scope(scope), Session(engine()) as db:
        from app.disk_folders import current_disk_roots
        current = db.get(Photo, photo.id)
        source = current.yandex_disk_path
        roots = current_disk_roots(db)
        current.cohort = "production"
        destination = storage_path(current, None, {"PRIVATE": ("Работа", "Работа")}, roots)
        current.cohort = "test"
        current.storage_status, current.processing_error = "ERROR", "ORIGINAL_MISSING"
        db.add(Job(kind="SYNC", object_id=photo.id, status="BLOCKED", last_error="ORIGINAL_MISSING",
                   attempts=2, next_run_at=now(), dedupe_key="missing-original"))
        closure = DayClosure(day=photo.photo_date, user_id=scope.owner_user_id, cohort="test", all_chats=True,
                             confirmed_at=now(), photo_count=1)
        db.add(closure)
        db.flush()
        receipt = DayPhotoReview(photo_id=photo.id, closure_id=closure.id)
        from app.day_verification import SNAPSHOT_FIELDS
        for key in SNAPSHOT_FIELDS:
            setattr(receipt, key, getattr(current, key))
        db.add(receipt)
        # This completed initial journal must not redirect a later owner promotion back to test.
        audit(db, None, "STORAGE_TRANSFER_PLANNED", "photo", photo.id, {"path": None},
              {"path": source, "sha256": photo.sha256})
        db.commit()
        db.refresh(current)
        version = current.version
    disk.files[destination if already_at_destination else source] = content
    monkeypatch.setattr("app.processing.YandexDisk", lambda: disk)
    response = owner.post(scope.prefix + f"/api/photos/{photo.id}/promote", json={"version": version})
    assert response.status_code == 200, response.text
    with organization_scope(scope), Session(engine()) as db:
        assert db.get(DayPhotoReview, photo.id) is None
        jobs = list(db.scalars(select(Job).where(Job.kind == "SYNC")))
        assert len(jobs) == 1 and jobs[0].status == "PENDING" and jobs[0].last_error is None
        assert db.get(ExchangeState, 1).intake_cohort == "test"
    with organization_scope(scope):
        sync_photo(photo.id)
    with organization_scope(scope), Session(engine()) as db:
        promoted = db.get(Photo, photo.id)
        assert promoted.yandex_disk_path == destination and promoted.processing_error is None
        assert promoted.storage_status == "SYNCED" and promoted.work_type_source == "AI"
        assert disk.files[destination] == content and source not in disk.files
        assert db.get(DayPhotoReview, photo.id) is None


def test_working_duplicate_is_linked_and_never_promoted_or_overwritten(companies):
    owner, scopes, _ = companies
    scope = scopes[0]
    prepare(owner, scope)
    test = seed(scope, mid="test")
    production = seed(scope, mid="working", cohort="production")
    path = scope.prefix + f"/api/photos/{test.id}"
    assert owner.get(path).json()["production_duplicate_id"] == production.id
    response = owner.post(path + "/promote", json={"version": test.version})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PRODUCTION_DUPLICATE"
    assert response.json()["detail"]["photo_id"] == production.id
    with organization_scope(scope), Session(engine()) as db:
        assert db.get(Photo, test.id).cohort == "test"
        assert db.get(Photo, production.id).yandex_disk_path == production.yandex_disk_path
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "PHOTO_PROMOTED_TO_PRODUCTION")) == 0


def test_invalid_or_removed_images_cannot_be_promoted_and_working_photos_cannot_be_reversed(companies):
    owner, scopes, _ = companies
    scope = scopes[0]
    prepare(owner, scope)
    photo = seed(scope)
    path = scope.prefix + f"/api/photos/{photo.id}/promote"
    for changes, status in [({"analyzed_at": None}, 409), ({"status": "REJECTED"}, 409),
                            ({"preview_removed_at": now()}, 404)]:
        with organization_scope(scope), Session(engine()) as db:
            current = db.get(Photo, photo.id)
            current.analyzed_at, current.status, current.preview_removed_at, current.cohort = now(), "ACCEPTED", None, "test"
            for key, value in changes.items():
                setattr(current, key, value)
            db.commit()
            db.refresh(current)
            version = current.version
        assert owner.post(path, json={"version": version}).status_code == status
    working = seed(scope, mid="working", content=b"different image", cohort="production")
    assert owner.post(scope.prefix + f"/api/photos/{working.id}/promote", json={"version": working.version}).status_code == 409
    assert owner.post(scope.prefix + "/api/photos/99999/promote", json={"version": 1}).status_code == 404


def test_legacy_administrator_is_not_a_platform_owner(db, admin):
    assert not settings().organizations_enabled
    response = admin.post("/api/photos/1/promote", json={"version": 1})
    assert response.status_code == 403


def test_sql_still_rejects_ungranted_cohort_identity_and_receipt_changes(db):
    setup_chat(db)
    photo = intake_photo(db)
    for grant in [None, (photo.id + 1, photo.version), (photo.id, photo.version + 1)]:
        with pytest.raises(DBAPIError, match="explicit owner promotion"), db.begin_nested():
            if grant:
                db.execute(text("SELECT set_config('max_photos.promote_id', :id, true), "
                                "set_config('max_photos.promote_version', :version, true)"),
                           {"id": str(grant[0]), "version": str(grant[1])})
            db.execute(text("UPDATE photos SET cohort='production' WHERE id=:id"), {"id": photo.id})
    for change in ["id=id+1000", "received_at=received_at + interval '1 second'"]:
        with pytest.raises(DBAPIError, match="immutable"), db.begin_nested():
            db.execute(text("UPDATE photos SET " + change + " WHERE id=:id"), {"id": photo.id})
    db.refresh(photo)
    assert photo.cohort == "test"
