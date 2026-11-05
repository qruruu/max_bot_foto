import json
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
from fastapi.testclient import TestClient

from app import local_assistant
from app.api import app
from app.auth import current_user
from app.catalog import Role
from app.config import settings
from app.db import get_db
from app.models import User


def test_assistant_rejects_operators_before_calling_model(monkeypatch):
    classify = Mock()
    db = Mock()
    monkeypatch.setattr(local_assistant, "classify_question", classify)
    monkeypatch.setenv("LOCAL_ASSISTANT_URL", "http://model:8080")
    settings.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: User(role=Role.OPERATOR))

    with TestClient(app) as client:
        response = client.post("/api/local-assistant/question", json={"question": "Сколько фото сегодня?"})

    assert response.status_code == 403
    classify.assert_not_called()
    db.scalar.assert_not_called()


def test_admin_question_uses_local_model_and_counts_by_local_receipt_date(monkeypatch):
    db = Mock()
    db.scalar.return_value = 7
    monkeypatch.setenv("LOCAL_ASSISTANT_URL", "http://model:8080")
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Yekaterinburg")
    settings.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: User(role=Role.ADMIN_OPERATOR))
    monkeypatch.setattr(local_assistant, "now", lambda: datetime(2026, 11, 4, 21, tzinfo=UTC))

    def complete(request):
        assert request.url == "http://model:8080/v1/chat/completions"
        assert json.loads(request.content)["messages"][-1]["content"] == "Сколько снимков пришло вчера?"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"period":"yesterday"}'}}]})

    http_client = httpx.Client
    with TestClient(app) as client:
        monkeypatch.setattr(local_assistant.httpx, "Client", lambda **kwargs: http_client(
            transport=httpx.MockTransport(complete), **kwargs,
        ))
        response = client.post("/api/local-assistant/question", json={"question": " Сколько снимков пришло вчера? "})

    assert response.status_code == 200
    assert response.json()["answer"] == "Поступило фото за 04.11.2026: 7 (без спама, по доступным вам чатам)."
    statement = db.scalar.call_args.args[0]
    assert "photos.received_at" in str(statement)
    assert "photos.is_spam" in str(statement)
