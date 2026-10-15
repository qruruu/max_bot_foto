"""Unknown MAX chats are visible to admins without enabling photo intake implicitly."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_integration import event, setup_chat
from test_receiver import MaxPage, configure

from app.db import engine
from app.domain import now
from app.intake import ingest
from app.models import Audit, Chat, DiscoveredChat, Inbox, Job, MaxReceiverState, Photo
from app.receiver import poll_once

pytestmark = pytest.mark.integration
SECRET = {"x-max-bot-api-secret": "test-secret-" * 4}


def message(chat_id=-987654321, text="Проверка нового чата", instant=None):
    update = event(chat_id=chat_id, attachments=[])
    update["message"]["recipient"]["chat_type"] = "chat"
    update["message"]["body"]["text"] = text
    update["timestamp"] = int((instant or now()).timestamp() * 1000)
    return update


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_plain_message_through_webhook_discovers_chat_without_processing_it(db, admin, monkeypatch):
    monkeypatch.setenv("MAX_UPDATE_MODE", "webhook")
    update = message()
    assert admin.post("/api/webhooks/max", json=update, headers=SECRET).status_code == 200
    rows = admin.get("/api/chats/discovered").json()
    assert len(rows) == 1
    assert rows[0]["max_chat_id"] == "-987654321"
    assert rows[0]["message_preview"] == "Проверка нового чата"
    assert rows[0]["first_seen_at"] and rows[0]["last_seen_at"]
    assert all(count(db, model) == 0 for model in (Chat, Inbox, Photo, Job))
    db.expire_all()
    state = db.get(MaxReceiverState, 1)
    assert state.events_received == 1 and state.inbox_received == 0 and state.marker is None


def test_repeated_and_out_of_order_events_leave_one_chat_and_latest_message(db, admin):
    instant = now()
    recent = message(text="Последнее сообщение", instant=instant)
    older = message(text="Старое сообщение", instant=instant - timedelta(hours=1))
    for update in (recent, recent, older):
        assert admin.post("/api/webhooks/max", json=update, headers=SECRET).status_code == 200
    assert count(db, DiscoveredChat) == 1
    assert admin.get("/api/chats/discovered").json()[0]["message_preview"] == "Последнее сообщение"


def test_add_discovered_chat_prefills_exact_id_then_only_new_photos_enter_pipeline(db, admin):
    chat_id = -9007199254740993  # outside JavaScript's exact Number range
    unknown_photo = event("before-add", chat_id=chat_id)
    assert admin.post("/api/webhooks/max", json=unknown_photo, headers=SECRET).status_code == 200
    discovered = admin.get("/api/chats/discovered").json()[0]
    assert discovered["max_chat_id"] == str(chat_id)
    assert discovered["message_preview"] == "Сообщение с вложением"
    result = admin.post(
        "/api/chats",
        json={
            "max_chat_id": discovered["max_chat_id"],
            "name": "Новый чат",
            "cv_work_type_enabled": False,
            "fixed_work_type_code": "BIN_EMPTYING",
        },
    )
    assert result.status_code == 201
    assert admin.get("/api/chats/discovered").json() == []
    configured = admin.get("/api/chats").json()[0]
    assert configured["max_chat_id"] == str(chat_id)
    assert admin.get("/api/meta").json()["chats"][0]["max_chat_id"] == str(chat_id)
    assert (
        admin.put(
            f"/api/chats/{configured['id']}",
            json={
                "max_chat_id": configured["max_chat_id"],
                "name": "Новое название",
            },
        ).status_code
        == 200
    )
    assert count(db, Photo) == 0
    assert (
        admin.post("/api/webhooks/max", json=event("after-add", chat_id=chat_id), headers=SECRET).status_code
        == 200
    )
    db.expire_all()
    photo = db.scalar(select(Photo))
    assert photo.max_chat_id == chat_id and photo.max_message_id == "after-add"
    assert photo.classification_mode == "CHAT_FIXED" and photo.fixed_work_type_snapshot == "BIN_EMPTYING"
    assert count(db, Photo) == count(db, Inbox) == 1
    assert db.scalar(select(Job).where(Job.kind == "BATCH")) is not None
    assert db.scalar(select(Audit).where(Audit.action == "CHAT_CREATED")) is not None


@pytest.mark.parametrize("active", [True, False])
def test_configured_or_disabled_chats_are_not_rediscovered(db, admin, active):
    chat = setup_chat(db)
    chat.active = active
    db.commit()
    assert admin.post("/api/webhooks/max", json=message(chat_id=123), headers=SECRET).status_code == 200
    assert count(db, DiscoveredChat) == count(db, Photo) == 0
    assert admin.get("/api/chats/discovered").json() == []


def test_discovery_requires_valid_webhook_secret(db, client):
    for headers in ({}, {"x-max-bot-api-secret": "incorrect"}):
        assert client.post("/api/webhooks/max", json=message(), headers=headers).status_code == 403
    assert count(db, DiscoveredChat) == 0


def test_only_admin_can_read_discovered_ids_and_previews(db, client, users):
    assert client.get("/api/chats/discovered").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"login": "operator", "password": "test-password-123"}
        ).status_code
        == 200
    )
    assert client.get("/api/chats/discovered").status_code == 403


@pytest.mark.parametrize("chat_id", [True, "-123", None, 2**63, -(2**63) - 1])
def test_invalid_chat_ids_are_not_stored(db, client, chat_id):
    assert client.post("/api/webhooks/max", json=message(chat_id=chat_id), headers=SECRET).status_code == 200
    assert count(db, DiscoveredChat) == 0


def test_bot_messages_and_direct_dialogs_do_not_populate_group_discovery(db, client):
    bot_message = message()
    bot_message["message"]["sender"]["is_bot"] = True
    direct = message(chat_id=999)
    direct["message"]["recipient"]["chat_type"] = "dialog"
    for update in (bot_message, direct):
        assert client.post("/api/webhooks/max", json=update, headers=SECRET).status_code == 200
    assert count(db, DiscoveredChat) == 0


def test_preview_is_bounded_and_no_attachments_or_payload_are_retained(db, admin):
    update = message(text="  Первая\n  строка\t" + "я" * 250)
    update["message"]["body"]["attachments"] = [
        {"type": "image", "payload": {"url": "https://private.invalid/image"}}
    ]
    assert admin.post("/api/webhooks/max", json=update, headers=SECRET).status_code == 200
    row = admin.get("/api/chats/discovered").json()[0]
    assert row["message_preview"].startswith("Первая строка ") and len(row["message_preview"]) == 200
    assert "private.invalid" not in str(row)
    assert count(db, Inbox) == count(db, Photo) == count(db, Job) == 0


def test_polling_discovers_in_same_transaction_as_checkpoint(db, monkeypatch):
    configure(monkeypatch)
    assert poll_once(MaxPage([message()], marker=500))
    db.expire_all()
    assert count(db, DiscoveredChat) == 1
    assert db.get(MaxReceiverState, 1).marker == 500
    assert count(db, Photo) == 0


def test_failed_poll_page_rolls_back_discovery_and_checkpoint(db, monkeypatch):
    configure(monkeypatch)
    setup_chat(db)
    assert poll_once(MaxPage([], marker=100))
    bad = event()
    bad["message"]["body"]["attachments"] = [None]
    assert not poll_once(MaxPage([message(), bad], marker=200))
    db.expire_all()
    assert db.get(MaxReceiverState, 1).marker == 100 and count(db, DiscoveredChat) == 0


def test_concurrent_first_messages_upsert_one_discovered_chat(db):
    def accept(n):
        with Session(engine()) as session:
            ingest(session, message(text=f"Сообщение {n}"))
            session.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(accept, range(8)))
    assert count(db, DiscoveredChat) == 1


def test_discovered_list_is_bounded_and_excludes_manually_configured_ids(db, admin):
    for index in range(105):
        ingest(db, message(chat_id=-1000 - index))
    db.commit()
    db.add(Chat(max_chat_id=-1104, name="Добавлен вручную", active=False))
    db.commit()
    rows = admin.get("/api/chats/discovered").json()
    assert len(rows) == 100 and rows[0]["max_chat_id"] == "-1103"
    assert "-1104" not in {row["max_chat_id"] for row in rows}
