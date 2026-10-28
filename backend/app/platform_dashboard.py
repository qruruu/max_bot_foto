"""Aggregates are available only to the verified platform owner."""
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, or_, select

from app.auth import Db
from app.config import base_settings
from app.domain import now
from app.models import CitizenAppeal, Organization
from app.organizations import Owner
from app.platform_models import (
    AnalyticsState,
    PlatformActivity,
    PlatformPageView,
    PlatformRequestMinute,
    PlatformRuntime,
    PlatformSample,
    PlatformVisit,
)

router = APIRouter(prefix='/api/platform/metrics', tags=['owner dashboard'])
SOURCE_LABELS = {'direct': 'Прямые / источник не передан', 'max': 'MAX', 'telegram': 'Telegram',
                 'vk': 'ВКонтакте', 'search': 'Поисковые системы', 'referral': 'Другие сайты', 'qr': 'QR-код'}


def bounds(days):
    local = now().astimezone(ZoneInfo(base_settings().app_timezone))
    start = datetime.combine(local.date() - timedelta(days=days - 1), time.min, local.tzinfo)
    return start, local, start - timedelta(days=days)


def traffic(db, product, start, end):
    view, visit = PlatformPageView, PlatformVisit
    conditions = [visit.product == product, view.at >= start, view.at < end, view.page != 'appeal_sent']
    query = select(func.count(distinct(visit.visitor_key)), func.count(distinct(visit.id)), func.count(view.id))\
        .select_from(view).join(visit).where(*conditions)
    people, visits, views = db.execute(query).one()
    return {'visitors': people, 'visits': visits, 'views': views}


@router.get('/usage')
def usage(db: Db, user: Owner, days: int = Query(default=7, ge=1, le=90)):
    start, end, previous = bounds(days)
    view, visit = PlatformPageView, PlatformVisit
    products = {}
    local_day = func.date(func.timezone(base_settings().app_timezone, view.at))
    for product in ('metka', 'signal'):
        conditions = [visit.product == product, view.at >= start, view.at < end, view.page != 'appeal_sent']
        sources = db.execute(select(visit.source, visit.referrer_host, func.count(distinct(visit.id)))
            .select_from(view).join(visit).where(*conditions).group_by(visit.source, visit.referrer_host)).all()
        pages = db.execute(select(view.page, func.count()).select_from(view).join(visit)
            .where(*conditions).group_by(view.page).order_by(func.count().desc())).all()
        daily = db.execute(select(local_day, func.count(distinct(visit.visitor_key)), func.count())
            .select_from(view).join(visit).where(*conditions).group_by(local_day).order_by(local_day)).all()
        devices = db.execute(select(visit.device, func.count(distinct(visit.id))).select_from(view)
            .join(visit).where(*conditions).group_by(visit.device)).all()
        products[product] = {**traffic(db, product, start, end), 'previous': traffic(db, product, previous, previous + (end - start)),
            'online': db.scalar(select(func.count(distinct(visit.visitor_key))).where(
                visit.product == product, visit.last_seen_at >= end - timedelta(minutes=5))),
            'sources': [{'source': s, 'label': SOURCE_LABELS.get(s, s), 'host': host, 'visits': count}
                        for s, host, count in sorted(sources, key=lambda r: -r[2])],
            'pages': [{'page': page, 'views': count} for page, count in pages],
            'daily': [{'day': day.isoformat(), 'visitors': count, 'views': total} for day, count, total in daily],
            'devices': [{'device': device, 'visits': count} for device, count in devices]}
    state = db.get(AnalyticsState, 1)
    first = db.scalar(select(func.min(visit.started_at)))
    active = db.scalar(select(func.count(distinct(PlatformActivity.actor_key))).where(
        PlatformActivity.day >= start.date(), PlatformActivity.day <= end.date()))
    return {'at': end, 'timezone': base_settings().app_timezone, 'days': days,
            'collection_started_at': state.started_at if state else None, 'first_visit_at': first,
            'active_accounts': active, 'products': products}


