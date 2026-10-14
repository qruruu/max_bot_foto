"""Use date/district paths for all photos and move spam to its own top-level root."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE photos SET archive_layout='district_v1' WHERE archive_layout='legacy'")
    op.execute("""INSERT INTO jobs(kind,object_id,dedupe_key,status,attempts)
        VALUES ('ARCHIVE_ORGANIZE',1,'archive-organize:v4','PENDING',0)
        ON CONFLICT (dedupe_key) DO NOTHING""")


def downgrade():
    # Remote moves are journaled and resumable; a schema downgrade must not move files back.
    pass
