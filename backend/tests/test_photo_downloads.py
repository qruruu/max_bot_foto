import asyncio
import io
import subprocess
import sys
import tracemalloc
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError
from starlette.requests import ClientDisconnect

from app import photo_archive, photo_downloads
from app.photo_archive import CHUNK_SIZE, stream_zip
from app.photo_downloads import (
    PhotoArchiveResponse,
    PhotoDownloadAdmission,
    PhotoDownloadInput,
    acquire_download,
    consume_ticket,
    download_directory,
    selection_read,
    write_ticket,
)


def test_streamed_zip_preserves_all_bytes_and_crc(tmp_path):
    paths = []
    for id in range(12):
        path = tmp_path / f"{id}.jpg"
        path.write_bytes(bytes([id]) * (CHUNK_SIZE + 71))
        paths.append((f"photo-{id}.jpg", path))
    chunks = list(stream_zip(paths, tmp_path, bytes_per_second=0))
    assert max(map(len, chunks)) <= CHUNK_SIZE
    with ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 12
        for name, path in paths:
            assert archive.read(name) == path.read_bytes()


def test_zip64_supports_more_than_65535_photos_without_growing_ram(tmp_path):
    path = tmp_path / "empty.jpg"
    path.touch()
    target = tmp_path / "archive.zip"
    tracemalloc.start()
    try:
        with target.open("wb") as result:
            for chunk in stream_zip(((f"photo-{i}.jpg", path) for i in range(66000)), tmp_path, bytes_per_second=0):
                result.write(chunk)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024
    with ZipFile(target) as archive:
        assert len(archive.namelist()) == 66000
        assert archive.read("photo-65999.jpg") == b""


