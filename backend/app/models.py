from datetime import date, datetime, time

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("role IN ('ADMIN_OPERATOR', 'OPERATOR')"),)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chat(Timestamps, Base):
    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    max_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(150))
    active: Mapped[bool] = mapped_column(default=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class District(Timestamps, Base):
    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    geometry: Mapped[object] = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))


class Inbox(Base):
    __tablename__ = "inbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    max_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reply_text: Mapped[str | None] = mapped_column(Text)
    reply_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("max_chat_id", "message_id"),)


class Photo(Timestamps, Base):
    __tablename__ = "photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    inbox_id: Mapped[int] = mapped_column(ForeignKey("inbox.id"), index=True)
    attachment_index: Mapped[int] = mapped_column(Integer)
    attachment: Mapped[dict] = mapped_column(JSONB, default=dict)
    sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("photos.id"))
    original_filename: Mapped[str | None] = mapped_column(String(500))
    stored_filename: Mapped[str | None] = mapped_column(String(255))
    extension: Mapped[str | None] = mapped_column(String(10))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    max_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_name: Mapped[str] = mapped_column(String(150))
    max_message_id: Mapped[str] = mapped_column(String(200))
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    is_forwarded: Mapped[bool] = mapped_column(default=False)
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    photo_date: Mapped[date | None] = mapped_column(Date, index=True)
    photo_time: Mapped[time | None] = mapped_column(Time)
    ocr_raw_text: Mapped[str | None] = mapped_column(Text)
    ocr_date_raw: Mapped[str | None] = mapped_column(Text)
    ocr_coordinates_raw: Mapped[str | None] = mapped_column(Text)
    coordinate_format: Mapped[str | None] = mapped_column(String(30))
    coordinate_parse_confidence: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    ocr_address_raw: Mapped[str | None] = mapped_column(Text)
    detected_address: Mapped[str | None] = mapped_column(Text)
    detected_city: Mapped[str | None] = mapped_column(String(300))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    ai_result: Mapped[dict | None] = mapped_column(JSONB)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_alternatives: Mapped[list] = mapped_column(JSONB, default=list)
    work_type: Mapped[str | None] = mapped_column(String(60), index=True)
    work_type_source: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED", index=True)
    review_reason: Mapped[list] = mapped_column(JSONB, default=list)
    yandex_disk_path: Mapped[str | None] = mapped_column(Text)
    storage_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    processing_error: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = (
        UniqueConstraint("inbox_id", "attachment_index"),
        CheckConstraint("latitude BETWEEN -90 AND 90"),
        CheckConstraint("longitude BETWEEN -180 AND 180"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)"),
        CheckConstraint(
            "status IN ('RECEIVED','PROCESSING','ACCEPTED','NEEDS_REVIEW','REJECTED','DUPLICATE','FORWARDED','ERROR','SPAM')",
            name="ck_photos_status",
        ),
        CheckConstraint("work_type_source IS NULL OR work_type_source IN ('AI','OPERATOR')"),
        Index("ix_photos_review_order", "status", "received_at", "id"),
    )


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    action: Mapped[str] = mapped_column(String(100))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[int] = mapped_column(Integer)
    photo_id: Mapped[int | None] = mapped_column(ForeignKey("photos.id"), index=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[int] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_jobs_ready", "status", "next_run_at"),)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    sample_count: Mapped[int] = mapped_column(Integer)
    labels_snapshot: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    supported_classes: Mapped[list] = mapped_column(JSONB, default=list)
    model_path: Mapped[str | None] = mapped_column(Text)
    model_sha256: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("ix_one_active_model", "status", unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )


class MaxReceiverState(Base):
    __tablename__ = "max_receiver_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_fingerprint: Mapped[str | None] = mapped_column(String(64))
    marker: Mapped[int | None] = mapped_column(BigInteger)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(100))
    events_received: Mapped[int] = mapped_column(BigInteger, default=0)
    inbox_received: Mapped[int] = mapped_column(BigInteger, default=0)
