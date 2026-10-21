"""Reusable Yandex accounts; secret tokens stay outside database/API responses."""

import json
import os
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import Field, SecretStr
from sqlalchemy import select, text

from app.auth import Db
from app.config import base_settings
from app.domain import audit
from app.models import DiskAccount, Organization, Photo
from app.organization_context import current_organization
from app.organization_registry import scope_for
from app.organizations import Owner
from app.schemas import StrictModel

router = APIRouter(prefix="/api/platform/disk-accounts", tags=["organizations"])


def token_path(id):
    return base_settings().data_dir / "disk-accounts" / (str(UUID(id)) + ".json")


def account_token(id):
    return json.loads(token_path(id).read_text())["token"]


def configured_token():
    organization = current_organization()
    if organization is None or not base_settings().organizations_enabled:
        from app.config import settings
        return settings().yandex_disk_token
    from app.organization_registry import control_session
    with control_session() as db:
        record = db.get(Organization, organization.id)
        if not record or record.status not in {"ACTIVE", "PAUSED"}:
            raise RuntimeError("ORGANIZATION_NOT_AVAILABLE")
        return account_token(record.disk_account_id) if record.disk_account_id else base_settings().yandex_disk_token


def identify(token):
    if not token:
        raise HTTPException(409, "Яндекс.Диск ещё не подключён")
    try:
        response = httpx.get("https://cloud-api.yandex.net/v1/disk/", headers={"Authorization": "OAuth " + token},
                             params={"fields": "user"}, timeout=15)
        if response.status_code in {401, 403}:
            raise HTTPException(422, "Яндекс не принял токен. Проверьте доступ к Диску.")
        response.raise_for_status()
        user = response.json()["user"]
        uid, login = str(user["uid"]), user["login"]
        if not uid.isdigit() or not isinstance(login, str) or not login or len(login) > 150:
            raise ValueError()
        return uid, login
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "Не удалось проверить Яндекс.Диск. Повторите позже.") from exc


def account_dict(account):
    return {"id": account.id, "name": account.name, "login": account.login}


class AccountInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    token: SecretStr


@router.get("")
def accounts(db: Db, user: Owner):
    return {"default_configured": bool(base_settings().yandex_disk_token),
            "items": [account_dict(account) for account in db.scalars(select(DiskAccount).order_by(DiskAccount.name))]}


@router.post("", status_code=201)
def connect_account(body: AccountInput, db: Db, user: Owner):
    token = body.token.get_secret_value().strip()
    if not 10 <= len(token) <= 4096:
        raise HTTPException(422, "Укажите токен Яндекс.Диска")
    uid, login = identify(token)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:uid, 7012))"), {"uid": uid})
    account = db.scalar(select(DiskAccount).where(DiskAccount.yandex_uid == uid))
    if account is None:
        account = DiskAccount(id=str(uuid4()), name=body.name, yandex_uid=uid, login=login)
        db.add(account)
    account.name, account.login = body.name, login
    path = token_path(account.id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix("." + uuid4().hex + ".tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump({"token": token}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    audit(db, user.id, "DISK_ACCOUNT_CONNECTED", "disk_account", 0, None, account_dict(account))
    db.commit()
    return account_dict(account)


def validate_selection(db, record, selected_id):
    selected_id = str(selected_id) if selected_id else None
    selected = db.get(DiskAccount, selected_id) if selected_id else None
    if selected_id and selected is None:
        raise HTTPException(422, "Выберите подключённый Яндекс.Диск")
    if record and selected_id != record.disk_account_id:
        from sqlalchemy.orm import Session

        from app.db import database_engine
        scope = scope_for(record)
        with Session(database_engine(scope.database_url)) as tenant:
            has_photos = tenant.scalar(select(Photo.id).limit(1)) is not None
        if has_photos:
            previous = db.get(DiskAccount, record.disk_account_id) if record.disk_account_id else None
            old_uid = previous.yandex_uid if previous else identify(base_settings().yandex_disk_token)[0]
            new_uid = selected.yandex_uid if selected else identify(base_settings().yandex_disk_token)[0]
            if old_uid != new_uid:
                raise HTTPException(409, "В организации уже есть фотографии. Для смены диска нужен перенос оригиналов; текущий аккаунт можно переподключить.")
        elif record.status != "PAUSED":
            raise HTTPException(409, "Перед выбором другого диска приостановите организацию и сохраните настройку.")
    return selected_id