def test_missing_photo_aborts_instead_of_finishing_an_incomplete_archive(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(stream_zip([("photo-1.jpg", tmp_path / "missing.jpg")], tmp_path))


def test_large_photo_bytes_do_not_accumulate_in_memory(tmp_path):
    path = tmp_path / "large.jpg"
    with path.open("wb") as file:
        file.truncate(256 * 1024 * 1024)
    tracemalloc.start()
    try:
        total = sum(len(chunk) for chunk in stream_zip([("photo-1.jpg", path)], tmp_path, bytes_per_second=0))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total > 256 * 1024 * 1024
    assert peak < 1024 * 1024


def test_directory_disk_budget_fails_safely(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo")
    monkeypatch.setattr(photo_archive, "MAX_DIRECTORY_BYTES", 1)
    with pytest.raises(OSError, match="disk budget"):
        list(stream_zip([("photo-1.jpg", path)], tmp_path, bytes_per_second=0))


def test_two_archives_can_run_and_third_waits_for_release():
    lease = acquire_download()
    second = acquire_download()
    try:
        with pytest.raises(HTTPException) as error:
            acquire_download()
        assert error.value.status_code == 503
    finally:
        lease.close()
        second.close()
    acquire_download().close()


def test_archive_lease_also_limits_other_processes():
    lease = acquire_download()
    script = (
        "import fcntl, sys\n"
        "with open(sys.argv[1], 'a+b') as lease:\n"
        " try: fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        " except BlockingIOError: sys.exit(17)\n"
    )
    try:
        assert subprocess.run([sys.executable, "-c", script, lease.name]).returncode == 17
    finally:
        lease.close()
    assert subprocess.run([sys.executable, "-c", script, lease.name]).returncode == 0


def test_low_disk_rejects_without_leaking_lease(monkeypatch):
    original = photo_downloads.shutil.disk_usage
    monkeypatch.setattr(photo_downloads.shutil, "disk_usage", lambda directory: SimpleNamespace(free=0))
    with pytest.raises(HTTPException) as error:
        acquire_download()
    assert error.value.status_code == 503
    monkeypatch.setattr(photo_downloads.shutil, "disk_usage", original)
    acquire_download().close()


def test_tickets_are_private_expiring_and_single_use(monkeypatch):
    owner = "a" * 64
    body = PhotoDownloadInput(filters={"chat_id": 123, "snapshot_id": 500})
    token = write_ticket(owner, body)
    with pytest.raises(HTTPException) as error:
        consume_ticket(token, "b" * 64)
    assert error.value.status_code == 404
    assert consume_ticket(token, owner) == body
    with pytest.raises(HTTPException) as error:
        consume_ticket(token, owner)
    assert error.value.status_code == 410
    token = write_ticket(owner, body)
    monkeypatch.setattr(photo_downloads.time, "time", lambda: 10**12)
    with pytest.raises(HTTPException) as error:
        consume_ticket(token, owner)
    assert error.value.status_code == 410


def test_expired_ticket_cleanup_precedes_capacity_check():
    directory = download_directory()
    import os
    for i in range(129):
        path = directory / f"{i:064x}.json"
        path.write_text("{}")
        os.utime(path, (1, 1))
    write_ticket("a" * 64, PhotoDownloadInput(ids=[1]))
    assert len(list(directory.glob("*.json"))) == 1


def test_database_statement_timeout_is_reported_as_busy():
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.scalar.return_value = True
    original = Exception("cancelled")
    original.sqlstate = "57014"
    with pytest.raises(HTTPException) as error, selection_read(db):
        raise DBAPIError("select", {}, original)
    assert error.value.status_code == 503
    assert any("statement_timeout" in str(call.args[0]) for call in db.execute.call_args_list)


def test_two_downloads_run_third_waits_and_map_is_not_blocked():
    async def run():
        release = asyncio.Event()
        calls = []

        async def app(scope, receive, send):
            calls.append(scope["path"])
            if "/downloads/" in scope["path"]:
                await release.wait()

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            raise AssertionError(f"No rejection expected: {message}")

        admission = PhotoDownloadAdmission(app)
        def scope(id):
            return {"type": "http", "method": "GET", "path": f"/api/photos/downloads/{id}"}
        first = asyncio.create_task(admission(scope("aa"), receive, send))
        second = asyncio.create_task(admission(scope("bb"), receive, send))
        for _ in range(20):
            if len(calls) == 2:
                break
            await asyncio.sleep(0)
        assert len(calls) == 2
        third = asyncio.create_task(admission(scope("cc"), receive, send))
        await asyncio.sleep(0)
        assert len(calls) == 2
        await admission({"type": "http", "method": "GET", "path": "/api/photos/map"}, receive, send)
        assert calls[-1] == "/api/photos/map"
        assert not third.done()
        release.set()
        await asyncio.gather(first, second, third)
        assert calls[-1] == "/api/photos/downloads/cc"
        assert admission.pending == 0
    asyncio.run(run())


def test_cancelled_waiter_does_not_retain_queue_or_archive_slot():
    async def run():
        release = asyncio.Event()
        async def app(scope, receive, send):
            await release.wait()
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            pass
        admission = PhotoDownloadAdmission(app)
        scope = {"type": "http", "method": "GET", "path": "/api/photos/downloads/aa"}
        tasks = [asyncio.create_task(admission(dict(scope), receive, send)) for _ in range(3)]
        for _ in range(10):
            await asyncio.sleep(0)
        tasks[-1].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[-1]
        assert admission.pending == 2
        release.set()
        await asyncio.gather(*tasks[:2])
        assert admission.pending == 0
        first, second = acquire_download(), acquire_download()
        first.close()
        second.close()
    asyncio.run(run())


def test_disconnect_closes_generator_and_cross_process_lease(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo" * 100000)
    lease = acquire_download()
    response = PhotoArchiveResponse(iter([("photo-1.jpg", path)]), lease)

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("disconnected")

    async def run():
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send)
    asyncio.run(run())
    assert lease.closed
    assert response.archive.gi_frame is None
    acquire_download().close()


def test_download_deadline_releases_lease(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo")
    lease = acquire_download()
    response = PhotoArchiveResponse(iter([("photo-1.jpg", path)]), lease)
    monkeypatch.setattr(photo_downloads, "MAX_SECONDS", 0.02)

    async def send(message):
        await asyncio.sleep(1)

    async def run():
        with pytest.raises(TimeoutError):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send)
    asyncio.run(run())
    assert lease.closed
    acquire_download().close()


def test_request_body_limit_applies_to_chunked_uploads():
    async def run():
        async def app(scope, receive, send):
            await receive()
        admission = PhotoDownloadAdmission(app)
        async def receive():
            return {"type": "http.request", "body": b"x" * (photo_downloads.BODY_LIMIT + 1)}
        with pytest.raises(HTTPException) as error:
            await admission({"type": "http", "method": "POST", "path": "/api/photos/downloads"}, receive, None)
        assert error.value.status_code == 413
    asyncio.run(run())


def test_waiting_timeout_does_not_occupy_a_database_or_leak_queue_capacity(monkeypatch):
    first, second = acquire_download(), acquire_download()
    monkeypatch.setattr(photo_downloads, 'QUEUE_SECONDS', 0.02)
    called = Mock()
    messages = []

    async def run():
        async def app(scope, receive, send):
            called()
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            messages.append(message)
        admission = PhotoDownloadAdmission(app)
        await admission({'type': 'http', 'method': 'GET', 'path': '/api/photos/downloads/aa'}, receive, send)
        assert admission.pending == 0
    try:
        asyncio.run(run())
    finally:
        first.close()
        second.close()
    assert messages[0]['status'] == 503
    called.assert_not_called()  # Authentication and DB dependencies were never entered.
