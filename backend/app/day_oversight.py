"""Read-only day progress, bounded by the viewer's current chat access."""

from datetime import UTC

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.chat_access import allowed_chat_ids, chat_condition
from app.day_verification import confirmed_condition
from app.models import Chat, DayClosure, DayClosureChat, DayPhotoReview, Photo, User
from app.organization_context import current_organization
from app.permissions import Permission, has_permission
from app.photo_scope import active_cohort
from app.reports import filtered
from app.schemas import PhotoFilters


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def operator_progress(db, viewer, day):
    chats = list(db.scalars(select(Chat).where(chat_condition(viewer, Chat.max_chat_id)).order_by(Chat.name, Chat.id)))
    if len(chats) < 2:
        raise HTTPException(403, "Контроль операторов доступен при доступе более чем к одному чату")
    by_max = {chat.max_chat_id: chat for chat in chats}
    cohort = active_cohort(db)
    base = filtered(PhotoFilters(review_day=day, work_only=True), viewer).where(
        Photo.max_chat_id.in_(by_max), Photo.cohort == cohort)
    stats = {cid: (total, confirmed) for cid, total, confirmed in db.execute(
        base.with_only_columns(Photo.max_chat_id, func.count(), func.count().filter(confirmed_condition()))
        .group_by(Photo.max_chat_id))}
    confirmations = list(db.execute(base.with_only_columns(
        Photo.max_chat_id, DayClosure.user_id, User.name, func.max(DayClosure.confirmed_at))
        .join(DayPhotoReview, DayPhotoReview.photo_id == Photo.id)
        .join(DayClosure, DayClosure.id == DayPhotoReview.closure_id)
        .join(User, User.id == DayClosure.user_id).where(confirmed_condition())
        .group_by(Photo.max_chat_id, DayClosure.user_id, User.name)))
    latest_reviews, confirmed_by = {}, {}
    for cid, _, name, instant in confirmations:
        instant = utc(instant)
        latest_reviews[cid] = max(instant, latest_reviews.get(cid, instant))
        confirmed_by.setdefault(cid, set()).add(name)

    closures = list(db.scalars(select(DayClosure).where(
        DayClosure.day == day, or_(DayClosure.cohort == cohort, DayClosure.cohort.is_(None)))))
    closure_ids = [row.id for row in closures]
    explicit = {}
    for closure_id, cid in db.execute(select(DayClosureChat.closure_id, DayClosureChat.max_chat_id).where(
        DayClosureChat.closure_id.in_(closure_ids), DayClosureChat.max_chat_id.in_(by_max))):
        explicit.setdefault(closure_id, set()).add(cid)
    inferred = {}
    for closure_id, cid in db.execute(select(DayPhotoReview.closure_id, Photo.max_chat_id)
        .join(Photo, Photo.id == DayPhotoReview.photo_id).where(
            DayPhotoReview.closure_id.in_(closure_ids), DayPhotoReview.cohort == cohort,
            Photo.max_chat_id.in_(by_max)).distinct()):
        inferred.setdefault(closure_id, set()).add(cid)
    cutoffs = {}
    for closure in closures:
        covered = (set(by_max) if closure.all_chats else explicit.get(closure.id, set())) if closure.cohort else inferred.get(closure.id, set())
        for cid in covered:
            key, instant = (closure.user_id, cid), utc(closure.confirmed_at)
            cutoffs[key] = max(instant, cutoffs.get(key, instant))

    scope = current_organization()
    items = []
    for operator in db.scalars(select(User).where(User.active).order_by(User.name, User.id)):
        if scope and operator.id == scope.owner_user_id and operator.login == "platform-owner":
            continue
        assigned = allowed_chat_ids(operator)
        visible = [chat for chat in chats if assigned is None or chat.id in assigned]
        if not visible:
            continue
        total = sum(stats.get(chat.max_chat_id, (0, 0))[0] for chat in visible)
        confirmed = sum(stats.get(chat.max_chat_id, (0, 0))[1] for chat in visible)
        pending = total - confirmed
        personal = [cutoffs[(operator.id, chat.max_chat_id)] for chat in visible if (operator.id, chat.max_chat_id) in cutoffs]
        can_close = has_permission(operator, Permission.DAYS_REVIEW)
        if not can_close:
            status = "NO_PERMISSION"
        elif not total:
            status = "NO_PHOTOS"
        elif pending:
            status = "ADDITIONS" if personal else "NOT_CLOSED"
        elif all((operator.id, chat.max_chat_id) in cutoffs and
                 latest_reviews.get(chat.max_chat_id, cutoffs[(operator.id, chat.max_chat_id)]) <= cutoffs[(operator.id, chat.max_chat_id)]
                 for chat in visible if stats.get(chat.max_chat_id, (0, 0))[0]):
            status = "CLOSED"
        else:
            status = "CLOSED_BY_OTHER"
        items.append({
            "id": operator.id, "name": operator.name, "status": status,
            "chats": [{"id": chat.id, "name": chat.name} for chat in visible],
            "total": total, "confirmed": confirmed, "pending": pending,
            "last_closed_at": max(personal) if personal else None,
            "confirmed_by": sorted({name for chat in visible for name in confirmed_by.get(chat.max_chat_id, set())}),
        })
    return {"day": day, "cohort": cohort, "items": items}
