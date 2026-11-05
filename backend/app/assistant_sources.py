"""Read administrative data through the same authenticated APIs used by the panel."""

import asyncio
import json
import re
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import Request
from pydantic import BaseModel, Field, create_model

from app.organization_context import workspace_url

DOMAINS = {
    "photos": ("Фотографии, статистика, отправители", ("/api/photos", "/api/reports", "/api/chats")),
    "tasks": ("Обращения, задачи, сроки, исполнители", ("/api/appeals",)),
    "reports": ("Ежедневные отчёты, контракты, реквизиты, календарь", ("/api/daily-reports",)),
    "people": ("Операторы и их доступы", ("/api/users", "/api/inspection-admin")),
    "territories": ("Микрорайоны, маршруты, здания, покрытие", ("/api/districts", "/api/photo-routes")),
    "catalog": ("Виды работ", ("/api/work-types",)),
    "days": ("Проверка и закрытие дней, работа операторов", ("/api/day-reviews",)),
    "messages": ("Моя переписка с операторами", ("/api/operator-chats",)),
    "news": ("Новости, рабочие инструкции из новостей", ("/api/news",)),
    "processing": ("Очередь обработки, ошибки, обучение нейросети", ("/api/jobs", "/api/ml", "/api/audit")),
    "exchange": ("Обмен с АРМ, папки хранения, подключение MAX", ("/api/exchange", "/api/storage-folders", "/api/max/status")),
}
# Files and navigation endpoints are opened from their existing panel views.
EXCLUDED = re.compile(r"/(?:preview|original|map|next|arrivals|avatars|contact-avatar|photo|assets|screenshots|xlsx|print|unread|notifications)(?:/|$)")
SENSITIVE = re.compile(r"password|token|secret|api_key|credential|cookie|authorization|database_url", re.I)


class SourceDomain(BaseModel):
    domain: Literal["photos", "tasks", "reports", "people", "territories", "catalog", "days",
                    "messages", "news", "processing", "exchange", "clarify"]


def sources_for(app, domain):
    prefixes = DOMAINS[domain][1]
    return {
        path: definition["get"] for path, definition in app.openapi()["paths"].items()
        if "get" in definition and any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
        and not EXCLUDED.search(path)
    }


def clean_data(value):
    if isinstance(value, dict):
        return {key: clean_data(item) for key, item in value.items() if not SENSITIVE.search(key)}
    if isinstance(value, list):
        return [clean_data(item) for item in value]
    return value


LABELS = {
    "items": "Записи", "total": "Всего", "name": "Название", "id": "Номер", "status": "Статус",
    "subject": "Тема", "description": "Описание", "due_date": "Срок", "operator_name": "Исполнитель",
    "created_at": "Создано", "updated_at": "Обновлено", "count": "Количество", "page": "Страница",
    "page_size": "Размер страницы", "active": "Активен", "login": "Логин", "role": "Роль",
}


def render_data(data, depth=0):
    if depth > 5:
        return [json.dumps(data, ensure_ascii=False)]
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            label = LABELS.get(key, key)
            if isinstance(value, (dict, list)):
                lines.append(label + ":")
                lines.extend("  " + line for line in render_data(value, depth + 1))
            else:
                lines.append(label + ": " + scalar(value))
        return lines
    if isinstance(data, list):
        if not data:
            return ["Нет записей."]
        lines = []
        for item in data:
            lines.extend("• " + line if index == 0 else "  " + line
                         for index, line in enumerate(render_data(item, depth + 1)))
        return lines
    return [scalar(data)]


def scalar(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    return str(value)


async def read_source(app, request, path, params):
    # Cookies stay in this transport and are never included in model context.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=str(request.base_url),
        cookies=dict(request.cookies), follow_redirects=False,
    ) as client:
        return await client.get(workspace_url(path), params=params)


def answer_source(body, request: Request, model_reply, today):
    from app.api import app

    history = [{"role": item.role, "content": item.content[:350]} for item in body.history[-4:]]
    messages = [
        {"role": "system", "content": "Выбери источник данных для запроса администратора. "
         "Ответ только JSON. Если запрос не относится к этим источникам, clarify. "
         + json.dumps({key: value[0] for key, value in DOMAINS.items()}, ensure_ascii=False)},
        *history, {"role": "user", "content": body.question},
    ]
    from app.config import settings
    url = settings().local_assistant_url
    try:
        domain = SourceDomain.model_validate_json(model_reply(url, messages, SourceDomain.model_json_schema())).domain
        if domain == "clarify":
            return {"answer": "Уточните раздел и что нужно найти: фото, задачи, отчёты, операторы, территории, переписка, новости, обработка или обмен."}
        routes = sources_for(app, domain)
        if not routes:
            return {"answer": "Для этого раздела источник данных ещё не подключён."}
        Selection = create_model("ReadSelection",
            path=(Literal[tuple(routes)], ...),
            path_values=(dict[str, str], Field(default_factory=dict)),
            query=(dict[str, str], Field(default_factory=dict)),
            needs_clarification=(bool, False),
        )
        descriptions = {
            path: {"description": spec.get("summary"), "parameters": spec.get("parameters", [])}
            for path, spec in routes.items()
        }
        selection = Selection.model_validate_json(model_reply(url, [
            {"role": "system", "content": "Выбери один GET источник и параметры запроса. Только JSON по схеме. "
             "Не выдумывай ID и имена, отсутствующий обязательный параметр означает needs_clarification=true. "
             "Для поиска используй q если источник поддерживает его. Даты в ISO. "
             "Один ответ содержит только страницу данных, не обобщай её как полный итог. "
             f"Сегодня {today.isoformat()}. Источники: " + json.dumps(descriptions, ensure_ascii=False)},
            *history, {"role": "user", "content": body.question},
        ], Selection.model_json_schema()))
    except ValueError:
        return {"answer": "Не удалось определить источник и параметры. Уточните раздел, дату или номер записи."}
    if selection.needs_clarification:
        return {"answer": "Уточните дату, имя или номер записи для поиска в разделе «" + DOMAINS[domain][0] + "»."}
    spec = routes[selection.path]
    allowed_query = {item["name"] for item in spec.get("parameters", []) if item["in"] == "query"}
    if selection.query.keys() - allowed_query:
        return {"answer": "Этот источник не поддерживает запрошенные условия. Уточните запрос."}
    path = selection.path
    required = set(re.findall(r"{(\w+)}", path))
    if selection.path_values.keys() != required:
        return {"answer": "Укажите номер или название записи, которую нужно открыть."}
    for key, value in selection.path_values.items():
        if not re.fullmatch(r"[\w-]{1,100}", value):
            return {"answer": "Не удалось определить номер записи."}
        path = path.replace("{" + key + "}", quote(value, safe=""))
    response = asyncio.run(read_source(app, request, path, selection.query))
    if response.status_code != 200:
        return {"answer": "Источник не выполнил запрос. Проверьте доступ, номер записи и обязательные параметры."}
    try:
        data = clean_data(response.json())
    except ValueError:
        return {"answer": "Этот источник нужно открыть в соответствующем разделе «Метки»."}
    text = "\n".join(render_data(data))
    truncated = len(text) > 14000
    text = text[:14000]
    return {"answer": "Данные раздела «" + DOMAINS[domain][0] + "». Ответ источника на этот запрос.\n"
            + text + ("\nПоказана часть ответа. Уточните запрос или страницу." if truncated else "")}