@router.get('/metka')
def metka(db: Db, user: Owner, days: int = Query(default=7, ge=1, le=90),
          cohort: Literal['production', 'test', 'all'] = 'production'):
    start, end, _ = bounds(days)
    rows = []
    snapshots = {r.key: r for r in db.scalars(select(PlatformRuntime).where(PlatformRuntime.key.like('organization:%')))}
    for org in db.scalars(select(Organization).order_by(Organization.name)):
        snapshot = snapshots.get('organization:' + org.id)
        data = snapshot.data if snapshot else {}
        unavailable = not snapshot or data.get('unavailable') or snapshot.sampled_at < end - timedelta(minutes=5)
        activity = db.scalar(select(func.count(distinct(PlatformActivity.actor_key))).where(
            PlatformActivity.organization_id == org.id, PlatformActivity.day >= start.date(),
            PlatformActivity.day <= end.date()))
        row = {'id': org.id, 'name': org.name, 'status': org.status, 'mode': data.get('mode'),
            'sampled_at': snapshot.sampled_at if snapshot else None, 'unavailable': bool(unavailable),
            'active_accounts': activity, 'operators': data.get('operators'), 'model': data.get('model')}
        if not unavailable:
            selected = ['production', 'test'] if cohort == 'all' else [cohort]
            daily = [r for r in data.get('daily', []) if r['cohort'] in selected
                     and start.date().isoformat() <= r['day'] <= end.date().isoformat()]
            states = [data['cohorts'][value] for value in selected]
            counts = {key: sum(s['statuses'].get(key, 0) for s in states)
                      for key in ('RECEIVED', 'PROCESSING', 'ACCEPTED', 'NEEDS_REVIEW', 'ERROR')}
            oldest = [s['oldest_pending_at'] for s in states if s.get('oldest_pending_at')]
            row.update(received=sum(d['received'] for d in daily), processed=sum(d['processed'] for d in daily),
                ai=sum(d['ai'] for d in daily), manual=sum(d['manual'] for d in daily),
                pending=counts['RECEIVED'] + counts['PROCESSING'], review=counts['NEEDS_REVIEW'], errors=counts['ERROR'],
                storage_pending=sum(s.get('storage_pending', 0) for s in states),
                blocked=sum(s['jobs'].get('BLOCKED', 0) for s in states), daily=daily,
                oldest_pending_at=min(oldest) if oldest else None)
        rows.append(row)
    totals = {key: sum(row.get(key, 0) for row in rows if not row['unavailable'])
              for key in ('received', 'processed', 'ai', 'manual', 'pending', 'review', 'errors', 'storage_pending', 'blocked')}
    return {'at': end, 'cohort': cohort, 'days': days, 'organizations': rows, 'totals': totals,
            'available': sum(not r['unavailable'] for r in rows), 'total': len(rows),
            'active_accounts': sum(r['active_accounts'] for r in rows)}


