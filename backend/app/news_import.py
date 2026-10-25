"""One-time, idempotent import of shipped articles into the platform database."""

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import base_settings
from app.models import NewsArticle, NewsAsset, NewsLegacyAsset, NewsPublishedAsset, NewsRevision


def import_posts(connection):
    from app.news import CONTENT_DIR, load_posts

    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        for post in load_posts():
            # Includes drafts and tombstones: deployment must never resurrect an unpublished/deleted post.
            if db.scalar(select(NewsArticle.id).where(NewsArticle.slug == post.slug)):
                continue
            instant = datetime.combine(
                post.publishedAt, datetime.min.time(), ZoneInfo(base_settings().app_timezone)
            )
            article_id, blocks, pictures = str(uuid4()), [], []
            for section in post.sections:
                blocks.append(
                    {
                        "type": "heading",
                        "attrs": {"level": 2},
                        "content": [{"type": "text", "text": section.title}],
                    }
                )
                blocks.extend(
                    {"type": "paragraph", "content": [{"type": "text", "text": p}]}
                    for p in section.paragraphs
                )
                if section.steps:
                    blocks.append(
                        {
                            "type": "orderedList",
                            "content": [
                                {
                                    "type": "listItem",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": step}]}
                                    ],
                                }
                                for step in section.steps
                            ],
                        }
                    )
                for image in section.screenshots:
                    aid = str(uuid4())
                    content = (CONTENT_DIR / post.slug / image.file).read_bytes()
                    db.add(
                        NewsAsset(
                            id=aid,
                            content=content,
                            mime_type={"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[
                                image.file.rsplit(".", 1)[1]
                            ],
                            width=image.width,
                            height=image.height,
                        )
                    )
                    pictures.append((aid, image.file))
                    blocks.append(
                        {
                            "type": "image",
                            "attrs": {"asset_id": aid, "alt": image.alt, "caption": image.caption},
                        }
                    )
            snapshot = {
                "title": post.title,
                "summary": post.summary,
                "category": post.category,
                "document": {"type": "doc", "content": blocks},
                "cover_id": None,
            }
            article = NewsArticle(
                id=article_id,
                slug=post.slug,
                version=1,
                draft=snapshot,
                published=snapshot,
                published_at=instant,
                author_name="Редакция MAX Фото",
                created_at=instant,
                updated_at=instant,
            )
            db.add(article)
            db.flush()
            db.add(
                NewsRevision(
                    id=str(uuid4()),
                    article_id=article_id,
                    version=1,
                    snapshot=snapshot,
                    action="IMPORT",
                    author_name=article.author_name,
                    created_at=instant,
                )
            )
            for aid, filename in pictures:
                db.add(NewsPublishedAsset(article_id=article_id, asset_id=aid))
                db.add(NewsLegacyAsset(article_id=article_id, filename=filename, asset_id=aid))
        db.flush()
        db.commit()
