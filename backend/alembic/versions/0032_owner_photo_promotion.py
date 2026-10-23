"""Permit one explicitly authorized test-to-production change per transaction."""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    # Regular edits and mode switches still cannot alter an existing photo's cohort.
    # Only the owner endpoint sets these transaction-local, row/version-specific grants.
    op.execute("""
        CREATE OR REPLACE FUNCTION photo_exchange_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
                RAISE EXCEPTION 'Photo identity and received_at are immutable';
            END IF;
            IF NEW.cohort IS DISTINCT FROM OLD.cohort AND NOT (
                OLD.cohort = 'test' AND NEW.cohort = 'production'
                AND COALESCE(current_setting('max_photos.promote_id', true), '') = OLD.id::text
                AND COALESCE(current_setting('max_photos.promote_version', true), '') = OLD.version::text
            ) THEN
                RAISE EXCEPTION 'Photo cohort requires an explicit owner promotion';
            END IF;
            IF ROW(NEW.cohort,NEW.photo_date,NEW.photo_time,NEW.max_chat_id,NEW.max_message_id,NEW.district_id,
                   NEW.district_name_snapshot,NEW.work_type,NEW.work_type_source,NEW.classification_mode,
                   NEW.work_rule_version,NEW.fixed_work_type_snapshot,NEW.ai_confidence,NEW.status,NEW.storage_status,NEW.review_reason,
                   NEW.duplicate_of,NEW.sha256,NEW.yandex_disk_path,NEW.processing_error,NEW.is_spam,
                   NEW.latitude,NEW.longitude)
               IS DISTINCT FROM
               ROW(OLD.cohort,OLD.photo_date,OLD.photo_time,OLD.max_chat_id,OLD.max_message_id,OLD.district_id,
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
    """)


def downgrade():
    raise RuntimeError("Restore a coordinated backup to preserve explicitly promoted photo identities.")
