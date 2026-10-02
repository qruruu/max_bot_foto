import json
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog import WORK_TYPES, Status
from app.config import settings
from app.models import Audit, District, Job, Photo


def now():
    return datetime.now(UTC)


def audit(
    db: Session,
    user_id: int | None,
    action: str,
    object_type: str,
    object_id: int,
    old: dict | None,
    new: dict | None,
):
    db.add(
        Audit(
            user_id=user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            photo_id=object_id if object_type == "photo" else None,
            old_value=json.loads(json.dumps(old, default=str)),
            new_value=json.loads(json.dumps(new, default=str)),
        )
    )


def enqueue(db: Session, kind: str, object_id: int, key: str):
    db.execute(
        insert(Job)
        .values(kind=kind, object_id=object_id, dedupe_key=key, status="PENDING", attempts=0)
        .on_conflict_do_nothing(index_elements=[Job.dedupe_key])
    )


def resolve_district(db: Session, latitude: float | None, longitude: float | None):
    if latitude is None or longitude is None:
        return None, "COORDINATES_MISSING"
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    ids = db.scalars(
        select(District.id).where(District.active, func.ST_Covers(District.geometry, point))
    ).all()
    if len(ids) == 1:
        return ids[0], None
    return None, "DISTRICT_OVERLAP" if ids else "OUTSIDE_DISTRICTS"


def reassess(db: Session, photo: Photo):
    photo.district_id, geo_reason = resolve_district(db, photo.latitude, photo.longitude)
    reasons = []
    if photo.photo_date is None:
        reasons.append("DATE_MISSING")
    if geo_reason:
        reasons.append(geo_reason)
    if not photo.work_type:
        result = (photo.ai_result or {}).get("classification", {}).get("result")
        reasons.append("WORK_MULTIPLE" if result == "MULTIPLE" else "WORK_UNCERTAIN")
    photo.review_reason = reasons
    photo.status = Status.NEEDS_REVIEW if reasons else Status.ACCEPTED


def safe_component(value: str, limit: int = 45) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", value)
    value = re.sub(r"\s+", "_", value).strip(". _")
    return (value or "Без_названия")[:limit]


def storage_path(photo: Photo, district_name: str | None):
    folder_date = photo.photo_date.isoformat() if photo.photo_date else "ДАТА_НЕ_ОПРЕДЕЛЕНА"
    district = safe_component(district_name, 35) if district_name else "МР_НЕ_ОПРЕДЕЛЕН"
    work = WORK_TYPES[photo.work_type][1] if photo.work_type else "НЕ_ОПРЕДЕЛЕНО"
    filename = f"{district}_{work}_{photo.id}{photo.extension}"
    return f"disk:/{settings().yandex_disk_root}/{folder_date}/{safe_component(photo.chat_name)}/{filename}"


def bot_reply(photos: list[Photo], district_names: dict[int, str]) -> str:
    if len(photos) > 1:
        accepted = sum(p.status in {Status.ACCEPTED, Status.NEEDS_REVIEW} for p in photos)
        return f"✅ Обработано фотографий: {len(photos)}\nПринято: {accepted}\nНе принято: {len(photos) - accepted}"
    photo = photos[0]
    if photo.status == Status.FORWARDED:
        return "❌ Не принято: пересланные фотографии не принимаются."
    if photo.status == Status.DUPLICATE:
        return "❌ Не принято: фотография уже была отправлена."
    if photo.status == Status.REJECTED:
        if "UNSUPPORTED_FORMAT" in photo.review_reason:
            return "❌ Не принято: неподдерживаемый формат файла."
        return "❌ Не принято: файл изображения повреждён или не читается."
    text = "✅ Принято"
    if photo.district_id in district_names:
        text += f"\nМикрорайон: {district_names[photo.district_id]}"
        if photo.work_type:
            text += f"\nВид работы: {WORK_TYPES[photo.work_type][0]}"
    return text
