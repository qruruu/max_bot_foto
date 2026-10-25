"""Platform-owner authoring API. All content and bytes live in the control database."""

import warnings
from copy import deepcopy
from io import BytesIO
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field
from sqlalchemy import delete, select

from app.auth import CurrentUser, is_platform_owner
from app.domain import now
from app.models import NewsArticle, NewsAsset, NewsPublishedAsset, NewsRevision
from app.news import NewsDb, render_snapshot
from app.news_documents import NewsSnapshot, asset_ids, publishable
from app.schemas import StrictModel

router = APIRouter(prefix="/api/platform/news", tags=["news editor"])
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def editor_only(user: CurrentUser):
    if not is_platform_owner(user):
        raise HTTPException(403, "Управление общими новостями доступно только владельцу сервиса")
    return user


Editor = Annotated[object, Depends(editor_only)]


class CreateArticle(StrictModel):
    template: Literal["empty", "update", "tip"] = "empty"


class SaveArticle(NewsSnapshot):
    expected_version: int = Field(ge=1)


class ArticleVersion(StrictModel):
    expected_version: int = Field(ge=1)


def template_snapshot(template):
    def paragraph(text=""):
        return {"type": "paragraph", **({"content": [{"type": "text", "text": text}]} if text else {})}

    blocks = [paragraph()]
    if template == "update":
        blocks = [
            paragraph("Расскажите, какую задачу оператора теперь проще выполнить."),
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Как пользоваться"}],
            },
            {
                "type": "orderedList",
                "content": [{"type": "listItem", "content": [paragraph("Откройте нужный раздел.")]}],
            },
            paragraph("Добавьте скриншот рядом с соответствующим действием."),
            {"type": "important", "content": [paragraph("Укажите нужные права и существенные условия.")]},
        ]
    elif template == "tip":
        blocks = [
            paragraph("Опишите знакомую рабочую ситуацию и полезный приём."),
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Попробуйте в работе"}],
            },
            paragraph("Покажите короткий пример и результат."),
        ]
    return {
        "title": "",
        "summary": "",
        "category": "Обновление" if template != "tip" else "Полезный совет",
        "document": {"type": "doc", "content": blocks},
        "cover_id": None,
    }


def actor(user):
    return getattr(user, "_platform_user_id", None) or user.id, user.name


def record_revision(db, article, user, action):
    article.author_id, article.author_name = actor(user)
    article.updated_at = now()
    db.add(
        NewsRevision(
            id=str(uuid4()),
            article_id=article.id,
            version=article.version,
            snapshot=deepcopy(article.draft),
            action=action,
            author_id=article.author_id,
            author_name=article.author_name,
            created_at=article.updated_at,
        )
    )


def detail(article):
    return {
        "id": article.id,
        "slug": article.slug,
        "version": article.version,
        "draft": article.draft,
        "published": article.published,
        "published_at": article.published_at,
        "deleted_at": article.deleted_at,
        "updated_at": article.updated_at,
        "author_name": article.author_name,
        "has_changes": article.draft != article.published,
    }


def locked(db, id, version, *, allow_trash=False):
    article = db.scalar(select(NewsArticle).where(NewsArticle.id == str(id)).with_for_update())
    if not article:
        raise HTTPException(404, "Новость не найдена")
    if article.version != version:
        raise HTTPException(
            409,
            {
                "code": "NEWS_CONFLICT",
                "message": "Эту новость уже изменили в другой вкладке. Ваш текст сохранён в редакторе. Скопируйте его или откройте свежую версию.",
                "version": article.version,
            },
        )
    if article.deleted_at and not allow_trash:
        raise HTTPException(409, "Новость находится в корзине. Сначала восстановите её.")
    return article


def check_assets(db, snapshot):
    ids = asset_ids(snapshot)
    if ids and set(db.scalars(select(NewsAsset.id).where(NewsAsset.id.in_(ids)))) != ids:
        raise HTTPException(422, "В статье есть изображение, которого нет в хранилище")


def published_assets(db, article):
    db.execute(delete(NewsPublishedAsset).where(NewsPublishedAsset.article_id == article.id))
    if article.published and not article.deleted_at:
        db.add_all(
            NewsPublishedAsset(article_id=article.id, asset_id=aid) for aid in asset_ids(article.published)
        )


@router.get("")
def articles(user: Editor, db: NewsDb, state: Literal["active", "trash"] = "active"):
    posts = db.scalars(
        select(NewsArticle)
        .where(NewsArticle.deleted_at.is_(None) if state == "active" else NewsArticle.deleted_at.is_not(None))
        .order_by(NewsArticle.updated_at.desc(), NewsArticle.id)
    )
    return [
        {
            **detail(post),
            "draft": {k: v for k, v in post.draft.items() if k != "document"},
            "published": bool(post.published),
        }
        for post in posts
    ]


@router.post("", status_code=201)
def create_article(body: CreateArticle, user: Editor, db: NewsDb):
    id = str(uuid4())
    post = NewsArticle(id=id, slug="post-" + id, version=1, draft=template_snapshot(body.template))
    db.add(post)
    record_revision(db, post, user, "CREATE")
    db.commit()
    return detail(post)


