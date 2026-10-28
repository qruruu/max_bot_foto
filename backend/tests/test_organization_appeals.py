import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_appeals import ORGANIZATION, body, send, start
from test_appeals import owner as owner
from test_organizations import companies as companies

from app.appeals_public import app as public_app
from app.db import engine
from app.models import AppealAddress, AppealPhoto, CitizenAppeal, District, Organization, User, WorkType
from app.organization_context import organization_scope
from app.organization_registry import control_session

pytestmark = pytest.mark.integration


@pytest.fixture
def recipients(companies):
    owner, scopes, clients = companies
    for index, scope in enumerate(scopes):
        with organization_scope(scope), Session(engine()) as tenant:
            tenant.add(WorkType(code="waste" if index == 0 else "roads", name="Вывоз мусора" if index == 0 else "Ремонт дорог",
                                filename_label="Работа", model_index=0, sort_order=1))
            polygon = MultiPolygon([Polygon([(72.57 + index, 61.1), (72.59 + index, 61.1),
                                              (72.59 + index, 61.12), (72.57 + index, 61.1)])])
            district = District(name="Участок " + str(index), active=True, geometry=from_shape(polygon, srid=4326))
            tenant.add(district)
            tenant.add(District(name="Скрытый участок", active=False, geometry=from_shape(polygon, srid=4326)))
            tenant.flush()
            district_id = district.id
            tenant.commit()
        with control_session() as control:
            control.add(AppealAddress(id=str(uuid4()), organization_id=scope.id, label="Улица Ленина, 10", district_id=district_id))
            control.commit()
    return owner, scopes, clients


def test_city_is_required_when_creating_and_editable_for_existing_organizations(owner, db):
    assert owner.post("/api/platform/organizations", json={"name": "Без города"}).status_code == 422
    assert owner.post("/api/platform/organizations", json={"name": "Без города", "city": "  "}).status_code == 422
    result = owner.patch(f"/api/platform/organizations/{ORGANIZATION}", json={
        "name": "Уборка города", "city": " Тюмень ", "status": "ACTIVE"})
    assert result.status_code == 200 and result.json()["city"] == "Тюмень"
    with TestClient(public_app) as citizen:
        session = start(citizen)
        assert send(citizen, session).status_code == 422
        assert send(citizen, session, {**body(session), "city": "Тюмень"}).status_code == 201


