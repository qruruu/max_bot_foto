import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine


@pytest.fixture(autouse=True)
def test_config(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAX_WEBHOOK_SECRET", "test-secret-" * 4)
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.fixture(scope="session")
def database_url():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL/PostGIS integration tests")
    if not make_url(url).database.endswith("_test"):
        raise RuntimeError("Use a disposable database whose name ends with _test")
    from alembic.config import Config

    from alembic import command

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    settings.cache_clear()
    admin_engine = create_engine(url)
    with admin_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    config = Config(str(__import__("pathlib").Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    admin_engine.dispose()
    yield url
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    settings.cache_clear()


@pytest.fixture
def db(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    settings.cache_clear()
    if engine.cache_info().currsize:
        engine().dispose()
    engine.cache_clear()
    from app.models import Base

    with engine().begin() as conn:
        tables = ", ".join('"' + table.name + '"' for table in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with Session(engine(), expire_on_commit=False) as session:
        yield session
    engine().dispose()
    engine.cache_clear()


@pytest.fixture
def client(db):
    from app.api import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def users(db):
    from app.auth import hasher
    from app.models import User

    for login, role in [("admin", "ADMIN_OPERATOR"), ("operator", "OPERATOR")]:
        db.add(
            User(
                login=login,
                name=login,
                role=role,
                active=True,
                password_hash=hasher.hash("test-password-123"),
            )
        )
    db.commit()


@pytest.fixture
def admin(client, users):
    response = client.post("/api/auth/login", json={"login": "admin", "password": "test-password-123"})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["csrf"]
    return client
