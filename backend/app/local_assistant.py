import logging
import re
from datetime import date, timedelta
from threading import Lock
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from app.auth import AdminUser, Db
from app.config import settings
from app.domain import now
from app.models import District, Photo
from app.organization_context import current_organization
from app.reports import filtered
from app.schemas import PhotoFilters
from app.work_types import catalog_rows

logger = logging.getLogger(__name__)
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


class StatisticsIntent(BaseModel):
    action: Literal["statistics", "help", "clarify"]
    date_from: date | None = None
    date_to: date | None = None
    work_type: str | None = None
    group_by: Literal["none", "work_type", "district", "both"] = "none"
    unsupported_filter: bool = False


def answer_statistics(body, db, user, today):
    catalog = catalog_rows(db)
    instructions = (
        "Разбери запрос для чтения статистики Метки. Верни только JSON по схеме. "
        "action=statistics для статистики фото, видов работ, территорий. "
        "action=help для вопросов о возможностях. Иначе clarify. "
        "Определи date_from и date_to как ISO даты. Текущий запрос важнее истории. "
        "Используй историю только для пропущенных параметров. Нет даты — null. "
        "group_by=both если запрошены виды работ и территории, иначе work_type или district. "
        "work_type — код из справочника для одного указанного вида работ, иначе null. "
        "unsupported_filter=true для фильтра по сотруднику, статусу или конкретной территории, "
        "или неизвестному виду работ. Не вычисляй количество. Числа из переписки не являются данными. "
        f"Сегодня {today.isoformat()}. Справочник: "
        + str([{"code": row.code, "name": row.name} for row in catalog])
    )
    period = conversational_photo_period(body.question.lower(), [], today)
    work_breakdown = bool(re.search(r"вид(?:ам|ов|ы)?(?: работ)?|по работ", body.question.lower()))
    district_breakdown = bool(re.search(r"территор|микрорайон|\bмкр\b", body.question.lower()))
    explicit_work = [
        row for row in catalog
        if re.search(r"(?<!\w)" + re.escape(row.name.casefold()) + r"(?!\w)", body.question.casefold())
    ]
    specific_filter = bool(re.search(r"оператор|отправил|принят|отклон", body.question.lower()))
    if period and work_breakdown and district_breakdown and not specific_filter and not explicit_work:
        intent = StatisticsIntent(action="statistics", date_from=period[0], date_to=period[1], group_by="both")
    else:
        try:
            intent = StatisticsIntent.model_validate_json(model_reply(settings().local_assistant_url, [
                {"role": "system", "content": instructions},
                *[{"role": item.role, "content": item.content[:300]} for item in body.history[-4:]],
                {"role": "user", "content": body.question},
            ], StatisticsIntent.model_json_schema()))
        except ValueError:
            return {"answer": "Не удалось однозначно разобрать запрос. Укажите дату, вид работ и нужную разбивку."}
    if intent.action == "help":
        return {"answer": "Могу посчитать поступившие фото за дату или период, показать разбивку по видам работ и территориям и помочь создать задачу. Для задачи напишите «создай задачу»."}
    works = {row.code: row.name for row in catalog}
    if (intent.action != "statistics" or intent.unsupported_filter or not intent.date_from
            or not intent.date_to or intent.date_from > intent.date_to
            or intent.work_type is not None and intent.work_type not in works):
        return {"answer": "Уточните дату или период и нужную разбивку: по видам работ или территориям. Этот запрос пока не удалось выполнить по базе."}
    joint = intent.group_by == "both"
    filters = PhotoFilters(date_from=intent.date_from, date_to=intent.date_to,
                           date_basis="photo" if joint else "received", work_only=joint,
                           work_type=intent.work_type)
    source = filtered(filters, user).subquery()
    total = db.scalar(select(func.count()).select_from(source))
    basis = "дате на фото" if joint else "дате поступления"
    lines = [f"По базе, по {basis} с {intent.date_from:%d.%m.%Y} по {intent.date_to:%d.%m.%Y}.",
             f"Всего {'рабочих ' if joint else ''}фото: {total} (без спама)."]
    if joint:
        groups = {}
        for name, code, count in db.execute(
            select(District.name, source.c.work_type, func.count()).select_from(source)
            .outerjoin(District, District.id == source.c.district_id)
            .group_by(source.c.district_id, District.name, source.c.work_type)
            .order_by(District.name, source.c.work_type)
        ):
            groups.setdefault(name or "Территория не определена", []).append(
                f"{works.get(code, 'Вид работ не определён')} — {count}")
        lines.extend(f"• {name}: " + "; ".join(values) for name, values in groups.items())
        return {"answer": "\n".join(lines)}
    if intent.work_type:
        lines.append("Вид работ: " + works[intent.work_type])
    if intent.group_by in {"work_type", "both"}:
        lines.append("По видам работ:")
        for code, count in db.execute(select(source.c.work_type, func.count()).group_by(source.c.work_type)):
            lines.append(f"• {works.get(code, 'Не определён')}: {count}")
    if intent.group_by in {"district", "both"}:
        lines.append("По территориям:")
        for name, count in db.execute(
            select(District.name, func.count()).select_from(source)
            .outerjoin(District, District.id == source.c.district_id)
            .group_by(source.c.district_id, District.name)
        ):
            lines.append(f"• {name or 'Не определена'}: {count}")
    return {"answer": "\n".join(lines)}


