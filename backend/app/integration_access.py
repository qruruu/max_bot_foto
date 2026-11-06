"""Application identities live in the control DB, separate from human sessions."""
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from app.auth import AdminUser, Db, digest
from app.config import base_settings
from app.domain import now
from app.models import IntegrationBudget, IntegrationKey, Organization
from app.organization_context import current_organization, organization_scope
from app.organization_registry import control_session, scope_for
from app.photo_scope import active_cohort
from app.security_telemetry import VerifiedApplication

PREFIX = '/api/integration/v1'
SCOPES = {'photos:read', 'geozones:read', 'work_types:read', 'changes:read', 'originals:read'}
RECORD_BYTES = 2 * 1024 * 1024
FILE_BYTES = 50 * 1024 * 1024
TOKEN = re.compile(r'^Bearer (metka_([0-9a-f-]{36})_[A-Za-z0-9_-]{64})$')


class IntegrationAccessLogFilter(logging.Filter):
    """The structured observer replaces URL-bearing Uvicorn access records."""
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            path = record.args[2].split('?', 1)[0]
            if path.startswith(PREFIX) or re.match(r'^/org/[0-9a-f-]{36}/api/integration', path):
                return False
        return True


logging.getLogger('uvicorn.access').addFilter(IntegrationAccessLogFilter())


class IntegrationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def resilient(request):
            try:
                return await handler(request)
            except SQLAlchemyError:
                raise HTTPException(503, 'API временно недоступен; повторите запрос') from None

        return resilient


router = APIRouter(prefix='/api/integration-keys', tags=['Application keys'], route_class=IntegrationRoute)


@dataclass(frozen=True)
class Application:
    id: str
    organization_id: str
    cohort: str
    scopes: frozenset[str]
    signing_key: str


def key_dict(key):
    return {name: getattr(key, name) for name in (
        'id', 'name', 'organization_id', 'cohort', 'scopes', 'created_at', 'expires_at',
        'revoked_at', 'last_used_at',
    )}


class CreateKey(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=len(SCOPES))
    expires_days: int = Field(default=90, ge=1, le=365)


def management_organization(request):
    organization = current_organization()
    if not organization or not base_settings().organizations_enabled:
        raise HTTPException(409, 'Сначала выберите организацию')
    if base_settings().app_env == 'production' and request.url.scheme != 'https':
        raise HTTPException(400, 'Для ключей требуется HTTPS')
    return organization


def new_key(organization_id, name, scopes, cohort, expires_days):
    id = str(uuid4())
    token = f'metka_{id}_{secrets.token_urlsafe(48)}'
    return IntegrationKey(id=id, organization_id=organization_id, name=name,
                          secret_hash=digest(token), scopes=sorted(scopes), cohort=cohort,
                          created_at=now(), expires_at=now() + timedelta(days=expires_days)), token


@router.get('')
def list_keys(request: Request, user: AdminUser):
    org = management_organization(request)
    with control_session() as control:
        return {'items': [key_dict(k) for k in control.scalars(select(IntegrationKey).where(
            IntegrationKey.organization_id == org.id).order_by(IntegrationKey.created_at.desc()).limit(200))]}


@router.post('', status_code=201)
def create_key(body: CreateKey, request: Request, db: Db, user: AdminUser):
    org = management_organization(request)
    if not set(body.scopes) <= SCOPES or not body.name.strip():
        raise HTTPException(422, 'Укажите название и допустимые права')
    with control_session() as control:
        record = control.scalar(select(Organization).where(Organization.id == org.id).with_for_update())
        if not record or record.status != 'ACTIVE':
            raise HTTPException(403, 'Организация неактивна')
        count = control.scalar(select(func.count()).select_from(IntegrationKey).where(
            IntegrationKey.organization_id == org.id, IntegrationKey.revoked_at.is_(None),
            IntegrationKey.expires_at > now()))
        if count >= 20:
            raise HTTPException(409, 'Допускается до 20 действующих ключей организации')
        key, token = new_key(org.id, body.name.strip(), body.scopes, active_cohort(db), body.expires_days)
        control.add(key)
        control.commit()
        return {**key_dict(key), 'key': token}


@router.delete('/{key_id}')
def revoke_key(key_id: str, request: Request, user: AdminUser):
    org = management_organization(request)
    with control_session() as control:
        key = control.scalar(select(IntegrationKey).where(
            IntegrationKey.id == key_id, IntegrationKey.organization_id == org.id).with_for_update())
        if not key:
            raise HTTPException(404, 'Ключ не найден')
        key.revoked_at = key.revoked_at or now()
        control.commit()
        return {'ok': True}


