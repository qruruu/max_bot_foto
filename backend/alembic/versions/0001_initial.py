"""Initial frozen PostgreSQL/PostGIS schema (not coupled to future ORM changes)."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS postgis
    """)
    op.execute("""
        CREATE TABLE chats (
            id SERIAL NOT NULL, 
            max_chat_id BIGINT NOT NULL, 
            name VARCHAR(150) NOT NULL, 
            active BOOLEAN NOT NULL, 
            last_reply_at TIMESTAMP WITH TIME ZONE, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            PRIMARY KEY (id), 
            UNIQUE (max_chat_id)
        )
    """)
    op.execute("""
        CREATE TABLE districts (
            id SERIAL NOT NULL, 
            name VARCHAR(120) NOT NULL, 
            active BOOLEAN NOT NULL, 
            geometry geometry(MULTIPOLYGON,4326) NOT NULL, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            PRIMARY KEY (id), 
            UNIQUE (name)
        )
    """)
    op.execute("""
        CREATE INDEX idx_districts_geometry ON districts USING gist (geometry)
    """)
    op.execute("""
        CREATE TABLE inbox (
            id SERIAL NOT NULL, 
            max_chat_id BIGINT NOT NULL, 
            message_id VARCHAR(200) NOT NULL, 
            payload JSONB NOT NULL, 
            received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            reply_text TEXT, 
            reply_sent_at TIMESTAMP WITH TIME ZONE, 
            PRIMARY KEY (id), 
            UNIQUE (max_chat_id, message_id)
        )
    """)
    op.execute("""
        CREATE TABLE jobs (
            id SERIAL NOT NULL, 
            kind VARCHAR(30) NOT NULL, 
            object_id INTEGER NOT NULL, 
            dedupe_key VARCHAR(200) NOT NULL, 
            status VARCHAR(20) NOT NULL, 
            attempts INTEGER NOT NULL, 
            next_run_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            last_error TEXT, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            PRIMARY KEY (id), 
            UNIQUE (dedupe_key)
        )
    """)
    op.execute("""
        CREATE INDEX ix_jobs_ready ON jobs (status, next_run_at)
    """)
    op.execute("""
        CREATE TABLE login_attempts (
            key VARCHAR(64) NOT NULL, 
            count INTEGER NOT NULL, 
            started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            PRIMARY KEY (key)
        )
    """)
    op.execute("""
        CREATE TABLE users (
            id SERIAL NOT NULL, 
            login VARCHAR(100) NOT NULL, 
            name VARCHAR(150) NOT NULL, 
            password_hash TEXT NOT NULL, 
            role VARCHAR(30) NOT NULL, 
            active BOOLEAN NOT NULL, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            PRIMARY KEY (id), 
            CHECK (role IN ('ADMIN_OPERATOR', 'OPERATOR')), 
            UNIQUE (login)
        )
    """)
    op.execute("""
        CREATE TABLE login_sessions (
            token_hash VARCHAR(64) NOT NULL, 
            csrf_hash VARCHAR(64) NOT NULL, 
            user_id INTEGER NOT NULL, 
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
            PRIMARY KEY (token_hash), 
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_login_sessions_expires_at ON login_sessions (expires_at)
    """)
    op.execute("""
        CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id)
    """)
    op.execute("""
        CREATE TABLE photos (
            id SERIAL NOT NULL, 
            inbox_id INTEGER NOT NULL, 
            attachment_index INTEGER NOT NULL, 
            attachment JSONB NOT NULL, 
            sha256 VARCHAR(64), 
            duplicate_of INTEGER, 
            original_filename VARCHAR(500), 
            stored_filename VARCHAR(255), 
            extension VARCHAR(10), 
            mime_type VARCHAR(100), 
            file_size BIGINT, 
            max_chat_id BIGINT NOT NULL, 
            chat_name VARCHAR(150) NOT NULL, 
            max_message_id VARCHAR(200) NOT NULL, 
            sender_id BIGINT, 
            received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            is_forwarded BOOLEAN NOT NULL, 
            photo_date DATE, 
            photo_time TIME WITHOUT TIME ZONE, 
            ocr_raw_text TEXT, 
            ocr_date_raw TEXT, 
            ocr_coordinates_raw TEXT, 
            coordinate_format VARCHAR(30), 
            coordinate_parse_confidence FLOAT, 
            latitude FLOAT, 
            longitude FLOAT, 
            ocr_address_raw TEXT, 
            detected_address TEXT, 
            detected_city VARCHAR(300), 
            district_id INTEGER, 
            ai_result JSONB, 
            ai_confidence FLOAT, 
            ai_alternatives JSONB NOT NULL, 
            work_type VARCHAR(60), 
            work_type_source VARCHAR(20), 
            status VARCHAR(30) NOT NULL, 
            review_reason JSONB NOT NULL, 
            yandex_disk_path TEXT, 
            storage_status VARCHAR(20) NOT NULL, 
            processing_error TEXT, 
            analyzed_at TIMESTAMP WITH TIME ZONE, 
            reviewed_by INTEGER, 
            reviewed_at TIMESTAMP WITH TIME ZONE, 
            version INTEGER NOT NULL, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            PRIMARY KEY (id), 
            UNIQUE (inbox_id, attachment_index), 
            CHECK (latitude BETWEEN -90 AND 90), 
            CHECK (longitude BETWEEN -180 AND 180), 
            CHECK ((latitude IS NULL) = (longitude IS NULL)), 
            CHECK (status IN ('RECEIVED','PROCESSING','ACCEPTED','NEEDS_REVIEW','REJECTED','DUPLICATE','FORWARDED','ERROR')), 
            CHECK (work_type_source IS NULL OR work_type_source IN ('AI','OPERATOR')), 
            FOREIGN KEY(inbox_id) REFERENCES inbox (id), 
            UNIQUE (sha256), 
            FOREIGN KEY(duplicate_of) REFERENCES photos (id), 
            FOREIGN KEY(district_id) REFERENCES districts (id), 
            FOREIGN KEY(reviewed_by) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_photos_work_type ON photos (work_type)
    """)
    op.execute("""
        CREATE INDEX ix_photos_inbox_id ON photos (inbox_id)
    """)
    op.execute("""
        CREATE INDEX ix_photos_status ON photos (status)
    """)
    op.execute("""
        CREATE INDEX ix_photos_max_chat_id ON photos (max_chat_id)
    """)
    op.execute("""
        CREATE INDEX ix_photos_photo_date ON photos (photo_date)
    """)
    op.execute("""
        CREATE INDEX ix_photos_review_order ON photos (status, received_at, id)
    """)
    op.execute("""
        CREATE INDEX ix_photos_district_id ON photos (district_id)
    """)
    op.execute("""
        CREATE INDEX ix_photos_reviewed_by ON photos (reviewed_by)
    """)
    op.execute("""
        CREATE INDEX ix_photos_received_at ON photos (received_at)
    """)
    op.execute("""
        CREATE TABLE audit_logs (
            id SERIAL NOT NULL, 
            user_id INTEGER, 
            at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
            action VARCHAR(100) NOT NULL, 
            object_type VARCHAR(40) NOT NULL, 
            object_id INTEGER NOT NULL, 
            photo_id INTEGER, 
            old_value JSONB, 
            new_value JSONB, 
            PRIMARY KEY (id), 
            FOREIGN KEY(user_id) REFERENCES users (id), 
            FOREIGN KEY(photo_id) REFERENCES photos (id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_audit_logs_photo_id ON audit_logs (photo_id)
    """)
    op.execute("""
        CREATE INDEX ix_audit_logs_at ON audit_logs (at)
    """)


def downgrade():
    op.drop_table("audit_logs")
    op.drop_table("photos")
    op.drop_table("login_sessions")
    op.drop_table("users")
    op.drop_table("login_attempts")
    op.drop_table("jobs")
    op.drop_table("inbox")
    op.drop_table("districts")
    op.drop_table("chats")
