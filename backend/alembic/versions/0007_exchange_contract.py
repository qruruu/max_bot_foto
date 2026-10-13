"""Restore the requested wire contract; separate private files from the client archive."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # Existing source identities stay unchanged. Exported test -> training changes need a new version.
    op.execute("UPDATE photos SET version=version+1 WHERE cohort='test'")
    # Never retry an immutable payload of the incorrect old wire format into the new namespace.
    op.execute("""UPDATE publications SET status='SUPERSEDED'
        WHERE status IN ('PENDING','UPLOADING','RETRY') AND payload IS NOT NULL""")
    op.execute("""INSERT INTO jobs(kind,object_id,dedupe_key,status,attempts)
        VALUES ('ARCHIVE_ORGANIZE',1,'archive-organize:v2','PENDING',0)
        ON CONFLICT (dedupe_key) DO NOTHING""")


def downgrade():
    # A rollback must not lower versions or move already relocated originals back into a client folder.
    pass
