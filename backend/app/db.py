from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import NullPool

from app.config import base_settings, settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=128)
def database_engine(url):
    if url != base_settings().database_url:
        # Idle companies must not reserve a connection in every service process.
        return create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
    # Keep few idle connections per company, but allow the nested job/storage locks.
    return create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=9, pool_recycle=300)


def engine():
    return database_engine(settings().database_url)


engine.cache_clear = database_engine.cache_clear
engine.cache_info = database_engine.cache_info


def get_db():
    with Session(engine(), expire_on_commit=False) as db:
        try:
            yield db
        finally:
            if "session_activity" in db.info:
                from app.session_details import record_session_activity

                record_session_activity(db)
