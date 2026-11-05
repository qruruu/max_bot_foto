from datetime import timedelta
from threading import Lock
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from app.auth import AdminUser, Db
from app.config import settings
from app.domain import now
from app.models import Photo
from app.reports import filtered
from app.schemas import PhotoFilters

router = APIRouter()
_inference = Lock()
_instructions = (
    'Определи, просит ли пользователь посчитать все поступившие фотографии за сегодня или вчера. '
    'Верни {"period":"today"} для сегодня, {"period":"yesterday"} для вчера. '
    'Для любого другого запроса, в том числе подсчёта по человеку, объекту или статусу, '
    'верни {"period":"unsupported"}. Отвечай только JSON.'
)


class AssistantQuestion(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PhotoCountIntent(BaseModel):
    period: Literal["today", "yesterday", "unsupported"]


def classify_question(url: str, question: str) -> PhotoCountIntent:
    if not _inference.acquire(blocking=False):
        raise HTTPException(429, "Помощник уже отвечает. Попробуйте ещё раз чуть позже.")
    try:
        with httpx.Client(timeout=httpx.Timeout(25.0, connect=3.0), trust_env=False) as client:
            response = client.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": _instructions},
                        {"role": "user", "content": question},
                    ],
                    "chat_template_kwargs": {"enable_thinking": False},
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "photo_count", "schema": PhotoCountIntent.model_json_schema()},
                    },
                    "temperature": 0,
                    "max_tokens": 40,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return PhotoCountIntent.model_validate_json(content)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(503, "Локальный помощник сейчас недоступен. Попробуйте позже.") from exc
    finally:
        _inference.release()


@router.post("/api/local-assistant/question")
def answer_question(body: AssistantQuestion, db: Db, user: AdminUser):
    config = settings()
    if not config.local_assistant_url:
        raise HTTPException(404, "Локальный помощник не включён.")

    intent = classify_question(config.local_assistant_url, body.question)
    if intent.period == "unsupported":
        return {"answer": "Пока могу посчитать фото за сегодня или вчера. Например: «Сколько фото поступило сегодня?»"}

    day = now().astimezone(ZoneInfo(config.app_timezone)).date()
    if intent.period == "yesterday":
        day -= timedelta(days=1)
    selection = filtered(PhotoFilters(day=day, date_basis="received"), user).with_only_columns(Photo.id)
    count = db.scalar(select(func.count()).select_from(selection.subquery()))
    return {"answer": f"Поступило фото за {day:%d.%m.%Y}: {count} (без спама, по доступным вам чатам)."}
