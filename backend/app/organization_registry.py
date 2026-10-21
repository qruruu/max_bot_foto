"""Platform registry and independently owned PostgreSQL workspaces."""

import json
import logging
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from alembic.config import Config
from psycopg import connect, sql
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.config import base_settings
from app.db import database_engine
from app.models import (
    Chat,
    DiskFolderSettings,
    MaxReceiverState,
    Organization,
    OrganizationChat,
    PlatformMaxReceiverState,
    PlatformOwner,
    User,
)
from app.organization_context import OrganizationScope, organization_scope

_provision_lock = RLock()
log = logging.getLogger(__name__)


@contextmanager
def lifecycle_lock():
    with _provision_lock, database_engine(base_settings().database_url).connect() as connection:
        if not connection.scalar(text("SELECT pg_try_advisory_lock(7009, 1)")):
            raise ValueError("Другая организация сейчас создаётся. Повторите немного позже.")
        connection.commit()
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(7009, 1)"))
            connection.commit()


@contextmanager
def control_session():
    with Session(database_engine(base_settings().database_url), expire_on_commit=False) as db:
        yield db


def organization_directory(id):
    return base_settings().data_dir / "organizations" / str(UUID(id))


def scope_for(record):
    cfg = base_settings()
    disk_token = None
    if record.disk_account_id:
        from app.disk_accounts import account_token
        disk_token = account_token(record.disk_account_id)
    if not record.owner_user_id:
        raise RuntimeError("ORGANIZATION_NOT_READY")
    if record.legacy:
        return OrganizationScope(record.id, record.name, cfg.database_url, cfg.data_dir, record.owner_user_id, disk_token)
    directory = organization_directory(record.id)
    secret = json.loads((directory / "database.json").read_text())
    url = make_url(cfg.database_url).set(database=record.database_name, username=record.database_role,
                                          password=secret["password"])
    return OrganizationScope(record.id, record.name, url.render_as_string(hide_password=False), directory,
                             record.owner_user_id, disk_token)


def scopes(*, include_paused=False):
    with control_session() as db:
        statuses = ["ACTIVE", "PAUSED"] if include_paused else ["ACTIVE"]
        result = []
        for record in db.scalars(
            select(Organization).where(Organization.status.in_(statuses)).order_by(Organization.id)
        ):
            try:
                result.append(scope_for(record))
            except (OSError, ValueError, RuntimeError):
                log.error("organization_unavailable=%s", record.id)
        return result


def bootstrap(owner_login, name, slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,59}", slug):
        raise ValueError("Use a lowercase organization slug of 2–60 letters/digits/hyphens")
    if not name.strip() or len(name.strip()) > 150:
        raise ValueError("Укажите название организации длиной до 150 символов")
    with lifecycle_lock(), control_session() as db:
        if db.scalar(select(Organization.id).limit(1)):
            raise ValueError("Organizations are already initialized")
        user = db.scalar(select(User).where(User.login == owner_login.lower(), User.active,
                                          User.role == "ADMIN_OPERATOR"))
        if user is None:
            raise ValueError("Choose an existing active administrator as platform owner")
        record = Organization(id=str(uuid4()), name=name, slug=slug, status="ACTIVE", legacy=True,
                              owner_user_id=user.id)
        db.add(record)
        db.add(PlatformOwner(user_id=user.id))
        receiver = db.get(MaxReceiverState, 1)
        if receiver and db.get(PlatformMaxReceiverState, 1) is None:
            db.add(PlatformMaxReceiverState(**{column.name: getattr(receiver, column.name)
                                              for column in MaxReceiverState.__table__.columns}))
        db.flush()
        db.add_all(OrganizationChat(max_chat_id=chat.max_chat_id, organization_id=record.id, name=chat.name)
                   for chat in db.scalars(select(Chat)))
        # A new company's database role must not connect to the legacy/control database.
        db.execute(text('REVOKE CONNECT ON DATABASE "' + db.bind.url.database.replace('"', '""') + '" FROM PUBLIC'))
        db.commit()
        from app.signin_directory import sync_directory
        sync_directory(scope_for(record))
        return record.id


def _create_database(record, password):
    url = make_url(base_settings().database_url)
    # Identifier names are generated UUIDs; SQL identifiers and literals are quoted separately.
    with connect(url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True) as db:
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (record.database_role,)).fetchone():
            db.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
                       .format(sql.Identifier(record.database_role), sql.Literal(password)))
        owner = db.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s",
                           (record.database_name,)).fetchone()
        if owner and owner[0] != record.database_role:
            raise ValueError("ORGANIZATION_DATABASE_CONFLICT")
        if not owner:
            db.execute(sql.SQL("CREATE DATABASE {} OWNER {}")
                       .format(sql.Identifier(record.database_name), sql.Identifier(record.database_role)))
        db.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(record.database_name)))
    admin_url = url.set(database=record.database_name)
    admin = create_engine(admin_url)
    try:
        with admin.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    finally:
        admin.dispose()


def provision(id):
    """Resumable provisioning never drops a database or overwrites an existing company."""
    with lifecycle_lock(), control_session() as db:
        record = db.get(Organization, id)
        if record is None or record.legacy or record.status not in {"PROVISIONING", "ERROR"}:
            raise ValueError("Organization cannot be provisioned")
        record.status, record.last_error = "PROVISIONING", None
        db.commit()
        try:
            directory = organization_directory(id)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            secret_file = directory / "database.json"
            if not secret_file.exists():
                with os.fdopen(os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
                    json.dump({"password": secrets.token_urlsafe(40)}, stream)
            password = json.loads(secret_file.read_text())["password"]
            _create_database(record, password)
            # A temporary owner id allows selecting this database during its migrations.
            record.owner_user_id = record.owner_user_id or 1
            scope = scope_for(record)
            with organization_scope(scope):
                config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
                config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
                command.upgrade(config, "head")
                with Session(database_engine(scope.database_url)) as tenant:
                    from app.auth import hasher
                    from app.disk_folders import company_roots
                    actor = tenant.scalar(select(User).where(User.login == "platform-owner"))
                    if actor is None:
                        actor = User(login="platform-owner", name="Владелец сервиса", role="ADMIN_OPERATOR",
                                     password_hash=hasher.hash(secrets.token_urlsafe(48)), active=True)
                        tenant.add(actor)
                        tenant.flush()
                    folders = tenant.get(DiskFolderSettings, 1)
                    if folders is None:
                        folders = DiskFolderSettings(id=1, version=1, folder_sets=[])
                        tenant.add(folders)
                    if not folders.folder_sets:
                        folders.folder_sets = [asdict(company_roots("MAX_PHOTOS_" + record.slug + "_" + id[:8]))]
                    record.owner_user_id = actor.id
                    tenant.commit()
            record.status = "ACTIVE"
        except Exception as exc:
            record.status, record.last_error = "ERROR", type(exc).__name__[:80]
            db.commit()
            raise RuntimeError("ORGANIZATION_PROVISIONING_FAILED") from exc
        db.commit()
        return record
