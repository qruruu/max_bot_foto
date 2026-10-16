from datetime import date, datetime, timezone

from sqlalchemy import select

from app.domain import now
from app.models import Inbox, Photo, User


def photo(db, inbox, i, **values):
    fields = dict(
        latitude=61.1,
        longitude=72.6,
        photo_date=date(2026, 10, 16),
        received_at=datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc),
        status="ACCEPTED",
        work_type="BIN_EMPTYING",
    )
    fields.update(values)
    row = Photo(
        inbox_id=inbox.id,
        attachment_index=i,
        max_message_id=inbox.message_id,
        max_chat_id=123,
        chat_name="Map test",
        **fields,
    )
    db.add(row)
    db.flush()
    return row


def inbox(db):
    row = Inbox(max_chat_id=123, message_id="map-test", payload={})
    db.add(row)
    db.flush()
    return row


def test_map_requires_photo_permission_and_separate_spam_permission(client, users, db):
    assert client.get("/api/photos/map").status_code == 401
    operator = db.scalar(select(User).where(User.login == "operator"))
    operator.permissions = ["reports_view"]
    db.commit()
    client.post("/api/auth/login", json={"login": "operator", "password": "test-password-123"})
    assert client.get("/api/photos/map").status_code == 403
    operator.permissions = ["photos_view"]
    db.commit()
    assert client.get("/api/photos/map").status_code == 200
    assert client.get("/api/photos/map?status=SPAM").status_code == 403


def test_map_omits_missing_coordinates_and_private_metadata(admin, db):
    message = inbox(db)
    good = photo(db, message, 0, latitude=0, longitude=0, sha256="a" * 64)
    for i in range(1, 6):
        photo(db, message, i, latitude=None, longitude=None)
    photo(db, message, 6, is_spam=True, status="SPAM")
    photo(db, message, 7, preview_removed_at=now())
    db.commit()
    response = admin.get("/api/photos/map")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["summary"] == dict(total=6, located=1, without_coordinates=5)
    assert [p["id"] for p in data["items"]] == [good.id]
    assert data["items"][0]["latitude"] == data["items"][0]["longitude"] == 0
    assert data["items"][0]["preview_url"] == f"/api/photos/{good.id}/preview"
    assert set(data["items"][0]) == {
        "id",
        "latitude",
        "longitude",
        "photo_date",
        "photo_time",
        "received_at",
        "chat_name",
        "status",
        "work_type_name",
        "preview_url",
    }
    assert admin.get("/api/photos/map?status=SPAM").json()["summary"]["total"] == 1


def test_map_uses_same_date_chat_work_status_district_filters_as_archive(admin, db):
    message = inbox(db)
    photo(db, message, 0, photo_date=date(2025, 11, 10))
    photo(db, message, 1, photo_date=None)
    photo(db, message, 2, status="NEEDS_REVIEW", work_type=None)
    db.commit()
    selections = [
        "date_from=2026-10-16&date_to=2026-10-16",
        "date_from=2026-10-16&date_to=2026-10-16&date_basis=received",
        "chat_id=999",
        "chat_id=123&work_type=BIN_EMPTYING",
        "status=NEEDS_REVIEW&district_id=0&operator_id=0&work_type=NONE",
        "accepted_only=true",
        "day=2025-11-10",
    ]
    for params in selections:
        mapped = admin.get("/api/photos/map?" + params).json()
        listed = admin.get("/api/photos?" + params).json()
        assert mapped["summary"]["total"] == listed["total"]
        assert {p["id"] for p in mapped["items"]} == {p["id"] for p in listed["items"]}
    assert admin.get("/api/photos/map?date_from=2026-10-17&date_to=2026-10-16").status_code == 422
    assert admin.get("/api/photos/map?after_id=-1").status_code == 422


def test_map_loads_all_batches_preserves_coincident_photos_and_bounds_new_arrivals(admin, db):
    message = inbox(db)
    rows = [photo(db, message, i) for i in range(1005)]
    db.commit()
    first = admin.get("/api/photos/map?page_size=1").json()
    assert len(first["items"]) == 1000
    assert first["summary"]["located"] == 1005
    extra = photo(db, message, 1005)
    db.commit()
    second = admin.get(
        "/api/photos/map",
        params={
            "after_id": first["next_after_id"],
            "snapshot_id": first["snapshot_id"],
        },
    ).json()
    assert second["summary"] is None
    assert second["next_after_id"] is None
    assert [p["id"] for p in first["items"] + second["items"]] == [p.id for p in rows]
    assert admin.get("/api/photos/map").json()["snapshot_id"] == extra.id


def test_map_empty_result(admin):
    assert admin.get("/api/photos/map").json() == dict(
        items=[],
        summary=dict(total=0, located=0, without_coordinates=0),
        snapshot_id=0,
        next_after_id=None,
    )
