"""Tenant-local snapshots and a durable, commit-ordered read API."""
import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text

from app.auth import Db
from app.config import settings
from app.domain import now
from app.integration_access import (
    FILE_BYTES,
    PREFIX,
    RECORD_BYTES,
    IntegrationRoute,
    require_scope,
    reserve_original,
)
from app.integrations import YandexDisk
from app.models import (
    IntegrationChange,
    IntegrationClock,
    IntegrationSnapshot,
    IntegrationSnapshotRow,
    Photo,
)

router = APIRouter(prefix=PREFIX, tags=['Read-only integrations v1'], route_class=IntegrationRoute)
RETENTION = timedelta(days=30)
SNAPSHOT_TTL = timedelta(hours=24)


def sign_cursor(application, clock, sequence):
    body = json.dumps([clock.epoch, sequence, int((now() + RETENTION).timestamp())], separators=(',', ':'))
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip('=')
    signature = hmac.new(application.signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + '.' + signature


def read_cursor(value, application, clock):
    try:
        if len(value) > 300:
            raise ValueError()
        encoded, signature = value.split('.')
        expected = hmac.new(application.signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        epoch, sequence, expires = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if type(sequence) is not int or type(expires) is not int or sequence < 0:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(400, 'Недействительный курсор') from None
    if epoch != clock.epoch or expires <= now().timestamp() or sequence < clock.floor:
        raise HTTPException(410, 'Курсор устарел; создайте новый снимок и замените локальные данные')
    if sequence > clock.sequence:
        raise HTTPException(410, 'История восстановлена из резервной копии; создайте новый снимок')
    return sequence


def clock_row(db, *, lock=False):
    db.execute(text("INSERT INTO integration_clock(id,epoch) VALUES (1,gen_random_uuid()::text) ON CONFLICT DO NOTHING"))
    stmt = select(IntegrationClock).where(IntegrationClock.id == 1)
    return db.scalar(stmt.with_for_update() if lock else stmt)


def present(data, application, entity='photo'):
    result = dict(data)
    if entity != 'photo':
        return result
    timezone = ZoneInfo(settings().app_timezone)
    result['received_at'] = datetime.fromisoformat(data['received_at']).astimezone(timezone).isoformat()
    result['captured_at'] = (
        datetime.fromisoformat(data['photo_date'] + 'T' + data['photo_time']).replace(tzinfo=timezone).isoformat()
        if data['photo_date'] and data['photo_time'] else None
    )
    result['original_url'] = (
        f'{PREFIX}/photos/{data["id"]}/original'
        if data['original_available'] and 'originals:read' in application.scopes else None
    )
    return result


def bounded_response(value):
    response = JSONResponse(value)
    if len(response.body) > RECORD_BYTES:
        raise HTTPException(413, 'Уменьшите размер страницы')
    return response


class SnapshotInput(BaseModel):
    photo_date: date | None = None


@router.post('/snapshots', status_code=201)
def create_snapshot(body: SnapshotInput, request: Request, db: Db):
    application = getattr(request.state, 'integration_application', None)
    permissions = application.scopes if application else frozenset()
    if not permissions.intersection({'photos:read', 'geozones:read'}):
        raise HTTPException(403, 'Нужно право чтения фото или геозон')
    # All photo/district writers serialize their journal entries through this row.
    # Holding it across INSERT ... SELECT makes snapshot contents and cursor atomic.
    db.execute(text("SET LOCAL lock_timeout = '10s'"))
    db.execute(text("SET LOCAL statement_timeout = '30s'"))
    clock = clock_row(db, lock=True)
    db.execute(delete(IntegrationSnapshot).where(IntegrationSnapshot.expires_at <= now()))
    count = db.scalar(select(func.count()).select_from(IntegrationSnapshot).where(
        IntegrationSnapshot.key_id == application.id))
    if count >= 2:
        raise HTTPException(409, 'Завершите и удалите предыдущий снимок (не более двух на ключ)')
    # Prune only a contiguous expired prefix; floor makes gaps explicit to clients.
    first_retained = db.scalar(select(func.min(IntegrationChange.sequence)).where(
        IntegrationChange.at >= now() - RETENTION))
    floor = first_retained - 1 if first_retained is not None else clock.sequence
    if floor > clock.floor:
        db.execute(delete(IntegrationChange).where(IntegrationChange.sequence <= floor))
        clock.floor = floor
    cursor = sign_cursor(application, clock, clock.sequence)
    snapshot = IntegrationSnapshot(id=str(uuid4()), key_id=application.id,
                                   expires_at=now() + SNAPSHOT_TTL, cursor=cursor, photo_date=body.photo_date)
    db.add(snapshot)
    db.flush()
    params = {'snapshot': snapshot.id, 'cohort': application.cohort, 'day': body.photo_date}
    if 'photos:read' in permissions:
        # INSERT SELECT does not materialize the entire organization in worker memory.
        db.execute(text('''INSERT INTO integration_snapshot_rows(snapshot_id,entity,entity_id,data)
            SELECT :snapshot, 'photo', p.id, integration_photo_data(p) FROM photos p
            WHERE p.cohort=:cohort AND p.preview_removed_at IS NULL
              AND (CAST(:day AS date) IS NULL OR p.photo_date=CAST(:day AS date))'''), params)
    if 'geozones:read' in permissions:
        db.execute(text('''INSERT INTO integration_snapshot_rows(snapshot_id,entity,entity_id,data)
            SELECT :snapshot, 'geozone', id, jsonb_build_object('id',id,'name',name,'active',active)
            FROM districts'''), params)
    db.commit()
    return {'id': snapshot.id, 'expires_at': snapshot.expires_at, 'cursor': cursor,
            'photo_date': body.photo_date, 'timezone': settings().app_timezone, 'cohort': application.cohort}


def get_snapshot(db, id, application):
    snapshot = db.get(IntegrationSnapshot, str(id))
    if not snapshot or snapshot.key_id != application.id:
        raise HTTPException(404, 'Снимок не найден')
    if snapshot.expires_at <= now():
        raise HTTPException(410, 'Снимок устарел; создайте новый')
    return snapshot


def snapshot_page(id, entity, request, db, after_id, limit):
    application = require_scope(request, 'photos:read' if entity == 'photo' else 'geozones:read')
    snapshot = get_snapshot(db, id, application)
    rows = list(db.scalars(select(IntegrationSnapshotRow).where(
        IntegrationSnapshotRow.snapshot_id == snapshot.id, IntegrationSnapshotRow.entity == entity,
        IntegrationSnapshotRow.entity_id > after_id).order_by(IntegrationSnapshotRow.entity_id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return bounded_response({'items': [present(r.data, application, entity) for r in rows],
                             'next_after_id': rows[-1].entity_id if more else None,
                             'cursor': snapshot.cursor, 'timezone': settings().app_timezone})


@router.get('/snapshots/{snapshot_id}/photos')
def snapshot_photos(snapshot_id: UUID, request: Request, db: Db,
                    after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    return snapshot_page(snapshot_id, 'photo', request, db, after_id, limit)


@router.get('/snapshots/{snapshot_id}/geozones')
def snapshot_geozones(snapshot_id: UUID, request: Request, db: Db,
                      after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    return snapshot_page(snapshot_id, 'geozone', request, db, after_id, limit)


@router.delete('/snapshots/{snapshot_id}', status_code=204)
def release_snapshot(snapshot_id: UUID, request: Request, db: Db):
    application = request.state.integration_application
    snapshot = get_snapshot(db, snapshot_id, application)
    db.delete(snapshot)
    db.commit()


@router.get('/changes')
def changes(request: Request, db: Db, cursor: str = Query(max_length=300),
            limit: int = Query(100, ge=1, le=100)):
    application = require_scope(request, 'changes:read')
    # Keep pruning and the page read atomic, including for a slow client with a
    # renewed cursor that still points into a backlog near the retention floor.
    clock = clock_row(db, lock=True)
    sequence = read_cursor(cursor, application, clock)
    entities = []
    if 'photos:read' in application.scopes:
        entities.append('photo')
    if 'geozones:read' in application.scopes:
        entities.append('geozone')
    rows = list(db.scalars(select(IntegrationChange).where(
        IntegrationChange.sequence > sequence, IntegrationChange.sequence <= clock.sequence,
        IntegrationChange.entity.in_(entities),
        (IntegrationChange.cohort.is_(None) | (IntegrationChange.cohort == application.cohort)),
    ).order_by(IntegrationChange.sequence).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    next_sequence = rows[-1].sequence if more else clock.sequence
    items = [{'sequence': r.sequence, 'at': r.at.isoformat(), 'entity': r.entity,
              'id': r.entity_id, 'operation': r.operation,
              'data': present(r.data, application, r.entity) if r.data else None} for r in rows]
    response = bounded_response({'items': items, 'has_more': more,
                                 'cursor': sign_cursor(application, clock, next_sequence)})
    db.commit()
    return response


@router.get('/photos/{photo_id}')
def photo(photo_id: int, request: Request, db: Db):
    application = require_scope(request, 'photos:read')
    data = db.execute(text('''SELECT integration_photo_data(p) FROM photos p
        WHERE p.id=:id AND p.cohort=:cohort AND p.preview_removed_at IS NULL'''),
        {'id': photo_id, 'cohort': application.cohort}).scalar_one_or_none()
    if data is None:
        raise HTTPException(404, 'Фото не найдено')
    return present(data, application)


@router.get('/geozones/{zone_id}')
def geozone(zone_id: int, request: Request, db: Db):
    require_scope(request, 'geozones:read')
    data = db.execute(text("SELECT jsonb_build_object('id',id,'name',name,'active',active) FROM districts WHERE id=:id"),
                      {'id': zone_id}).scalar_one_or_none()
    if data is None:
        raise HTTPException(404, 'Геозона не найдена')
    return data


@router.get('/photos/{photo_id}/original')
def original(photo_id: int, request: Request, db: Db):
    application = require_scope(request, 'originals:read')
    photo = db.scalar(select(Photo).where(Photo.id == photo_id, Photo.cohort == application.cohort,
                                         Photo.preview_removed_at.is_(None)))
    if not photo:
        raise HTTPException(404, 'Фото не найдено')
    if not photo.yandex_disk_path or photo.processing_error == 'ORIGINAL_MISSING':
        raise HTTPException(409, 'Оригинал пока недоступен')
    temporary = TemporaryDirectory(prefix='metka-api-original-')
    target = Path(temporary.name) / 'original'
    try:
        YandexDisk().download(photo.yandex_disk_path, target)
        size = target.stat().st_size
        if size > FILE_BYTES:
            raise HTTPException(413, 'Оригинал превышает 50 МиБ')
        reserve_original(application, size)
    except HTTPException:
        temporary.cleanup()
        raise
    except (httpx.HTTPError, ValueError, RuntimeError, OSError, KeyError, TypeError):
        temporary.cleanup()
        raise HTTPException(502, 'Хранилище оригиналов временно недоступно') from None

    def chunks():
        try:
            with target.open('rb') as stream:
                while chunk := stream.read(64 * 1024):
                    yield chunk
        finally:
            temporary.cleanup()

    return StreamingResponse(chunks(), media_type='application/octet-stream', headers={
        'Content-Length': str(size), 'Content-Disposition': f'attachment; filename="photo-{photo_id}.original"',
        'Cache-Control': 'no-store',
    })
