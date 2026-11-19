from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models import CitizenAppeal, InspectionAgency, InspectionMessage, Inspector, InspectorAppealShare
from app.schemas import StrictModel


class AppealShareInput(StrictModel):
    appeal_ids: list[Annotated[int, Field(gt=0, le=2147483647)]] = Field(min_length=1, max_length=50)
    inspector_id: int = Field(gt=0, le=2147483647)
    client_id: UUID | None = None


def share_recipients(db, q, *, exclude=None):
    term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    query = select(Inspector.id, Inspector.name, InspectionAgency.name).join(InspectionAgency).where(
        Inspector.active, InspectionAgency.active,
        func.concat_ws(" ", Inspector.name, InspectionAgency.name).ilike("%" + term + "%", escape="\\"),
    )
    if exclude is not None:
        query = query.where(Inspector.id != exclude)
    rows = db.execute(query.order_by(func.lower(Inspector.name), Inspector.id).limit(50))
    return [{"id": id, "name": name, "agency": agency} for id, name, agency in rows]


def save_task_shares(db, body, condition, actor, *, exclude=None):
    from app.inspection_chats import lock_message_send

    ids = sorted(set(body.appeal_ids))
    appeals = list(db.scalars(select(CitizenAppeal).where(condition, CitizenAppeal.id.in_(ids))
                             .order_by(CitizenAppeal.id).with_for_update(read=True)))
    if [appeal.id for appeal in appeals] != ids:
        raise HTTPException(404, "Задача не найдена")
    peer = f"i:{body.inspector_id}"
    if actor == peer or body.inspector_id == exclude:
        raise HTTPException(404, "Проверяющий недоступен")
    lock_message_send(db, actor, peer)
    recipient = db.scalar(select(Inspector.id).join(InspectionAgency).where(
        Inspector.id == body.inspector_id, Inspector.active, InspectionAgency.active,
    ).with_for_update(read=True))
    if recipient is None:
        raise HTTPException(404, "Проверяющий недоступен")
    db.execute(insert(InspectorAppealShare).values(
        [{"appeal_id": id, "inspector_id": recipient} for id in ids]
    ).on_conflict_do_nothing())
    for appeal in appeals:
        key = str(uuid5(body.client_id or NAMESPACE_URL, f"appeal-share:{actor}:{peer}:{appeal.id}"))
        existing = db.scalar(select(InspectionMessage.id).where(
            InspectionMessage.sender_key == actor, InspectionMessage.client_id == key,
        ))
        if existing is None:
            db.add(InspectionMessage(sender_key=actor, recipient_key=peer, client_id=key, shared_appeal_id=appeal.id,
                                     body=appeal.subject or f"Обращение ОБ-{appeal.id:06d}"))
    db.commit()
    return {"ok": True}
