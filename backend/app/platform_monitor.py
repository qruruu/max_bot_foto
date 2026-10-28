"""Local CLI ingestion; there is deliberately no public monitoring-ingest endpoint."""
import json
import logging
import math
import sys
from datetime import datetime, timedelta
from ipaddress import ip_address

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import base_settings
from app.db import database_engine
from app.domain import now
from app.models import ExchangeState, Job, ModelVersion, Organization, Photo, User
from app.organization_registry import control_session, scope_for
from app.platform_models import (
    PlatformActivity,
    PlatformPageView,
    PlatformRequestMinute,
    PlatformRuntime,
    PlatformSample,
    PlatformVisit,
)

log = logging.getLogger(__name__)


def organization_snapshot(record):
    scope = scope_for(record)
    with Session(database_engine(scope.database_url)) as db:
        db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        local_day = func.date(func.timezone(base_settings().app_timezone, Photo.received_at))
        counts = list(db.execute(select(Photo.cohort, local_day.label('day'), func.count().label('received'),
            func.count().filter(Photo.analyzed_at.is_not(None)).label('processed'),
            func.count().filter(Photo.status == 'ACCEPTED', Photo.work_type_source == 'AI').label('ai'),
            func.count().filter(Photo.work_type_source == 'OPERATOR').label('manual'))
            .where(Photo.received_at >= now() - timedelta(days=91)).group_by(Photo.cohort, local_day)))
        result = {'daily': [dict(cohort=r.cohort, day=r.day.isoformat(), received=r.received,
            processed=r.processed, ai=r.ai, manual=r.manual) for r in counts], 'cohorts': {}}
        for cohort in ('production', 'test'):
            statuses = dict(db.execute(select(Photo.status, func.count()).where(Photo.cohort == cohort)
                                       .group_by(Photo.status)).all())
            jobs = dict(db.execute(select(Job.status, func.count()).join(Photo, Photo.id == Job.object_id)
                .where(Photo.cohort == cohort, Job.kind.in_(['ANALYZE', 'SYNC', 'RELOCATE', 'TRAINING_RELOCATE']),
                       Job.status != 'DONE').group_by(Job.status)).all())
            oldest = db.scalar(select(func.min(Photo.received_at)).where(Photo.cohort == cohort,
                Photo.status.in_(['RECEIVED', 'PROCESSING'])))
            result['cohorts'][cohort] = {'statuses': statuses, 'jobs': jobs,
                'oldest_pending_at': oldest.isoformat() if oldest else None,
                'storage_pending': db.scalar(select(func.count()).select_from(Photo).where(Photo.cohort == cohort,
                    Photo.status == 'ACCEPTED', Photo.storage_status != 'SYNCED'))}
        state = db.get(ExchangeState, 1)
        result['mode'] = state.intake_cohort if state else 'test'
        result['operators'] = db.scalar(select(func.count()).select_from(User).where(User.active,
            User.id != record.owner_user_id))
        model = db.scalar(select(ModelVersion).where(ModelVersion.status == 'ACTIVE'))
        result['model'] = {'ready': model is not None, 'samples': model.sample_count if model else 0,
            'macro_f1': model.metrics.get('macro_f1') if model else None}
        return result


def save_runtime(key, data, instant=None):
    instant = instant or now()
    with control_session() as db:
        db.execute(insert(PlatformRuntime).values(key=key, sampled_at=instant, data=data)
            .on_conflict_do_update(index_elements=['key'], set_={'sampled_at': instant, 'data': data}))
        db.commit()


