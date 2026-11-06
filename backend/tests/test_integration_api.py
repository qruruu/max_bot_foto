"""Exercise real PostgreSQL journal ordering and independent organization databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from threading import Event
from time import sleep
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from test_organizations import companies as companies

from app.auth import digest
from app.db import engine
from app.domain import now
from app.integration_access import PREFIX
from app.integration_api import read_cursor, sign_cursor
from app.models import Inbox, IntegrationChange, IntegrationKey, Organization, Photo, WorkType
from app.organization_context import organization_scope
from app.organization_registry import control_session


def test_cursor_authenticity_expiry_and_rotation():
    application = SimpleNamespace(signing_key='test-hash')
    clock = SimpleNamespace(epoch='epoch', sequence=50, floor=5)
    cursor = sign_cursor(application, clock, 10)
    assert read_cursor(cursor, application, clock) == 10
    for value in (cursor+'x', '', 'e30.bad'):
        with pytest.raises(HTTPException) as exc:
            read_cursor(value, application, clock)
        assert exc.value.status_code == 400
    clock.floor = 11
    with pytest.raises(HTTPException) as exc:
        read_cursor(cursor, application, clock)
    assert exc.value.status_code == 410
    clock.floor, clock.epoch = 0, 'restored'
    with pytest.raises(HTTPException) as exc:
        read_cursor(cursor, application, clock)
    assert exc.value.status_code == 410


def seed(scope, ids=(1, 2, 3)):
    with organization_scope(scope), Session(engine()) as db:
        for id in ids:
            db.add(Inbox(id=id, max_chat_id=100, message_id=str(id), payload={}))
            db.flush()
            db.add(Photo(id=id, inbox_id=id, attachment_index=0, max_chat_id=100, chat_name='Test', max_message_id=str(id),
                         photo_date=date(2026, 11, 5), photo_time=time(0 if id==1 else 23, 59),
                         received_at=datetime(2026, 11, 4, 19, tzinfo=UTC), status='ACCEPTED', cohort='test'))
        db.commit()


def issue(owner, scope, scopes=None):
    response = owner.post(f'/org/{scope.id}/api/integration-keys', json={
        'name': 'Reports', 'scopes': scopes or ['photos:read','geozones:read','changes:read','originals:read']})
    assert response.status_code == 201, response.text
    return response.json()


def headers(key):
    return {'Authorization': 'Bearer ' + key['key']}


def snapshot(owner, key, **body):
    response = owner.post(PREFIX+'/snapshots', json=body, headers=headers(key))
    assert response.status_code == 201, response.text
    return response.json()


def test_work_types_are_read_from_the_organization_catalog_without_photos(companies):
    owner, (alpha, beta), _ = companies
    for scope, code, name in ((alpha, 'MOWING', 'Покос травы'), (beta, 'WATERING', 'Полив')):
        with organization_scope(scope), Session(engine()) as db:
            db.add(WorkType(code=code, name=name, filename_label=name, model_index=0, sort_order=1))
            db.commit()

    path = PREFIX + '/work-types'
    key = issue(owner, alpha, ['work_types:read'])
    response = owner.get(path, headers={**headers(key), 'X-Organization-Id': beta.id})
    assert response.status_code == 200
    assert response.json() == {'items': [{'code': 'MOWING', 'name': 'Покос травы', 'active': True}]}
    assert owner.get(path, headers=headers(issue(owner, alpha))).status_code == 403
    assert owner.post(path, headers=headers(key), json={}).status_code == 405


def test_keys_isolation_scopes_revocation_and_limits(companies, monkeypatch):
    owner, scopes, operators = companies
    alpha, beta = scopes
    seed(alpha, (1,))
    seed(beta, (2,))
    key = issue(owner, alpha)
    listing = owner.get(f'/org/{alpha.id}/api/integration-keys').json()['items']
    assert 'key' not in listing[0] and 'secret_hash' not in listing[0]
    with control_session() as db:
        assert db.get(IntegrationKey, key['id']).secret_hash == digest(key['key'])
    assert operators[0].post(f'/org/{alpha.id}/api/integration-keys', json={'name':'bad','scopes':['photos:read']}).status_code == 403
    assert owner.get(PREFIX+'/photos/2', headers={**headers(key), 'X-Organization-Id':beta.id}).status_code == 404
    assert owner.get(PREFIX+'/photos/1', headers=headers(key)).status_code == 200
    assert owner.get(f'/org/{beta.id}'+PREFIX+'/photos/2', headers=headers(key)).status_code == 404
    assert owner.get(PREFIX+'/photos/1', headers={'Authorization':'Bearer invalid'}).status_code == 401
    limited = issue(owner, alpha, ['photos:read'])
    assert owner.get(PREFIX+'/changes', params={'cursor':'bad'}, headers=headers(limited)).status_code == 403
    assert owner.get(PREFIX+'/photos/1/original', headers=headers(limited)).status_code == 403
    foreign = issue(owner, beta)
    snap = snapshot(owner, key)
    assert owner.get(PREFIX+f'/snapshots/{snap["id"]}/photos', headers=headers(foreign)).status_code == 404
    assert owner.get(PREFIX+'/changes', params={'cursor':snap['cursor']}, headers=headers(foreign)).status_code == 400
    with control_session() as db:
        db.get(IntegrationKey, key['id']).expires_at = now()-timedelta(seconds=1)
        db.commit()
    assert owner.get(PREFIX+'/photos/1', headers=headers(key)).status_code == 401
    rotated = owner.post(f'/org/{alpha.id}/api/integration-keys/{limited["id"]}/rotate').json()
    assert owner.get(PREFIX+'/photos/1', headers=headers(limited)).status_code == 401
    assert owner.get(PREFIX+'/photos/1', headers=headers(rotated)).status_code == 200
    with control_session() as db:
        record = db.get(IntegrationKey, rotated['id'])
        record.requests, record.window = 60, int(now().timestamp())//60
        db.commit()
    assert owner.get(PREFIX+'/photos/1', headers={**headers(rotated),'X-Forwarded-For':'203.0.113.50'}).status_code == 429
    assert owner.delete(f'/org/{alpha.id}/api/integration-keys/{rotated["id"]}').status_code == 200
    assert owner.get(PREFIX+'/photos/1', headers=headers(rotated)).status_code == 401
    with control_session() as db:
        db.get(Organization, beta.id).status = 'PAUSED'
        db.commit()
    assert owner.get(PREFIX+'/photos/2', headers=headers(foreign)).status_code == 401


def test_snapshot_changes_date_deletion_and_originals(companies, monkeypatch):
    owner, (alpha, _), _ = companies
    seed(alpha)
    key = issue(owner, alpha)
    snap = snapshot(owner, key, photo_date='2026-11-05')
    first = owner.get(PREFIX+f'/snapshots/{snap["id"]}/photos?limit=1', headers=headers(key)).json()
    assert first['items'][0]['id'] == 1 and first['next_after_id'] == 1
    assert first['items'][0]['received_at'] == '2026-11-05T00:00:00+05:00'
    assert first['items'][0]['captured_at'] == '2026-11-05T00:59:00+05:00'
    with organization_scope(alpha), Session(engine()) as db:
        db.get(Photo, 1).photo_date = date(2026, 11, 6)
        db.get(Photo, 2).preview_removed_at = now()
        db.get(Photo, 3).yandex_disk_path = 'disk:/private-original'
        db.commit()
    # Immutable pagination still contains the old date and the subsequently hidden row.
    page = owner.get(PREFIX+f'/snapshots/{snap["id"]}/photos?after_id=1', headers=headers(key)).json()
    assert [p['id'] for p in page['items']] == [2,3]
    day = snapshot(owner, key, photo_date='2026-11-05')
    day_rows = owner.get(PREFIX+f'/snapshots/{day["id"]}/photos', headers=headers(key)).json()['items']
    assert [p['id'] for p in day_rows] == [3]
    cursor = snap['cursor']
    received = []
    while True:
        result = owner.get(PREFIX+'/changes', params={'cursor':cursor,'limit':1}, headers=headers(key)).json()
        received += result['items']
        cursor = result['cursor']
        if not result['has_more']:
            break
    assert {(r['id'],r['operation']) for r in received} == {(1,'upsert'),(2,'delete'),(3,'upsert')}
    assert received[0]['data']['photo_date'] == '2026-11-06'
    replay = owner.get(PREFIX+'/changes', params={'cursor':snap['cursor']}, headers=headers(key)).json()
    assert replay['items'] == received
    assert owner.get(PREFIX+'/photos/2', headers=headers(key)).status_code == 404
    assert owner.get(PREFIX+'/photos/2/original', headers=headers(key)).status_code == 404
    def download(self, source, target):
        assert source == 'disk:/private-original'
        target.write_bytes(b'original-data')
    monkeypatch.setattr('app.integration_api.YandexDisk.download', download)
    original = owner.get(PREFIX+'/photos/3/original', headers=headers(key))
    assert original.status_code == 200 and original.content == b'original-data' and 'location' not in original.headers
    with organization_scope(alpha), Session(engine()) as db:
        db.delete(db.get(Photo, 3))
        db.commit()
    removed = owner.get(PREFIX+'/changes', params={'cursor':cursor}, headers=headers(key)).json()['items']
    assert removed[0]['id'] == 3 and removed[0]['operation'] == 'delete'
    assert owner.get(PREFIX+f'/snapshots/{snap["id"]}/photos?limit=101', headers=headers(key)).status_code == 422
    assert owner.delete(PREFIX+f'/snapshots/{day["id"]}', headers=headers(key)).status_code == 204


def test_journal_orders_commits_not_sequence_allocation(db):
    # Different rows, concurrent transactions: the journal lock must prevent a
    # later sequence from becoming visible before the first writer commits.
    db.add_all([Inbox(id=i,max_chat_id=1,message_id=str(i),payload={}) for i in (1,2)])
    db.flush()
    db.add_all([Photo(id=i,inbox_id=i,attachment_index=0,max_chat_id=1,chat_name='T',max_message_id=str(i),cohort='test') for i in (1,2)])
    db.commit()
    started = Event()
    def second():
        with Session(engine()) as writer:
            started.set()
            writer.execute(update(Photo).where(Photo.id==2).values(status='ACCEPTED'))
            writer.commit()
    with Session(engine()) as first, ThreadPoolExecutor(max_workers=1) as workers:
        first.execute(update(Photo).where(Photo.id==1).values(status='NEEDS_REVIEW'))
        future = workers.submit(second)
        assert started.wait(5)
        # pg_stat_activity confirms the second write is actually blocked on our lock.
        try:
            for _ in range(100):
                db.execute(text('SELECT pg_stat_clear_snapshot()'))
                waiting = db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE 'UPDATE photos%'"))
                if waiting:
                    break
                sleep(0.01)
            assert waiting
            assert not future.done()
        finally:
            first.commit()
        future.result(timeout=10)
    rows = list(db.scalars(select(IntegrationChange).order_by(IntegrationChange.sequence)))
    assert [r.entity_id for r in rows][-2:] == [1,2]


def test_geozones_retention_expired_snapshots_and_byte_budgets(companies):
    from app.models import District, IntegrationBudget, IntegrationSnapshot
    owner, (alpha,beta), _ = companies
    key = issue(owner, alpha)
    initial = snapshot(owner, key)
    with organization_scope(alpha), Session(engine()) as db:
        db.add(District(id=10, name='Микрорайон 10', active=True,
                       geometry='SRID=4326;MULTIPOLYGON(((0 0,0 1,1 1,1 0,0 0)))'))
        db.commit()
    zone = owner.get(PREFIX+'/geozones/10', headers=headers(key))
    assert zone.json() == {'id':10,'name':'Микрорайон 10','active':True}
    foreign = issue(owner, beta)
    assert owner.get(PREFIX+'/geozones/10', headers=headers(foreign)).status_code == 404
    events = owner.get(PREFIX+'/changes', params={'cursor':initial['cursor']}, headers=headers(key)).json()['items']
    assert events[0]['entity'] == 'geozone' and events[0]['data']['name'] == 'Микрорайон 10'
    with organization_scope(alpha), Session(engine()) as db:
        db.get(District,10).name = 'Новое имя'
        db.commit()
        db.delete(db.get(District,10))
        db.commit()
        for record in db.scalars(select(IntegrationChange)):
            record.at = now()-timedelta(days=31)
        db.commit()
    fresh = snapshot(owner, key)
    assert owner.get(PREFIX+'/changes', params={'cursor':initial['cursor']}, headers=headers(key)).status_code == 410
    with organization_scope(alpha), Session(engine()) as db:
        db.get(IntegrationSnapshot, fresh['id']).expires_at = now()-timedelta(seconds=1)
        db.commit()
    assert owner.get(PREFIX+f'/snapshots/{fresh["id"]}/geozones', headers=headers(key)).status_code == 410
    with control_session() as db:
        record = db.get(IntegrationKey,key['id'])
        record.reserved_bytes, record.window = 256*1024*1024, int(now().timestamp())//60
        db.commit()
    assert owner.get(PREFIX+'/geozones/10', headers=headers(key)).status_code == 429
    with control_session() as db:
        db.get(IntegrationKey,key['id']).reserved_bytes = 0
        budget = db.get(IntegrationBudget,alpha.id)
        budget.requests, budget.window = 180, int(now().timestamp())//60
        db.commit()
    assert owner.get(PREFIX+'/geozones/10', headers={**headers(key),'X-Forwarded-For':'192.0.2.20'}).status_code == 429


def test_transport_and_access_logs_do_not_expose_credentials(monkeypatch):
    import logging

    from starlette.requests import Request

    from app.integration_access import IntegrationAccessLogFilter, authenticate

    monkeypatch.setattr('app.integration_access.base_settings', lambda: SimpleNamespace(
        organizations_enabled=True, app_env='production'))
    request = Request({'type':'http','path':PREFIX+'/changes','scheme':'http',
                       'server':('example.test',80),'headers':[],'query_string':b''})
    with pytest.raises(HTTPException) as exc:
        authenticate(request)
    assert exc.value.status_code == 400
    access = IntegrationAccessLogFilter()
    record = logging.LogRecord('uvicorn.access',20,'',0,'%s %s %s %s %s',
                               ('client','GET',PREFIX+'/changes?cursor=PRIVATE_CURSOR','1.1',200),None)
    assert access.filter(record) is False
    record.args = ('client','GET','/api/health','1.1',200)
    assert access.filter(record) is True
