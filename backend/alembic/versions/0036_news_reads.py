"""Remember read product news independently for each authenticated account."""

import sqlalchemy as sa

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "news_reads",
        sa.Column("reader_key", sa.String(100), primary_key=True),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("news_articles.id"), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("news_reads")
