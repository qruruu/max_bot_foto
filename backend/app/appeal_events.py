"""Staff-only, organization-scoped appeal discussion and history."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import func, or_, select

from app.domain import now
from app.models import AppealEvent
from app.organization_context import current_organization
from app.schemas import StrictModel


class CommentInput(StrictModel):
    client_id: UUID
    comment: str = Field(min_length=1, max_length=4000)

    @field_validator("comment")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Напишите сообщение")
        return value.strip()


def actor_fields(user=None, *, inspector=False):
    return {"actor_type": "CITIZEN" if user is None else "INSPECTOR" if inspector else "ORGANIZATION_USER" if current_organization() else "OWNER",
            "actor_id": str(user.id) if user else "", "actor_name": user.name if user else "Житель",
            "actor_role": "INSPECTOR" if inspector else user.role if user else "CITIZEN"}


def record_event(db, appeal, kind, user=None, *, inspector=False, comment="", visibility="STAFF", operator_id=None,
                 client_id=None):
    event = AppealEvent(appeal_id=appeal.id, kind=kind, **actor_fields(user, inspector=inspector),
                        status=appeal.status, comment=comment, visibility=visibility, operator_id=operator_id,
                        client_id=str(client_id) if client_id else None)
    db.add(event)
    return event


def unanswered_comments(db, appeal_ids, user, *, inspector=False):
    """Other participants' messages since this person's last reply; viewing does not clear them."""
    if not appeal_ids:
        return {}
    actor = actor_fields(user, inspector=inspector)
    own = (AppealEvent.actor_type == actor["actor_type"]) & (AppealEvent.actor_id == actor["actor_id"])
    replies = select(AppealEvent.appeal_id, func.max(AppealEvent.id).label("last_reply")).where(
        AppealEvent.appeal_id.in_(appeal_ids), AppealEvent.kind == "COMMENT", own
    ).group_by(AppealEvent.appeal_id).subquery()
    return dict(db.execute(select(AppealEvent.appeal_id, func.count()).outerjoin(
        replies, replies.c.appeal_id == AppealEvent.appeal_id).where(
        AppealEvent.appeal_id.in_(appeal_ids), AppealEvent.kind == "COMMENT", AppealEvent.visibility == "STAFF",
        ~own, AppealEvent.id > func.coalesce(replies.c.last_reply, 0)
    ).group_by(AppealEvent.appeal_id)).all())


def event_page(db, appeal, *, user=None, inspector=False, before=0, after=0):
    conditions = [AppealEvent.appeal_id == appeal.id]
    if inspector:
        conditions.append(AppealEvent.visibility == "STAFF")
    elif user.role == "OPERATOR":
        conditions.append(or_(AppealEvent.visibility == "STAFF",
                              (AppealEvent.visibility == "TASK") & (AppealEvent.operator_id == user.id)))
    if before:
        conditions.append(AppealEvent.id < before)
    if after:
        conditions.append(AppealEvent.id > after)
    query = select(AppealEvent).where(*conditions)
    rows = list(db.scalars(query.order_by(AppealEvent.id if after else AppealEvent.id.desc()).limit(101)))
    more = len(rows) > 100
    rows = rows[:100]
    if not after:
        rows.reverse()
    return {"items": [{key: getattr(row, key) for key in (
        "id", "kind", "actor_name", "actor_role", "status", "comment", "visibility", "created_at")} for row in rows],
        "has_more": more, "can_comment": appeal.archived_at is None}


def add_comment(db, appeal, body, user, *, inspector=False):
    actor = actor_fields(user, inspector=inspector)
    existing = db.scalar(select(AppealEvent).where(AppealEvent.appeal_id == appeal.id,
        AppealEvent.actor_type == actor["actor_type"], AppealEvent.actor_id == actor["actor_id"],
        AppealEvent.client_id == str(body.client_id)))
    if existing:
        return {"id": existing.id}
    if appeal.archived_at:
        raise HTTPException(409, "Обращение в архиве. Сначала верните его из архива.")
    event = record_event(db, appeal, "COMMENT", user, inspector=inspector, comment=body.comment, client_id=body.client_id)
    appeal.updated_at = now()
    db.flush()
    db.commit()
    return {"id": event.id}
