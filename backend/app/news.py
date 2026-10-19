"""Versioned release articles; access and screenshots share one explicit permission."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import CurrentUser, check_permission
from app.permissions import Permission

router = APIRouter(prefix="/api/news", tags=["news"])
CONTENT_DIR = Path(__file__).with_name("news_content")


class Screenshot(BaseModel):
    file: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*\.(png|jpg|webp)$")
    alt: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class Section(BaseModel):
    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    screenshots: list[Screenshot] = Field(default_factory=list)


class Post(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    publishedAt: date
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)


@lru_cache(maxsize=1)
def load_posts():
    posts = [Post.model_validate(row) for row in json.loads((CONTENT_DIR / "posts.json").read_text())]
    if len({post.slug for post in posts}) != len(posts):
        raise ValueError("News slugs must be unique")
    return sorted(posts, key=lambda post: (post.publishedAt, post.slug), reverse=True)


def require_post(slug):
    for post in load_posts():
        if post.slug == slug:
            return post
    raise HTTPException(404, "Новость не найдена")


@router.get("")
def news_list(user: CurrentUser):
    check_permission(user, Permission.NEWS_VIEW)
    return [post.model_dump(mode="json", exclude={"sections"}) for post in load_posts()]


@router.get("/{slug}")
def news_post(slug: str, user: CurrentUser):
    check_permission(user, Permission.NEWS_VIEW)
    post = require_post(slug)
    result = post.model_dump(mode="json")
    for section in result["sections"]:
        for screenshot in section["screenshots"]:
            screenshot["src"] = f"/api/news/{post.slug}/screenshots/{screenshot.pop('file')}"
    return result


@router.get("/{slug}/screenshots/{filename}")
def news_screenshot(slug: str, filename: str, user: CurrentUser):
    check_permission(user, Permission.NEWS_VIEW)
    post = require_post(slug)
    declared = {image.file for section in post.sections for image in section.screenshots}
    if filename not in declared:
        raise HTTPException(404, "Скриншот не найден")
    folder = (CONTENT_DIR / post.slug).resolve()
    path = (folder / filename).resolve()
    if not folder.is_relative_to(CONTENT_DIR.resolve()) or not path.is_relative_to(folder) or not path.is_file():
        raise HTTPException(404, "Скриншот не найден")
    return FileResponse(path)
