"""Staff-only, organization-scoped appeal discussion and history."""

import base64
import binascii
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import aliased

from app.chat_messages import quote
from app.domain import now
from app.models import AppealEvent, CitizenAppeal
from app.organization_context import current_organization
from app.schemas import StrictModel


class CommentInput(StrictModel):
    client_id: UUID
    comment: str = Field(default="", max_length=4000)
    channel: Literal["inspector", "executor"] | None = None
    reply_to_id: int | None = Field(default=None, gt=0)
    forward_message_id: int | None = Field(default=None, gt=0)
    screenshots: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("comment")
    @classmethod
    def nonempty(cls, value):
        return value.strip()


class CommentReadInput(StrictModel):
    through_id: int = Field(gt=0)
    channel: Literal["inspector", "executor"] | None = None


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
    scope = [AppealEvent.appeal_id == appeal.id, *visible_conditions(appeal, user=user, inspector=inspector, channel=channel)]
    conditions = list(scope)
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
    actor = actor_fields(user, inspector=inspector)
    receipts = list(db.scalars(select(AppealEvent.id).where(
        *scope, AppealEvent.kind == "COMMENT", AppealEvent.read_at.is_not(None),
        AppealEvent.actor_type == actor["actor_type"], AppealEvent.actor_id == actor["actor_id"],
    ).order_by(AppealEvent.id.desc()).limit(100)))
    return {"items": [{"outgoing": row.actor_type == actor["actor_type"] and row.actor_id == actor["actor_id"],
        "files": [file_dict(file, url) for file in files if file.event_id == row.id],
        **{key: getattr(row, key) for key in (
        "id", "kind", "actor_name", "actor_role", "status", "comment", "visibility", "created_at", "reply", "forwarded_name", "read_at")}} for row in rows],
        "has_more": more, "read_ids": receipts,
        "unanswered_comments": unanswered_comments(db, [appeal.id], user, inspector=inspector,
            channel=resolve_channel(appeal, user=user, inspector=inspector, channel=channel)).get(appeal.id, 0),
        "can_comment": appeal.archived_at is None and (not inspector or bool(appeal.submitted_by_inspector_id))}


def mark_comments_read(db, appeal, body, user, *, inspector=False):
    if inspector and not appeal.submitted_by_inspector_id:
        raise HTTPException(403, "Переписка недоступна")
    channel = resolve_channel(appeal, user=user, inspector=inspector, channel=body.channel)
    scope = [AppealEvent.appeal_id == appeal.id, AppealEvent.kind == "COMMENT",
             *visible_conditions(appeal, user=user, inspector=inspector, channel=channel)]
    if not db.scalar(select(AppealEvent.id).where(*scope, AppealEvent.id == body.through_id)):
        raise HTTPException(404, "Сообщение недоступно")
    actor = actor_fields(user, inspector=inspector)
    db.execute(update(AppealEvent).where(
        *scope, AppealEvent.id <= body.through_id, AppealEvent.read_at.is_(None),
        AppealEvent.visibility != "ADMIN",
        or_(AppealEvent.actor_type != actor["actor_type"], AppealEvent.actor_id != actor["actor_id"]),
    ).values(read_at=now()))
    db.commit()
    return {"ok": True}


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
    from app.models import AppealFile
    screenshots, reply, forwarded_name = [], None, None
    content = body.comment
    if body.forward_message_id:
        if body.comment or body.screenshots or body.reply_to_id:
            raise HTTPException(422, "Пересылаемое сообщение нельзя изменять")
        source_appeal, source = forward_source(db, appeal, body.forward_message_id, user, inspector=inspector, channel=channel)
        if source_appeal.id == appeal.id:
            raise HTTPException(422, "Выберите другую задачу")
        content, forwarded_name = source.comment, source.forwarded_name or source.actor_name
        screenshots = [{"name": file.name, "media_type": file.media_type, "content": file.content}
                       for file in db.scalars(select(AppealFile).where(AppealFile.event_id == source.id))]
    elif not body.comment and not body.screenshots:
        raise HTTPException(422, "Напишите сообщение или приложите скриншот")
    if body.reply_to_id:
        source = db.scalar(select(AppealEvent).where(AppealEvent.id == body.reply_to_id,
            AppealEvent.appeal_id == appeal.id, AppealEvent.kind == "COMMENT", AppealEvent.visibility != "ADMIN",
            *visible_conditions(appeal, user=user, inspector=inspector, channel=channel)))
        if source is None:
            raise HTTPException(404, "Сообщение для ответа недоступно")
        reply = quote(source.id, source.actor_name, source.comment, True)
    for encoded in body.screenshots:
        if len(encoded) > 35 * 1024 * 1024:
            raise HTTPException(422, "Скриншот слишком большой")
        try:
            content_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, "Не удалось прочитать скриншот") from exc
        screenshots.append(prepare_screenshot(content_bytes))
    operator_id = None
    if channel == "executor":
        from app.appeal_workflow import latest_task
        task = latest_task(db, appeal.id)
        if not task and appeal.submitted_by_inspector_id:
            raise HTTPException(409, "Сначала назначьте исполнителя")
        operator_id = task.operator_id if task else None
    visibility = "INSPECTOR" if channel == "inspector" else "TASK" if operator_id else "STAFF"
    event = record_event(db, appeal, "COMMENT", user, inspector=inspector, comment=content,
                         client_id=body.client_id, visibility=visibility, operator_id=operator_id)
    event.reply, event.forwarded_name = reply, forwarded_name
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
        if inspector:
            shared = shared & (AppealEvent.actor_role != "OPERATOR") & (AppealEvent.kind != "ASSIGNED")
        return [or_(shared, legacy, AppealEvent.visibility == "INSPECTOR")]
    task = AppealEvent.visibility == "TASK"
    if user.role == "OPERATOR":
        task = task & (AppealEvent.operator_id == user.id)
    return [or_(shared, task, legacy if not appeal.submitted_by_inspector_id else False,
                AppealEvent.visibility == "ADMIN" if user.role != "OPERATOR" else False)]


