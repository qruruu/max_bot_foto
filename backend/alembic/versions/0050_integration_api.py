"""Read-only application keys and commit-ordered, tenant-local synchronization."""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


PHOTO_DATA = """jsonb_build_object(
    'id', p.id, 'photo_date', p.photo_date, 'photo_time', p.photo_time,
    'received_at', p.received_at, 'district_id', p.district_id,
    'work_type', p.work_type, 'status', p.status,
    'is_spam', p.is_spam, 'is_forwarded', p.is_forwarded,
    'duplicate_of', p.duplicate_of, 'is_defect', p.is_defect,
    'original_available', p.yandex_disk_path IS NOT NULL AND p.processing_error IS DISTINCT FROM 'ORIGINAL_MISSING'
)"""


def upgrade():
    op.execute("""
    CREATE TABLE integration_keys (
        id varchar(36) PRIMARY KEY, organization_id varchar(36) NOT NULL REFERENCES organizations(id),
        name varchar(100) NOT NULL, secret_hash varchar(64) NOT NULL, scopes jsonb NOT NULL,
        cohort varchar(20) NOT NULL CHECK (cohort IN ('test','production')),
        created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
        revoked_at timestamptz, last_used_at timestamptz,
        "window" bigint NOT NULL DEFAULT 0, requests integer NOT NULL DEFAULT 0,
        reserved_bytes bigint NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_integration_keys_organization_id ON integration_keys(organization_id);
    CREATE TABLE integration_budgets (
        organization_id varchar(36) PRIMARY KEY REFERENCES organizations(id),
        "window" bigint NOT NULL DEFAULT 0, requests integer NOT NULL DEFAULT 0,
        reserved_bytes bigint NOT NULL DEFAULT 0
    );
    CREATE TABLE integration_clock (
        id integer PRIMARY KEY CHECK (id=1), epoch varchar(36) NOT NULL,
        sequence bigint NOT NULL DEFAULT 0, floor bigint NOT NULL DEFAULT 0
    );
    INSERT INTO integration_clock(id, epoch) VALUES (1, gen_random_uuid()::text);
    CREATE TABLE integration_changes (
        sequence bigint PRIMARY KEY, at timestamptz NOT NULL,
        entity varchar(20) NOT NULL, entity_id integer NOT NULL,
        cohort varchar(20), operation varchar(10) NOT NULL, data jsonb
    );
    CREATE INDEX ix_integration_changes_at ON integration_changes(at);
    CREATE TABLE integration_snapshots (
        id varchar(36) PRIMARY KEY, key_id varchar(36) NOT NULL,
        expires_at timestamptz NOT NULL, cursor text NOT NULL, photo_date date
    );
    CREATE INDEX ix_integration_snapshots_key_id ON integration_snapshots(key_id);
    CREATE INDEX ix_integration_snapshots_expires_at ON integration_snapshots(expires_at);
    CREATE TABLE integration_snapshot_rows (
        snapshot_id varchar(36) NOT NULL REFERENCES integration_snapshots(id) ON DELETE CASCADE,
        entity varchar(20) NOT NULL, entity_id integer NOT NULL, data jsonb NOT NULL,
        PRIMARY KEY(snapshot_id, entity, entity_id)
    );
    """)
    op.execute(f"""
    CREATE FUNCTION integration_photo_data(p photos) RETURNS jsonb LANGUAGE sql STABLE AS $$
        SELECT {PHOTO_DATA};
    $$;
    CREATE FUNCTION integration_record(e text, i integer, c text, o text, d jsonb)
    RETURNS void LANGUAGE plpgsql AS $$
    DECLARE s bigint;
    BEGIN
        INSERT INTO integration_clock(id, epoch) VALUES (1, gen_random_uuid()::text) ON CONFLICT DO NOTHING;
        UPDATE integration_clock SET sequence=sequence+1 WHERE id=1 RETURNING sequence INTO s;
        INSERT INTO integration_changes VALUES (s, clock_timestamp(), e, i, c, o, d);
    END; $$;
    CREATE FUNCTION integration_photo_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP <> 'INSERT' AND OLD.preview_removed_at IS NULL AND (
            TG_OP = 'DELETE' OR NEW.preview_removed_at IS NOT NULL OR NEW.cohort <> OLD.cohort
        ) THEN
            PERFORM integration_record('photo', OLD.id, OLD.cohort, 'delete', NULL);
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.preview_removed_at IS NULL THEN
            PERFORM integration_record('photo', NEW.id, NEW.cohort, 'upsert', integration_photo_data(NEW));
        END IF;
        RETURN NULL;
    END; $$;
    CREATE TRIGGER integration_photo_change AFTER INSERT OR UPDATE OR DELETE ON photos
        FOR EACH ROW EXECUTE FUNCTION integration_photo_change();
    CREATE FUNCTION integration_district_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            PERFORM integration_record('geozone', OLD.id, NULL, 'delete', NULL);
        ELSE
            PERFORM integration_record('geozone', NEW.id, NULL, 'upsert',
                jsonb_build_object('id', NEW.id, 'name', NEW.name, 'active', NEW.active));
        END IF;
        RETURN NULL;
    END; $$;
    CREATE TRIGGER integration_district_change AFTER INSERT OR UPDATE OR DELETE ON districts
        FOR EACH ROW EXECUTE FUNCTION integration_district_change();
    """)


def downgrade():
    op.execute("""
    DROP TRIGGER integration_photo_change ON photos;
    DROP TRIGGER integration_district_change ON districts;
    DROP FUNCTION integration_photo_change();
    DROP FUNCTION integration_district_change();
    DROP FUNCTION integration_record(text, integer, text, text, jsonb);
    DROP FUNCTION integration_photo_data(photos);
    DROP TABLE integration_snapshot_rows, integration_snapshots, integration_changes,
        integration_clock, integration_budgets, integration_keys;
    """)
