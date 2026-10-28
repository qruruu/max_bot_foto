"""Real control-database checks for analytics privacy, isolation and security evidence."""
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import app
from app.config import settings
from app.domain import now
from app.models import CitizenAppeal, Inbox, Photo
from app.organization_registry import bootstrap
from app.platform_models import (
    PlatformPageView,
    PlatformSecurityAlert,
    PlatformSecurityEvent,
    PlatformVisit,
)
from app.platform_security import record_security

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(db, users, monkeypatch):
    organization = bootstrap('admin', 'Компания', 'control-test')
    monkeypatch.setenv('ORGANIZATIONS_ENABLED', 'true')
    monkeypatch.setenv('PUBLIC_APPEALS_ORIGIN', 'https://signal.example')
    settings.cache_clear()
    with TestClient(app, client=('198.51.100.10', 50000)) as owner:
        result = owner.post('/api/auth/login', json={'login': 'admin', 'password': 'test-password-123'})
        assert result.status_code == 200, result.text
        owner.headers['X-CSRF-Token'] = owner.cookies['platform_csrf']
        yield owner, str(organization)


def visit(product='signal', page='appeal_form', **overrides):
    return dict(visitor_id=str(uuid4()), session_id=str(uuid4()), event_id=str(uuid4()),
                product=product, page=page, source='telegram', device='phone', **overrides)


HEADERS = {'Origin': 'http://testserver', 'X-Usage-Event': 'page'}


def test_collection_deduplicates_views_keeps_sources_and_excludes_owner(platform, db):
    owner, _ = platform
    payload = visit(referrer_host='t.me')
    assert owner.post('/api/public/metrics/visit', json=payload, headers=HEADERS).status_code == 204
    assert db.scalar(select(func.count()).select_from(PlatformVisit)) == 0
    with TestClient(app) as public:
        assert public.post('/api/public/metrics/visit', json=payload).status_code == 403
        for _ in range(2):
            assert public.post('/api/public/metrics/visit', json=payload, headers=HEADERS).status_code == 204
        heartbeat = {**payload, 'event_id': str(uuid4()), 'heartbeat': True}
        assert public.post('/api/public/metrics/visit', json=heartbeat, headers=HEADERS).status_code == 204
        assert public.post('/api/public/metrics/visit', json={**payload, 'visitor_id': str(uuid4())}, headers=HEADERS).status_code == 409
        assert public.post('/api/public/metrics/visit', json={**payload, 'referrer_host': 'https://t.me/?secret=password'}, headers=HEADERS).status_code == 422
        assert public.post('/api/public/metrics/visit', json={**payload, 'password': 'not-allowed'}, headers=HEADERS).status_code == 422
    assert db.scalar(select(func.count()).select_from(PlatformPageView)) == 1
    stored = db.scalar(select(PlatformVisit))
    assert stored.visitor_key != payload['visitor_id'] and len(stored.visitor_key) == 64
    data = owner.get('/api/platform/metrics/usage').json()
    assert data['products']['signal']['visitors'] == 1
    assert data['products']['signal']['views'] == 1
    assert data['products']['signal']['sources'][0]['source'] == 'telegram'
    assert data['products']['metka']['visitors'] == 0
    assert data['collection_started_at']


def test_owner_only_server_missing_is_not_zero_and_private_appeals_excluded(platform, db):
    owner, org_id = platform
    for endpoint in ('usage', 'metka', 'signal', 'server', 'security'):
        assert owner.get('/api/platform/metrics/'+endpoint).status_code == 200
    host = owner.get('/api/platform/metrics/server').json()
    assert host['current'] is None and not host['fresh']
    assert host['requests']['signal']['error_percent'] is None
    with TestClient(app) as outsider:
        assert outsider.get('/api/platform/metrics/security').status_code == 401
        result = outsider.post('/api/auth/login', json={'login': 'operator', 'password': 'test-password-123'})
        assert result.status_code == 200, result.text
        for endpoint in ('usage', 'metka', 'signal', 'server', 'security'):
            assert outsider.get('/api/platform/metrics/'+endpoint).status_code in (401, 403)
            assert outsider.get('/org/'+org_id+'/api/platform/metrics/'+endpoint).status_code == 404
    base = dict(organization_id=org_id, organization_name='Компания', city='Город', address='Улица',
                place='Двор', category='BIN_EMPTYING', description='Пример', contact='', photo_count=1)
    db.add_all([CitizenAppeal(**base, status='NEW', is_public=True), CitizenAppeal(**base, status='SPAM', is_public=False)])
    db.commit()
    data = owner.get('/api/platform/metrics/signal').json()
    assert data['received'] == data['unassigned'] == 1
    assert data['funnel'] == {'started': 0, 'sent': 0}
    assert owner.get('/api/platform/metrics/usage?days=999').status_code == 422


