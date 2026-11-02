"""Opt-in photo trajectories, scoped to the tenant, chat and territory."""
import math
from collections import defaultdict
from datetime import date, datetime, time

import httpx
from fastapi import APIRouter, HTTPException, Query
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import polygonize, unary_union
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.auth import AdminUser, Db, PhotosReader
from app.chat_access import allowed_chat_ids
from app.domain import audit
from app.models import Chat, District, Photo, PhotoRoutePlan
from app.photo_route_geometry import RouteNetwork
from app.photo_scope import active_cohort_condition

router = APIRouter(prefix="/api/photo-routes", tags=["photo-routes"])


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    enabled: bool
    chat_ids: list[int] = Field(max_length=200)
    paths: list[list[tuple[float, float]]] = Field(max_length=300)
    buildings: list[dict] = Field(max_length=3000)
    buildings_source: str = Field(default="manual", max_length=100)
    buildings_checked: bool
    snap_m: int = Field(default=25, ge=1, le=50)
    max_gap_minutes: int = Field(default=45, ge=1, le=120)

    @model_validator(mode="after")
    def validate_geometry(self):
        if sum(map(len, self.paths)) > 10000:
            raise ValueError("В маршруте слишком много точек")
        for path in self.paths:
            if len(path) < 2:
                raise ValueError("В каждом участке нужны хотя бы две точки")
            for lon, lat in path:
                if not math.isfinite(lon + lat) or not (-180 <= lon <= 180 and -80 <= lat <= 80):
                    raise ValueError("Некорректные координаты маршрута")
        count = 0
        for building in self.buildings:
            try:
                polygon = shape(building)
                if polygon.geom_type not in {"Polygon", "MultiPolygon"} or polygon.is_empty or not polygon.is_valid:
                    raise ValueError()
                bounds = polygon.bounds
                if not all(math.isfinite(v) for v in bounds) or not (-180 <= bounds[0] <= bounds[2] <= 180 and -80 <= bounds[1] <= bounds[3] <= 80):
                    raise ValueError()
                from shapely import get_num_coordinates
                count += get_num_coordinates(polygon)
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                raise ValueError("Некорректный контур здания") from exc
        if count > 100000:
            raise ValueError("Слишком много точек в контурах зданий")
        if self.enabled and (not self.paths or not self.chat_ids or not self.buildings_checked):
            raise ValueError("Выберите чаты, отметьте маршрут и подтвердите проверку контуров домов")
        return self


def visible_chats(db, user):
    statement = select(Chat).where(Chat.active.is_(True))
    ids = allowed_chat_ids(user)
    if ids is not None:
        statement = statement.where(Chat.id.in_(ids))
    return {chat.id: chat for chat in db.scalars(statement)}


def plan_dict(plan, chat_ids):
    return {"district_id": plan.district_id, "version": plan.version, "enabled": plan.enabled,
            "chat_ids": sorted(set(plan.chat_ids) & set(chat_ids)), "paths": plan.paths,
            "buildings": plan.buildings, "buildings_source": plan.buildings_source,
            "snap_m": plan.snap_m, "max_gap_minutes": plan.max_gap_minutes}


@router.get("")
def plans(db: Db, user: PhotosReader):
    chats = visible_chats(db, user)
    admin = user.role == "ADMIN_OPERATOR"
    rows = list(db.scalars(select(PhotoRoutePlan)))
    rows = [p for p in rows if admin or (p.enabled and set(p.chat_ids) & chats.keys())]
    eligible = set(chats) if admin else {cid for p in rows for cid in p.chat_ids if cid in chats}
    return {"plans": [plan_dict(p, chats) for p in rows],
            "chats": [{"id": cid, "name": chats[cid].name} for cid in sorted(eligible)],
            "territories": [{"type": "Feature", "geometry": mapping(to_shape(d.geometry)),
                             "properties": {"id": d.id, "name": d.name, "active": d.active}}
                            for d in db.scalars(select(District).where(District.active.is_(True)))
                            if admin or any(p.district_id == d.id for p in rows)]}


@router.put("/{district_id}")
def save_plan(district_id: int, body: PlanInput, db: Db, user: AdminUser):
    district = db.get(District, district_id)
    if not district or not district.active:
        raise HTTPException(404, "Территория не найдена")
    if set(body.chat_ids) - visible_chats(db, user).keys():
        raise HTTPException(422, "Выберите действующие чаты")
    try:
        RouteNetwork(to_shape(district.geometry), body.paths, body.buildings)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Reserve a new row before locking; concurrent initial saves use the same version check.
    db.execute(insert(PhotoRoutePlan).values(district_id=district_id, version=0, enabled=False,
               chat_ids=[], paths=[], buildings=[], buildings_source="manual", snap_m=25,
               max_gap_minutes=45).on_conflict_do_nothing())
    plan = db.scalar(select(PhotoRoutePlan).where(PhotoRoutePlan.district_id == district_id).with_for_update())
    if plan.version != body.version:
        raise HTTPException(409, "Маршрут уже изменён. Обновите страницу перед сохранением")
    for key, value in body.model_dump(exclude={"version", "buildings_checked"}).items():
        setattr(plan, key, value)
    plan.version += 1
    audit(db, user.id, "PHOTO_ROUTE_SAVED", "district", district_id, None,
          {"version": plan.version, "enabled": plan.enabled, "chat_ids": plan.chat_ids})
    db.commit()
    return plan_dict(plan, visible_chats(db, user))


