import json
from datetime import UTC, date, datetime
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import local_assistant
from app.api import app
from app.auth import current_user
from app.catalog import Role
from app.config import settings
from app.db import get_db
from app.models import User


@pytest.fixture
def assistant_db(monkeypatch):
    db = Mock()
    db.scalar.return_value = 7
    monkeypatch.setattr(local_assistant, "catalog_rows", lambda db: [])
    monkeypatch.setenv("LOCAL_ASSISTANT_URL", "http://model:8080")
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Yekaterinburg")
    settings.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: User(role=Role.ADMIN_OPERATOR))
    monkeypatch.setattr(local_assistant, "now", lambda: datetime(2026, 11, 4, 21, tzinfo=UTC))
    return db


def test_assistant_rejects_operators_before_calling_model(monkeypatch, assistant_db):
    extract = Mock()
    monkeypatch.setattr(local_assistant, "extract_task", extract)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: User(role=Role.OPERATOR))

    with TestClient(app) as client:
        response = client.post("/api/local-assistant/question", json={"question": "Создай задачу Иванову"})

    assert response.status_code == 403
    extract.assert_not_called()
    assistant_db.scalar.assert_not_called()


@pytest.mark.parametrize(("question", "context", "start", "end"), [
    ("Сколько снимков пришло вчера?", None, date(2026, 11, 4), date(2026, 11, 4)),
    ("сколько фото 10 дней назад ?", None, date(2026, 10, 26), date(2026, 10, 26)),
    ("а 5 дней ?", "ago", date(2026, 10, 31), date(2026, 10, 31)),
    ("сколько фото за последние 5 дней?", None, date(2026, 11, 1), date(2026, 11, 5)),
    ("сколько фото за 03.11.2026?", None, date(2026, 11, 3), date(2026, 11, 3)),
])
def test_photo_count_uses_explicit_local_receipt_dates(assistant_db, question, context, start, end):
    with TestClient(app) as client:
        response = client.post("/api/local-assistant/question", json={"question": question, "date_context": context})

    assert response.status_code == 200
    statement = assistant_db.scalar.call_args.args[0]
    assert {start, end} <= set(statement.compile().params.values())
    assert "photos.received_at" in str(statement)
    assert "photos.is_spam" in str(statement)


def test_ambiguous_or_filtered_photo_request_never_counts_a_different_period(assistant_db):
    with TestClient(app) as client:
        for question in ("а 5 дней?", "сколько фото за 31.02.2026?", "сколько фото Иванов отправил сегодня?"):
            response = client.post("/api/local-assistant/question", json={"question": question})
            assert response.status_code == 200
            assert "Уточните дату" in response.json()["answer"]
    assistant_db.scalar.assert_not_called()


def test_task_request_returns_only_a_draft_with_missing_fields(monkeypatch, assistant_db):
    monkeypatch.setattr(local_assistant, "current_organization", lambda: object())
    question = "создай задачу андрею дмитриевичу шашко"

    def complete(request):
        assert request.url == "http://model:8080/v1/chat/completions"
        assert json.loads(request.content)["messages"][-1]["content"] == question
        content = '{"executor":"Андрей Дмитриевич Шашко","subject":null,"description":null,"due":null}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    http_client = httpx.Client
    with TestClient(app) as client:
        monkeypatch.setattr(local_assistant.httpx, "Client", lambda **kwargs: http_client(
            transport=httpx.MockTransport(complete), **kwargs,
        ))
        response = client.post("/api/local-assistant/question", json={"question": question})

    assert response.status_code == 200
    assert response.json()["task"] == {
        "executor": "Андрей Дмитриевич Шашко", "subject": None, "description": None, "dueDate": None,
    }
    assistant_db.scalar.assert_not_called()


def test_photo_correction_and_confirmation_query_database_instead_of_echoing_user(assistant_db, monkeypatch):
    model = Mock(side_effect=AssertionError("Photo statistics must use database"))
    monkeypatch.setattr(local_assistant, "model_reply", model)
    history = [
        {"role": "user", "content": "ты сказал что 10 дней назад было 15 фото"},
        {"role": "assistant", "content": "Сколько фото было именно 2026-10-26?"},
    ]
    with TestClient(app) as client:
        for question in ("ты сказал что 10 дней назад было 15 фото", "ну да", "26 числа было не 10 фото"):
            response = client.post("/api/local-assistant/question", json={"question": question, "history": history})
            assert response.status_code == 200
            assert response.json()["answer"] == "Поступило фото за 26.10.2026: 7 (без спама)."
    assert assistant_db.scalar.call_count == 3
    model.assert_not_called()