def model_reply(url: str, messages: list[dict], schema: dict | None = None):
    if not _inference.acquire(blocking=False):
        raise HTTPException(429, "Помощник уже отвечает. Попробуйте ещё раз чуть позже.")
    try:
        with httpx.Client(timeout=httpx.Timeout(70.0, connect=3.0), trust_env=False) as client:
            response = client.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                headers={"Authorization": "Bearer " + settings().local_assistant_api_key.get_secret_value()}
                if settings().local_assistant_api_key.get_secret_value() else {},
                json={
                    "messages": messages,
                    "chat_template_kwargs": {"enable_thinking": False},
                    **({"response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "task_draft", "schema": schema},
                    }} if schema else {}),
                    "temperature": 0,
                    "max_tokens": 512 if schema else 160,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty model response")
            return content.strip()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        # Log only the error category and status, never prompts or authentication headers.
        logger.warning("Assistant inference failed: %s status=%s", type(exc).__name__,
                       exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None)
        raise HTTPException(503, "Локальный помощник сейчас недоступен. Попробуйте позже.") from exc
    finally:
        _inference.release()


def extract_task(url: str, question: str) -> TaskDraft:
    try:
        draft = TaskDraft.model_validate_json(model_reply(url, [
            {"role": "system", "content": _task_instructions},
            {"role": "user", "content": question},
        ], TaskDraft.model_json_schema()))
        if not draft.description or not draft.description.strip():
            draft.subject = None
            draft.description = None
        return draft
    except ValueError as exc:
        raise HTTPException(503, "Не удалось разобрать задачу. Уточните поручение.") from exc


def calendar_day(value: str, today: date) -> date | None:
    if value in {"сегодня", "вчера", "позавчера", "завтра", "послезавтра"}:
        return today + timedelta(days={"сегодня": 0, "вчера": -1, "позавчера": -2, "завтра": 1, "послезавтра": 2}[value])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
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


def conversational_photo_period(question: str, history: list[ConversationMessage], today: date):
    # Dates in previous messages only select a scope. Counts always come from the database.
    candidates = [question, *(item.content.lower() for item in reversed(history))]
    for text in candidates:
        if match := re.search(r"\b(позавчера|вчера|сегодня)\b", text):
            day = calendar_day(match[1], today)
            return day, day, None
        if match := re.search(rf"{_day_quantity}\s+назад", text):
            return photo_period(match[0], today, None)
        if match := re.search(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})\b", text):
            if day := calendar_day(match[0], today):
                return day, day, None
    return None


@router.post("/api/local-assistant/question")
def answer_question(body: AssistantQuestion, db: Db, user: AdminUser, request: Request):
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

    if re.search(r"территор|микрорайон|разбив|по видам|виды работ", question):
        return answer_statistics(body, db, user, today)

    photo = _photo_question.fullmatch(question)
    period = photo_period((photo[1] or "") if photo else question, today, body.date_context) if (
        photo or body.date_context and _follow_up.fullmatch(question)
    ) else None
    photo_reference = bool(re.search(r"фото|снимк", question))
    confirmation = question in {"да", "ну да", "верно", "именно", "проверь", "пересчитай", "точно"}
    photo_history = any(re.search(r"фото|снимк", item.content.lower()) for item in body.history)
    if not period and (photo_reference or confirmation and photo_history):
        period = conversational_photo_period(question, body.history, today)
        # Additional filters require a supported query instead of silently counting every photo.
        if re.search(r"оператор|отправил|иванов|принят|отклон|объект", question):
            period = None
        if not period:
            return {"answer": "Уточните дату и условия подсчёта. Могу проверить общее число поступивших фото за дату, например 26.10.2026."}
    if period:
        start, end, date_context = period
        matches = [
            row for row in catalog_rows(db)
            if re.search(r"(?<!\w)" + re.escape(row.name.casefold()) + r"(?!\w)", question)
        ]
        if len(matches) > 1:
            return {"answer": "Укажите один вид работ для подсчёта."}
        work = matches[0] if matches else None
        filters = PhotoFilters(date_from=start, date_to=end, date_basis="received",
                               work_type=work.code if work else None)
        selection = filtered(filters, user).with_only_columns(Photo.id)
        count = db.scalar(select(func.count()).select_from(selection.subquery()))
        label = f"за {start:%d.%m.%Y}" if start == end else f"с {start:%d.%m.%Y} по {end:%d.%m.%Y}"
        return {"answer": f"Поступило фото{f' по виду работ «{work.name}»' if work else ''} {label}: {count} (без спама).", "date_context": date_context}

    if photo or _follow_up.fullmatch(question):
        return {"answer": "Уточните дату или период. Например, «сколько фото 10 дней назад?» или «сколько фото за последние 5 дней?»."}
    from app.assistant_sources import answer_source
    return answer_source(body, request, model_reply, today)
