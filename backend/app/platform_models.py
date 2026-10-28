"""Owner analytics live in the control database, never in a company's workspace."""
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalyticsState(Base):
    __tablename__ = 'platform_analytics_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformVisit(Base):
    __tablename__ = 'platform_visits'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product: Mapped[str] = mapped_column(String(10))
    visitor_key: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(20))
    referrer_host: Mapped[str] = mapped_column(String(253), default='')
    device: Mapped[str] = mapped_column(String(15))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (Index('ix_platform_visits_period', 'product', 'started_at'),)


class PlatformPageView(Base):
    __tablename__ = 'platform_page_views'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str] = mapped_column(ForeignKey('platform_visits.id', ondelete='CASCADE'), index=True)
    page: Mapped[str] = mapped_column(String(30))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PlatformActivity(Base):
    __tablename__ = 'platform_activity'
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    actor_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey('organizations.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlatformRequestMinute(Base):
    __tablename__ = 'platform_request_minutes'
    minute: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    product: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer)
    errors: Mapped[int] = mapped_column(Integer)
    rejected: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[float] = mapped_column(Float)
    maximum_ms: Mapped[float] = mapped_column(Float)
    buckets: Mapped[list] = mapped_column(JSONB)


class PlatformSample(Base):
    __tablename__ = 'platform_samples'
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB)


class PlatformRuntime(Base):
    __tablename__ = 'platform_runtime'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSONB)


class PlatformSecurityEvent(Base):
    __tablename__ = 'platform_security_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    product: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    actor_key: Mapped[str] = mapped_column(String(100), default='')
    actor_label: Mapped[str] = mapped_column(String(150), default='')
    organization_id: Mapped[str | None] = mapped_column(ForeignKey('organizations.id'))
    resource: Mapped[str] = mapped_column(String(100), default='')
    count: Mapped[int] = mapped_column(Integer, default=1)
    bytes_sent: Mapped[int] = mapped_column(BigInteger, default=0)
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index('ix_security_ip_period', 'ip_address', 'at'),
                     Index('ix_security_actor_period', 'actor_key', 'at'))


class PlatformSecurityAlert(Base):
    __tablename__ = 'platform_security_alerts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(15))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    actor_label: Mapped[str] = mapped_column(String(150), default='')
    organization_id: Mapped[str | None] = mapped_column(ForeignKey('organizations.id'))
    summary: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[dict] = mapped_column(JSONB)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
