"""Explicit offline cutover of an existing standalone company, preserving its identifiers."""

import hashlib
import secrets
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.auth import hasher
from app.db import Base, database_engine
from app.disk_folders import DiskRoots
from app.models import (
    Chat,
    DiskFolderSettings,
    ExchangeState,
    LoginSession,
    ModelVersion,
    Organization,
    OrganizationChat,
    Photo,
    User,
    WorkType,
)
from app.organization_context import organization_scope
from app.organization_registry import control_session, lifecycle_lock, scope_for


def prepare(id):
    """Only a never-used, paused workspace may be emptied to receive a data-only backup."""
    id = str(UUID(id))
    with lifecycle_lock(), control_session() as control:
        record = control.get(Organization, id, with_for_update=True)
        if not record or record.legacy or record.status != "PAUSED":
            raise ValueError("Для переноса создайте новую организацию и приостановите её")
        scope = scope_for(record)
        with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
            for table in (Photo, Chat, WorkType, ModelVersion):
                if tenant.scalar(select(func.count()).select_from(table)):
                    raise ValueError("Организация уже использовалась. Создайте новую; существующие данные не удалены")
            if tenant.scalar(select(func.count()).select_from(User)) != 1:
                raise ValueError("В организации уже созданы операторы; существующие данные не удалены")
            if control.scalar(select(OrganizationChat.max_chat_id).where(OrganizationChat.organization_id == id)):
                raise ValueError("За организацией уже закреплены чаты")
            record.status = "IMPORTING"
            control.commit()  # All HTTP access and workers are blocked throughout the import.
            tables = ", ".join('"' + table.name + '"' for table in reversed(Base.metadata.sorted_tables))
            tenant.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            tenant.commit()
        return record.database_name, scope.data_dir


def finish(id, *, old_data_dir, roots):
    id = str(UUID(id))
    with lifecycle_lock(), control_session() as control:
        record = control.get(Organization, id, with_for_update=True)
        if not record or record.legacy or record.status != "IMPORTING":
            raise ValueError("Организация не подготовлена для переноса")
        scope = scope_for(record)
        old_root = Path(old_data_dir)
        with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
            if not tenant.scalar(select(User.id).limit(1)) or tenant.get(ExchangeState, 1) is None:
                raise ValueError("Восстановите полную копию данных исходной компании")
            instance_id = tenant.get(ExchangeState, 1).instance_id
            for other in control.scalars(select(Organization).where(
                Organization.id != id, Organization.status.in_(["ACTIVE", "PAUSED"])
            )):
                other_scope = scope_for(other)
                with Session(database_engine(other_scope.database_url)) as other_db:
                    state = other_db.get(ExchangeState, 1)
                    if state and state.instance_id == instance_id:
                        raise ValueError("Копия этой компании уже подключена к сервису")
            chats = list(tenant.scalars(select(Chat)))
            for chat in sorted(chats, key=lambda row: row.max_chat_id):
                control.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:chat, 7010))"),
                                {"chat": str(chat.max_chat_id)})
                binding = control.get(OrganizationChat, chat.max_chat_id)
                if binding and binding.organization_id != id:
                    raise ValueError("MAX chat ID уже принадлежит другой компании: " + str(chat.max_chat_id))
            for version in tenant.scalars(select(ModelVersion).where(ModelVersion.model_path.is_not(None))):
                try:
                    current_path = Path(version.model_path)
                    try:
                        relative = current_path.relative_to(scope.data_dir / "models")
                    except ValueError:
                        relative = current_path.relative_to(old_root / "models")
                except ValueError as exc:
                    raise ValueError("Путь модели находится вне папки моделей исходной компании") from exc
                target = scope.data_dir / "models" / relative
                if not target.resolve().is_relative_to((scope.data_dir / "models").resolve()):
                    raise ValueError("Недопустимый путь модели")
                if version.status == "ACTIVE":
                    if not target.is_file():
                        raise ValueError("Не скопирован файл действующей модели")
                    with target.open("rb") as file:
                        if hashlib.file_digest(file, "sha256").hexdigest() != version.model_sha256:
                            raise ValueError("Контрольная сумма действующей модели не совпадает")
                version.model_path = str(target)
            actor = tenant.scalar(select(User).where(User.login == "platform-owner"))
            if actor is None:
                actor = User(login="platform-owner", name="Владелец сервиса", role="ADMIN_OPERATOR", active=True,
                             password_hash=hasher.hash(secrets.token_urlsafe(48)))
                tenant.add(actor)
                tenant.flush()
            actor.role, actor.active, actor.allowed_chat_ids = "ADMIN_OPERATOR", True, None
            actor.password_hash = hasher.hash(secrets.token_urlsafe(48))
            folders = tenant.get(DiskFolderSettings, 1)
            if folders is None:
                raise ValueError("Сначала обновите исходную компанию до текущей версии")
            if not folders.folder_sets:
                # Keep original folder names when they were previously set only in .env.
                folders.folder_sets = [asdict(DiskRoots(**roots))]
            tenant.execute(delete(LoginSession))
            tenant.commit()
            for chat in chats:
                if control.get(OrganizationChat, chat.max_chat_id) is None:
                    control.add(OrganizationChat(max_chat_id=chat.max_chat_id, organization_id=id, name=chat.name))
            record.owner_user_id, record.status = actor.id, "PAUSED"
            control.commit()
        from app.signin_directory import sync_directory
        sync_directory(scope_for(record))
        return record.id
