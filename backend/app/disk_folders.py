"""Company folder settings, previous destinations and Disk ownership claims."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AdminUser, Db
from app.config import settings
from app.db import engine
from app.domain import audit
from app.integrations import YandexDisk
from app.models import Audit, DiskFolderSettings, ExchangeState
from app.schemas import StrictModel

router = APIRouter(prefix="/api/storage-folders", tags=["storage"])
OWNER_FILE = "_MAX_FOTO_OWNER.json"


@dataclass(frozen=True)
class DiskRoots:
    photo_root: str
    training_root: str
    spam_root: str
    exchange_root: str

    @property
    def yandex_disk_root(self):
        return self.photo_root

    @property
    def training_folder(self):
        return self.training_root

    @property
    def spam_folder(self):
        return self.spam_root

    @property
    def exchange_folder(self):
        return self.exchange_root

    def photo_roots(self):
        return (self.photo_root, self.training_root, self.spam_root)


def environment_roots():
    cfg = settings()
    return DiskRoots(cfg.yandex_disk_root, cfg.training_folder, cfg.spam_folder, cfg.exchange_folder)


def company_roots(name):
    return DiskRoots(name, name+"_TRAINING", name+"_SPAM", name+"_ARM_EXCHANGE")


def folder_sets(db):
    row = db.get(DiskFolderSettings, 1)
    return [DiskRoots(**values) for values in row.folder_sets] if row and row.folder_sets else [environment_roots()]


def current_disk_roots(db):
    return folder_sets(db)[-1]


def configured_disk_roots():
    with Session(engine()) as db:
        return current_disk_roots(db)


def known_photo_roots(db):
    return {root for group in folder_sets(db) for root in group.photo_roots()}


def roots_for_photo(db, photo):
    """Keep old photos, spam transitions and interrupted writes in their original folder family."""
    groups = folder_sets(db)
    path = photo.yandex_disk_path
    if not path:
        plan = db.scalar(select(Audit).where(
            Audit.photo_id == photo.id,
            Audit.action.in_(["STORAGE_TRANSFER_PLANNED", "TRAINING_RELOCATION_PLANNED"]),
        ).order_by(Audit.id.desc()).limit(1))
        if plan and (plan.old_value or {}).get("path") is None and (plan.new_value or {}).get("sha256") == photo.sha256:
            path = (plan.new_value or {}).get("path")
    if path:
        if ".." not in PurePosixPath(path).parts:
            for group in groups:
                if any(path.startswith(f"disk:/{root}/") for root in group.photo_roots()):
                    return group
        raise RuntimeError("INVALID_STORAGE_TRANSFER_PATH")
    return groups[-1]


class FolderChange(StrictModel):
    photo_root: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)

    @field_validator("photo_root")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value or value in {".", ".."}:
            raise ValueError("Укажите название папки компании")
        if any(ord(char) < 32 or ord(char) == 127 or char in '/\\:*?"<>|' for char in value):
            raise ValueError("Введите одно название папки без слешей, двоеточия и специальных символов")
        return value


def settings_dict(db):
    row = db.get(DiskFolderSettings, 1)
    return {"version": row.version if row else 1, **asdict(current_disk_roots(db))}


def claim_folders(disk, roots, instance_id):
    plans = []
    # Check every destination first. Never adopt an existing unowned archive.
    for kind, name in asdict(roots).items():
        data = json.dumps({"source_instance_id": instance_id, "purpose": kind, "schema_version": 1},
                          sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(data).hexdigest()
        target = f"disk:/{name}/{OWNER_FILE}"
        existing = disk.metadata(f"disk:/{name}")
        if existing and (existing.get("type") != "dir" or not disk.matches(target, digest)):
            raise HTTPException(409, f"Папка «{name}» уже существует и не принадлежит этой программе. Выберите другое название.")
        plans.append((target, data, digest))
    with TemporaryDirectory(prefix="max-folder-claim-") as temp:
        file = Path(temp)/OWNER_FILE
        for target, data, digest in plans:
            file.write_bytes(data)
            disk.upload(file, target, digest)


@router.get("")
def get_folder_settings(db: Db, user: AdminUser):
    return settings_dict(db)


@router.put("")
def change_folder_settings(body: FolderChange, db: Db, user: AdminUser):
    from app.exchange_housekeeping import publisher_lock
    from app.processing import storage_lock

    # Same lock order as archive organization. Each process reads settings from the DB.
    with publisher_lock(), storage_lock(shared=False):
        row = db.scalar(select(DiskFolderSettings).where(DiskFolderSettings.id == 1).with_for_update())
        if not row or row.version != body.version:
            raise HTTPException(409, "Настройки уже изменены. Обновите страницу.")
        before = settings_dict(db)
        if body.photo_root == before["photo_root"]:
            return before
        groups = folder_sets(db)
        roots = company_roots(body.photo_root)
        used = {name.casefold() for group in groups for name in asdict(group).values()}
        if any(name.casefold() in used for name in asdict(roots).values()):
            raise HTTPException(409, "Название пересекается с прежними папками этой программы. Выберите новое название.")
        state = db.get(ExchangeState, 1)
        try:
            claim_folders(YandexDisk(), roots, state.instance_id)
        except HTTPException:
            raise
        except RuntimeError as exc:
            if str(exc) == "YANDEX_DESTINATION_CONFLICT":
                raise HTTPException(409, "Папка занята другой программой. Выберите другое название.") from None
            raise HTTPException(503, "Не удалось проверить папки. Проверьте подключение Яндекс.Диска и повторите.") from None
        except Exception:
            raise HTTPException(503, "Не удалось проверить папки. Проверьте подключение Яндекс.Диска и повторите.") from None
        row.folder_sets = [asdict(group) for group in [*groups, roots]]
        row.version += 1
        after = settings_dict(db)
        audit(db, user.id, "DISK_FOLDERS_CHANGED", "disk_folder_settings", 1, before, after)
        db.commit()
        return after