def test_security_real_login_failures_exports_deduplication_and_review(platform, db):
    owner, _ = platform
    with TestClient(app, client=('198.51.100.30', 50000)) as attacker:
        result = attacker.post('/api/auth/login', json={'login': 'unknown-account', 'password': 'secret-should-not-appear'})
        assert result.status_code == 401
    login = db.scalar(select(PlatformSecurityEvent).where(PlatformSecurityEvent.ip_address == '198.51.100.30'))
    assert login.kind == 'LOGIN_FAILED' and login.actor_label == 'unknown-account'
    assert 'secret-should-not-appear' not in str(login.__dict__)
    context = dict(product='metka', kind='LOGIN_FAILED', ip_address='198.51.100.50', actor_label='admin', resource='Вход')
    for _ in range(10):
        record_security(context)
    record_security({**context, 'kind':'LOGIN_SUCCESS', 'actor_key':'account:99'})
    record_security({**context, 'kind':'EXPORT', 'actor_key':'account:99', 'count':10, 'bytes_sent':1024})
    external = {**context, 'kind':'SSH_FAILED', 'actor_key':'ssh:root', 'occurred_at':now()-timedelta(seconds=40)}
    record_security(external, external_id='ssh:cursor-for-one-event')
    record_security(external, external_id='ssh:cursor-for-one-event')
    db.expire_all()
    event = db.scalar(select(PlatformSecurityEvent).where(PlatformSecurityEvent.kind == 'SSH_FAILED'))
    assert event.count == 1 and abs((event.at-external['occurred_at']).total_seconds()) < 1
    data = owner.get('/api/platform/metrics/security').json()
    codes = {a['code'] for a in data['alerts']}
    assert {'PASSWORD_GUESSING','LOGIN_AFTER_FAILURES','BULK_DOWNLOAD'} <= codes
    item = next(a for a in data['alerts'] if a['code'] == 'BULK_DOWNLOAD')
    assert item['evidence']['exports'] == 10 and item['evidence']['bytes'] == 1024
    path = '/api/platform/metrics/security/'+item['id']+'/review'
    assert owner.post(path, headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert owner.post(path).status_code == 200
    assert db.get(PlatformSecurityAlert, item['id']).reviewed_at is not None


def test_host_ingestion_real_snapshot_cohorts_and_ssh_evidence(platform, db):
    from app.platform_monitor import ingest
    owner, org_id = platform
    for mid, cohort, status in [('working','production','ACCEPTED'), ('testing','test','NEEDS_REVIEW')]:
        inbox = Inbox(max_chat_id=1, message_id=mid, payload={})
        db.add(inbox)
        db.flush()
        db.add(Photo(inbox_id=inbox.id, attachment_index=0, max_chat_id=1, chat_name='Chat',
                     max_message_id=mid, cohort=cohort, status=status,
                     work_type_source='AI' if cohort == 'production' else None, analyzed_at=now()))
    db.commit()
    # No made-up host values: absent metrics stay null. Photo counts are read from the actual test workspace.
    ingest({'source':'linux-host', 'services':[], 'backup':{}, 'security_sources':{'ssh':True,'edge':False},
            'ports':[{'port':5432,'public':True,'binding':'0.0.0.0'}],
            'changed_source_files':2, 'certificates':[{'name':'example.test','expires_at':(now()+timedelta(days=2)).isoformat()}]})
    result = owner.get('/api/platform/metrics/server').json()
    assert result['fresh'] and result['current']['cpu_percent'] is None
    assert result['database']['size_bytes'] > 0
    result = owner.get('/api/platform/metrics/metka').json()
    assert result['available'] == 1 and result['organizations'][0]['id'] == org_id
    assert result['totals']['received'] == 1 and result['totals']['ai'] == 1
    assert result['totals']['review'] == 0
    testing = owner.get('/api/platform/metrics/metka?cohort=test').json()
    assert testing['totals']['received'] == testing['totals']['review'] == 1
    assert owner.get('/api/platform/metrics/metka?cohort=all').json()['totals']['received'] == 2
    codes = {a['code'] for a in owner.get('/api/platform/metrics/security').json()['alerts']}
    assert {'EXPOSED_SERVICE','SOURCE_CHANGED','CERTIFICATE_EXPIRING'} <= codes
    with pytest.raises(ValueError):
        ingest({'source':'linux-host','cpu_percent':float('nan')})
