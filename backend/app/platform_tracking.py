"""First-party, link-source analytics. Never store IPs, full URLs or form contents."""
import hashlib
import logging
import re
from threading import Lock
from time import perf_counter
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import Field, field_validator
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import base_settings
from app.domain import now
from app.organization_registry import control_session
from app.platform_models import (
    AnalyticsState,
    PlatformActivity,
    PlatformPageView,
    PlatformRequestMinute,
    PlatformVisit,
)
from app.schemas import StrictModel

log = logging.getLogger(__name__)
public_router = APIRouter(prefix='/api/public/metrics', tags=['usage'])
SOURCES = Literal['direct', 'max', 'telegram', 'vk', 'search', 'referral', 'qr']
PAGES = Literal['home', 'login', 'photos', 'photo_map', 'days', 'review', 'reports', 'messages',
                'appeals', 'appeal_form', 'appeal_sent', 'settings', 'news', 'other']
BUCKETS = (100, 300, 1000, 3000, 10000)


class VisitInput(StrictModel):
    visitor_id: UUID
    session_id: UUID
    event_id: UUID
    product: Literal['metka', 'signal']
    page: PAGES
    source: SOURCES = 'direct'
    referrer_host: str = Field(default='', max_length=253)
    device: Literal['desktop', 'phone', 'tablet', 'unknown'] = 'unknown'
    heartbeat: bool = False

    @field_validator('referrer_host')
    @classmethod
    def domain_only(cls, value):
        if value and not re.fullmatch(r'[a-zA-Z0-9.-]+', value):
            raise ValueError('Передавайте только имя сайта')
        return value.lower()


def visitor_key(id):
    return hashlib.sha256(('analytics:' + str(id)).encode()).hexdigest()


@public_router.post('/visit', status_code=204)
def visit(body: VisitInput, request: Request):
    cfg = base_settings()
    if not cfg.organizations_enabled:
        return Response(status_code=204)
    origins = {cfg.app_origin.rstrip('/'), cfg.public_appeals_origin.rstrip('/')} - {''}
    if request.headers.get('origin') not in origins or request.headers.get('x-usage-event') != 'page':
        raise HTTPException(403, 'Откройте приложение')
    if request.cookies.get('platform_session'):
        from app.organization_middleware import platform_login_session
        if platform_login_session(request):
            return Response(status_code=204)  # The owner's work must not inflate customer usage.
    from app.appeals import rate_limit
    try:
        with control_session() as db:
            rate_limit(db, request, 'usage', 180, 1)
            instant = now()
            key = visitor_key(body.visitor_id)
            existing = db.get(PlatformVisit, str(body.session_id))
            if existing and (existing.product != body.product or existing.visitor_key != key):
                raise HTTPException(409, 'Начните новое посещение')
            db.execute(insert(PlatformVisit).values(id=str(body.session_id), product=body.product,
                visitor_key=key, source=body.source, referrer_host=body.referrer_host, device=body.device,
                started_at=instant, last_seen_at=instant).on_conflict_do_update(
                    index_elements=['id'], set_={'last_seen_at': instant}))
            if not body.heartbeat:
                db.execute(insert(PlatformPageView).values(id=str(body.event_id), visit_id=str(body.session_id),
                    page=body.page, at=instant).on_conflict_do_nothing(index_elements=['id']))
            db.execute(insert(AnalyticsState).values(id=1, started_at=instant).on_conflict_do_nothing())
            db.commit()
    except SQLAlchemyError:
        # Auxiliary analytics must never break a submission or fill logs with client data.
        log.warning('usage_write_unavailable')
    return Response(status_code=204)


def record_operator_activity(activity):
    actor = activity.get('analytics_actor')
    if not actor or not base_settings().organizations_enabled:
        return
    instant = activity['at']
    day = instant.astimezone(ZoneInfo(base_settings().app_timezone)).date()
    try:
        with control_session() as db:
            db.execute(insert(PlatformActivity).values(day=day, actor_key=visitor_key(actor['key']),
                organization_id=actor.get('organization_id'), kind=actor['kind'], last_seen_at=instant)
                .on_conflict_do_update(index_elements=['day', 'actor_key'], set_={'last_seen_at': instant}))
            db.commit()
    except SQLAlchemyError:
        log.warning('usage_activity_unavailable')


def save_requests(product, minute, values):
    if not base_settings().organizations_enabled:
        return
    try:
        with control_session() as db:
            statement = insert(PlatformRequestMinute).values(minute=minute, product=product, **values)
            columns = PlatformRequestMinute
            db.execute(statement.on_conflict_do_update(index_elements=['minute', 'product'], set_={
                'requests': columns.requests + values['requests'], 'errors': columns.errors + values['errors'],
                'rejected': columns.rejected + values['rejected'], 'duration_ms': columns.duration_ms + values['duration_ms'],
                'maximum_ms': func.greatest(columns.maximum_ms, values['maximum_ms']),
                'buckets': func.jsonb_build_array(*[columns.buckets[i].as_integer() + n
                                                   for i, n in enumerate(values['buckets'])])}))
            db.commit()
    except SQLAlchemyError:
        log.warning('usage_request_metrics_unavailable')


class RequestMetricsMiddleware:
    """One small database write per minute, rather than a write for every API request."""
    def __init__(self, app, product='metka'):
        self.app, self.product = app, product
        self.lock = Lock()
        self.minute = None
        self.values = self.empty()

    @staticmethod
    def empty():
        return dict(requests=0, errors=0, rejected=0, duration_ms=0.0, maximum_ms=0.0, buckets=[0] * 6)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        previous = None
        if scope['type'] == 'http':
            minute = now().replace(second=0, microsecond=0)
            with self.lock:
                if self.minute is not None and self.minute != minute:
                    previous = (self.minute, self.values)
                    self.values = self.empty()
                    self.minute = None
            if previous:
                await run_in_threadpool(save_requests, self.product, *previous)
        if (scope['type'] != 'http' or '/api/' not in path or path.endswith('/health')
                or '/metrics/' in path):
            return await self.app(scope, receive, send)
        started, status = perf_counter(), 500

        async def observed_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        previous = None
        try:
            return await self.app(scope, receive, observed_send)
        finally:
            duration = (perf_counter() - started) * 1000
            minute = now().replace(second=0, microsecond=0)
            with self.lock:
                if self.minute is not None and self.minute != minute:
                    previous = (self.minute, self.values)
                    self.values = self.empty()
                self.minute = minute
                v = self.values
                v['requests'] += 1
                v['errors'] += int(status >= 500)
                v['rejected'] += int(400 <= status < 500)
                v['duration_ms'] += duration
                v['maximum_ms'] = max(v['maximum_ms'], duration)
                v['buckets'][sum(duration > edge for edge in BUCKETS)] += 1
            if previous:
                await run_in_threadpool(save_requests, self.product, *previous)
