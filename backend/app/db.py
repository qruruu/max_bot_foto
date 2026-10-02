from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    return create_engine(settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def get_db():
    with Session(engine(), expire_on_commit=False) as db:
        yield db
