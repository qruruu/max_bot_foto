"""Global published product articles; drafts are served only by the owner API."""

# The shipped JSON is an import source only. Live reads never fall back to it.
import json
from copy import deepcopy
from datetime import UTC
from functools import lru_cache
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth import CurrentUser, check_permission, is_platform_owner
from app.config import base_settings
from app.models import NewsArticle, NewsAsset, NewsLegacyAsset, NewsPublishedAsset, NewsRead
from app.news_legacy import CONTENT_DIR, Post
from app.organization_context import current_organization, workspace_url
from app.organization_registry import control_session
from app.permissions import Permission

router = APIRouter(prefix="/api/news", tags=["news"])


@lru_cache(maxsize=1)
def load_posts():
    posts = [Post.model_validate(row) for row in json.loads((CONTENT_DIR / "posts.json").read_text())]
    if len({post.slug for post in posts}) != len(posts):
        raise ValueError("News slugs must be unique")
    return sorted(posts, key=lambda post: (post.publishedAt, post.slug), reverse=True)


def get_news_db():
    with control_session() as db:
        yield db


NewsDb = Annotated[Session, Depends(get_news_db)]


def news_reader_key(user):
    if is_platform_owner(user):
        return f"owner:{getattr(user, '_platform_user_id', None) or user.id}"
    organization = current_organization()
    scope = f"organization:{organization.id}" if organization else "legacy"
    return f"{scope}:user:{user.id}"


def unread_news_count(db, user):
    read = select(NewsRead.article_id).where(NewsRead.reader_key == news_reader_key(user))
    return db.scalar(select(func.count()).select_from(NewsArticle).where(
        NewsArticle.published.is_not(None), NewsArticle.deleted_at.is_(None), NewsArticle.id.not_in(read),
    ))


def asset_url(asset_id):
    return workspace_url(f"/api/news/assets/{asset_id}")


def render_snapshot(snapshot, published_at=None, slug=None, *, editor=False, db=None):
    result = deepcopy(snapshot)
    url = (lambda aid: f"/api/platform/news/assets/{aid}") if editor else asset_url

    def walk(value):
        if value["type"] == "image":
            aid = value["attrs"]["asset_id"]
            value["attrs"]["src"] = url(aid)
            if db is not None:
                dimensions = db.execute(
                    select(NewsAsset.width, NewsAsset.height).where(NewsAsset.id == aid)
                ).first()
                if dimensions:
                    value["attrs"].update(width=dimensions.width, height=dimensions.height)
        for child in value.get("content", []):
            walk(child)

    walk(result["document"])
    result["cover_src"] = url(result["cover_id"]) if result.get("cover_id") else None
    if published_at:
        result["publishedAt"] = (
            (published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC))
            .astimezone(ZoneInfo(base_settings().app_timezone))
            .date()
            .isoformat()
        )
    if slug:
        result["slug"] = slug
    return result


def compatibility_sections(document):
    """Keep cached older clients and stable article links usable after the upgrade."""
    sections = []
    current = None

    def text(value):
        return value.get("text", "") + "".join(text(child) for child in value.get("content", []))

    for block in document["content"]:
        if block["type"] == "heading" or current is None:
            current = {
                "title": text(block) if block["type"] == "heading" else "",
                "paragraphs": [],
                "steps": [],
                "screenshots": [],
            }
            sections.append(current)
            if block["type"] == "heading":
                continue
        if block["type"] == "image":
            current["screenshots"].append(
                {key: block["attrs"][key] for key in ("src", "alt", "caption", "width", "height")}
            )
        elif block["type"] in {"orderedList", "bulletList"}:
            current["steps"].extend(text(item) for item in block["content"])
        else:
            current["paragraphs"].append(text(block))
    return sections


@router.get("")
def news_list(user: CurrentUser, db: NewsDb):
    check_permission(user, Permission.NEWS_VIEW)
    read = set(db.scalars(select(NewsRead.article_id).where(NewsRead.reader_key == news_reader_key(user))))
    result = []
    for post in db.scalars(
        select(NewsArticle)
        .where(NewsArticle.published.is_not(None), NewsArticle.deleted_at.is_(None))
        .order_by(NewsArticle.published_at.desc(), NewsArticle.slug.desc())
    ):
        snapshot = render_snapshot(post.published, post.published_at, post.slug)
        snapshot.pop("document")
        snapshot["unread"] = post.id not in read
        result.append(snapshot)
    return result


@router.get("/unread")
def news_unread(user: CurrentUser, db: NewsDb):
    check_permission(user, Permission.NEWS_VIEW)
    return {"unread": unread_news_count(db, user)}


@router.get("/assets/{asset_id}")
def news_asset(asset_id: UUID, user: CurrentUser, db: NewsDb):
    check_permission(user, Permission.NEWS_VIEW)
    referenced = db.scalar(
        select(NewsPublishedAsset.asset_id)
        .join(NewsArticle)
        .where(
            NewsPublishedAsset.asset_id == str(asset_id),
            NewsArticle.published.is_not(None),
            NewsArticle.deleted_at.is_(None),
        )
        .limit(1)
    )
    asset = db.get(NewsAsset, str(asset_id)) if referenced else None
    if not asset:
        raise HTTPException(404, "Изображение не найдено")
    return Response(asset.content, media_type=asset.mime_type)


@router.get("/{slug}")
def news_post(slug: str, user: CurrentUser, db: NewsDb):
    check_permission(user, Permission.NEWS_VIEW)
    post = db.scalar(
        select(NewsArticle).where(
            NewsArticle.slug == slug, NewsArticle.published.is_not(None), NewsArticle.deleted_at.is_(None)
        )
    )
    if not post:
        raise HTTPException(404, "Новость не найдена")
    result = render_snapshot(post.published, post.published_at, post.slug, db=db)
    result["unread"] = db.get(NewsRead, (news_reader_key(user), post.id)) is None
    result["sections"] = compatibility_sections(result["document"])
    return result


@router.post("/{slug}/read")
def read_news_post(slug: str, user: CurrentUser, db: NewsDb):
    check_permission(user, Permission.NEWS_VIEW)
    post = db.scalar(select(NewsArticle).where(
        NewsArticle.slug == slug, NewsArticle.published.is_not(None), NewsArticle.deleted_at.is_(None),
    ))
    if not post:
        raise HTTPException(404, "Новость не найдена")
    db.execute(insert(NewsRead).values(reader_key=news_reader_key(user), article_id=post.id)
               .on_conflict_do_nothing(index_elements=[NewsRead.reader_key, NewsRead.article_id]))
    db.commit()
    return {"ok": True}


@router.get("/{slug}/screenshots/{filename}")
def news_screenshot(slug: str, filename: str, user: CurrentUser, db: NewsDb):
    check_permission(user, Permission.NEWS_VIEW)
    aid = db.scalar(
        select(NewsLegacyAsset.asset_id)
        .join(NewsArticle)
        .join(
            NewsPublishedAsset,
            (NewsPublishedAsset.article_id == NewsArticle.id)
            & (NewsPublishedAsset.asset_id == NewsLegacyAsset.asset_id),
        )
        .where(
            NewsArticle.slug == slug,
            NewsArticle.published.is_not(None),
            NewsArticle.deleted_at.is_(None),
            NewsLegacyAsset.filename == filename,
        )
    )
    asset = db.get(NewsAsset, aid) if aid else None
    if not asset:
        raise HTTPException(404, "Скриншот не найден")
    return Response(asset.content, media_type=asset.mime_type)
