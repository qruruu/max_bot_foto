"""Remove obsolete service output without creating another legacy copy on Disk."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    # A separate generation also runs on installations that already completed the old relocation.
    op.execute("""INSERT INTO jobs(kind,object_id,dedupe_key,status,attempts)
        VALUES ('ARCHIVE_ORGANIZE',1,'archive-organize:v3','PENDING',0)
        ON CONFLICT (dedupe_key) DO NOTHING""")


def downgrade():
    # Do not restore obsolete output into the customer's photo folder.
    pass
