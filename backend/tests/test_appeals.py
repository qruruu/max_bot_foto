import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import func, select
from test_appeal_images import frame
from test_organizations import companies as companies

from app.api import app
from app.appeals_public import app as public_app
from app.config import settings
from app.domain import now
from app.models import (
    AppealAddress,
    AppealCaptureSession,
    AppealPhoto,
    CitizenAppeal,
    District,
    Organization,
    Photo,
    PlatformOwner,
    User,
    WorkType,
)
from app.organization_registry import control_session

pytestmark = pytest.mark.integration
HEADERS = {"origin": "http://testserver", "x-appeal-request": "form"}
ORGANIZATION = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def owner(db, users, monkeypatch):
    owner_id = db.scalar(select(User.id).where(User.login == "admin"))
    db.add(PlatformOwner(user_id=owner_id))
    db.add(Organization(id=ORGANIZATION, name="Уборка города", city="Сургут", slug="appeals-test",
                        status="ACTIVE", legacy=True, owner_user_id=owner_id))
    db.add(WorkType(code="waste", name="Вывоз мусора", filename_label="Вывоз мусора", model_index=100, sort_order=100))
    db.commit()
    district = District(name="Участок", active=True, geometry=from_shape(MultiPolygon([
        Polygon([(72, 61), (73, 61), (73, 62), (72, 62), (72, 61)])]), srid=4326))
    db.add(district)
    db.flush()
    db.add(AppealAddress(id=str(uuid4()), organization_id=ORGANIZATION, label="Улица Ленина, 10", district_id=district.id))
    db.commit()
    monkeypatch.setenv("ORGANIZATIONS_ENABLED", "true")
    settings.cache_clear()
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"login": "admin", "password": "test-password-123"})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = client.cookies["platform_csrf"]
        yield client


