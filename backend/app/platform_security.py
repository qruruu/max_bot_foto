"""Evidence-based owner alerts; never log bodies, passwords, cookies or signed URLs."""
import hashlib
import logging
from datetime import timedelta
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import base_settings
from app.domain import now
from app.organization_context import current_organization
from app.organization_registry import control_session
from app.platform_models import PlatformSecurityAlert, PlatformSecurityEvent
from app.session_details import client_address

log = logging.getLogger(__name__)
DOWNLOAD_LIMIT = 100
DOWNLOAD_BYTES = 250 * 1024 * 1024


def clean_label(value, maximum=150):
    return ''.join(c for c in str(value) if c.isprintable())[:maximum]


def actor_context(request, user, *, inspector=False):
    scope = current_organization()
    owner = bool(getattr(user, '_platform_owner', False))
    prefix = 'inspector' if inspector else 'owner' if owner else scope.id if scope else 'account'
    request.state.security_actor = {'key': f'{prefix}:{getattr(user, "_platform_user_id", None) or user.id}', 'label': clean_label(user.name),
        'organization_id': scope.id if scope and not inspector else None}


def alert(db, code, summary, severity, context, evidence):
    instant = context.get('occurred_at') or now()
    identity = context.get('actor_key') or context.get('ip_address') or 'host'
    key = hashlib.sha256(f'{code}:{identity}:{instant:%Y%m%d%H}'.encode()).hexdigest()
    data = dict(last_at=instant, summary=summary, evidence=evidence)
    db.execute(insert(PlatformSecurityAlert).values(id=key, at=instant, code=code, severity=severity,
        ip_address=context.get('ip_address'), actor_label=context.get('actor_label', ''),
        organization_id=context.get('organization_id'), **data)
        .on_conflict_do_update(index_elements=['id'], set_=data))


def detect(db, context):
    instant = now()
    cutoff = instant - timedelta(minutes=10)
    event = PlatformSecurityEvent
    ip = context.get('ip_address')
    actor = context.get('actor_key')
    if not ip and not actor:
        return
    failures = db.scalar(select(func.coalesce(func.sum(event.count), 0)).where(event.at >= cutoff,
        event.ip_address == ip, event.kind.in_(['LOGIN_FAILED', 'SSH_FAILED']))) if ip else 0
    if failures >= 10:
        alert(db, 'PASSWORD_GUESSING', f'{failures} неудачных входов за 10 минут с одного IP',
              'high', context, {'attempts': failures, 'window_minutes': 10})
    if context['kind'] in {'LOGIN_SUCCESS', 'SSH_SUCCESS'} and failures >= 5:
        alert(db, 'LOGIN_AFTER_FAILURES', 'Успешный вход после серии неудачных попыток с того же IP',
              'high', context, {'failed_attempts': failures, 'successful_login': True})
    if context['kind'] == 'LOGIN_SUCCESS' and actor and ip:
        known = db.scalar(select(PlatformSecurityEvent.id).where(PlatformSecurityEvent.actor_key == actor,
            PlatformSecurityEvent.kind == 'LOGIN_SUCCESS', PlatformSecurityEvent.at < cutoff).limit(1))
        known_source = db.scalar(select(PlatformSecurityEvent.id).where(PlatformSecurityEvent.actor_key == actor,
            PlatformSecurityEvent.kind == 'LOGIN_SUCCESS', PlatformSecurityEvent.ip_address == ip,
            PlatformSecurityEvent.at < cutoff).limit(1))
        if known and not known_source:
            alert(db, 'NEW_LOGIN_SOURCE', 'Успешный вход с IP, которого не было в сохранённой истории аккаунта',
                  'notice', context, {'source_ip': ip, 'reason': 'Это может быть новая сеть или VPN; проверьте вход'})
    if context['kind'] == 'LOGIN_RATE_LIMIT':
        alert(db, 'LOGIN_RATE_LIMIT', 'Сработало ограничение попыток входа. Новые попытки временно блокируются.',
              'warning', context, {'status_code': 429})
    if context['kind'] in {'DOWNLOAD', 'EXPORT'}:
        identity = event.actor_key == actor if actor else event.ip_address == ip
        count, size, exports = db.execute(select(func.coalesce(func.sum(event.count), 0),
            func.coalesce(func.sum(event.bytes_sent), 0),
            func.coalesce(func.sum(event.count).filter(event.kind == 'EXPORT'), 0))
            .where(event.at >= cutoff, identity, event.kind.in_(['DOWNLOAD', 'EXPORT']))).one()
        count, size, exports = int(count), int(size), int(exports)
        if count >= DOWNLOAD_LIMIT or size >= DOWNLOAD_BYTES or exports >= 10:
            alert(db, 'BULK_DOWNLOAD', f'За 10 минут выполнено {count} выдач файлов, включая {exports} экспортов',
                'warning', context, {'files': count, 'exports': exports, 'bytes': size,
                                     'window_minutes': 10, 'reason': 'Проверьте, соответствует ли выгрузка работе пользователя'})
    if ip and context['kind'] in {'ACCESS_DENIED', 'UNAUTHORIZED', 'HTTP_PROBE', 'EDGE_RATE_LIMIT'}:
        count = db.scalar(select(func.coalesce(func.sum(event.count), 0)).where(event.at >= cutoff,
            event.ip_address == ip, event.kind.in_(['ACCESS_DENIED', 'UNAUTHORIZED', 'HTTP_PROBE', 'EDGE_RATE_LIMIT'])))
        if count >= 20:
            alert(db, 'ACCESS_PROBING', f'{count} отказов или обращений к служебным ресурсам за 10 минут',
                'warning', context, {'requests': count, 'window_minutes': 10})


