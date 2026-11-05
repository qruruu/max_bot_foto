import re
from datetime import date, timedelta
from threading import Lock
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from app.auth import AdminUser, Db
from app.config import settings
from app.domain import now
from app.models import Photo
from app.organization_context import current_organization
from app.reports import filtered
from app.schemas import PhotoFilters

router = APIRouter()
_inference = Lock()
_task_request = re.compile(r"(?:создай|создайте|назначь|назначьте|поставь|поставьте|добавь)\s+(?:новую\s+)?задачу\b")
_photo_question = re.compile(
    r"сколько\s+(?:поступило\s+|пришло\s+|получили\s+)?(?:фото(?:графий)?|снимков)"
    r"(?:\s+(?:поступило|пришло|получили))?(?:\s+(.*))?"
)
_day_quantity = r"([1-9]\d{0,3})\s+(?:день|дня|дней)"
_follow_up = re.compile(rf"(?:а\s+)?{_day_quantity}")
DateContext = Literal["ago", "last"]

_task_instructions = (
    "Из запроса на создание задачи извлеки поля executor (имя исполнителя в именительном падеже), "
    "subject (название до 80 знаков), description (что надо сделать), due (срок словами пользователя). "
    "Сохраняй фамилию и подробности пользователя. Отсутствующее поле верни как null. "
    "Если есть только имя исполнителя, subject и description должны быть null. "
    "Пример: «создай задачу андрею дмитриевичу шашко» → "
    '{"executor":"Андрей Дмитриевич Шашко","subject":null,"description":null,"due":null}.'
)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantQuestion(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    date_context: DateContext | None = None
    history: list[ConversationMessage] = Field(default_factory=list, max_length=8)


class TaskDraft(BaseModel):
    executor: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    due: str | None = Field(default=None, max_length=60)


def model_reply(url: str, messages: list[dict], schema: dict | None = None):
    if not _inference.acquire(blocking=False):
        raise HTTPException(429, "Помощник уже отвечает. Попробуйте ещё раз чуть позже.")
    try:
        with httpx.Client(timeout=httpx.Timeout(70.0, connect=3.0), trust_env=False) as client:
            response = client.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                json={
                    "messages": messages,
                    "chat_template_kwargs": {"enable_thinking": False},
                    **({"response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "task_draft", "schema": schema},
                    }} if schema else {}),
                    "temperature": 0,
                    "max_tokens": 200 if schema else 160,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty model response")
            return content.strip()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(503, "Локальный помощник сейчас недоступен. Попробуйте позже.") from exc
    finally:
        _inference.release()


def extract_task(url: str, question: str) -> TaskDraft:
    try:
        return TaskDraft.model_validate_json(model_reply(url, [
            {"role": "system", "content": _task_instructions},
            {"role": "user", "content": question},
        ], TaskDraft.model_json_schema()))
    except ValueError as exc:
        raise HTTPException(503, "Не удалось разобрать задачу. Уточните поручение.") from exc


def calendar_day(value: str, today: date) -> date | None:
    if value in {"сегодня", "вчера", "позавчера", "завтра", "послезавтра"}:
        return today + timedelta(days={"сегодня": 0, "вчера": -1, "позавчера": -2, "завтра": 1, "послезавтра": 2}[value])
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?", value)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year) if year else today.year, int(month), int(day))
        except ValueError:
            return None
    return None


def photo_period(text: str, today: date, context: DateContext | None):
    follow_up = _follow_up.fullmatch(text)
    if follow_up and context:
        text = f"{follow_up[1]} дней назад" if context == "ago" else f"за {follow_up[1]} дней"

    if match := re.fullmatch(rf"{_day_quantity}\s+назад", text):
        day = today - timedelta(days=int(match[1]))
        return day, day, "ago"
    if match := re.fullmatch(rf"за\s+(?:последние\s+)?{_day_quantity}", text):
        return today - timedelta(days=int(match[1]) - 1), today, "last"
    if day := calendar_day(text.removeprefix("за "), today):
        return day, day, None
    return None


@router.post("/api/local-assistant/question")
def answer_question(body: AssistantQuestion, db: Db, user: AdminUser):
    config = settings()
    if not config.local_assistant_url:
        raise HTTPException(404, "Локальный помощник не включён.")

    question = " ".join(body.question.lower().strip(" ?!").split())
    today = now().astimezone(ZoneInfo(config.app_timezone)).date()
    if _task_request.match(question):
        if not current_organization():
            return {"answer": "Откройте чат в кабинете нужной организации, чтобы назначить задачу."}
        draft = extract_task(config.local_assistant_url, body.question)
        due_date = calendar_day(draft.due.lower().strip(" .") if draft.due else "", today)
        return {
            "answer": "Уточним данные для задачи и проверим их перед созданием.",
            "task": {
                "executor": draft.executor,
                "subject": draft.subject,
                "description": draft.description,
                "dueDate": due_date.isoformat() if due_date and due_date >= today else None,
            },
        }

    photo = _photo_question.fullmatch(question)
    period = photo_period((photo[1] or "") if photo else question, today, body.date_context) if (
        photo or body.date_context and _follow_up.fullmatch(question)
    ) else None
    if period:
        start, end, date_context = period
        filters = PhotoFilters(date_from=start, date_to=end, date_basis="received")
        selection = filtered(filters, user).with_only_columns(Photo.id)
        count = db.scalar(select(func.count()).select_from(selection.subquery()))
        label = f"за {start:%d.%m.%Y}" if start == end else f"с {start:%d.%m.%Y} по {end:%d.%m.%Y}"
        return {"answer": f"Поступило фото {label}: {count} (без спама).", "date_context": date_context}

    if photo or _follow_up.fullmatch(question):
        return {"answer": "Уточните дату или период. Например, «сколько фото 10 дней назад?» или «сколько фото за последние 5 дней?»."}
    instructions = (
        "Ты Даня ИИ, локальный помощник в системе Метка. Отвечай кратко по-русски. "
        "Доступные функции: подсчёт поступивших фото по дате и подготовка задач. "
        "Для подсчёта предложи написать «сколько фото за 03.11.2026» или «сколько фото 10 дней назад». "
        "Для задачи предложи написать «создай задачу» с именем и поручением. "
        "При создании бот уточняет исполнителя и поручение, предлагает необязательные срок и фото, "
        "показывает итог и ждёт подтверждения. "
        "Отчёты, отправка сообщений и поиск по инструкциям ещё не подключены. "
        "У тебя нет прямого доступа к базе, не выдумывай статистику, документы, сотрудников "
        "и результаты действий. Не заявляй о создании задачи. "
        f"Сегодня {today.isoformat()}."
    )
    history = [{"role": item.role, "content": item.content} for item in body.history]
    return {"answer": model_reply(config.local_assistant_url, [
        {"role": "system", "content": instructions},
        *history,
        {"role": "user", "content": body.question},
    ])}
