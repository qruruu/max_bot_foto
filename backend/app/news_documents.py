"""Small, validated Tiptap schema. No arbitrary HTML, CSS, remote image URLs or embeds."""

import json
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas import StrictModel

MAX_DOCUMENT_BYTES = 512_000
WORKSPACE_PATHS = {
    "/",
    "/photos",
    "/photo-map",
    "/review",
    "/days",
    "/districts",
    "/work-types",
    "/news",
    "/learning",
    "/jobs",
    "/exchange",
    "/settings",
    "/messages",
    "/chats",
    "/users",
}


def safe_link(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2000
        or any(ord(c) < 32 or c in "\\" for c in value)
    ):
        raise ValueError("Укажите обычную ссылку https://… или путь раздела /photos")
    parsed = urlsplit(value)
    if parsed.path.startswith("/org/"):
        raise ValueError("Используйте общий путь раздела без организации, например /photos")
    if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password:
        return value
    if (
        not parsed.scheme
        and not parsed.netloc
        and value.startswith("/")
        and not value.startswith("//")
        and (parsed.path in WORKSPACE_PATHS or parsed.path.startswith(("/news/", "/settings/")))
    ):
        return value
    raise ValueError("Ссылка на раздел должна быть общей, без /org/ и адреса организации")


def validate_document(document):
    if (
        not isinstance(document, dict)
        or len(json.dumps(document, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES
    ):
        raise ValueError("Текст слишком большой")
    count = 0

    def node(value, allowed, depth=0):
        nonlocal count
        count += 1
        if depth > 8 or count > 3000 or not isinstance(value, dict):
            raise ValueError("Слишком сложная структура статьи")
        kind = value.get("type")
        if (
            not isinstance(kind, str)
            or kind not in allowed
            or set(value) - {"type", "content", "attrs", "text", "marks"}
        ):
            raise ValueError("Неподдерживаемый блок статьи")
        attrs, children = value.get("attrs", {}), value.get("content", [])
        if not isinstance(attrs, dict) or not isinstance(children, list):
            raise ValueError("Неверный формат блока")
        if kind != "text" and ("text" in value or "marks" in value):
            raise ValueError("Текст и выделение допустимы только внутри абзаца")
        if kind == "text":
            if attrs or children or not isinstance(value.get("text"), str) or not value["text"]:
                raise ValueError("Неверный текст")
            marks = value.get("marks", [])
            if not isinstance(marks, list) or len(marks) > 3:
                raise ValueError("Неверное выделение")
            types = set()
            for mark in marks:
                if (
                    not isinstance(mark, dict)
                    or set(mark) - {"type", "attrs"}
                    or not isinstance(mark.get("type"), str)
                    or mark.get("type") not in {"bold", "italic", "link"}
                ):
                    raise ValueError("Неподдерживаемое выделение")
                if mark["type"] in types:
                    raise ValueError("Повторное выделение")
                types.add(mark["type"])
                if mark["type"] == "link":
                    if not isinstance(mark.get("attrs"), dict) or set(mark.get("attrs", {})) - {
                        "href",
                        "target",
                        "rel",
                        "class",
                    }:
                        raise ValueError("Неверная ссылка")
                    safe_link(mark.get("attrs", {}).get("href"))
                    # Only href is persisted; editor/browser presentation is not trusted input.
                    mark["attrs"] = {"href": mark["attrs"]["href"]}
                elif mark.get("attrs"):
                    raise ValueError("У выделения нет дополнительных настроек")
            return
        child_types = {"text", "hardBreak"}
        if kind == "doc":
            if attrs or not children:
                raise ValueError("В статье нужен хотя бы один абзац")
            child_types = {
                "paragraph",
                "heading",
                "bulletList",
                "orderedList",
                "important",
                "image",
                "action",
            }
        elif kind == "heading":
            if set(attrs) != {"level"} or type(attrs["level"]) is not int or attrs["level"] not in {2, 3}:
                raise ValueError("Поддерживаются подзаголовки второго и третьего уровня")
        elif kind in {"bulletList", "orderedList"}:
            if (
                (kind == "bulletList" and attrs)
                or (
                    kind == "orderedList"
                    and (
                        set(attrs) - {"start", "type"}
                        or (attrs.get("type") is not None and attrs.get("type") != "1")
                        or type(attrs.get("start", 1)) is not int
                        or not 1 <= attrs.get("start", 1) <= 1000
                    )
                )
                or not children
            ):
                raise ValueError("Неверный список")
            child_types = {"listItem"}
        elif kind == "listItem":
            if (
                attrs
                or not children
                or (children[0].get("type") if isinstance(children[0], dict) else None) != "paragraph"
            ):
                raise ValueError("Пункт списка должен начинаться с абзаца")
            child_types = {"paragraph", "bulletList", "orderedList"}
        elif kind == "important":
            if attrs or not children:
                raise ValueError("Добавьте текст заметки")
            child_types = {"paragraph", "bulletList", "orderedList"}
        elif kind == "image":
            if children or set(attrs) != {"asset_id", "alt", "caption"}:
                raise ValueError("Неверный блок изображения")
            if not isinstance(attrs["asset_id"], str):
                raise ValueError("Неверный номер изображения")
            UUID(attrs["asset_id"])
            if any(not isinstance(attrs[key], str) or len(attrs[key]) > 500 for key in ("alt", "caption")):
                raise ValueError("Описание изображения должно быть короче 500 символов")
            return
        elif kind == "action":
            if (
                children
                or set(attrs) != {"href", "label"}
                or not isinstance(attrs["label"], str)
                or not 1 <= len(attrs["label"]) <= 100
            ):
                raise ValueError("Добавьте название кнопки")
            safe_link(attrs["href"])
            return
        elif attrs or (kind == "hardBreak" and children):
            raise ValueError("Неверный абзац")
        for child in children:
            node(child, child_types, depth + 1)

    node(document, {"doc"})
    return document


class NewsSnapshot(StrictModel):
    title: str = Field(max_length=200)
    summary: str = Field(max_length=600)
    category: str = Field(max_length=60)
    document: dict
    cover_id: str | None = None

    @field_validator("document")
    @classmethod
    def document_schema(cls, value):
        return validate_document(value)

    @field_validator("cover_id")
    @classmethod
    def cover_uuid(cls, value):
        return str(UUID(value)) if value else None


def asset_ids(snapshot):
    result = {snapshot["cover_id"]} if snapshot.get("cover_id") else set()

    def walk(value):
        if value["type"] == "image":
            result.add(value["attrs"]["asset_id"])
        for child in value.get("content", []):
            walk(child)

    walk(snapshot["document"])
    return result


def publishable(snapshot):
    if any(not snapshot[key].strip() for key in ("title", "summary", "category")):
        raise ValueError("Перед публикацией заполните заголовок, анонс и категорию")
    meaningful = False

    def walk(value):
        nonlocal meaningful
        if value["type"] in {"image", "action"} or value.get("text", "").strip():
            meaningful = True
        if value["type"] == "image" and not value["attrs"]["alt"].strip():
            raise ValueError("Добавьте альтернативное описание ко всем изображениям")
        for child in value.get("content", []):
            walk(child)

    walk(snapshot["document"])
    if not meaningful:
        raise ValueError("Добавьте текст статьи")