@router.get("/{district_id}/coverage")
def coverage(district_id: int, db: Db, user: PhotosReader, date_from: date, date_to: date,
             chat_id: int | None = None):
    if not 0 <= (date_to - date_from).days <= 30:
        raise HTTPException(422, "Выберите один день или период до 31 дня")
    plan, district = db.get(PhotoRoutePlan, district_id), db.get(District, district_id)
    chats = visible_chats(db, user)
    ids = set(plan.chat_ids) & chats.keys() if plan and plan.enabled else set()
    if chat_id is not None:
        ids &= {chat_id}
    if not ids or not district or not district.active:
        raise HTTPException(404, "Для выбранного чата и территории маршрут не включён")
    # Include out-of-territory observations so they interrupt, rather than bridge, trajectories.
    rows = db.scalars(select(Photo).where(
        Photo.max_chat_id.in_([chats[cid].max_chat_id for cid in ids]), active_cohort_condition(),
        Photo.photo_date.between(date_from, date_to), Photo.is_spam.is_(False),
        Photo.preview_removed_at.is_(None), Photo.status == "ACCEPTED",
    ).order_by(Photo.id).limit(5001)).all()
    if len(rows) > 5000:
        raise HTTPException(422, "Более 5000 фотографий. Уменьшите период или выберите один чат")
    observations = [{"id": p.id, "longitude": p.longitude, "latitude": p.latitude,
                     "chat_id": p.max_chat_id, "sender_id": p.sender_id,
                     "taken_at": datetime.combine(p.photo_date, p.photo_time or time.min), "time_known": p.photo_time is not None}
                    for p in rows]
    try:
        network = RouteNetwork(to_shape(district.geometry), plan.paths, plan.buildings)
        result = network.coverage(observations, plan.snap_m, plan.max_gap_minutes)
    except ValueError as exc:
        raise HTTPException(422, "Границы изменились. Исправьте план маршрута: " + str(exc)) from exc
    result.update({"version": plan.version, "photo_count": len(rows), "photos": [
        {"id": p.id, "longitude": p.longitude, "latitude": p.latitude,
         "taken_at": p.photo_date.isoformat() + " " + str(p.photo_time or ""), "chat_name": p.chat_name}
        for p in rows if p.latitude is not None and p.longitude is not None
        and to_shape(district.geometry).covers(Point(p.longitude, p.latitude))],
        "unknown_time": sum(p.photo_time is None for p in rows)})
    return result


@router.get("/{district_id}/buildings")
def load_buildings(district_id: int, db: Db, user: AdminUser,
                   source: str = Query(default="osm", pattern="^osm$")):
    district = db.get(District, district_id)
    if not district:
        raise HTTPException(404, "Территория не найдена")
    area = to_shape(district.geometry)
    west, south, east, north = area.bounds
    if (east - west) * (north - south) > .08:
        raise HTTPException(422, "Слишком большая территория для загрузки контуров домов")
    query = f'[out:json][timeout:25];(way["building"]({south},{west},{north},{east});relation["building"]({south},{west},{north},{east}););out geom;'
    try:
        with httpx.Client(timeout=35) as client, client.stream(
            "POST", "https://overpass-api.de/api/interpreter", data={"data": query},
            headers={"User-Agent": "Metka-photo-routes/1.0"},
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 10_000_000:
                    raise ValueError("Слишком большой ответ карты")
                chunks.append(chunk)
        import json
        data = json.loads(b"".join(chunks))
        buildings = []
        for element in data.get("elements", []):
            if element["type"] == "way":
                coords = [(p["lon"], p["lat"]) for p in element.get("geometry", [])]
                candidates = [Polygon(coords)] if len(coords) >= 4 and coords[0] == coords[-1] else []
            else:
                rings = defaultdict(list)
                for member in element.get("members", []):
                    coords = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
                    if len(coords) > 1:
                        rings[member.get("role") or "outer"].append(LineString(coords))
                outer = unary_union(list(polygonize(unary_union(rings["outer"]))))
                inner = unary_union(list(polygonize(unary_union(rings["inner"]))))
                candidates = [outer.difference(inner)]
            for polygon in candidates:
                if polygon.geom_type in {"Polygon", "MultiPolygon"} and polygon.is_valid and polygon.intersects(area):
                    buildings.append(mapping(polygon))
        if len(buildings) > 3000:
            raise ValueError("Слишком много зданий: уменьшите территорию")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "Не удалось загрузить контуры домов. Повторите позже или отметьте их вручную") from exc
    return {"buildings": buildings, "source": "OpenStreetMap", "notice": "Проверьте полноту контуров домов перед сохранением"}