def require_forwardable_comment(db, message_id):
    source = db.get(AppealEvent, message_id)
    if not source or source.kind != "COMMENT" or source.visibility not in {"STAFF", "INSPECTOR", "TASK"}:
        raise HTTPException(404, "Сообщение недоступно")
    return source


def personal_forward_source(db, user, message_id, *, include_content=True):
    from app.appeals import find_appeal
    from app.auth import admin_user
    from app.models import AppealFile

    admin_user(user)
    if current_organization() is None:
        raise HTTPException(404, "Сообщение недоступно")
    source = require_forwardable_comment(db, message_id)
    find_appeal(db, source.appeal_id, user=user)
    if not include_content:
        return
    screenshots = list(db.scalars(select(AppealFile.content).where(
        AppealFile.event_id == source.id, AppealFile.media_type == "image/jpeg",
    ).order_by(AppealFile.id)))
    return source.comment, screenshots or None, source.forwarded_name or source.actor_name


def forward_source(db, destination, message_id, user, *, inspector, channel):
    from app.appeals import find_appeal
    from app.inspections import find_inspector_appeal
    source = require_forwardable_comment(db, message_id)
    appeal = (find_inspector_appeal(db, destination.organization_id, source.appeal_id) if inspector
              else find_appeal(db, source.appeal_id, user=user))
    if (not destination.organization_id or appeal.organization_id != destination.organization_id or
            channel == "inspector" and not appeal.submitted_by_inspector_id or
            not db.scalar(select(AppealEvent.id).where(AppealEvent.id == message_id,
                *visible_conditions(appeal, user=user, inspector=inspector, channel=channel)))):
        raise HTTPException(404, "Сообщение недоступно")
    return appeal, source


def forward_targets(db, appeal, message_id, user, channel, search, *, inspector=False):
    from app.appeal_search import appeal_search
    from app.appeals import appeal_conditions
    from app.inspections import inspector_appeal_scope
    from app.models import AppealTask
    channel = resolve_channel(appeal, user=user, inspector=inspector, channel=channel)
    source, _ = forward_source(db, appeal, message_id, user, inspector=inspector, channel=channel)
    if source.id != appeal.id:
        raise HTTPException(404, "Сообщение недоступно")
    scope = [inspector_appeal_scope(appeal.organization_id)] if inspector else appeal_conditions(user)
    query = select(CitizenAppeal.id, CitizenAppeal.subject, CitizenAppeal.description).where(
        *scope, CitizenAppeal.organization_id == appeal.organization_id,
        CitizenAppeal.id != appeal.id, CitizenAppeal.archived_at.is_(None), *appeal_search(search))
    if channel == "inspector":
        query = query.where(CitizenAppeal.submitted_by_inspector_id.is_not(None))
    else:
        query = query.where(select(AppealTask.id).where(AppealTask.appeal_id == CitizenAppeal.id).exists())
    return [{"id": id, "title": " · ".join((f"ОБ-{id:06d}", subject or description[:80].split("\n", 1)[0]))}
            for id, subject, description in db.execute(query.order_by(CitizenAppeal.id.desc()).limit(50))]