def ingest(payload):
    """Accept only output of the local host sampler, bounded and without shell content."""
    instant = now()
    if not isinstance(payload, dict) or payload.get('source') != 'linux-host':
        raise ValueError('Expected a Linux host sample')
    numeric = ('cpu_percent', 'iowait_percent', 'cpu_cores', 'load_1', 'load_5', 'load_15',
               'memory_total', 'memory_available', 'swap_total', 'swap_used', 'disk_total', 'disk_free',
               'disk_used', 'network_rx_bytes_sec', 'network_tx_bytes_sec', 'uptime_seconds')
    clean = {'source': 'linux-host'}
    for key in numeric:
        value = payload.get(key)
        if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError('Invalid host metric')
        clean[key] = value
    clean['services'] = [{'name': str(s['name'])[:40], 'running': bool(s.get('running')),
        'health': str(s.get('health', 'unknown'))[:20], 'restarts': int(s.get('restarts', 0)),
        'oom_killed': bool(s.get('oom_killed'))} for s in payload.get('services', [])[:30]]
    clean['backup'] = {key: payload.get('backup', {}).get(key) for key in (
        'last_success_at', 'last_attempt_ok', 'last_attempt_at', 'verified_at', 'verification_ok')}
    clean['security_sources'] = {key: bool(payload.get('security_sources', {}).get(key)) for key in ('ssh', 'edge')}
    ports = payload.get('ports')
    clean['ports'] = None if ports is None else [
        {'port': int(p['port']), 'public': bool(p.get('public')), 'binding': str(p.get('binding', ''))[:50]}
        for p in ports[:300] if isinstance(p, dict) and isinstance(p.get('port'), int) and 1 <= p['port'] <= 65535]
    clean['certificates'] = []
    for item in payload.get('certificates', [])[:20]:
        if not isinstance(item, dict):
            continue
        expiry = item.get('expires_at')
        try:
            if expiry and datetime.fromisoformat(expiry).tzinfo is None:
                expiry = None
        except (TypeError, ValueError):
            expiry = None
        clean['certificates'].append({'name': str(item.get('name', ''))[:100], 'expires_at': expiry})
    changed = payload.get('changed_source_files')
    clean['changed_source_files'] = max(0, min(changed, 100000)) if isinstance(changed, int) else None
    with control_session() as db:
        db.add(PlatformSample(at=instant, data=clean))
        db.commit()
        records = list(db.scalars(select(Organization).where(Organization.status.in_(['ACTIVE', 'PAUSED']))))
    from app.platform_security import alert, clean_label, record_security
    for event in payload.get('security_events', [])[:1000]:
        if event.get('kind') not in {'SSH_FAILED', 'SSH_SUCCESS', 'HTTP_PROBE', 'EDGE_RATE_LIMIT'}:
            continue
        try:
            context = {key: clean_label(event.get(key, ''), 100) for key in ('kind', 'actor_label', 'actor_key', 'resource', 'product')}
            context.update(ip_address=str(ip_address(event['ip_address'])),
                occurred_at=datetime.fromisoformat(event['at']), status_code=int(event.get('status_code', 0)))
            if context['occurred_at'].tzinfo is None or abs((instant - context['occurred_at']).total_seconds()) > 86400:
                continue
            record_security(context, external_id=clean_label(event['id'], 300))
        except (KeyError, ValueError, TypeError):
            continue
    with control_session() as db:
        context = {'ip_address': None, 'actor_label': 'Сервер', 'actor_key': 'host'}
        exposed = sorted({p['port'] for p in clean.get('ports') or [] if p.get('public')
                          and p.get('port') in {2375, 3306, 5432, 6379, 9200, 11211, 27017}})
        if exposed:
            alert(db, 'EXPOSED_SERVICE', 'Служебный порт слушает сетевой интерфейс: ' + ', '.join(map(str, exposed)),
                  'high', context, {'ports': exposed})
        if clean.get('changed_source_files'):
            alert(db, 'SOURCE_CHANGED', 'На сервере изменены отслеживаемые файлы приложения', 'warning', context,
                  {'changed_files': clean['changed_source_files']})
        for certificate in clean['certificates']:
            if not certificate.get('expires_at'):
                continue
            remaining = (datetime.fromisoformat(certificate['expires_at']) - instant).total_seconds() / 86400
            if remaining < 14:
                alert(db, 'CERTIFICATE_EXPIRING', 'Заканчивается HTTPS-сертификат: ' + certificate['name'],
                      'high' if remaining < 3 else 'warning', {**context, 'actor_key': 'certificate:' + certificate['name']},
                      {'days_left': round(remaining, 1), 'certificate': certificate['name']})
        db.commit()
    for record in records:
        try:
            data = organization_snapshot(record)
        except (OSError, ValueError, RuntimeError, SQLAlchemyError):
            # A failed company connection is explicit, never a zero value for its activity.
            data = {'unavailable': True}
        save_runtime('organization:' + record.id, data, instant)
    with control_session() as db:
        connections = db.scalar(text('SELECT count(*) FROM pg_stat_activity'))
        maximum = int(db.scalar(text('SHOW max_connections')))
        sizes = db.execute(text('SELECT datname, pg_database_size(oid) FROM pg_database '
                                "WHERE datname = current_database() OR datname LIKE 'org_%'")).all()
    save_runtime('database', {'connections': connections, 'max_connections': maximum,
                             'size_bytes': sum(row[1] for row in sizes)}, instant)
    with control_session() as db:
        cutoff = instant - timedelta(days=90)
        db.execute(delete(PlatformPageView).where(PlatformPageView.at < cutoff))
        db.execute(delete(PlatformVisit).where(PlatformVisit.last_seen_at < cutoff))
        db.execute(delete(PlatformActivity).where(PlatformActivity.day < cutoff.date()))
        db.execute(delete(PlatformSample).where(PlatformSample.at < instant - timedelta(days=30)))
        db.execute(delete(PlatformRequestMinute).where(PlatformRequestMinute.minute < instant - timedelta(days=30)))
        from app.platform_models import PlatformSecurityAlert, PlatformSecurityEvent
        db.execute(delete(PlatformSecurityEvent).where(PlatformSecurityEvent.at < instant - timedelta(days=30)))
        db.execute(delete(PlatformSecurityAlert).where(PlatformSecurityAlert.at < cutoff, PlatformSecurityAlert.reviewed_at.is_not(None)))
        db.commit()


if __name__ == '__main__':
    if sys.argv[1:] != ['ingest']:
        raise SystemExit('Usage: python -m app.platform_monitor ingest < sample.json')
    raw = sys.stdin.buffer.read(1_048_577)
    if len(raw) > 1_048_576:
        raise SystemExit('Sample too large')
    ingest(json.loads(raw))
    print('Monitoring sample saved')
