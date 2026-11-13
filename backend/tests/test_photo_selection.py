from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import photo_selection
from app.models import Chat, ExchangeState, Photo, WorkType
from app.photo_downloads import PhotoDownloadInput
from app.schemas import PhotoSelectionFilters


@pytest.fixture
def selection_db():
    # Exercise the actual filter query without requiring PostGIS photo geometry.
    columns = (
        "id", "received_at", "preview_removed_at", "is_spam", "photo_date", "photo_time", "sha256",
        "max_chat_id", "district_id", "work_type", "status", "reviewed_by", "sender_id", "cohort",
    )
    metadata = MetaData()
    table = Table("photos", metadata, *(
        Column(name, Photo.__table__.c[name].type, primary_key=name == "id") for name in columns
    ))
    chats = Table("chats", metadata, *(
        Column(name, Chat.__table__.c[name].type, primary_key=name == "id") for name in ("id", "max_chat_id")
    ))
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    metadata.create_all(engine)
    ExchangeState.__table__.create(engine)
    WorkType.__table__.create(engine)
    with Session(engine) as db:
        db.add(WorkType(code="BIN_EMPTYING", name="Урны", filename_label="Урны", model_index=0, sort_order=1))
        db.execute(chats.insert().values(id=1, max_chat_id=123))

        def add(id, **values):
            fields = dict(
                id=id, received_at=datetime(2026, 11, 12), photo_date=date(2026, 11, 12),
                is_spam=False, sha256="a" * 64, max_chat_id=123, district_id=5,
                work_type="BIN_EMPTYING", status="ACCEPTED", reviewed_by=2, sender_id=9, cohort="test",
            )
            db.execute(table.insert().values(**(fields | values)))

        yield db, add
    engine.dispose()


def read(db, user=None, **filters):
    return photo_selection(db, user or SimpleNamespace(role="ADMIN_OPERATOR"), PhotoDownloadInput(filters=PhotoSelectionFilters(**filters)))


def test_select_all_keeps_filters_and_ignores_list_page(selection_db):
    db, add = selection_db
    add(1)
    add(2, max_chat_id=456)
    add(3, district_id=6)
    add(4, status="NEEDS_REVIEW")
    add(5, reviewed_by=3)
    add(6, sender_id=10)
    add(7, photo_date=date(2026, 11, 11))
    add(8, sha256=None)
    add(9, preview_removed_at=datetime(2026, 11, 12))
    add(10, cohort="production")
    add(11, is_spam=True)
    add(12)
    result = read(db, page=9, page_size=1, chat_id=123, district_id=5, status="ACCEPTED",
                  operator_id=2, sender_id=9, review_day="2026-11-12", work_type="BIN_EMPTYING")
    assert result["ids"] == [1, 12]
    assert result["count"] == 2


def test_select_all_is_capped_at_fifty_in_the_visible_sort_order(selection_db):
    db, add = selection_db
    for id in range(1, 1003):
        add(id)
    first = read(db)
    assert first["count"] == 50
    assert first["ids"] == list(range(1, 51))
    assert first["snapshot_id"] == 50
    add(1003)
    second = read(db, snapshot_id=first["snapshot_id"])
    assert second["count"] == 50
    assert second["ids"] == first["ids"]
    descending = read(db, sort_order="desc")
    assert descending["ids"] == list(range(1003, 953, -1))


def test_selection_respects_chat_access_and_spam_permission(selection_db):
    db, add = selection_db
    add(1)
    add(2, max_chat_id=456)
    user = SimpleNamespace(role="OPERATOR", permissions=["photos_view"], allowed_chat_ids=[1])
    assert read(db, user)["ids"] == [1]
    with pytest.raises(HTTPException) as error:
        read(db, user, status="SPAM")
    assert error.value.status_code == 403


def test_explicit_selection_and_exclusions_keep_access_boundaries(selection_db):
    db, add = selection_db
    add(1)
    add(2, max_chat_id=456)
    add(3)
    user = SimpleNamespace(role="OPERATOR", permissions=["photos_view"], allowed_chat_ids=[1])
    result = photo_selection(db, user, PhotoDownloadInput(ids=[1, 2, 3], excluded_ids=[3]))
    assert result["ids"] == [1]
    assert result["count"] == 1


def test_stream_reads_small_batches_and_returns_connections_before_yield(selection_db, monkeypatch, tmp_path):
    from app import photo_downloads

    db, add = selection_db
    for id in range(1, 8):
        add(id)
    db.commit()
    active = []
    calls = []

    class ReadSession(Session):
        def __enter__(self):
            active.append(self)
            calls.append(self)
            return super().__enter__()

        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:
                active.remove(self)

        def get(self, model, key, *args, **kwargs):
            from app.models import User
            if model is User:
                return SimpleNamespace(id=key, role="ADMIN_OPERATOR", active=True)
            return super().get(model, key, *args, **kwargs)

    monkeypatch.setattr(photo_downloads, "Session", ReadSession)
    monkeypatch.setattr(photo_downloads, "BATCH_SIZE", 2)
    files = photo_downloads.photo_files(db.get_bind(), 1, PhotoDownloadInput(filters=PhotoSelectionFilters()), tmp_path)
    names = []
    for name, _path in files:
        assert active == []
        names.append(name)
    assert names == [f"photo-{id}.jpg" for id in range(1, 8)]
    assert len(calls) == 5  # Four pages, then one empty terminal page.


