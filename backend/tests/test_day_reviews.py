import runpy
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.domain import now
from app.models import Audit, DayClosure, DayPhotoReview, Inbox, Photo, User
from app.permissions import DEFAULT_OPERATOR_PERMISSIONS

DAY = "2026-10-18"
ROOT = "/api/day-reviews/" + DAY


def add_photo(engine, id=70, *, day=date(2026, 10, 18), chat_id=100):
    with AccessSession(engine) as db:
        db.add(Inbox(id=id, max_chat_id=chat_id, message_id=str(id), payload={}))
        db.add(Photo(id=id, inbox_id=id, attachment_index=0, version=1, cohort="production",
                     max_chat_id=chat_id, chat_name="Дополнение", max_message_id=str(id),
                     photo_date=day, received_at=now()+timedelta(days=2),
                     is_spam=False, is_defect=False, status="ACCEPTED", storage_status="SYNCED",
                     latitude=61.1, longitude=72.6, work_type="BIN_EMPTYING", work_type_source="AI",
                     sha256=f"{id:064x}", review_reason=[], analyzed_at=now(), extension=".jpg"))
        db.commit()


def close(client):
    summary = client.get(ROOT).json()
    response = client.post(ROOT + "/close", json={"snapshot": summary["snapshot"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_close_all_accessible_chats_and_append_late_photos_without_rechecking(access_api):
    client, engine = access_api
    actor(client, 4)
    initial = client.get(ROOT).json()
    assert (initial["total"], initial["pending"], initial["confirmed"], initial["can_close"]) == (4, 4, 0, True)
    assert close(client)["confirmed"] == 4
    assert client.get(ROOT).json()["pending"] == 0
    with AccessSession(engine) as db:
        assert {r.photo_id for r in db.scalars(select(DayPhotoReview))} == {10, 20, 50, 60}
        for photo in db.scalars(select(Photo)):
            assert photo.version == 1 and photo.work_type_source == "AI" and photo.reviewed_by is None
        assert len(list(db.scalars(select(Audit).where(Audit.action == "DAY_PHOTO_CONFIRMED")))) == 4
    add_photo(engine)
    summary = client.get(ROOT).json()
    assert summary["closed_before"] and summary["can_close"]
    assert (summary["confirmed"], summary["pending"], summary["new"], summary["changed"]) == (4, 1, 1, 0)
    pending = client.get('/api/photos', params={"review_day": DAY, "day_review": "pending"}).json()
    assert [p["id"] for p in pending["items"]] == [70]
    assert close(client)["confirmed"] == 1
    assert client.get(ROOT).json()["confirmed"] == 5
    report = client.get('/api/reports', params={"review_day": DAY, "day_review": "confirmed"}).json()
    assert report["total"] == 5
    report = client.get('/api/reports', params={"review_day": DAY, "day_review": "confirmed",
                                              "date_from": DAY, "date_to": DAY,
                                              "date_basis": "received", "sort_order": "desc"}).json()
    assert report["total"] == 5


def test_other_chats_and_spam_never_get_confirmed_or_leak_into_counts(access_api):
    client, engine = access_api
    assert close(client)["confirmed"] == 2
    add_photo(engine, chat_id=200)
    assert client.get(ROOT).json()["pending"] == 0
    with AccessSession(engine) as db:
        assert {r.photo_id for r in db.scalars(select(DayPhotoReview))} == {10, 50}
    actor(client, 3)
    summary = client.get(ROOT).json()
    assert summary["total"] == 0 and not summary["closed_before"]
    assert client.post(ROOT+'/close', json={"snapshot": summary["snapshot"]}).status_code == 409
    actor(client, 1)
    assert client.get(ROOT).json()["pending"] == 3


def test_changed_content_returns_to_pending_but_sync_and_label_source_do_not(access_api):
    client, engine = access_api
    close(client)
    with AccessSession(engine) as db:
        p = db.get(Photo, 10)
        p.version += 1
        p.storage_status, p.yandex_disk_path = "SYNCED", "disk:/another/folder/photo.jpg"
        p.work_type_source, p.reviewed_by = "OPERATOR", 2
        db.commit()
    assert client.get(ROOT).json()["pending"] == 0
    with AccessSession(engine) as db:
        db.get(Photo, 10).is_defect = True
        db.commit()
    summary = client.get(ROOT).json()
    assert (summary["confirmed"], summary["pending"], summary["new"], summary["changed"]) == (1, 1, 0, 1)
    assert client.get('/api/photos/50/next', params={"review_day": DAY, "day_review": "pending"}).json() == {"id":10}
    assert close(client)["confirmed"] == 1


def test_only_neural_predictions_need_visual_recheck_manual_results_join_when_closing(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.get(Photo, 50).work_type_source = "OPERATOR"
        db.get(Photo, 50).reviewed_by = 2
        db.commit()
    summary = client.get(ROOT).json()
    assert (summary["ai_pending"], summary["manual_pending"]) == (1, 1)
    filters = {"review_day": DAY, "day_review": "pending", "day_ai_only": True}
    assert [p["id"] for p in client.get('/api/photos', params=filters).json()["items"]] == [10]
    assert client.get('/api/photos/10/next', params=filters).json() == {"id": None}
    assert close(client)["confirmed"] == 2
    assert client.get('/api/photos', params=filters).json()["total"] == 0
    add_photo(engine)
    with AccessSession(engine) as db:
        db.get(Photo, 70).work_type_source = "OPERATOR"
        db.commit()
    summary = client.get(ROOT).json()
    assert (summary["ai_pending"], summary["manual_pending"], summary["can_close"]) == (0, 1, True)
    assert close(client)["confirmed"] == 1


@pytest.mark.parametrize("field,value", [("work_type", "SWEEPING"), ("district_id", 99),
                                          ("latitude", 61.2), ("photo_date", date(2026,10,17))])
def test_snapshot_rejects_content_changes_before_confirmation(access_api, field, value):
    client, engine = access_api
    token = client.get(ROOT).json()["snapshot"]
    with AccessSession(engine) as db:
        setattr(db.get(Photo, 10), field, value)
        db.commit()
    response = client.post(ROOT+'/close', json={"snapshot": token})
    assert response.status_code == 409
    with AccessSession(engine) as db:
        assert not list(db.scalars(select(DayClosure)))


def test_new_arrival_and_overlapping_operator_confirmation_invalidate_snapshot(access_api):
    client, engine = access_api
    token = client.get(ROOT).json()["snapshot"]
    add_photo(engine)
    assert client.post(ROOT+'/close', json={"snapshot": token}).status_code == 409
    token = client.get(ROOT).json()["snapshot"]
    actor(client, 4)
    close(client)
    actor(client, 2)
    assert client.post(ROOT+'/close', json={"snapshot": token}).status_code == 409


def test_unresolved_photos_block_close_and_fail_without_partial_confirmation(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.get(Photo, 10).status = "NEEDS_REVIEW"
        db.commit()
    summary = client.get(ROOT).json()
    assert summary["blocked"] == 1 and not summary["can_close"]
    assert client.post(ROOT+'/close', json={"snapshot": summary["snapshot"]}).status_code == 409
    with AccessSession(engine) as db:
        assert not list(db.scalars(select(DayPhotoReview)))
        db.get(Photo, 10).status = "ACCEPTED"
        db.commit()
    assert close(client)["confirmed"] == 2


def test_photo_date_has_priority_over_received_date_and_unknown_dates_are_not_included(access_api):
    client, engine = access_api
    add_photo(engine, day=date(2026,10,17))
    add_photo(engine, id=71, day=None)
    assert client.get(ROOT).json()["total"] == 2
    assert client.get('/api/photos', params={"review_day": DAY, "date_basis": "received"}).json()["total"] == 2


def test_permission_is_opt_in_and_direct_filters_and_closure_require_it(access_api):
    client, engine = access_api
    assert "days_review" not in DEFAULT_OPERATOR_PERMISSIONS
    with AccessSession(engine) as db:
        db.get(User, 2).permissions = ["photos_view", "photos_edit", "reports_view", "reports_export"]
        db.commit()
    assert client.get(ROOT).status_code == 403
    assert client.post(ROOT+'/close', json={"snapshot": "0"*64}).status_code == 403
    for path in ['/api/photos', '/api/reports', '/api/photos/filter-counts', '/api/photos/map',
                 '/api/photos/10/next', '/api/export.xlsx']:
        assert client.get(path, params={"day_review": "confirmed"}).status_code == 403
    actor(client, 1)
    assert client.get(ROOT).status_code == 200


def test_scope_and_csrf_cannot_be_overridden_and_stale_scope_cannot_close(access_api):
    client, engine = access_api
    token = client.get(ROOT).json()["snapshot"]
    assert client.post(ROOT+'/close', json={"snapshot": token,"chat_id":200}).status_code == 422
    with AccessSession(engine) as db:
        db.get(User, 2).allowed_chat_ids = [2]
        db.commit()
    assert client.post(ROOT+'/close', json={"snapshot": token}).status_code == 409
    token = client.get(ROOT).json()["snapshot"]
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post(ROOT+'/close', json={"snapshot": token}).status_code == 403


def test_migration_adds_empty_review_tables_without_touching_existing_photos(access_api):
    _, engine = access_api
    with engine.begin() as connection:
        DayPhotoReview.__table__.drop(connection)
        DayClosure.__table__.drop(connection)
        before = connection.execute(select(Photo.__table__)).all()
        migration = runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0028_day_reviews.py'))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        assert connection.execute(select(Photo.__table__)).all() == before
        assert {'day_photo_reviews', 'day_closures'} <= set(inspect(connection).get_table_names())
        assert not connection.execute(select(DayPhotoReview)).all()


def test_postgres_close_and_filters_share_confirmations(admin, db):
    from tests.test_integration import intake_photo, setup_chat
    setup_chat(db)
    photo = intake_photo(db)
    photo.photo_date, photo.work_type, photo.status, photo.analyzed_at = date(2026,10,18), 'BIN_EMPTYING', 'ACCEPTED', now()
    db.commit()
    close(admin)
    result = admin.get('/api/photos', params={"review_day": DAY, "day_review": "confirmed"})
    assert result.status_code == 200 and result.json()["total"] == 1