@router.get('/signal')
def signal(db: Db, user: Owner, days: int = Query(default=7, ge=1, le=90)):
    start, end, _ = bounds(days)
    appeal = CitizenAppeal
    resident = [appeal.submitted_by_inspector_id.is_(None), appeal.status != 'SPAM']
    period = [*resident, appeal.created_at >= start, appeal.created_at < end]
    opened = ['NEW', 'IN_REVIEW', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'REJECTED', 'CANCELLED']
    received = db.scalar(select(func.count()).select_from(appeal).where(*period))
    closed = db.scalar(select(func.count()).select_from(appeal).where(*resident, appeal.status == 'RESOLVED',
        appeal.resolved_at >= start, appeal.resolved_at < end))
    refused = db.scalar(select(func.count()).select_from(appeal).where(*resident, appeal.status == 'DECLINED',
        appeal.resolved_at >= start, appeal.resolved_at < end))
    unassigned = db.scalar(select(func.count()).select_from(appeal).where(*resident, appeal.status.in_(['NEW', 'IN_REVIEW'])))
    aging = db.scalar(select(func.count()).select_from(appeal).where(*resident, appeal.status.in_(opened),
        appeal.created_at < end - timedelta(hours=24)))
    median = db.scalar(select(func.percentile_cont(0.5).within_group(func.extract('epoch', appeal.resolved_at - appeal.created_at)))
        .where(*resident, appeal.status == 'RESOLVED', appeal.resolved_at >= start, appeal.resolved_at < end))
    orgs = db.execute(select(appeal.organization_id, appeal.organization_name,
        func.count().filter(appeal.created_at >= start, appeal.created_at < end),
        func.count().filter(appeal.status.in_(opened)),
        func.count().filter(appeal.status == 'RESOLVED', appeal.resolved_at >= start, appeal.resolved_at < end))
        .where(*resident).group_by(appeal.organization_id, appeal.organization_name)).all()
    view, visit = PlatformPageView, PlatformVisit
    started = select(distinct(view.visit_id)).join(visit).where(visit.product == 'signal',
        view.page == 'appeal_form', view.at >= start, view.at < end)
    form_sessions = db.scalar(select(func.count()).select_from(started.subquery()))
    sent = db.scalar(select(func.count(distinct(view.visit_id))).where(view.page == 'appeal_sent',
        view.at >= start, view.at < end, view.visit_id.in_(started)))
    local_day = func.date(func.timezone(base_settings().app_timezone, appeal.created_at))
    daily = db.execute(select(local_day, func.count()).where(*period).group_by(local_day))
    return {'at': end, 'days': days, 'received': received, 'closed': closed, 'refused': refused,
        'unassigned': unassigned, 'open_over_24h': aging, 'median_resolution_seconds': median,
        'funnel': {'started': form_sessions, 'sent': sent},
        'daily': [{'day': str(day), 'received': count} for day, count in daily],
        'organizations': [{'id': id, 'name': name, 'received': got, 'open': pending, 'closed': done}
                          for id, name, got, pending, done in orgs]}


def request_summary(rows):
    total = sum(row.requests for row in rows)
    errors = sum(row.errors for row in rows)
    bins = [sum(row.buckets[i] for row in rows) for i in range(6)]
    percentile = None
    running = 0
    for boundary, count in zip([100, 300, 1000, 3000, 10000, None], bins, strict=True):
        running += count
        if total and running >= total * .95:
            percentile = boundary
            break
    return {'requests': total, 'errors': errors, 'rejected': sum(row.rejected for row in rows),
            'error_percent': round(errors / total * 100, 2) if total else None,
            'average_ms': sum(row.duration_ms for row in rows) / total if total else None,
            'p95_upper_ms': percentile, 'has_data': bool(total)}