@pytest.mark.parametrize("selected_ids", [[1], [1, 2]])
def test_ticket_to_native_response_preserves_photos_and_releases_lease(selection_db, monkeypatch, selected_ids):
    import asyncio
    import io
    from zipfile import ZipFile

    from app import photo_downloads
    from app.api import create_photo_download, get_photo_download
    from app.config import settings

    db, add = selection_db
    user = SimpleNamespace(id=1, active=True, role="ADMIN_OPERATOR")
    for id in (1, 2):
        add(id)
    db.commit()
    directory = settings().data_dir / "previews"
    directory.mkdir(parents=True)
    for id in (1, 2):
        (directory / f"{id}.jpg").write_bytes(f"jpeg-{id}".encode())

    class ReadSession(Session):
        def get(self, model, key, *args, **kwargs):
            from app.models import User
            return user if model is User else super().get(model, key, *args, **kwargs)

    monkeypatch.setattr(photo_downloads, "Session", ReadSession)
    request = SimpleNamespace(state=SimpleNamespace(login_session=SimpleNamespace(token_hash="session")))
    ticket = create_photo_download(request, db, user, PhotoDownloadInput(ids=selected_ids))
    token = ticket["url"].rsplit("/", 1)[1]
    response = get_photo_download(token, request, db, user)
    chunks = []

    async def send(message):
        if message["type"] == "http.response.body":
            chunks.append(message["body"])

    asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.4"}}, None, send))
    assert response.lease.closed
    if len(selected_ids) == 1:
        assert response.media_type == "image/jpeg"
        assert b"".join(chunks) == b"jpeg-1"
    else:
        with ZipFile(io.BytesIO(b"".join(chunks))) as archive:
            assert archive.read("photo-1.jpg") == b"jpeg-1"
            assert archive.read("photo-2.jpg") == b"jpeg-2"
            assert archive.testzip() is None


@pytest.mark.parametrize('count', [50, 51])
def test_server_enforces_download_limit_before_creating_ticket(selection_db, count):
    from app.api import create_photo_download

    db, add = selection_db
    for id in range(1, count + 1):
        add(id)
    request = SimpleNamespace(state=SimpleNamespace(login_session=SimpleNamespace(token_hash="session")))
    user = SimpleNamespace(id=1, role="ADMIN_OPERATOR")
    body = PhotoDownloadInput(filters=PhotoSelectionFilters())
    if count == 50:
        assert create_photo_download(request, db, user, body)["url"].startswith('/api/photos/downloads/')
    else:
        with pytest.raises(HTTPException) as error:
            create_photo_download(request, db, user, body)
        assert error.value.status_code == 400
        assert '50' in error.value.detail


def test_selection_growth_cannot_bypass_fifty_photo_limit(selection_db, monkeypatch):
    from sqlalchemy import text

    from app import photo_downloads
    from app.api import create_photo_download, get_photo_download

    db, add = selection_db
    for id in range(1, 52):
        add(id, work_type='SWEEPING' if id == 25 else 'BIN_EMPTYING')
    db.commit()
    user = SimpleNamespace(id=1, active=True, role='ADMIN_OPERATOR')
    request = SimpleNamespace(state=SimpleNamespace(login_session=SimpleNamespace(token_hash='session')))
    ticket = create_photo_download(request, db, user, PhotoDownloadInput(filters=PhotoSelectionFilters(work_type='BIN_EMPTYING')))
    token = ticket['url'].rsplit('/', 1)[1]
    db.execute(text("UPDATE photos SET work_type = :work_type WHERE id = :id"),
               {"work_type": "BIN_EMPTYING", "id": 25})
    db.commit()

    class ReadSession(Session):
        def get(self, model, key, *args, **kwargs):
            from app.models import User
            return user if model is User else super().get(model, key, *args, **kwargs)
    monkeypatch.setattr(photo_downloads, 'Session', ReadSession)
    with pytest.raises(HTTPException) as error:
        get_photo_download(token, request, db, user)
    assert error.value.status_code == 400
    assert '50' in error.value.detail
    assert photo_downloads.read_ticket(token, photo_downloads.ticket_owner(request, user))['state'] == 'failed'


@pytest.mark.parametrize("count", [1, 5, 50])
def test_download_through_real_http_middleware(selection_db, monkeypatch, count):
    import asyncio
    import io
    from zipfile import ZipFile

    import httpx
    from fastapi import Request

    from app import photo_downloads
    from app.api import app
    from app.auth import current_user
    from app.config import settings
    from app.db import get_db

    db, add = selection_db
    for id in range(1, count + 1):
        add(id)
    db.commit()
    engine = db.get_bind()
    directory = settings().data_dir / 'previews'
    directory.mkdir(parents=True)
    for id in range(1, count + 1):
        (directory / f'{id}.jpg').write_bytes(f'jpeg-{id}'.encode())
    user = SimpleNamespace(id=1, active=True, role='ADMIN_OPERATOR')

    def login(request: Request):
        request.state.login_session = SimpleNamespace(token_hash='session')
        return user

    def database():
        with Session(engine) as session:
            yield session

    class ReadSession(Session):
        def get(self, model, key, *args, **kwargs):
            from app.models import User
            return user if model is User else super().get(model, key, *args, **kwargs)

    monkeypatch.setattr(photo_downloads, 'Session', ReadSession)
    app.dependency_overrides[current_user] = login
    app.dependency_overrides[get_db] = database

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            created = await client.post('/api/photos/downloads', json={'ids': list(range(1, count + 1))})
            assert created.status_code == 200, created.text
            ticket = created.json()
            async with asyncio.timeout(3):
                response = await client.get(ticket['url'])
            assert response.status_code == 200
            if count == 1:
                assert response.content == b'jpeg-1'
            else:
                with ZipFile(io.BytesIO(response.content)) as archive:
                    assert len(archive.namelist()) == count
                    assert archive.testzip() is None
            status = await client.get('/api' + ticket['status_url'])
            assert status.json() == {'state': 'finished'}
    try:
        asyncio.run(run())
    finally:
        app.dependency_overrides.clear()
