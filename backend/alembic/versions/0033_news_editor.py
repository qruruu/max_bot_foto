"""Durable global news, independent drafts, publication snapshots and immutable revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.config import base_settings, settings

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "news_articles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(150), unique=True, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft", postgresql.JSONB(), nullable=False),
        sa.Column("published", postgresql.JSONB(none_as_null=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("author_id", sa.Integer()),
        sa.Column("author_name", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "news_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(30), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "news_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("news_articles.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("author_id", sa.Integer()),
        sa.Column("author_name", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("article_id", "version"),
    )
    op.create_index("ix_news_revisions_article_id", "news_revisions", ["article_id"])
    op.create_table(
        "news_published_assets",
        sa.Column("article_id", sa.String(36), sa.ForeignKey("news_articles.id"), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("news_assets.id"), primary_key=True),
    )
    op.create_table(
        "news_legacy_assets",
        sa.Column("article_id", sa.String(36), sa.ForeignKey("news_articles.id"), primary_key=True),
        sa.Column("filename", sa.String(150), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("news_assets.id"), nullable=False),
    )
    # Company databases follow the schema, but never own/seed global content.
    if settings().database_url == base_settings().database_url:
        from app.news_import import import_posts

        import_posts(op.get_bind())


def downgrade():
    raise RuntimeError("Restore a coordinated backup; downgrading would delete published news and revisions.")
