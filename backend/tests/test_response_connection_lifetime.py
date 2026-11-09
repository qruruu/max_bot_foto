"""Slow image responses must not starve login/health checks of DB connections."""

import asyncio
import time
from typing import Annotated

import anyio
import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from app.auth import Db
from app.news import NewsDb
from app.preview_admission import PreviewAdmission


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


@pytest.mark.parametrize("prefix", [
    "/org/00000000-0000-0000-0000-000000000000/api",
    "/api/inspection/organizations/00000000-0000-0000-0000-000000000000",
])
def test_large_map_preview_burst_leaves_worker_threads_for_active_requests(monkeypatch, tmp_path, prefix):
    engine = create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=10, max_overflow=0,
        pool_timeout=0.3, connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr("app.db.engine", lambda: engine)
    app = FastAPI()
    app.add_middleware(PreviewAdmission)
    image = tmp_path / "preview.jpg"
    image.write_bytes(b"authorized preview")

    def authorized(db: Db):
        db.execute(text("SELECT 1"))
        # Concurrent auth checks hold their connections until the next sync handler runs.
        time.sleep(0.025)
        return True

    @app.get(prefix + "/photos/{photo_id}/preview")
    def preview(db: Db, _allowed: Annotated[bool, Depends(authorized)]):
        db.execute(text("SELECT 1"))
        return FileResponse(image)

    @app.get("/api/health")
    def health(db: Db):
        return {"ok": db.scalar(text("SELECT 1")) == 1}

    async def exercise():
        anyio.to_thread.current_default_thread_limiter().total_tokens = 16
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            previews = asyncio.gather(*(
                client.get(f"{prefix}/photos/{photo_id}/preview")
                for photo_id in range(1, 81)
            ))
            await asyncio.sleep(0.05)
            try:
                response = await asyncio.wait_for(client.get("/api/health"), timeout=1)
                assert response.json() == {"ok": True}
            finally:
                responses = await asyncio.wait_for(previews, timeout=4)
            assert all(response.status_code == 200 and response.content == b"authorized preview"
                       for response in responses)
        assert engine.pool.checkedout() == 0

    try:
        asyncio.run(exercise())
    finally:
        engine.dispose()


def test_map_burst_is_rejected_before_using_the_shared_database_pool():
    from app.photo_map import PhotoMapAdmission

    async def exercise():
        app = FastAPI()
        app.add_middleware(PhotoMapAdmission)
        ready, release = asyncio.Event(), asyncio.Event()
        entered = 0

        @app.get("/api/photos/map")
        @app.get("/api/photos/map-filter-counts")
        async def map_read():
            nonlocal entered
            entered += 1
            if entered == 2:
                ready.set()
            await release.wait()
            return {"ok": True}

        @app.get("/api/health")
        async def health():
            return {"ok": True}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            in_progress = [asyncio.create_task(client.get("/api/photos/map")) for _ in range(2)]
            try:
                await asyncio.wait_for(ready.wait(), timeout=2)
                others = [client.get("/api/photos/map-filter-counts") for _ in range(8)]
                responses = await asyncio.wait_for(asyncio.gather(*others, client.get("/api/health")), timeout=2)
                assert [response.status_code for response in responses] == [503] * 8 + [200]
                assert entered == 2
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(*in_progress), timeout=2)

    asyncio.run(exercise())
