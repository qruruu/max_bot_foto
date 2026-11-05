"""Slow image responses must not starve login/health checks of DB connections."""

import asyncio
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from app.auth import Db
from app.news import NewsDb


def test_database_connections_are_released_before_slow_file_transfer(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0,
        pool_timeout=0.1, connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr("app.db.engine", lambda: engine)
    monkeypatch.setattr("app.organization_registry.database_engine", lambda _: engine)
    app = FastAPI()
    image = tmp_path / "preview.jpg"
    image.write_bytes(b"authorized preview")

    # Exercise the non-yield authentication dependency above the shared Db alias.
    def authorized(db: Db):
        db.execute(text("SELECT 1"))
        return True

    @app.get("/preview")
    def preview(db: Db, _allowed: Annotated[bool, Depends(authorized)]):
        db.execute(text("SELECT 1"))
        return FileResponse(image)

    @app.get("/health")
    def health(db: Db):
        return {"ok": db.scalar(text("SELECT 1")) == 1}

    @app.get("/news-file")
    def news_file(db: NewsDb):
        db.execute(text("SELECT 1"))
        return StreamingResponse(iter([b"published image"]))

    async def exercise(path, count=1):
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.start":
                # ASGI backpressure models an image transfer still in progress.
                if sum(item["type"] == "http.response.start" for item in messages) == count:
                    entered.set()
                await release.wait()

        async def receive():
            await release.wait()
            return {"type": "http.disconnect"}

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": path, "raw_path": path.encode(), "query_string": b"",
            "root_path": "", "headers": [], "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
        transfers = [asyncio.create_task(app(dict(scope), receive, send)) for _ in range(count)]
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            assert engine.pool.checkedout() == 0
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await asyncio.wait_for(client.get("/health"), timeout=2)
                assert response.status_code == 200
                assert response.json() == {"ok": True}
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(*transfers), timeout=3)
        assert sum(item.get("status") == 200 for item in messages) == count
        assert engine.pool.checkedout() == 0

    try:
        asyncio.run(exercise("/preview", count=16))
        asyncio.run(exercise("/news-file"))
    finally:
        engine.dispose()