def test_work_type_today_overrides_old_conversation_date(assistant_db, monkeypatch):
    work = Mock(code="DEICING_MANUAL")
    work.name = "ПГМ"
    monkeypatch.setattr(local_assistant, "catalog_rows", lambda db: [work])
    with TestClient(app) as client:
        response = client.post("/api/local-assistant/question", json={
            "question": "сколько фото пгм было сегодня ?",
            "history": [{"role": "assistant", "content": "Поступило фото за 30.10.2026: 449."}],
        })
    assert response.json()["answer"] == "Поступило фото по виду работ «ПГМ» за 05.11.2026: 7 (без спама)."
    params = assistant_db.scalar.call_args.args[0].compile().params.values()
    assert date(2026, 11, 5) in params
    assert "DEICING_MANUAL" in params


def test_breakdown_renders_only_database_numbers_and_catalog_names(assistant_db, monkeypatch):
    work = Mock(code="DEICING_MANUAL")
    work.name = "ПГМ"
    monkeypatch.setattr(local_assistant, "catalog_rows", lambda db: [work])
    monkeypatch.setattr(local_assistant, "model_reply", lambda *args: json.dumps({
        "action": "statistics", "date_from": "2026-11-04", "date_to": "2026-11-04",
        "group_by": "both", "unsupported_filter": False,
    }))
    assistant_db.execute.return_value = [("КА-1", "DEICING_MANUAL", 7)]
    with TestClient(app) as client:
        result = client.post("/api/local-assistant/question", json={
            "question": "Покажи виды работ и территории за вчера",
            "history": [{"role": "assistant", "content": "ПОДХОДЫ: 39, РАБОТЫ: 12, КА-1: 5"}],
        })
    assert result.status_code == 200
    answer = result.json()["answer"]
    assert "КА-1: ПГМ — 7" in answer
    assert "39" not in answer and "РАБОТЫ" not in answer
    assert assistant_db.scalar.call_count == 1


def test_unstructured_model_answer_cannot_reach_chat(assistant_db, monkeypatch):
    monkeypatch.setattr(local_assistant, "model_reply", lambda *args: "ПОДХОДЫ: 39, КА-1: 5")
    with TestClient(app) as client:
        result = client.post("/api/local-assistant/question", json={"question": "разбивку за вчера"})
    assert "Укажите дату" in result.json()["answer"]
    assert "39" not in result.json()["answer"]
    assistant_db.scalar.assert_not_called()


@pytest.mark.parametrize("question", [
    "дай статистику за вчера в разрезе видов работ и территорий",
    "мне нужно знать сколько вчера было выполнено работ по видам и территориям одновременно за весь день 04.11.2026 по всем микрорайонам",
])
def test_joint_work_breakdown_works_without_inference(assistant_db, monkeypatch, question):
    monkeypatch.setattr(local_assistant, "model_reply", Mock(side_effect=AssertionError("No inference needed")))
    work = Mock(code="SNOW_MANUAL")
    work.name = "ПОДХОДЫ"
    monkeypatch.setattr(local_assistant, "catalog_rows", lambda db: [work])
    assistant_db.execute.return_value = [("2 мкр", "SNOW_MANUAL", 7)]
    with TestClient(app) as client:
        response = client.post("/api/local-assistant/question", json={"question": question})
    assert response.status_code == 200
    assert "2 мкр: ПОДХОДЫ — 7" in response.json()["answer"]
    statement = assistant_db.scalar.call_args.args[0]
    assert date(2026, 11, 4) in statement.compile().params.values()
    assert "photos.photo_date" in str(statement)


def test_inference_sends_authentication_without_exposing_key(monkeypatch):
    monkeypatch.setenv("LOCAL_ASSISTANT_API_KEY", "private-test-key")
    settings.cache_clear()
    http_client = httpx.Client

    def complete(request):
        assert request.headers["Authorization"] == "Bearer private-test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"executor":"Иванов"}'}}]})

    monkeypatch.setattr(local_assistant.httpx, "Client", lambda **kwargs: http_client(
        transport=httpx.MockTransport(complete), **kwargs,
    ))
    assert local_assistant.extract_task("http://model", "Создай задачу Иванову").executor == "Иванов"