@router.get('/server')
def server(db: Db, user: Owner, hours: int = Query(default=24, ge=1, le=168)):
    instant = now()
    latest = db.scalar(select(PlatformSample).order_by(PlatformSample.at.desc()).limit(1))
    fresh = bool(latest and latest.at >= instant - timedelta(minutes=5))
    samples = list(db.scalars(select(PlatformSample).where(PlatformSample.at >= instant - timedelta(hours=hours))
                             .order_by(PlatformSample.at)))
    step = max(1, (len(samples) + 499) // 500)
    history = [{'at': sample.at, **{key: sample.data.get(key) for key in ('cpu_percent', 'memory_available',
        'memory_total', 'disk_free', 'disk_total', 'load_1')}} for sample in samples[::step]]
    if samples and (not history or history[-1]['at'] != samples[-1].at):
        history.append({'at': samples[-1].at, **{key: samples[-1].data.get(key) for key in
            ('cpu_percent', 'memory_available', 'memory_total', 'disk_free', 'disk_total', 'load_1')}})
    requests = list(db.scalars(select(PlatformRequestMinute).where(
        PlatformRequestMinute.minute >= instant - timedelta(hours=hours))))
    database = db.get(PlatformRuntime, 'database')
    return {'at': instant, 'hours': hours, 'fresh': fresh, 'sampled_at': latest.at if latest else None,
        'current': latest.data if latest else None, 'history': history,
        'database': database.data if database and database.sampled_at >= instant - timedelta(minutes=5) else None,
        'requests': {product: request_summary([r for r in requests if r.product == product]) for product in ('metka', 'signal')}}


@router.get('/security')
def security(db: Db, user: Owner, days: int = Query(default=7, ge=1, le=90),
             page: int = Query(default=1, ge=1, le=10000)):
    from app.platform_models import PlatformSecurityAlert, PlatformSecurityEvent
    start, end, _ = bounds(days)
    event = PlatformSecurityEvent
    alerts = list(db.scalars(select(PlatformSecurityAlert).where(or_(PlatformSecurityAlert.at >= start,
                            PlatformSecurityAlert.reviewed_at.is_(None)))
                            .order_by(PlatformSecurityAlert.reviewed_at.is_not(None), PlatformSecurityAlert.last_at.desc()).limit(100)))
    events = list(db.scalars(select(event).where(event.at >= start).order_by(event.last_at.desc())
                            .offset((page - 1) * 50).limit(50)))
    failures, exports, downloads, size = db.execute(select(
        func.coalesce(func.sum(event.count).filter(event.kind.in_(['LOGIN_FAILED', 'SSH_FAILED'])), 0),
        func.coalesce(func.sum(event.count).filter(event.kind == 'EXPORT'), 0),
        func.coalesce(func.sum(event.count).filter(event.kind == 'DOWNLOAD'), 0),
        func.coalesce(func.sum(event.bytes_sent), 0)).where(event.at >= start)).one()
    return {'at': end, 'days': days, 'page': page, 'page_size': 50,
        'event_total': db.scalar(select(func.count()).select_from(event).where(event.at >= start)),
        'open_alerts': db.scalar(select(func.count()).select_from(PlatformSecurityAlert).where(PlatformSecurityAlert.reviewed_at.is_(None))),
        'totals': {'failed_logins': failures, 'exports': exports, 'downloads': downloads, 'bytes_sent': size},
        'alerts': [{key: getattr(row, key) for key in ('id', 'at', 'last_at', 'code', 'severity',
            'ip_address', 'actor_label', 'organization_id', 'summary', 'evidence', 'reviewed_at')} for row in alerts],
        'events': [{key: getattr(row, key) for key in ('id', 'at', 'last_at', 'product', 'kind',
            'ip_address', 'actor_label', 'organization_id', 'resource', 'count', 'bytes_sent', 'status_code')} for row in events],
        'rules': [{'title': 'Подбор пароля', 'detail': 'От 10 неудачных входов с одного IP за 10 минут'},
            {'title': 'Вход после ошибок', 'detail': 'Успешный вход после 5 неудачных с того же IP'},
            {'title': 'Ограничение входа', 'detail': 'Срабатывание существующего ограничения попыток входа'},
            {'title': 'Новый источник входа', 'detail': 'Новый IP аккаунта, у которого есть более ранняя история входов'},
            {'title': 'Массовая выгрузка', 'detail': 'От 100 скачиваний, 250 МиБ или 10 экспортов за 10 минут на аккаунт / IP'},
            {'title': 'Попытки доступа', 'detail': 'От 20 отказов или обращений к служебным ресурсам с одного IP за 10 минут'}]}


@router.post('/security/{alert_id}/review')
def review_security_alert(alert_id: str, db: Db, user: Owner):
    from fastapi import HTTPException

    from app.domain import audit
    from app.platform_models import PlatformSecurityAlert
    row = db.get(PlatformSecurityAlert, alert_id)
    if not row:
        raise HTTPException(404, 'Событие не найдено')
    row.reviewed_at = now()
    audit(db, user.id, 'SECURITY_ALERT_REVIEWED', 'security_alert', 0, None, {'alert_id': row.id})
    db.commit()
    return {'reviewed_at': row.reviewed_at}
