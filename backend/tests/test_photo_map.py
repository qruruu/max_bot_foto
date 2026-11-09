from datetime import date, datetime, timezone

from sqlalchemy import select

from app.domain import now
from app.media import media_path
from app.models import Chat, Inbox, Photo, User


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
        max_chat_id=inbox.max_chat_id,
        chat_name="Map test",
        **fields,
    )
    db.add(row)
    db.flush()
    return row


def inbox(db, chat_id=123, message_id="map-test"):
    row = Inbox(max_chat_id=chat_id, message_id=message_id, payload={})
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


def test_operator_can_load_previews_only_for_map_points_in_allowed_chats(client, users, db):
    chat = Chat(max_chat_id=123, name="Allowed chat")
    db.add(chat)
    db.flush()
    operator = db.scalar(select(User).where(User.login == "operator"))
    operator.allowed_chat_ids = [chat.id]
    message = inbox(db)
    visible = photo(db, message, 0, sha256="a" * 64)
    hidden = photo(db, inbox(db, 456, "private-map-test"), 0, sha256="b" * 64)
    db.commit()
    media_path(visible.id, preview=True).write_bytes(b"allowed preview")
    media_path(hidden.id, preview=True).write_bytes(b"private preview")

    assert client.post("/api/auth/login", json={"login": "operator", "password": "test-password-123"}).status_code == 200
    result = client.get("/api/photos/map")
    assert result.status_code == 200
    points = result.json()["items"]
    assert [point["id"] for point in points] == [visible.id]
    preview = client.get(points[0]["preview_url"])
    assert preview.headers["content-type"] == "image/jpeg"
    assert preview.content == b"allowed preview"
    assert client.get(f"/api/photos/{hidden.id}/preview").status_code == 404


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


def test_viewport_limits_results_and_filters_before_paginating(admin, db):
    message = inbox(db)
    photo(db, message, 0, longitude=73)
    photo(db, message, 1, longitude=None, latitude=None)
    inside = [photo(db, message, i).id for i in range(2, 126)]
    photo(db, message, 126, photo_date=date(2026, 10, 15))
    db.commit()

    params = {"bounds": "72.5,61,72.7,61.2", "date_from": "2026-10-16"}
    first = admin.get("/api/photos/map", params=params)
    assert first.status_code == 200
    first_page = first.json()
    assert first_page["summary"] is None
    assert [p["id"] for p in first_page["items"]] == inside[:120]
    second = admin.get("/api/photos/map", params={**params, "after_id": first_page["next_after_id"]}).json()
    assert [p["id"] for p in second["items"]] == inside[120:]
    assert second["next_after_id"] is None
    assert admin.get("/api/photos/map", params={"bounds": "72.5,NaN,72.7,61.2"}).status_code == 422


def test_viewport_handles_the_date_line(admin, db):
    message = inbox(db)
    visible = [photo(db, message, i, longitude=lng).id for i, lng in enumerate((179.5, -179.5))]
    photo(db, message, 2, longitude=0)
    db.commit()
    response = admin.get("/api/photos/map", params={"bounds": "179,61,-179,62"})
    assert [p["id"] for p in response.json()["items"]] == visible


def test_map_and_filter_counts_degrade_without_blocking_regular_requests(admin, db):
    from sqlalchemy import text

    db.execute(text("SELECT pg_advisory_xact_lock(7041, 1), pg_advisory_xact_lock(7041, 2)"))
    try:
        for path in ("/api/photos/map?bounds=72,61,73,62", "/api/photos/map-filter-counts"):
            response = admin.get(path)
            assert response.status_code == 503
            assert response.headers["retry-after"] == "2"
        assert admin.get("/api/health").status_code == 200
        assert admin.get("/api/photos").status_code == 200
    finally:
        db.rollback()
    assert admin.get("/api/photos/map?bounds=72,61,73,62").status_code == 200