def test_server_rejects_unregistered_city_recipient_and_other_work_types(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        metadata = body(session)
        for invalid in ({**metadata, "organization_id": "22222222-2222-4222-8222-222222222222"},
                        {**metadata, "city": "Москва"}, {**metadata, "category": "arbitrary"},
                        {**metadata, "category": "SPAM"}, {key: value for key, value in metadata.items() if key != "organization_id"}):
            response = send(citizen, session, invalid)
            assert response.status_code == 422, response.text
        assert db.scalar(select(func.count()).select_from(CitizenAppeal)) == 0
        assert db.scalar(select(func.count()).select_from(AppealPhoto)) == 0
        response = send(citizen, session)
        assert response.status_code == 201, response.text
        saved = db.scalar(select(CitizenAppeal))
        assert saved.organization_id == ORGANIZATION and saved.work_type_name == "Вывоз мусора"
        assert saved.organization_name == "Уборка города"


def test_catalog_publishes_only_city_work_types_and_active_territories(recipients):
    owner, scopes, _ = recipients
    with TestClient(public_app) as citizen:
        response = citizen.get("/api/public/appeals/catalog")
        assert response.status_code == 200, response.text
        catalog = response.json()
        assert set(catalog) == {"organizations", "yandex_maps_api_key"}
        rows = {item["id"]: item for item in catalog["organizations"]}
        assert set(rows) == {scope.id for scope in scopes}
        assert rows[scopes[0].id]["city"] == "Сургут" and rows[scopes[1].id]["city"] == "Тюмень"
        assert rows[scopes[0].id]["color"] != rows[scopes[1].id]["color"]
        for index, scope in enumerate(scopes):
            assert set(rows[scope.id]) == {"id", "name", "city", "color", "work_types", "territories", "addresses"}
            assert len(rows[scope.id]["territories"]) == 1
            assert rows[scope.id]["territories"][0]["name"] == "Участок " + str(index)
            assert rows[scope.id]["territories"][0]["geometry"]["type"] == "MultiPolygon"
        encoded = json.dumps(catalog)
        assert all(key not in encoded for key in ("password", "owner_user_id", "database_name", "database_role", "contact", "login"))
        paused = owner.patch(f"/api/platform/organizations/{scopes[1].id}", json={"name": "Beta", "status": "PAUSED"})
        assert paused.status_code == 200
        visible = citizen.get("/api/public/appeals/catalog").json()["organizations"]
        assert len(visible) == 1 and visible[0]["color"] == rows[scopes[0].id]["color"]
        with control_session() as control:
            control.get(Organization, scopes[0].id).city = None
            control.commit()
        assert citizen.get("/api/public/appeals/catalog").json()["organizations"] == []


def test_admin_notifications_inbox_photos_and_updates_are_isolated_per_company(recipients):
    owner, scopes, clients = recipients
    with TestClient(public_app) as citizen:
        session = start(citizen)
        response = send(citizen, session, body(session, scopes[0].id))
        assert response.status_code == 201, response.text
    for client, scope in zip(clients, scopes, strict=True):
        assert client.get(scope.prefix + "/api/appeals").json()["total"] == 0
        assert client.get(scope.prefix + "/api/appeals/notifications").json()["new_count"] == 0
        with organization_scope(scope), Session(engine()) as tenant:
            tenant.scalar(select(User).where(User.login == "same-login")).role = "ADMIN_OPERATOR"
            tenant.commit()
    target, other = (scope.prefix + "/api/appeals" for scope in scopes)
    item = clients[0].get(target).json()["items"][0]
    assert item["organization_id"] == scopes[0].id and item["work_type_name"] == "Вывоз мусора"
    assert clients[0].get(target + "/notifications").json() == {"new_count": 1, "latest_id": item["id"]}
    assert clients[1].get(other + "/notifications").json() == {"new_count": 0, "latest_id": 0}
    assert clients[1].get(other).json()["total"] == 0
    detail = clients[0].get(target + f'/{item["id"]}').json()
    photo = detail["photos"][0]
    assert photo["url"].startswith(target)
    assert clients[0].get(photo["url"]).status_code == 200
    assert owner.get(photo["url"]).status_code == 200
    assert owner.get(target).json()["total"] == 1
    assert owner.get(other).json()["total"] == 0
    assert clients[1].get(other + f'/{item["id"]}').status_code == 404
    assert clients[1].get(other + f'/{item["id"]}/photos/{photo["id"]}').status_code == 404
    assert clients[1].get(photo["url"]).status_code == 401
    update = {"status": "IN_REVIEW", "owner_note": "Назначена уборка", "expected_version": 1}
    assert clients[1].patch(other + f'/{item["id"]}', json=update).status_code == 404
    assert clients[0].patch(target + f'/{item["id"]}', json=update).status_code == 200
    assert owner.get(target + f'/{item["id"]}').json()["owner_note"] == "Назначена уборка"
    assert clients[0].get(target + "/notifications").json()["new_count"] == 0
    assert owner.patch(target + f'/{item["id"]}', json=update).status_code == 409


def test_paused_organization_and_foreign_work_catalog_cannot_receive_new_appeals(recipients):
    owner, scopes, _ = recipients
    with TestClient(public_app) as citizen:
        session = start(citizen)
        metadata = {**body(session, scopes[0].id), "category": "roads"}
        assert send(citizen, session, metadata).status_code == 422
        owner.patch(f"/api/platform/organizations/{scopes[0].id}", json={"name": "Alpha", "status": "PAUSED"})
        assert send(citizen, session, {**metadata, "category": "waste"}).status_code == 422


def test_existing_unassigned_appeals_remain_owner_only(owner, db):
    appeal = CitizenAppeal(city="Сургут", address="Ленина, 10", place="У входа", category="waste",
                           description="Обращение из прежней версии", photo_count=1)
    db.add(appeal)
    db.commit()
    assert owner.get("/api/platform/appeals").json()["total"] == 1
    assert owner.get(f"/org/{ORGANIZATION}/api/appeals").json()["total"] == 0
