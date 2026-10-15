"""Track independent JSON generations without changing the public exchange contract."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exchange_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("publication_id", sa.Integer(), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("root", sa.Text(), nullable=False),
        sa.Column("file_ref", sa.Text(), nullable=False),
        sa.Column("section", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("document", JSONB()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("root", "file_ref"),
        sa.CheckConstraint("status IN ('PENDING','AVAILABLE','DELETING','DELETED')"),
    )
    op.create_index("ix_exchange_files_section", "exchange_files", ["root", "section", "publication_id"])
    op.execute("""INSERT INTO jobs(kind,object_id,dedupe_key,status,attempts)
        SELECT 'EXCHANGE_GC',1,'exchange-gc:shared-files-v1','PENDING',0
        WHERE EXISTS (SELECT 1 FROM publications WHERE payload IS NOT NULL)
        ON CONFLICT (dedupe_key) DO NOTHING""")


def downgrade():
    # An old collector would delete shared files along with their first index.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM exchange_files"))
    if count:
        raise RuntimeError("Shared JSON files require the current publisher; restore a backup to roll back")
    op.drop_table("exchange_files")