@router.post("/assets", status_code=201)
async def upload_asset(request: Request, user: Editor, db: NewsDb):
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(415, "Можно загрузить PNG, JPG или WebP")
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Изображение должно быть не больше 8 МБ")
        chunks.extend(chunk)
    asset = await run_in_threadpool(normalize_asset, bytes(chunks), content_type)
    asset.id, asset.author_id = str(uuid4()), actor(user)[0]
    db.add(asset)
    db.commit()
    return {
        "id": asset.id,
        "src": f"/api/platform/news/assets/{asset.id}",
        "width": asset.width,
        "height": asset.height,
    }


def normalize_asset(content, mime_type):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("format")
                if image.width * image.height > 24_000_000 or max(image.size) > 10000:
                    raise ValueError("dimensions")
                if Image.MIME[image.format] != mime_type:
                    raise ValueError("mime")
                image.load()
                image = ImageOps.exif_transpose(image).convert("RGBA" if "A" in image.getbands() else "RGB")
                output = BytesIO()
                image.save(output, format="WEBP", quality=90, method=4)
                if output.tell() > MAX_UPLOAD_BYTES:
                    raise ValueError("size")
                return NewsAsset(
                    content=output.getvalue(), mime_type="image/webp", width=image.width, height=image.height
                )
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise HTTPException(
            422,
            "Не удалось прочитать изображение. Нужен статичный PNG/JPG/WebP до 24 Мп и 10 000 пикселей по стороне.",
        ) from exc


@router.get("/assets/{id}")
def editor_asset(id: UUID, user: Editor, db: NewsDb):
    asset = db.get(NewsAsset, str(id))
    if not asset:
        raise HTTPException(404, "Изображение не найдено")
    return Response(asset.content, media_type=asset.mime_type)


@router.get("/{id}")
def get_article(id: UUID, user: Editor, db: NewsDb):
    post = db.get(NewsArticle, str(id))
    if not post:
        raise HTTPException(404, "Новость не найдена")
    return detail(post)


@router.put("/{id}")
def save_article(id: UUID, body: SaveArticle, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version)
    snapshot = body.model_dump(exclude={"expected_version"})
    check_assets(db, snapshot)
    if snapshot != post.draft:
        post.draft = snapshot
        post.version += 1
        record_revision(db, post, user, "SAVE")
        db.commit()
    return detail(post)


@router.post("/{id}/preview")
def preview_article(id: UUID, body: ArticleVersion, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version)
    return render_snapshot(post.draft, post.published_at or now(), post.slug, editor=True)


@router.post("/{id}/publish")
def publish_article(id: UUID, body: ArticleVersion, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version)
    try:
        publishable(post.draft)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    check_assets(db, post.draft)
    post.published = deepcopy(post.draft)
    post.published_at = post.published_at or now()
    post.version += 1
    published_assets(db, post)
    record_revision(db, post, user, "PUBLISH")
    db.commit()
    return detail(post)


@router.post("/{id}/unpublish")
def unpublish_article(id: UUID, body: ArticleVersion, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version)
    post.published = None
    post.version += 1
    published_assets(db, post)
    record_revision(db, post, user, "UNPUBLISH")
    db.commit()
    return detail(post)


@router.post("/{id}/trash")
def trash_article(id: UUID, body: ArticleVersion, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version)
    post.deleted_at = now()
    post.version += 1
    published_assets(db, post)
    record_revision(db, post, user, "TRASH")
    db.commit()
    return detail(post)


@router.post("/{id}/restore")
def restore_article(id: UUID, body: ArticleVersion, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version, allow_trash=True)
    if not post.deleted_at:
        raise HTTPException(409, "Эта новость уже восстановлена")
    post.deleted_at = None
    # Restoring never silently republishes previously removed content.
    post.published = None
    post.version += 1
    record_revision(db, post, user, "RESTORE")
    db.commit()
    return detail(post)


@router.get("/{id}/revisions")
def revisions(id: UUID, user: Editor, db: NewsDb):
    if not db.get(NewsArticle, str(id)):
        raise HTTPException(404, "Новость не найдена")
    return [
        {
            "id": row.id,
            "version": row.version,
            "action": row.action,
            "author_name": row.author_name,
            "created_at": row.created_at,
            "snapshot": row.snapshot,
        }
        for row in db.scalars(
            select(NewsRevision)
            .where(NewsRevision.article_id == str(id))
            .order_by(NewsRevision.version.desc())
        )
    ]


@router.post("/{id}/revisions/{revision_id}/restore")
def restore_revision(id: UUID, revision_id: UUID, body: ArticleVersion, user: Editor, db: NewsDb):
    post = locked(db, id, body.expected_version)
    revision = db.get(NewsRevision, str(revision_id))
    if not revision or revision.article_id != post.id:
        raise HTTPException(404, "Редакция не найдена")
    post.draft = deepcopy(revision.snapshot)
    post.version += 1
    record_revision(db, post, user, "RESTORE_REVISION")
    db.commit()
    return detail(post)
