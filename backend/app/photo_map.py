"""Bounded photo map reads, shared by workspaces and inspection."""

import math
import re
from asyncio import Semaphore
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, literal_column, or_, text
from sqlalchemy.exc import DBAPIError

PAGE_SIZE = 120
BUSY = "Карта сейчас занята. Попробуйте ещё раз через несколько секунд."
MAP_PATH = re.compile(
    r"(?:(?:/org/[0-9a-f-]{36})?/api|/api/inspection/organizations/[0-9a-f-]{36})/photos/map"
    r"|(?:/org/[0-9a-f-]{36})?/api/photos/map-filter-counts"
)


class PhotoMapAdmission:
    """Keep map traffic out of the shared API pool before authentication."""

    def __init__(self, app):
        self.app = app
        self.slots = Semaphore(2)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET" and MAP_PATH.fullmatch(scope["path"]):
            if self.slots.locked():
                return await JSONResponse({"detail": BUSY}, status_code=503, headers={"Retry-After": "2"})(scope, receive, send)
            async with self.slots:
                return await self.app(scope, receive, send)
        return await self.app(scope, receive, send)


@contextmanager
def map_read(db):
    # Transaction-scoped slots also apply when several API processes share a database.
    db.execute(text("SET LOCAL statement_timeout = '2s'"))
    if not any(db.scalar(text("SELECT pg_try_advisory_xact_lock(7041, :slot)"), {"slot": slot})
               for slot in (1, 2)):
        raise HTTPException(503, BUSY, headers={"Retry-After": "2"})
    try:
        yield
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != "57014":
            raise
        raise HTTPException(503, "Карта не успела загрузиться. Приблизьте область или сократите период.", headers={"Retry-After": "2"}) from exc


def map_bounds(raw):
    try:
        west, south, east, north = map(float, raw.split(","))
        if (not all(map(math.isfinite, (west, south, east, north)))
                or not -180 <= west <= 180 or not -180 <= east <= 180
                or west == east or not -90 <= south < north <= 90):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Некорректные границы карты") from None
    return west, south, east, north


def viewport_page(db, selection, bounds, after_id):
    from app.models import Photo

    west, south, east, north = map_bounds(bounds)
    point = func.ST_SetSRID(func.ST_MakePoint(Photo.longitude, Photo.latitude), literal_column("4326"))
    ranges = [(west, east)] if west < east else [(west, 180), (-180, east)]
    area = or_(*[
        point.op("&&")(func.ST_MakeEnvelope(left, south, right, north, 4326))
        & Photo.longitude.between(left, right)
        for left, right in ranges
    ])
    return db.execute(selection.where(
        Photo.id > after_id, Photo.longitude.is_not(None), Photo.latitude.is_not(None),
        Photo.latitude.between(south, north), area,
    ).order_by(Photo.id).limit(PAGE_SIZE + 1)).mappings().all()
