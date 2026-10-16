from datetime import timedelta

from sqlalchemy import select

from app.domain import now
from app.models import Inbox, Photo, User


def add_photo(db, inbox, index, **values):
    photo = Photo(
        inbox_id=inbox.id,
        attachment_index=index,
        max_chat_id=123,
        chat_name="Notification test",
        max_message_id=inbox.message_id,
        **values,
    )
    db.add(photo)
    db.flush()
    return photo


def test_arrivals_require_login_and_photo_permission(client, users, db):
    assert client.get("/api/photos/arrivals").status_code == 401
    operator = db.scalar(select(User).where(User.login == "operator"))
    operator.permissions = ["reports_view"]
    db.commit()
    assert (
        client.post(
            "/api/auth/login", json={"login": "operator", "password": "test-password-123"}
        ).status_code
        == 200
    )
    assert client.get("/api/photos/arrivals").status_code == 403
    operator.permissions = ["photos_view"]
    db.commit()
    assert client.get("/api/photos/arrivals").status_code == 200


def test_arrival_snapshot_contains_recent_photos_only_and_no_private_metadata(admin, db):
    inbox = Inbox(max_chat_id=123, message_id="notification-test", payload={})
    db.add(inbox)
    db.flush()
    visible = [
        add_photo(db, inbox, i, status=status)
        for i, status in enumerate(
            ["RECEIVED", "PROCESSING", "NEEDS_REVIEW", "ACCEPTED", "DUPLICATE", "ERROR"]
        )
    ]
    add_photo(db, inbox, 10, received_at=now() - timedelta(days=2))
    add_photo(db, inbox, 11, status="SPAM", is_spam=True)
    add_photo(db, inbox, 12, preview_removed_at=now())
    add_photo(db, inbox, 13, status="FORWARDED", is_forwarded=True)
    add_photo(db, inbox, 14, status="REJECTED")
    db.commit()
    response = admin.get("/api/photos/arrivals")
    assert response.status_code == 200
    assert response.json() == {"photo_ids": [p.id for p in visible]}
    assert response.headers["cache-control"] == "no-store"
    visible[0].status = "NEEDS_REVIEW"
    visible[0].detected_address = "Operator correction"
    db.commit()
    assert admin.get("/api/photos/arrivals").json() == response.json()


def test_batch_of_500_photos_is_not_truncated(admin, db):
    inbox = Inbox(max_chat_id=123, message_id="notification-batch", payload={})
    db.add(inbox)
    db.flush()
    photos = [add_photo(db, inbox, i) for i in range(500)]
    db.commit()
    assert admin.get("/api/photos/arrivals").json() == {"photo_ids": [p.id for p in photos]}


def test_arrivals_include_a_late_committed_lower_id(admin, db):
    from sqlalchemy.orm import Session

    from app.db import engine

    inbox = Inbox(max_chat_id=123, message_id="notification-concurrency", payload={})
    db.add(inbox)
    db.commit()
    with Session(engine()) as late:
        older_id = add_photo(late, inbox, 0).id
        newer = add_photo(db, inbox, 1)
        db.commit()
        assert admin.get("/api/photos/arrivals").json() == {"photo_ids": [newer.id]}
        late.commit()
        assert admin.get("/api/photos/arrivals").json() == {"photo_ids": [older_id, newer.id]}
