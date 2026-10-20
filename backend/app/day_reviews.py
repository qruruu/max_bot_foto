"""Close a dated set across every authorized chat; later arrivals stay pending."""

import hashlib
import json
import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, text

from app.auth import Db, require_permission
from app.chat_access import allowed_chat_ids, chat_condition
from app.day_verification import SNAPSHOT_FIELDS
from app.domain import audit, now
from app.models import DayClosure, DayPhotoReview, Photo, User
from app.permissions import Permission
from app.reports import filtered
from app.schemas import PhotoFilters, StrictModel
from app.work_types import work_catalog

router = APIRouter(prefix="/api/day-reviews", tags=["day-reviews"])
DayReviewer = Annotated[User, Depends(require_permission(Permission.DAYS_REVIEW))]


class CloseDayInput(StrictModel):
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")


def selection(db, user, day, *, lock=False):
    stmt = filtered(PhotoFilters(review_day=day, work_only=True), user).add_columns(DayPhotoReview).outerjoin(
        DayPhotoReview, DayPhotoReview.photo_id == Photo.id
    ).order_by(Photo.id)
    if lock:
        stmt = stmt.with_for_update(of=Photo)
    return list(db.execute(stmt).all())


def is_confirmed(photo, review):
    return review is not None and photo.status == "ACCEPTED" and all(
        getattr(photo, key) == getattr(review, key) for key in SNAPSHOT_FIELDS
    )


def snapshot_token(rows, user, day):
    content = [
        [p.id, p.max_chat_id, p.status, bool(p.analyzed_at),
         *[getattr(p, key) for key in SNAPSHOT_FIELDS], r.closure_id if r else None]
        for p, r in rows
    ]
    value = [str(day), allowed_chat_ids(user), content]
    return hashlib.sha256(json.dumps(value, default=str, separators=(",", ":")).encode()).hexdigest()


def day_summary(db, user, day, rows):
    catalog = work_catalog(db)
    pending = [(p, r) for p, r in rows if not is_confirmed(p, r)]
    ai_pending = sum(p.work_type_source == "AI" for p, _ in pending)
    last_confirmation = db.scalar(
        select(DayClosure.confirmed_at).join(DayPhotoReview, DayPhotoReview.closure_id == DayClosure.id)
        .join(Photo, Photo.id == DayPhotoReview.photo_id)
        .where(DayClosure.day == day, chat_condition(user))
        .order_by(DayClosure.id.desc()).limit(1)
    )
    works = {}
    for p, r in rows:
        code = p.work_type or "NONE"
        entry = works.setdefault(code, {
            "code": code, "name": catalog.get(code, ("Не определён",))[0],
            "confirmed": 0, "pending": 0,
        })
        if is_confirmed(p, r):
            entry["confirmed"] += 1
        elif p.work_type_source == "AI":
            entry["pending"] += 1
    blocked = sum(p.status != "ACCEPTED" or not p.analyzed_at for p, _ in pending)
    return {
        "day": day, "total": len(rows), "confirmed": len(rows) - len(pending),
        "pending": len(pending), "new": sum(r is None for _, r in pending),
        "changed": sum(r is not None for _, r in pending), "blocked": blocked,
        "ai_pending": ai_pending, "manual_pending": len(pending) - ai_pending,
        "closed_before": last_confirmation is not None, "last_confirmation_at": last_confirmation,
        "can_close": bool(pending) and not blocked,
        "snapshot": snapshot_token(rows, user, day),
        "work_types": sorted(works.values(), key=lambda item: item["name"]),
    }


@router.get("/{day}")
def get_day(day: date, db: Db, user: DayReviewer):
    return day_summary(db, user, day, selection(db, user, day))


@router.post("/{day}/close")
def close_day(day: date, body: CloseDayInput, db: Db, user: DayReviewer):
    # All closures of the same date share a lock, even when operators' scopes overlap.
    db.execute(text("SELECT pg_advisory_xact_lock(7012, :day)"), {"day": day.toordinal()})
    rows = selection(db, user, day, lock=True)
    if not secrets.compare_digest(body.snapshot, snapshot_token(rows, user, day)):
        raise HTTPException(409, "Состав дня изменился. Обновите список и проверьте новые фотографии.")
    pending = [(p, r) for p, r in rows if not is_confirmed(p, r)]
    if not pending:
        raise HTTPException(409, "Нет новых фотографий для подтверждения.")
    if any(p.status != "ACCEPTED" or not p.analyzed_at for p, _ in pending):
        raise HTTPException(409, "Сначала разберите фотографии с вопросами или ошибками обработки.")
    closure = DayClosure(day=day, user_id=user.id, confirmed_at=now(), photo_count=len(pending))
    db.add(closure)
    db.flush()
    for photo, review in pending:
        if review is None:
            review = DayPhotoReview(photo_id=photo.id)
            db.add(review)
        review.closure_id = closure.id
        for key in SNAPSHOT_FIELDS:
            setattr(review, key, getattr(photo, key))
        # Per-photo audit entries obey the existing chat-scoped audit access rules.
        audit(db, user.id, "DAY_PHOTO_CONFIRMED", "photo", photo.id, None,
              {"day": str(day), "closure_id": closure.id})
    db.commit()
    return {"confirmed": len(pending), "day": day}
