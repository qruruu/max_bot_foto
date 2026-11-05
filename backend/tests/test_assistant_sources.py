import json
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import assistant_sources, local_assistant
from app.api import app
from app.auth import current_user
from app.catalog import Role
from app.config import settings
from app.db import get_db
from app.models import User


def test_source_catalog_contains_only_allowed_read_routes():
    for domain in assistant_sources.DOMAINS:
        routes = assistant_sources.sources_for(app, domain)
        assert routes
        assert all("post" not in spec and "delete" not in spec for spec in routes.values())
        assert all(not assistant_sources.EXCLUDED.search(path) for path in routes)
        assert all("integration-keys" not in path and "/auth/" not in path for path in routes)


def test_source_reader_authenticates_through_existing_api_and_redacts_secrets(monkeypatch):
    monkeypatch.setenv("LOCAL_ASSISTANT_URL", "http://model")
    settings.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: Mock())
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: User(role=Role.ADMIN_OPERATOR))
    replies = iter([
        json.dumps({"domain": "people"}),
        json.dumps({"path": "/api/users", "query": {}, "path_values": {}}),
    ])
    monkeypatch.setattr(local_assistant, "model_reply", lambda *args: next(replies))

    async def read(app_arg, request, path, params):
        import httpx
        assert request.cookies.get("session") == "private-session"
        assert path == "/api/users"
        return httpx.Response(200, json=[{"id": 1, "name": "Иван", "password_hash": "hidden"}])
    monkeypatch.setattr(assistant_sources, "read_source", read)
    with TestClient(app) as client:
        client.cookies.set("session", "private-session")
        response = client.post("/api/local-assistant/question", json={"question": "Покажи операторов"})
    assert response.status_code == 200
    assert "Иван" in response.json()["answer"]
    assert "hidden" not in response.json()["answer"]


def test_internal_read_does_not_bypass_authorization():
    import asyncio

    from starlette.requests import Request

    target = FastAPI()

    @target.get("/api/users")
    def users():
        from fastapi import HTTPException
        raise HTTPException(403)

    request = Request({"type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
                       "path": "/", "headers": []})
    result = asyncio.run(assistant_sources.read_source(target, request, "/api/users", {}))
    assert result.status_code == 403


def test_territory_list_and_greeting_do_not_call_the_model(monkeypatch):
    monkeypatch.setenv("LOCAL_ASSISTANT_URL", "http://model")
    settings.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: Mock())
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: User(role=Role.ADMIN_OPERATOR))
    model = Mock(side_effect=AssertionError("No model needed"))
    monkeypatch.setattr(local_assistant, "model_reply", model)

    async def read(app_arg, request, path, params):
        import httpx
        assert path == "/api/districts"
        return httpx.Response(200, json={
            "type": "FeatureCollection", "features": [
                {"properties": {"id": 2, "name": "2 мкр", "active": True},
                 "geometry": {"coordinates": [100, 200]}},
            ],
        })
    monkeypatch.setattr(assistant_sources, "read_source", read)
    with TestClient(app) as client:
        greeting = client.post("/api/local-assistant/question", json={"question": "привет"})
        assert greeting.status_code == 200
        assert greeting.json()["answer"].startswith("Привет!")
        for question in ("список территорий", "покажи все микрорайоны", "территории"):
            response = client.post("/api/local-assistant/question", json={"question": question})
            assert "2 мкр" in response.json()["answer"]
            assert "Всего: 1" in response.json()["answer"]
            assert "дату" not in response.json()["answer"]
            assert "coordinates" not in response.json()["answer"]
    model.assert_not_called()