@router.post('/{key_id}/rotate', status_code=201)
def rotate_key(key_id: str, request: Request, user: AdminUser):
    org = management_organization(request)
    with control_session() as control:
        # Same lock order as creation/authentication: organization, then key.
        record = control.scalar(select(Organization).where(Organization.id == org.id).with_for_update())
        if not record or record.status != 'ACTIVE':
            raise HTTPException(403, 'Организация неактивна')
        key = control.scalar(select(IntegrationKey).where(
            IntegrationKey.id == key_id, IntegrationKey.organization_id == org.id).with_for_update())
        if not key or key.revoked_at:
            raise HTTPException(404, 'Действующий ключ не найден')
        replacement, token = new_key(org.id, key.name, key.scopes, key.cohort, 90)
        key.revoked_at = now()
        control.add(replacement)
        control.commit()
        return {**key_dict(replacement), 'key': token}


def authenticate(request):
    if not base_settings().organizations_enabled:
        raise HTTPException(503, 'API требует включённого режима организаций')
    if request.scope.get('root_path') or current_organization():
        raise HTTPException(404, 'Используйте общий адрес API')
    if base_settings().app_env == 'production' and request.url.scheme != 'https':
        raise HTTPException(400, 'Требуется HTTPS')
    match = TOKEN.fullmatch(request.headers.get('authorization', ''))
    if not match:
        raise HTTPException(401, 'Недействительный API-ключ')
    with control_session() as db:
        key = db.get(IntegrationKey, match[2])
        if not key or not secrets.compare_digest(key.secret_hash, digest(match[1])):
            raise HTTPException(401, 'Недействительный API-ключ')
        org = db.scalar(select(Organization).where(Organization.id == key.organization_id).with_for_update())
        # Refresh after acquiring the org lock so revocation cannot be missed.
        db.refresh(key, with_for_update=True)
        if key.revoked_at or key.expires_at <= now() or not org or org.status != 'ACTIVE':
            raise HTTPException(401, 'API-ключ недоступен')
        request.state.metka_verified_application = VerifiedApplication(key.id, org.id)
        minute = int(now().timestamp()) // 60
        db.execute(insert(IntegrationBudget).values(organization_id=org.id).on_conflict_do_nothing())
        budget = db.get(IntegrationBudget, org.id)
        # Original bytes are charged at their actual size before the response starts.
        reservation = 0 if request.url.path.endswith('/original') else RECORD_BYTES
        for item, req_limit, byte_limit in ((key, 60, 256 * 1024 * 1024), (budget, 180, 512 * 1024 * 1024)):
            if item.window != minute:
                item.window, item.requests, item.reserved_bytes = minute, 0, 0
            if item.requests >= req_limit or item.reserved_bytes + reservation > byte_limit:
                raise HTTPException(429, 'Лимит API; повторите через минуту', headers={'Retry-After': '60'})
            item.requests += 1
            item.reserved_bytes += reservation
        key.last_used_at = now()
        result = Application(key.id, org.id, key.cohort, frozenset(key.scopes), key.secret_hash)
        workspace = scope_for(org)
        db.commit()
        return result, workspace


def reserve_original(application, size):
    with control_session() as db:
        org = db.scalar(select(Organization).where(
            Organization.id == application.organization_id).with_for_update())
        key = db.scalar(select(IntegrationKey).where(IntegrationKey.id == application.id).with_for_update())
        if not org or org.status != 'ACTIVE' or not key or key.revoked_at or key.expires_at <= now():
            raise HTTPException(401, 'API-ключ недоступен')
        budget = db.get(IntegrationBudget, org.id)
        minute = int(now().timestamp()) // 60
        for item, cap in ((key, 256 * 1024 * 1024), (budget, 512 * 1024 * 1024)):
            if item.window != minute:
                item.window, item.requests, item.reserved_bytes = minute, 0, 0
            if item.reserved_bytes + size > cap:
                raise HTTPException(429, 'Лимит объёма API', headers={'Retry-After': '60'})
            item.reserved_bytes += size
        db.commit()


class IntegrationAccess:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not (scope['path'] == PREFIX or scope['path'].startswith(PREFIX + '/')):
            return await self.app(scope, receive, send)
        try:
            application, workspace = await run_in_threadpool(authenticate, Request(scope))
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, exc.status_code, headers=exc.headers)(scope, receive, send)
        except (OSError, ValueError, RuntimeError, SQLAlchemyError):
            return await JSONResponse({'detail': 'API временно недоступен'}, 503)(scope, receive, send)
        scope.setdefault('state', {})['integration_application'] = application
        with organization_scope(workspace):
            return await self.app(scope, receive, send)


def require_scope(request, permission):
    application = getattr(request.state, 'integration_application', None)
    if not isinstance(application, Application):
        raise HTTPException(401, 'Требуется API-ключ')
    if permission not in application.scopes:
        raise HTTPException(403, 'Недостаточно прав API-ключа')
    return application