def record_security(context, *, external_id=None):
    if not base_settings().organizations_enabled:
        return
    instant = context.get('occurred_at') or now()
    minute = instant.replace(second=0, microsecond=0)
    identity = f"{context['kind']}:{context.get('ip_address')}:{context.get('actor_key') or context.get('actor_label')}:{context.get('resource')}:{minute.isoformat()}"
    key = hashlib.sha256((external_id or identity).encode()).hexdigest()
    data = {k: context.get(k, '') for k in ('product', 'kind', 'actor_key', 'actor_label', 'resource')}
    data.update(ip_address=context.get('ip_address'), organization_id=context.get('organization_id'),
                count=int(context.get('count', 1)), bytes_sent=int(context.get('bytes_sent', 0)),
                status_code=int(context.get('status_code', 0)))
    try:
        with control_session() as db:
            statement = insert(PlatformSecurityEvent).values(id=key, at=instant, last_at=instant, **data)
            if external_id:
                statement = statement.on_conflict_do_nothing(index_elements=['id'])
            else:
                statement = statement.on_conflict_do_update(index_elements=['id'], set_={
                    'last_at': instant, 'count': PlatformSecurityEvent.count + data['count'],
                    'bytes_sent': PlatformSecurityEvent.bytes_sent + data['bytes_sent']})
            result = db.execute(statement)
            if result.rowcount:
                detect(db, {**context, **data})
            db.commit()
    except SQLAlchemyError:
        log.warning('security_event_write_unavailable')


def classify(path, method, status, headers, query=b''):
    if method == 'POST' and path.endswith('/auth/login'):
        return 'LOGIN_FAILED' if status == 401 else 'LOGIN_RATE_LIMIT' if status == 429 else None
    if status == 403:
        return 'ACCESS_DENIED'
    if status == 401:
        return 'UNAUTHORIZED'
    if status not in {200, 206} or method != 'GET':
        return None
    if b'attachment' in headers.get(b'content-disposition', b'').lower() or path.endswith(('.xlsx', '.zip')):
        return 'EXPORT'
    if path.endswith('/original'):
        return 'DOWNLOAD'
    if '/photos/' in path and '/preview' not in path:
        # Only the allowlisted variant is inspected; query strings are never persisted.
        if parse_qs(query.decode(errors='replace')).get('variant', [''])[0] in {'original', 'stamped'}:
            return 'DOWNLOAD'
    return None


class SecurityMiddleware:
    def __init__(self, app, product='metka'):
        self.app, self.product = app, product

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or '/api/' not in path or '/public/metrics/' in path or path.endswith('/health'):
            return await self.app(scope, receive, send)
        status, size, response_headers = 500, 0, {}
        async def observed_send(message):
            nonlocal status, size, response_headers
            if message['type'] == 'http.response.start':
                status = message['status']
                response_headers = dict(message.get('headers', []))
            elif message['type'] == 'http.response.body':
                size += len(message.get('body', b''))
            await send(message)
        try:
            return await self.app(scope, receive, observed_send)
        finally:
            request = Request(scope)
            kind = classify(path, scope.get('method'), status, response_headers, scope.get('query_string', b''))
            actor = getattr(request.state, 'security_actor', {})
            if path.endswith('/auth/login') and status == 200 and actor:
                kind = 'LOGIN_SUCCESS'
            if kind:
                context = {'kind': kind, 'product': self.product, 'ip_address': client_address(request),
                    'actor_key': actor.get('key', ''), 'actor_label': actor.get('label') or clean_label(
                        getattr(request.state, 'security_login', 'Не авторизован')),
                    'organization_id': actor.get('organization_id'),
                    'resource': 'Вход' if '/auth/' in path else 'Экспорт' if kind == 'EXPORT' else
                                'Оригинал фото' if kind == 'DOWNLOAD' else 'Защищённый API',
                    'bytes_sent': size if kind in {'DOWNLOAD', 'EXPORT'} else 0, 'status_code': status}
                await run_in_threadpool(record_security, context)
