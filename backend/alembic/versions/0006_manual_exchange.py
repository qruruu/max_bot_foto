"""Manual, isolated test/production exchange and per-chat classification snapshots."""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from app.config import settings

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chats", sa.Column("cv_work_type_enabled", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("chats", sa.Column("fixed_work_type_code", sa.String(60)))
    op.add_column("chats", sa.Column("work_rule_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("photos", sa.Column("cohort", sa.String(20), nullable=False, server_default="test"))
    # Freeze existing paths, including files that are still waiting to synchronize.
    op.add_column(
        "photos", sa.Column("archive_layout", sa.String(20), nullable=False, server_default="legacy")
    )
    op.alter_column("photos", "archive_layout", server_default="district_v1")
    op.add_column(
        "photos",
        sa.Column("classification_mode", sa.String(30), nullable=False, server_default="LEGACY_UNKNOWN"),
    )
    op.add_column("photos", sa.Column("fixed_work_type_snapshot", sa.String(60)))
    op.add_column("photos", sa.Column("work_rule_version", sa.Integer()))
    op.add_column("photos", sa.Column("district_name_snapshot", sa.String(120)))
    op.execute("""
        UPDATE photos p SET district_name_snapshot=d.name FROM districts d WHERE p.district_id=d.id
    """)
    inspector = sa.inspect(op.get_bind())
    sha_constraints = [
        c for c in inspector.get_unique_constraints("photos") if c["column_names"] == ["sha256"]
    ]
    if len(sha_constraints) != 1:
        raise RuntimeError("Expected one legacy global SHA constraint")
    op.drop_constraint(sha_constraints[0]["name"], "photos", type_="unique")
    op.create_unique_constraint("uq_photos_cohort_sha256", "photos", ["cohort", "sha256"])
    source_checks = [
        c for c in inspector.get_check_constraints("photos") if "work_type_source" in c["sqltext"]
    ]
    if len(source_checks) != 1:
        raise RuntimeError("Expected one work_type_source constraint")
    op.drop_constraint(source_checks[0]["name"], "photos", type_="check")
    op.create_check_constraint(
        "ck_photos_work_type_source",
        "photos",
        "work_type_source IS NULL OR work_type_source IN ('AI','OPERATOR','CHAT_FIXED')",
    )
    op.create_check_constraint("ck_photos_cohort", "photos", "cohort IN ('test','production')")
    op.create_check_constraint(
        "ck_photos_archive_layout", "photos", "archive_layout IN ('legacy','district_v1')"
    )
    op.create_table(
        "exchange_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("source_timezone", sa.String(60), nullable=False),
        sa.Column("intake_cohort", sa.String(20), nullable=False),
        sa.Column("production_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_test_publication_id", sa.Integer()),
        sa.Column("last_production_publication_id", sa.Integer()),
        sa.CheckConstraint("id=1"),
        sa.CheckConstraint("intake_cohort IN ('test','production')"),
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO exchange_state(id,instance_id,source_timezone,intake_cohort) VALUES (1,:instance,:tz,'test')"
        ),
        {"instance": str(uuid.uuid4()), "tz": settings().app_timezone},
    )
    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cohort", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("as_of", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("payload", JSONB),
        sa.Column("index_path", sa.Text()),
        sa.Column("photo_count", sa.Integer()),
        sa.Column("last_error", sa.String(100)),
    )
    # Every exported change needs a version, including failures and intermediate statuses.
    # Immutable cohort prevents later corrections from promoting test data to production.
    op.execute("""
        CREATE FUNCTION photo_exchange_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.cohort IS DISTINCT FROM OLD.cohort
               OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
                RAISE EXCEPTION 'Photo identity, cohort and received_at are immutable';
            END IF;
            IF ROW(NEW.photo_date,NEW.photo_time,NEW.max_chat_id,NEW.max_message_id,NEW.district_id,
                   NEW.district_name_snapshot,NEW.work_type,NEW.work_type_source,NEW.classification_mode,
                   NEW.work_rule_version,NEW.fixed_work_type_snapshot,NEW.ai_confidence,NEW.status,NEW.storage_status,NEW.review_reason,
                   NEW.duplicate_of,NEW.sha256,NEW.yandex_disk_path,NEW.processing_error,NEW.is_spam,
                   NEW.latitude,NEW.longitude)
               IS DISTINCT FROM
               ROW(OLD.photo_date,OLD.photo_time,OLD.max_chat_id,OLD.max_message_id,OLD.district_id,
                   OLD.district_name_snapshot,OLD.work_type,OLD.work_type_source,OLD.classification_mode,
                   OLD.work_rule_version,OLD.fixed_work_type_snapshot,OLD.ai_confidence,OLD.status,OLD.storage_status,OLD.review_reason,
                   OLD.duplicate_of,OLD.sha256,OLD.yandex_disk_path,OLD.processing_error,OLD.is_spam,
                   OLD.latitude,OLD.longitude) THEN
                NEW.version := GREATEST(OLD.version+1,NEW.version);
                NEW.updated_at := now();
            ELSIF NEW.version > OLD.version THEN
                NEW.updated_at := now();
            ELSE
                NEW.version := OLD.version;
                NEW.updated_at := OLD.updated_at;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER photo_exchange_version BEFORE UPDATE ON photos
            FOR EACH ROW EXECUTE FUNCTION photo_exchange_version();
    """)


def downgrade():
    conn = op.get_bind()
    if conn.scalar(sa.text("SELECT count(*) FROM publications")) or conn.scalar(
        sa.text("SELECT count(*) FROM photos WHERE cohort='production' OR work_type_source='CHAT_FIXED'")
    ):
        raise RuntimeError("Restore a backup to preserve published identities and fixed-chat provenance")
    op.execute("DROP TRIGGER photo_exchange_version ON photos; DROP FUNCTION photo_exchange_version()")
    op.drop_table("publications")
    op.drop_table("exchange_state")
    op.drop_constraint("uq_photos_cohort_sha256", "photos", type_="unique")
    op.create_unique_constraint("photos_sha256_key", "photos", ["sha256"])
    op.drop_constraint("ck_photos_work_type_source", "photos", type_="check")
    op.create_check_constraint(
        "ck_photos_work_type_source",
        "photos",
        "work_type_source IS NULL OR work_type_source IN ('AI','OPERATOR')",
    )
    op.drop_constraint("ck_photos_cohort", "photos", type_="check")
    op.drop_constraint("ck_photos_archive_layout", "photos", type_="check")
    for column in [
        "cohort",
        "archive_layout",
        "classification_mode",
        "fixed_work_type_snapshot",
        "work_rule_version",
        "district_name_snapshot",
    ]:
        op.drop_column("photos", column)
    for column in ["cv_work_type_enabled", "fixed_work_type_code", "work_rule_version"]:
        op.drop_column("chats", column)
