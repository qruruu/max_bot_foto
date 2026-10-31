"""Staff-only, organization-scoped appeal discussion and history."""

import base64
import binascii
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import aliased

from app.domain import now
from app.models import AppealEvent
from app.organization_context import current_organization
from app.schemas import StrictModel


class CommentInput(StrictModel):
    client_id: UUID
    comment: str = Field(default="", max_length=4000)
    channel: Literal["inspector", "executor"] | None = None
    screenshots: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("comment")
    @classmethod
    def nonempty(cls, value):
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


def unanswered_comments(db, appeal_ids, user, *, inspector=False, channel=None):
    """Other participants' messages since this person's last reply; viewing does not clear them."""
    if not appeal_ids:
        return {}
    from app.models import CitizenAppeal
    actor = actor_fields(user, inspector=inspector)
    reply = aliased(AppealEvent)
    def audience(event):
        return case((event.visibility == "INSPECTOR", "inspector"),
                    ((event.visibility == "STAFF") & CitizenAppeal.submitted_by_inspector_id.is_not(None), "inspector"),
                    else_="executor")
    last = select(func.max(reply.id)).where(
        reply.appeal_id == AppealEvent.appeal_id, reply.kind == "COMMENT",
        audience(reply) == audience(AppealEvent),
        reply.actor_type == actor["actor_type"], reply.actor_id == actor["actor_id"]
    ).correlate(AppealEvent, CitizenAppeal).scalar_subquery()
    conditions = [AppealEvent.appeal_id.in_(appeal_ids), AppealEvent.kind == "COMMENT",
                  ~((AppealEvent.actor_type == actor["actor_type"]) & (AppealEvent.actor_id == actor["actor_id"])),
                  AppealEvent.id > func.coalesce(last, 0)]
    if inspector:
        conditions.extend([CitizenAppeal.submitted_by_inspector_id.is_not(None),
                           AppealEvent.visibility.in_(["STAFF", "INSPECTOR"])])
    elif user.role == "OPERATOR":
        conditions.append(or_((AppealEvent.visibility == "TASK") & (AppealEvent.operator_id == user.id),
            (AppealEvent.visibility == "STAFF") & CitizenAppeal.submitted_by_inspector_id.is_(None)))
    if channel:
        conditions.append(audience(AppealEvent) == channel)
    return dict(db.execute(select(AppealEvent.appeal_id, func.count()).join(
        CitizenAppeal, CitizenAppeal.id == AppealEvent.appeal_id).where(*conditions)
        .group_by(AppealEvent.appeal_id)).all())


def event_page(db, appeal, *, user=None, inspector=False, before=0, after=0, channel=None):
    conditions = [AppealEvent.appeal_id == appeal.id]
    conditions.extend(visible_conditions(appeal, user=user, inspector=inspector, channel=channel))
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
    from app.appeal_files import file_dict
    from app.appeals import private_url
    from app.models import AppealFile
    url = (lambda path: f"/api/inspection/organizations/{appeal.organization_id}/appeals" + path) if inspector else private_url
    files = list(db.scalars(select(AppealFile).where(AppealFile.event_id.in_([row.id for row in rows]))))
    return {"items": [{"files": [file_dict(file, url) for file in files if file.event_id == row.id],
        **{key: getattr(row, key) for key in (
        "id", "kind", "actor_name", "actor_role", "status", "comment", "visibility", "created_at")}} for row in rows],
        "has_more": more,
        "unanswered_comments": unanswered_comments(db, [appeal.id], user, inspector=inspector,
            channel=resolve_channel(appeal, user=user, inspector=inspector, channel=channel)).get(appeal.id, 0),
        "can_comment": appeal.archived_at is None and (not inspector or bool(appeal.submitted_by_inspector_id))}


def add_comment(db, appeal, body, user, *, inspector=False):
    if inspector and not appeal.submitted_by_inspector_id:
        raise HTTPException(403, "Обращения граждан доступны проверяющему только для просмотра")
    channel = resolve_channel(appeal, user=user, inspector=inspector, channel=body.channel)
    actor = actor_fields(user, inspector=inspector)
    existing = db.scalar(select(AppealEvent).where(AppealEvent.appeal_id == appeal.id,
        AppealEvent.actor_type == actor["actor_type"], AppealEvent.actor_id == actor["actor_id"],
        AppealEvent.client_id == str(body.client_id)))
    if existing:
        return {"id": existing.id}
    if appeal.archived_at:
        raise HTTPException(409, "Обращение в архиве. Сначала верните его из архива.")
    from app.appeal_files import prepare_screenshot, store_files
    screenshots = []
    if not body.comment and not body.screenshots:
        raise HTTPException(422, "Напишите сообщение или приложите скриншот")
    for encoded in body.screenshots:
        if len(encoded) > 35 * 1024 * 1024:
            raise HTTPException(422, "Скриншот слишком большой")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, "Не удалось прочитать скриншот") from exc
        screenshots.append(prepare_screenshot(content))
    operator_id = None
    if channel == "executor":
        from app.appeal_workflow import latest_task
        task = latest_task(db, appeal.id)
        if not task and appeal.submitted_by_inspector_id:
            raise HTTPException(409, "Сначала назначьте исполнителя")
        operator_id = task.operator_id if task else None
    visibility = "INSPECTOR" if channel == "inspector" else "TASK" if operator_id else "STAFF"
    event = record_event(db, appeal, "COMMENT", user, inspector=inspector, comment=body.comment,
                         client_id=body.client_id, visibility=visibility, operator_id=operator_id)
    appeal.updated_at = now()
    db.flush()
    store_files(db, appeal, screenshots, event.id)
    db.commit()
    return {"id": event.id}


def resolve_channel(appeal, *, user=None, inspector=False, channel=None):
    if inspector:
        if channel == "executor":
            raise HTTPException(403, "Переписка исполнителя недоступна проверяющему")
        return "inspector"
    if user.role == "OPERATOR":
        if channel == "inspector":
            raise HTTPException(403, "Переписка проверяющего недоступна исполнителю")
        return "executor"
    if channel == "inspector" and not appeal.submitted_by_inspector_id:
        raise HTTPException(422, "У обращения нет проверяющего")
    return channel or ("inspector" if appeal.submitted_by_inspector_id else "executor")


def visible_conditions(appeal, *, user=None, inspector=False, channel=None):
    if not inspector and user.role != "OPERATOR" and channel is None:
        return []
    selected = resolve_channel(appeal, user=user, inspector=inspector, channel=channel)
    shared = (AppealEvent.visibility == "STAFF") & (AppealEvent.kind != "COMMENT")
    # Old shared messages stay with the checking side for private inspector tasks.
    legacy = (AppealEvent.visibility == "STAFF") & (AppealEvent.kind == "COMMENT")
    if selected == "inspector":
        return [or_(shared, legacy, AppealEvent.visibility == "INSPECTOR")]
    task = AppealEvent.visibility == "TASK"
    if user.role == "OPERATOR":
        task = task & (AppealEvent.operator_id == user.id)
    return [or_(shared, task, legacy if not appeal.submitted_by_inspector_id else False,
                AppealEvent.visibility == "ADMIN" if user.role != "OPERATOR" else False)]
