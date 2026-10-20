import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    JSON,
    Column,
    DefaultClause,
    Integer,
    MetaData,
    Table,
    create_engine,
    event,
    func,
    select,
    text,
)
from sqlalchemy.orm import Session, attributes
from sqlalchemy.pool import StaticPool

from app.auth import digest
from app.auth import router as auth_router
from app.db import get_db
from app.domain import now
from app.models import LoginSession, OperatorMessage, User
from app.operator_chats import router


class ChatTestSession(Session):
    def get(self, entity, ident, **kwargs):
        result = super().get(entity, ident, **kwargs)
        if isinstance(result, LoginSession):
            for key in ("expires_at", "last_seen_at", "created_at"):
                value = getattr(result, key)
                if value and value.tzinfo is None:
                    attributes.set_committed_value(result, key, value.replace(tzinfo=UTC))
        return result


def chat_test_engine(url="sqlite://"):
    """Exercise real ORM queries without a local PostGIS installation."""
    options = {"poolclass": StaticPool} if url == "sqlite://" else {}
    engine = create_engine(url, connect_args={"check_same_thread": False}, **options)

    @event.listens_for(engine, "connect")
    def functions(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function("jsonb_typeof", 1, lambda value: "array" if isinstance(json.loads(value), list) else "object")
        connection.create_function("pg_advisory_xact_lock", 1, lambda _key: 0)

    metadata = MetaData()
    users = User.__table__.to_metadata(metadata)
    users.c.permissions.type = JSON()
    users.c.allowed_chat_ids.type = JSON(none_as_null=True)
    users.c.sidebar_order.type = JSON()
    users.c.permissions.server_default = DefaultClause(text("'[]'"))
    users.c.sidebar_order.server_default = DefaultClause(text("'[]'"))
    sessions = LoginSession.__table__.to_metadata(metadata)
    sessions.c.id.server_default = None
    Table("photos", metadata, Column("id", Integer, primary_key=True))
    OperatorMessage.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    return engine


def seed_users(engine):
    with ChatTestSession(engine) as db:
        for user_id, name, role, active in [
            (1, "Анна", "OPERATOR", True), (2, "Борис", "ADMIN_OPERATOR", True),
            (3, "Вера", "OPERATOR", True), (4, "Глеб", "OPERATOR", False),
        ]:
            db.add(User(id=user_id, login=f"user{user_id}", name=name, role=role, active=active, permissions=[], password_hash="unused"))
        db.flush()
        for user_id in range(1, 5):
            db.add(LoginSession(
                id=str(uuid4()), token_hash=digest(f"user{user_id}"), csrf_hash=digest("chat-csrf"),
                user_id=user_id, expires_at=now() + timedelta(hours=1), last_seen_at=now(),
            ))
        db.commit()


@pytest.fixture
def chat_api():
    engine = chat_test_engine()
    seed_users(engine)
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(router)

    def database():
        with ChatTestSession(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        actor(client, 1)
        yield client, engine
    engine.dispose()


def actor(client, user_id):
    client.cookies.clear()
    client.cookies.set("session", f"user{user_id}")
    client.headers["X-CSRF-Token"] = "chat-csrf"


def send(client, peer_id=2, body="Привет!", client_id=None):
    return client.post(f"/api/operator-chats/{peer_id}/messages", json={"body": body, "client_id": client_id or str(uuid4())})


def test_operator_without_work_permissions_can_find_colleagues_and_send(chat_api):
    client, engine = chat_api
    contacts = client.get("/api/operator-chats").json()
    assert {peer["id"] for peer in contacts["items"]} == {2, 3}
    assert contacts["unread"] == 0
    assert all("login" not in peer and "permissions" not in peer for peer in contacts["items"])
    response = send(client, body="  Первая строка\nВторая строка  ")
    assert response.status_code == 201, response.text
    message = response.json()
    assert message["sender_id"] == 1 and message["recipient_id"] == 2
    assert message["body"] == "Первая строка\nВторая строка"
    assert datetime.fromisoformat(message["created_at"]).utcoffset() == timedelta(0)
    with ChatTestSession(engine) as db:
        assert db.get(OperatorMessage, message["id"]).body == message["body"]
    assert client.get("/api/operator-chats").json()["items"][0]["last_message"]["id"] == message["id"]


def test_read_receipts_and_unread_counts_belong_only_to_participants(chat_api):
    client, _engine = chat_api
    message = send(client).json()
    actor(client, 2)
    assert client.get("/api/operator-chats/unread").json() == {"unread": 1}
    assert client.get("/api/operator-chats").json()["items"][0]["unread"] == 1
    actor(client, 3)
    assert client.get("/api/operator-chats/1/messages").json()["items"] == []
    assert client.get("/api/operator-chats/2/messages").json()["items"] == []
    assert all(peer["last_message"] is None for peer in client.get("/api/operator-chats").json()["items"])
    assert client.post("/api/operator-chats/1/read", json={"through_id": message["id"]}).status_code == 404
    actor(client, 2)
    assert client.post("/api/operator-chats/1/read", json={"through_id": message["id"]}).status_code == 200
    assert client.get("/api/operator-chats/unread").json() == {"unread": 0}
    actor(client, 1)
    page = client.get("/api/operator-chats/2/messages").json()
    assert page["peer_read_through_id"] == message["id"]
    assert page["items"][0]["read_at"]


def test_retries_do_not_duplicate_messages_or_reuse_ids_for_another_body(chat_api):
    client, engine = chat_api
    key = str(uuid4())
    first, retry = send(client, client_id=key), send(client, client_id=key)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert send(client, body="Изменённый текст", client_id=key).status_code == 409
    assert send(client, peer_id=3, client_id=key).status_code == 409
    with ChatTestSession(engine) as db:
        assert db.scalar(select(func.count()).select_from(OperatorMessage)) == 1


def test_history_paginates_in_both_directions_without_other_conversations(chat_api):
    client, engine = chat_api
    with ChatTestSession(engine) as db:
        for index in range(123):
            db.add(OperatorMessage(sender_id=1 if index % 2 else 2, recipient_id=2 if index % 2 else 1,
                                   client_id=str(uuid4()), body=f"Сообщение {index}"))
        db.add(OperatorMessage(sender_id=2, recipient_id=3, client_id=str(uuid4()), body="Чужая переписка"))
        db.commit()
    first = client.get("/api/operator-chats/2/messages").json()
    assert [message["id"] for message in first["items"]] == list(range(74, 124))
    assert first["has_older"] and not first["has_newer"]
    older = client.get("/api/operator-chats/2/messages?before_id=74").json()
    oldest = client.get("/api/operator-chats/2/messages?before_id=24").json()
    assert [message["id"] for message in older["items"]] == list(range(24, 74))
    assert [message["id"] for message in oldest["items"]] == list(range(1, 24))
    assert not oldest["has_older"]
    newer = client.get("/api/operator-chats/2/messages?after_id=0&limit=100").json()
    assert newer["has_newer"] and len(newer["items"]) == 100
    rest = client.get("/api/operator-chats/2/messages?after_id=100&limit=100").json()
    assert [message["id"] for message in rest["items"]] == list(range(101, 124))
    assert not rest["has_newer"]


def test_mark_read_does_not_acknowledge_messages_after_the_displayed_cursor(chat_api):
    client, _engine = chat_api
    actor(client, 2)
    incoming = [send(client, 1).json() for _ in range(3)]
    actor(client, 1)
    result = client.post("/api/operator-chats/2/read", json={"through_id": incoming[1]["id"]})
    assert result.status_code == 200
    assert client.get("/api/operator-chats/unread").json() == {"unread": 1}
    page = client.get("/api/operator-chats/2/messages").json()["items"]
    assert page[0]["read_at"] and page[1]["read_at"] and page[2]["read_at"] is None
    client.post("/api/operator-chats/2/read", json={"through_id": incoming[1]["id"]})
    assert client.get("/api/operator-chats/2/messages").json()["items"][0]["read_at"] == page[0]["read_at"]


def test_disabled_colleague_keeps_history_but_cannot_receive_new_messages(chat_api):
    client, engine = chat_api
    send(client)
    with ChatTestSession(engine) as db:
        db.get(User, 2).active = False
        db.commit()
    contacts = client.get("/api/operator-chats").json()["items"]
    assert contacts[0]["id"] == 2 and not contacts[0]["active"]
    assert len(client.get("/api/operator-chats/2/messages").json()["items"]) == 1
    assert send(client).status_code == 409
    assert client.get("/api/operator-chats/4/messages").status_code == 404
    actor(client, 2)
    assert client.get("/api/operator-chats").status_code == 401


@pytest.mark.parametrize("payload", [
    {"body": ""}, {"body": " \n "}, {"body": "x" * 4001}, {"body": "Hi", "client_id": "invalid"},
    {"body": "Hi", "sender_id": 3},
])
def test_invalid_messages_and_forged_senders_are_rejected(chat_api, payload):
    client, _engine = chat_api
    response = client.post("/api/operator-chats/2/messages", json={"client_id": str(uuid4()), **payload})
    assert response.status_code == 422
    assert client.get("/api/operator-chats/2/messages").json()["items"] == []


def test_chat_requires_authentication_csrf_and_same_origin(chat_api):
    client, _engine = chat_api
    client.headers.pop("X-CSRF-Token")
    assert send(client).status_code == 403
    assert client.post("/api/operator-chats/2/read", json={"through_id": 1}).status_code == 403
    client.headers["X-CSRF-Token"] = "chat-csrf"
    assert client.post("/api/operator-chats/2/messages", json={"body": "Hi", "client_id": str(uuid4())}, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    client.cookies.clear()
    for path in ("", "/unread", "/2/messages", "/avatars/2"):
        assert client.get("/api/operator-chats" + path).status_code == 401
    assert send(client).status_code == 401


def test_contact_avatars_are_authenticated_and_do_not_expose_disabled_accounts(chat_api):
    client, engine = chat_api
    with ChatTestSession(engine) as db:
        db.get(User, 2).avatar_image = b"normalized-jpeg"
        db.get(User, 4).avatar_image = b"inactive-avatar"
        db.commit()
    url = next(peer for peer in client.get("/api/operator-chats").json()["items"] if peer["id"] == 2)["avatar_url"]
    assert client.get(url).content == b"normalized-jpeg"
    assert client.get("/api/auth/avatar/2").status_code == 404
    assert client.get("/api/operator-chats/avatars/4").status_code == 404


def test_self_unknown_peers_and_invalid_cursors_are_rejected(chat_api):
    client, _engine = chat_api
    assert send(client, 1).status_code == 422
    assert send(client, 999).status_code == 404
    for query in ("before_id=0", "after_id=-1", "limit=101", "limit=0", "before_id=1&after_id=1"):
        assert client.get("/api/operator-chats/2/messages?" + query).status_code == 422


@pytest.mark.integration
def test_postgres_chat_persists_a_message(admin, db):
    peer = db.scalar(select(User).where(User.login == "operator"))
    response = send(admin, peer.id)
    assert response.status_code == 201
    assert db.get(OperatorMessage, response.json()["id"]).recipient_id == peer.id
