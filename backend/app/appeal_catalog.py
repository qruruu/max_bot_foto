"""Public allowlist: only selected fields from ready, registered organizations."""

import colorsys
import json
import logging
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import database_engine
from app.models import District, Organization, WorkType
from app.organization_registry import scope_for

log = logging.getLogger(__name__)
PALETTE = ("#2563eb", "#d97706", "#15803d", "#9333ea", "#dc2626", "#0891b2", "#be185d", "#4d7c0f")


def organization_colors(records):
    """Reserve colors for inactive records too, so pause/city edits don't recolor neighbors."""
    used, result = set(), {}
    for index, record in enumerate(records):
        color = PALETTE[index] if index < len(PALETTE) else None
        step = index
        while color is None or color in used:
            rgb = colorsys.hsv_to_rgb((step * .61803398875) % 1, .75, .73)
            color = "#" + "".join(f"{round(value * 255):02x}" for value in rgb)
            step += 1
        result[record.id] = color
        used.add(color)
    return result


def organization_catalog(record, *, public=True):
    scope = scope_for(record)
    with Session(database_engine(scope.database_url)) as tenant:
        tenant.execute(text("SET TRANSACTION READ ONLY"))
        tenant.execute(text("SET LOCAL statement_timeout = '4000ms'"))
        works = [{"code": code, "name": name} for code, name in tenant.execute(
            select(WorkType.code, WorkType.name).where(
                WorkType.code.not_in(("SPAM", "DRAIN_CLEANING") if public else ("SPAM",)))
            .order_by(WorkType.sort_order, WorkType.id))]
        territories = [{"id": id, "name": name, "geometry": json.loads(geometry)}
                       for id, name, geometry in tenant.execute(select(
                           District.id, District.name, func.ST_AsGeoJSON(District.geometry))
                           .where(District.active).order_by(District.name, District.id))]
    return {"id": record.id, "name": record.name, "city": record.city,
            "work_types": works, "territories": territories}


def public_organizations(db):
    records = db.scalars(select(Organization).order_by(Organization.created_at, Organization.id)).all()
    colors = organization_colors(records)
    items = []
    for record in records:
        if record.status != "ACTIVE" or not record.city:
            continue
        try:
            item = organization_appeal_catalog(db, record)
        except (OSError, ValueError, RuntimeError, SQLAlchemyError):
            log.warning("appeal_catalog_unavailable organization=%s", record.id)
            continue
        # A blank work catalog cannot receive a valid appeal.
        if item["work_types"]:
            items.append({**item, "color": colors[record.id]})
    return items


def organization_appeal_catalog(db, record):
    item = organization_catalog(record)
    # The questionnaire and map use the same active districts from the tenant database.
    # Keep stable UUIDs for mobile drafts and compatibility with the intake contract.
    return {**item, "addresses": [{"id": territory_choice_id(record.id, area["id"]),
                                  "label": area["name"], "district_id": area["id"]}
                                 for area in item["territories"]]}


def territory_choice_id(organization_id, district_id):
    return str(uuid5(UUID(str(organization_id)), "appeal-territory:" + str(district_id)))


def validate_recipient(db, body, *, require_work_type=True):
    record = db.get(Organization, str(body.organization_id), with_for_update=True)
    if not record or record.status != "ACTIVE" or not record.city:
        raise HTTPException(422, "Выберите действующую организацию из списка")
    if body.city != record.city:
        raise HTTPException(422, "Выберите город, указанный у этой организации")
    if not require_work_type and not body.category:
        return record, None
    try:
        catalog = organization_catalog(record)
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        raise HTTPException(503, "Организация временно недоступна. Анкета и снимки сохранены.") from exc
    work = next((item for item in catalog["work_types"] if item["code"] == body.category), None)
    if work is None:
        raise HTTPException(422, "Выберите вид работ из справочника этой организации")
    return record, work