def start(client):
    response = client.post("/api/public/appeals/sessions", headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def body(session, organization_id=ORGANIZATION):
    with control_session() as db:
        address = db.scalar(select(AppealAddress).where(AppealAddress.organization_id == organization_id))
        address_id = address.id
    return {"organization_id": organization_id, "city": "Сургут", "address": "Улица Ленина, 10", "address_id": address_id,
            "place": "Тротуар возле подъезда", "latitude": 61.1025, "longitude": 72.5794, "public_consent": True,
            "category": "waste", "description": "Урна переполнена, мусор лежит рядом",
            "contact": "+7 900 123-45-67", "capture_source": "gallery"}


def send(client, session, metadata=None, content=None):
    return client.post("/api/public/appeals", headers={**HEADERS, "x-capture-token": session["token"]},
        data={"metadata": json.dumps(metadata or body(session))},
        files=[("photos", ("camera.jpg", content if content is not None else frame(), "image/jpeg"))])


def test_public_intake_owner_review_idempotency_and_protected_photos(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        response = send(citizen, session)
        assert response.status_code == 201, response.text
        assert set(response.json()) == {"number", "message"}
        assert send(citizen, session).json() == response.json()
        assert db.scalar(select(func.count()).select_from(CitizenAppeal)) == 1
        assert db.scalar(select(func.count()).select_from(AppealPhoto)) == 1
        assert db.scalar(select(func.count()).select_from(Photo)) == 0
        listing = owner.get("/api/platform/appeals").json()
        assert listing["total"] == 1 and listing["items"][0]["contact"] == "+7 900 123-45-67"
        item = listing["items"][0]
        detail = owner.get(f'/api/platform/appeals/{item["id"]}').json()
        photo = detail["photos"][0]
        stamped = owner.get(photo["url"])
        original = owner.get(photo["original_url"])
        assert stamped.status_code == original.status_code == 200
        assert stamped.content == original.content
        assert "no-store" in stamped.headers["cache-control"]
        assert citizen.get(photo["url"]).status_code == 404
        assert citizen.get("/api/platform/appeals").status_code == 404
        update = {"status": "IN_REVIEW", "owner_note": "Уточнить обслуживающую организацию", "expected_version": 1}
        assert owner.patch(f'/api/platform/appeals/{item["id"]}', json=update).json()["version"] == 2
        assert owner.patch(f'/api/platform/appeals/{item["id"]}', json=update).status_code == 409
        assert owner.get("/api/platform/appeals?status=NEW").json()["total"] == 0
        assert owner.get("/api/platform/appeals?status=IN_REVIEW").json()["total"] == 1
    with TestClient(app) as anonymous:
        assert anonymous.get(photo["url"]).status_code == 401
        assert anonymous.get("/api/platform/appeals").status_code == 401


def test_public_service_has_no_operator_endpoints(owner):
    with TestClient(public_app) as citizen:
        for path in ("/api/auth/login", "/api/auth/me", "/api/docs", "/api/openapi.json", "/docs", "/api/photos", "/api/platform/appeals"):
            assert citizen.get(path).status_code == 404
        assert citizen.post("/api/auth/login", json={}).status_code == 404
        assert citizen.post("/api/public/appeals/capture-sessions").status_code == 403
        assert citizen.post("/api/public/appeals/capture-sessions", headers={**HEADERS, "origin": "https://foreign.example"}).status_code == 403


def test_required_gallery_photo_map_location_and_valid_file(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        metadata = body(session)
        for invalid in ({**metadata, "capture_source": "camera"}, {**metadata, "public_consent": False},
                        {**metadata, "captures": [{"captured_at": session["server_time"]}]},
                        {**metadata, "city": " "}):
            assert send(citizen, session, invalid).status_code == 422
        for invalid_frame in (b"a file renamed to jpg", frame((100, 100))):
            assert send(citizen, session, content=invalid_frame).status_code == 422
        assert citizen.post("/api/public/appeals", headers={**HEADERS, "x-capture-token": session["token"]},
            data={"metadata": json.dumps(metadata)}).status_code == 422
        assert citizen.post("/api/public/appeals", headers=HEADERS).status_code == 422
        assert db.scalar(select(func.count()).select_from(CitizenAppeal)) == 0
        assert db.scalar(select(func.count()).select_from(AppealPhoto)) == 0
        assert send(citizen, session).status_code == 201


def test_stale_session_and_untrusted_capture_fields_are_rejected(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        metadata = body(session)
        metadata["captures"] = [{"captured_at": (now() - timedelta(hours=1)).isoformat()}]
        assert send(citizen, session, metadata).status_code == 422
        record = db.get(AppealCaptureSession, sha256(session["token"].encode()).hexdigest())
        record.expires_at = now() - timedelta(seconds=1)
        db.commit()
        assert send(citizen, session).status_code == 409


def test_limit_requests_and_reject_oversized_body_before_parsing(owner):
    with TestClient(public_app) as citizen:
        for _ in range(20):
            assert citizen.post("/api/public/appeals/capture-sessions", headers=HEADERS).status_code == 201
        limited = citizen.post("/api/public/appeals/capture-sessions", headers=HEADERS)
        assert limited.status_code == 429 and "retry-after" in limited.headers
        assert citizen.post("/api/public/appeals", content=b"", headers={**HEADERS, "content-length": "99999999"}).status_code == 413


def test_tenant_operator_and_owner_inside_company_cannot_read_global_inbox(companies):
    owner, scopes, operators = companies
    from sqlalchemy.orm import Session

    from app.db import engine
    from app.organization_context import organization_scope

    with organization_scope(scopes[0]), Session(engine()) as tenant:
        tenant.add(WorkType(code="waste", name="Вывоз мусора", filename_label="Мусор", model_index=0, sort_order=1))
        district = District(name="Участок", active=True, geometry=from_shape(MultiPolygon([
            Polygon([(72, 61), (73, 61), (73, 62), (72, 62), (72, 61)])]), srid=4326))
        tenant.add(district)
        tenant.flush()
        district_id = district.id
        tenant.commit()
    with control_session() as control:
        control.add(AppealAddress(id=str(uuid4()), organization_id=scopes[0].id, label="Улица Ленина, 10", district_id=district_id))
        control.commit()
    with TestClient(public_app) as citizen:
        session = start(citizen)
        assert send(citizen, session, body(session, scopes[0].id)).status_code == 201
    item = owner.get("/api/platform/appeals").json()["items"][0]
    photo = owner.get(f'/api/platform/appeals/{item["id"]}').json()["photos"][0]
    for operator, scope in zip(operators, scopes, strict=True):
        assert operator.get("/api/platform/appeals").status_code == 401
        assert operator.get(photo["url"]).status_code == 401
        assert operator.get(scope.prefix + "/api/platform/appeals").status_code == 404
        assert owner.get(scope.prefix + "/api/platform/appeals").status_code == 404
        assert operator.post(scope.prefix + "/api/public/appeals/capture-sessions", headers=HEADERS).status_code == 404


def test_concurrent_retries_create_only_one_appeal(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
    def submit(_):
        with TestClient(public_app) as citizen:
            return send(citizen, session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert all(response.status_code == 201 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert db.scalar(select(func.count()).select_from(CitizenAppeal)) == 1
    assert db.scalar(select(func.count()).select_from(AppealPhoto)) == 1


def test_invalid_second_frame_does_not_save_partial_appeal(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        metadata = body(session)
        response = citizen.post("/api/public/appeals", headers={**HEADERS, "x-capture-token": session["token"]},
            data={"metadata": json.dumps(metadata)}, files=[
                ("photos", ("camera-1.jpg", frame(), "image/jpeg")),
                ("photos", ("camera-2.jpg", b"corrupt frame", "image/jpeg")),
            ])
        assert response.status_code == 422
        assert db.scalar(select(func.count()).select_from(CitizenAppeal)) == 0
        assert db.scalar(select(func.count()).select_from(AppealPhoto)) == 0
        assert db.get(AppealCaptureSession, sha256(session["token"].encode()).hexdigest()).appeal_id is None
        assert send(citizen, session).status_code == 201


def test_mobile_draft_resume_resyncs_clock_and_recovers_receipt_without_exposing_personal_data(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        headers = {**HEADERS, "x-capture-token": session["token"]}
        resumed = citizen.post("/api/public/appeals/capture-sessions/resume", headers=headers)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["token"] == session["token"]
        assert resumed.json()["submitted"] is None and not resumed.json()["expired"]
        assert db.scalar(select(func.count()).select_from(CitizenAppeal)) == 0
        receipt = send(citizen, session).json()
        record = db.get(AppealCaptureSession, sha256(session["token"].encode()).hexdigest())
        record.expires_at = now() - timedelta(minutes=1)
        db.commit()
        resumed = citizen.post("/api/public/appeals/capture-sessions/resume", headers=headers).json()
        assert resumed["expired"] and resumed["submitted"] == receipt
        assert not ({"contact", "description", "photos", "city", "address"} & resumed.keys())
        assert citizen.post("/api/public/appeals/capture-sessions/resume", headers=HEADERS).status_code == 422
        assert citizen.post("/api/public/appeals/capture-sessions/resume", headers={**headers, "origin": "https://other.example"}).status_code == 403


def test_expired_mobile_draft_can_keep_its_questionnaire_and_photos_but_needs_new_session(owner, db):
    with TestClient(public_app) as citizen:
        session = start(citizen)
        record = db.get(AppealCaptureSession, sha256(session["token"].encode()).hexdigest())
        record.expires_at = now() - timedelta(minutes=1)
        db.commit()
        resumed = citizen.post("/api/public/appeals/capture-sessions/resume",
            headers={**HEADERS, "x-capture-token": session["token"]})
        assert resumed.status_code == 200 and resumed.json()["expired"] and resumed.json()["submitted"] is None
        assert send(citizen, session).status_code == 409
