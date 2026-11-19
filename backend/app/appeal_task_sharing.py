from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from app.models import CitizenAppeal, InspectionMessage, OperatorMessage, User
from app.schemas import StrictModel


class AppealShareInput(StrictModel):
    appeal_ids: list[Annotated[int, Field(gt=0, le=2147483647)]] = Field(min_length=1, max_length=50)
    recipient: str = Field(min_length=1, max_length=100)
    client_id: UUID | None = None


def staff_targets(db, *, roles, prefix="", exclude=None):
    accounts = db.scalars(select(User).where(User.active, User.role.in_(roles))
                          .order_by(User.name, User.id))
    return [recipient(prefix + str(account.id), account.name, account.role) for account in accounts if account.id != exclude]


def recipient(key, name, role):
    return {"key": key, "name": name, "label": "Оператор" if role == "OPERATOR" else "Администратор"}


def search_targets(targets, q):
    term = q.strip().casefold()
    return [item for item in targets if term in (item["name"] + " " + item["label"]).casefold()][:50]


def load_tasks(db, body, conditions):
    ids = sorted(set(body.appeal_ids))
    appeals = list(db.scalars(select(CitizenAppeal).where(*conditions, CitizenAppeal.id.in_(ids))
                             .order_by(CitizenAppeal.id).with_for_update(read=True)))
    if [appeal.id for appeal in appeals] != ids:
        raise HTTPException(404, "Задача не найдена")
    return appeals


def save_task_messages(db, body, appeals, actor, peer, *, workspace=False):
    if workspace:
        from app.operator_chats import lock_operator_send

        lock_operator_send(db, actor, peer)
        model = OperatorMessage
        parties = {"sender_id": actor, "recipient_id": peer}
    else:
        from app.inspection_chats import lock_message_send

        lock_message_send(db, actor, peer)
        model = InspectionMessage
        parties = {"sender_key": actor, "recipient_key": peer}
    for appeal in appeals:
        key = str(uuid5(body.client_id or NAMESPACE_URL, f"appeal-share:{actor}:{peer}:{appeal.id}"))
        existing = db.scalar(select(model.id).filter_by(**parties, client_id=key))
        if existing is None:
            db.add(model(**parties, client_id=key, shared_appeal_id=appeal.id,
                         body=appeal.subject or f"Обращение ОБ-{appeal.id:06d}"))
    db.commit()
    return {"ok": True}
