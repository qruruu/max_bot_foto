import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from PIL import Image
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_appeal_images import frame, phone_jpeg
from test_inspections import grant
from test_inspections import inspection as inspection
from test_organizations import companies as companies

from app.appeal_catalog import territory_choice_id
from app.appeals_public import app as public_app
from app.db import engine
from app.models import AppealPhoto, CitizenAppeal, District, User, WorkType
from app.organization_context import organization_scope
from app.organization_registry import control_session

pytestmark = pytest.mark.integration
HEADERS = {"origin": "http://testserver", "x-appeal-request": "form"}


@pytest.fixture
def workflow(inspection):
    owner, scopes, operators, _, accounts, inspectors = inspection
    addresses, operator_ids = [], []
    polygon = MultiPolygon([Polygon([(72, 61), (73, 61), (73, 62), (72, 62), (72, 61)],
                                   holes=[[(72.7, 61.7), (72.8, 61.7), (72.8, 61.8), (72.7, 61.8), (72.7, 61.7)]])])
    for scope in scopes:
        with organization_scope(scope), Session(engine()) as tenant:
            tenant.add(WorkType(code="BIN_EMPTYING", name="УРНЫ", filename_label="УРНЫ", model_index=0, sort_order=1))
            tenant.add(WorkType(code="DRAIN_CLEANING", name="КОЛОДЦЫ", filename_label="КОЛОДЦЫ", model_index=1, sort_order=2))
            district = District(name="Обслуживаемая территория", geometry=from_shape(polygon, srid=4326), active=True)
            tenant.add(district)
            tenant.flush()
            district_id = district.id
            operator_ids.append(tenant.scalar(select(User.id).where(User.login == "same-login")))
            tenant.commit()
        addresses.append({"id": territory_choice_id(scope.id, district_id), "label": "Обслуживаемая территория", "district_id": district_id})
    grant(owner, inspectors[0], scopes[0])
    return owner, scopes, operators, operator_ids, addresses, inspectors


def metadata(scope, address):
    return {"capture_source": "gallery", "organization_id": scope.id, "city": "Сургут" if scope.name == "Alpha" else "Тюмень",
            "address_id": address["id"], "address": address["label"], "latitude": 61.1, "longitude": 72.6,
            "place": "Около подъезда", "category": "BIN_EMPTYING", "description": "Урна переполнена, рядом лежит мусор",
            "contact": "private-phone-and-email@example.org", "website": "", "public_consent": True}


def session(citizen):
    response = citizen.post("/api/public/appeals/sessions", headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()["token"]


def submit(citizen, body, token=None):
    return citizen.post("/api/public/appeals/submissions", headers={**HEADERS, "x-capture-token": token or session(citizen)},
                        data={"metadata": json.dumps(body)}, files={"photos": ("personal-filename.jpg", frame(), "image/jpeg")})


def multipart(client, path, body, photos=True):
    return client.post(path, data={"metadata": json.dumps(body)},
                       files={"photos": ("result.jpg", frame(), "image/jpeg")} if photos else None)


def test_large_citizen_photo_and_phone_jpeg_operator_admin_results(workflow):
    owner, scopes, operators, operator_ids, addresses, _ = workflow
    scope = scopes[0]
    endpoint = scope.prefix + "/api/appeals"
    large = BytesIO()
    Image.new("RGB", (1800, 1300), "green").save(large, "PNG", compress_level=0)
    assert len(large.getvalue()) > 6 * 1024 * 1024
    with TestClient(public_app) as citizen:
        submitted = citizen.post("/api/public/appeals/submissions", headers={**HEADERS, "x-capture-token": session(citizen)},
                                 data={"metadata": json.dumps(metadata(scope, addresses[0]))},
                                 files={"photos": ("phone.png", large.getvalue(), "image/png")})
        assert submitted.status_code == 201, submitted.text
        appeal = owner.get(endpoint).json()["items"][0]
        path = endpoint + f'/{appeal["id"]}'
        assigned = owner.post(path + "/assign", json={"operator_id": operator_ids[0], "expected_version": 1})
        assert assigned.status_code == 200, assigned.text
        result = operators[0].post(path + "/result", data={"metadata": json.dumps({
            "status": "COMPLETED", "comment": "Почистили", "expected_version": 2})},
            files={"photos": ("IMG_3557.jpeg", phone_jpeg(), "image/jpeg")})
        assert result.status_code == 200, result.text
        closed = owner.post(path + "/close", data={"metadata": json.dumps({
            "comment": "Работа выполнена", "expected_version": 3, "operator_photo_ids": []})},
            files={"photos": ("IMG_3558.jpeg", phone_jpeg(), "image/jpeg")})
        assert closed.status_code == 200, closed.text
        wall = citizen.get(f'/api/public/appeals/wall/{appeal["id"]}').json()
        assert wall["status"] == "RESOLVED"
        published = citizen.get(wall["response"]["photos"][0]["url"])
        assert published.status_code == 200
        with Image.open(BytesIO(published.content)) as image:
            assert image.format == "JPEG" and getattr(image, "n_frames", 1) == 1
            red, green, blue = image.getpixel((100, 100))
            assert green > 100 and red < 10 and blue < 10


def test_gallery_requires_allowed_address_map_point_photos_and_consent(workflow):
    owner, scopes, operators, _, addresses, _ = workflow
    with TestClient(public_app) as citizen:
        body, token = metadata(scopes[0], addresses[0]), session(citizen)
        catalog = citizen.get("/api/public/appeals/catalog").json()
        first = next(item for item in catalog["organizations"] if item["id"] == scopes[0].id)
        assert first["addresses"] == [addresses[0]]
        assert [work["code"] for work in first["work_types"]] == ["BIN_EMPTYING"]
        for changes in ({"address_id": addresses[1]["id"]}, {"address": "Другой адрес"}, {"longitude": 70},
                        {"longitude": 72.75, "latitude": 61.75}, {"public_consent": False},
                        {"category": "DRAIN_CLEANING"}, {"city": "Москва"}):
            response = submit(citizen, {**body, **changes}, token)
            assert response.status_code == 422, response.text
        empty = citizen.post("/api/public/appeals/submissions", headers={**HEADERS, "x-capture-token": token},
                             data={"metadata": json.dumps(body)})
        assert empty.status_code == 422
        result = submit(citizen, body, token)
        assert result.status_code == 201, result.text
        assert submit(citizen, body, token).json() == result.json()
        wall = citizen.get("/api/public/appeals/wall", params={"city": body["city"]}).json()
        assert wall["total"] == 1
        row = wall["items"][0]
        assert "contact" not in row and "owner_note" not in row and "task" not in row
        assert "private-phone" not in json.dumps(row) and "personal-filename" not in json.dumps(row)
        assert operators[0].get(scopes[0].prefix + "/api/appeals").json()["total"] == 0
        with control_session() as db:
            appeal = db.get(CitizenAppeal, row["id"])
            photo = db.scalar(select(AppealPhoto).where(AppealPhoto.appeal_id == appeal.id))
            assert photo.original == photo.stamped
            with Image.open(BytesIO(photo.original)) as image:
                assert not image.getexif()
        image = citizen.get(row["photos"][0]["url"])
        assert image.status_code == 200 and "no-store" in image.headers["cache-control"]
        assert owner.get(scopes[0].prefix + "/api/appeals/workflow/settings").status_code == 200
        assert operators[0].get(scopes[0].prefix + "/api/appeals/workflow/settings").status_code == 403


@pytest.mark.parametrize("include_category", [False, True])
def test_citizen_can_submit_without_a_work_type_and_retry_without_duplicates(workflow, include_category):
    owner, scopes, _, _, addresses, _ = workflow
    scope = scopes[0]
    body = metadata(scope, addresses[0])
    if include_category:
        body["category"] = ""
    else:
        del body["category"]
    with TestClient(public_app) as citizen:
        token = session(citizen)
        response = submit(citizen, body, token)
        assert response.status_code == 201, response.text
        assert submit(citizen, body, token).json() == response.json()
        listing = owner.get(scope.prefix + "/api/appeals").json()
        assert listing["total"] == 1
        appeal = listing["items"][0]
        assert appeal["category"] == appeal["work_type_name"] == ""
        assert citizen.get(f'/api/public/appeals/wall/{appeal["id"]}').json()["description"] == body["description"]


def test_citizen_subject_is_saved_searchable_and_separate_from_work_type(workflow):
    owner, scopes, _, _, addresses, _ = workflow
    body = {**metadata(scopes[0], addresses[0]), "subject": "  Сломана   скамейка  ", "category": ""}
    with TestClient(public_app) as citizen:
        token = session(citizen)
        oversized = submit(citizen, {**body, "subject": "Я" * 81}, token)
        assert oversized.status_code == 422
        response = submit(citizen, body, token)
        assert response.status_code == 201, response.text
        assert submit(citizen, body, token).json() == response.json()
        wall = citizen.get("/api/public/appeals/wall", params={"city": body["city"], "q": "скамейка"}).json()
        assert wall["total"] == 1
        row = wall["items"][0]
        assert row["subject"] == "Сломана скамейка"
        assert row["description"] == body["description"]
        assert row["category"] == row["work_type_name"] == ""
        detail = owner.get(scopes[0].prefix + f'/api/appeals/{row["id"]}').json()
        assert detail["subject"] == row["subject"]
        public_page = citizen.get(f'/a/{row["id"]}')
        assert '<h1>Сломана скамейка</h1>' in public_page.text


def test_admin_assigns_original_work_types_with_versioning_history_and_owner_access(workflow):
    owner, scopes, clients, _, addresses, _ = workflow
    scope = scopes[0]
    with TestClient(public_app) as citizen:
        response = submit(citizen, {**metadata(scope, addresses[0]), "category": ""})
        assert response.status_code == 201, response.text
    id = int(response.json()["number"].split("-")[-1])
    path = scope.prefix + f"/api/appeals/{id}"
    global_path = f"/api/platform/appeals/{id}"
    options = owner.get(global_path + "/work-types")
    assert options.status_code == 200, options.text
    assert options.json() == [{"code": "BIN_EMPTYING", "name": "УРНЫ"},
                              {"code": "DRAIN_CLEANING", "name": "КОЛОДЦЫ"}]
    edit = {"status": "NEW", "owner_note": "", "expected_version": 1, "category": "BIN_EMPTYING"}
    assert clients[0].get(path + "/work-types").status_code == 403
    assert clients[0].patch(path, json=edit).status_code == 403
    for code in ("SPAM", "FOREIGN", "Переполненная урна"):
        assert owner.patch(path, json={**edit, "category": code}).status_code == 422
    assert owner.get(path).json()["version"] == 1
    with organization_scope(scope), Session(engine()) as tenant:
        tenant.scalar(select(User).where(User.login == "same-login")).role = "ADMIN_OPERATOR"
        tenant.commit()
    result = clients[0].patch(path, json=edit)
    assert result.status_code == 200, result.text
    assert result.json()["category"] == "BIN_EMPTYING" and result.json()["work_type_name"] == "УРНЫ"
    assert result.json()["version"] == 2
    events = clients[0].get(path + "/events").json()["items"]
    assigned = [event for event in events if event["kind"] == "WORK_TYPE"]
    assert len(assigned) == 1 and assigned[0]["actor_name"] == "Operator 0"
    assert assigned[0]["comment"] == "Не назначен → УРНЫ"
    assert owner.patch(global_path, json={**edit, "category": "DRAIN_CLEANING"}).status_code == 409
    replaced = owner.patch(global_path, json={**edit, "category": "DRAIN_CLEANING", "expected_version": 2})
    assert replaced.status_code == 200 and replaced.json()["work_type_name"] == "КОЛОДЦЫ"
    cleared = owner.patch(global_path, json={**edit, "category": "", "expected_version": 3})
    assert cleared.status_code == 200 and cleared.json()["category"] == cleared.json()["work_type_name"] == ""


def test_work_type_edit_is_isolated_preserves_old_labels_and_respects_archive(workflow, monkeypatch):
    from app.domain import now

    owner, scopes, clients, _, addresses, inspectors = workflow
    scope = scopes[0]
    with TestClient(public_app) as citizen:
        response = submit(citizen, metadata(scope, addresses[0]))
        assert response.status_code == 201
    id = int(response.json()["number"].split("-")[-1])
    path = scope.prefix + f"/api/appeals/{id}"
    other_path = scopes[1].prefix + f"/api/appeals/{id}"
    edit = {"status": "NEW", "owner_note": "Заметка", "expected_version": 1, "category": "DRAIN_CLEANING"}
    assert owner.get(other_path + "/work-types").status_code == 404
    assert owner.patch(other_path, json=edit).status_code == 404
    assert clients[1].patch(path, json=edit).status_code == 401
    assert inspectors[0].patch(path, json=edit).status_code in (401, 403)
    with organization_scope(scope), Session(engine()) as tenant:
        tenant.delete(tenant.scalar(select(WorkType).where(WorkType.code == "BIN_EMPTYING")))
        tenant.commit()
    saved = owner.patch(path, json={key: value for key, value in edit.items() if key != "category"})
    assert saved.status_code == 200 and saved.json()["work_type_name"] == "УРНЫ"
    assert saved.json()["category"] == "BIN_EMPTYING"
    assert owner.patch(path, json={**edit, "category": "BIN_EMPTYING", "expected_version": 2}).status_code == 200
    with control_session() as db:
        appeal = db.get(CitizenAppeal, id)
        appeal.archived_at = now()
        db.commit()
    assert owner.patch(path, json={**edit, "expected_version": 3}).status_code == 409
    with control_session() as db:
        db.get(CitizenAppeal, id).archived_at = None
        db.commit()
    def unavailable(*args, **kwargs):
        raise RuntimeError("Organization database is temporarily unavailable")
    monkeypatch.setattr("app.appeals.organization_catalog", unavailable)
    assert owner.get(path + "/work-types").status_code == 503
    assert owner.patch(path, json={**edit, "expected_version": 3}).status_code == 503
    assert owner.get(path).json()["category"] == "BIN_EMPTYING"


def test_assignment_operator_result_admin_publication_and_spam_privacy(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    scope, other = scopes
    endpoint = scope.prefix + "/api/appeals"
    with TestClient(public_app) as citizen:
        assert submit(citizen, metadata(scope, addresses[0])).status_code == 201
        assert inspectors[0].get('/api/inspection/appeals/notifications').json()['new_count'] == 1
        assert inspectors[1].get('/api/inspection/appeals/notifications').json()['new_count'] == 0
        appeal = owner.get(endpoint).json()["items"][0]
        id = appeal["id"]
        assert owner.post(endpoint + f"/{id}/assign", json={"operator_id": 999999, "instruction": "private-instruction", "expected_version": 1}).status_code == 422
        assigned = owner.post(endpoint + f"/{id}/assign", json={"operator_id": operator_ids[0], "instruction": "private-instruction", "expected_version": 1})
        assert assigned.status_code == 200, assigned.text
        assert owner.get(endpoint + '/notifications').json()['new_count'] == 0
        assert operators[0].get(endpoint + '/notifications').json()['new_count'] == 1
        detail = operators[0].get(endpoint + f"/{id}").json()
        assert detail["task"]["instruction"] == "private-instruction" and detail["can_execute"]
        assert "contact" not in detail and "owner_note" not in detail
        assert operators[0].get(endpoint).json()["total"] == 1
        assert operators[1].get(other.prefix + f"/api/appeals/{id}").status_code == 404
        inspected = inspectors[0].get(f"/api/inspection/organizations/{scope.id}/appeals/{id}")
        assert inspected.status_code == 200 and inspected.json()["status"] == "ASSIGNED"
        assert "private-instruction" not in inspected.text and "private-phone" not in inspected.text
        assert inspectors[0].get(f"/api/inspection/organizations/{scope.id}/appeals/notifications").status_code == 200
        assert inspectors[0].post(endpoint + f"/{id}/assign", json={"operator_id": operator_ids[0], "expected_version": 2}).status_code in (401, 403)
        assert operators[0].patch(endpoint + f"/{id}", json={"status": "RESOLVED", "owner_note": "", "expected_version": 2}).status_code == 403
        no_photo = multipart(operators[0], endpoint + f"/{id}/result", {"status": "COMPLETED", "comment": "Урна очищена", "expected_version": 2}, False)
        assert no_photo.status_code == 422
        result = multipart(operators[0], endpoint + f"/{id}/result", {"status": "COMPLETED", "comment": "operator-result", "expected_version": 2})
        assert result.status_code == 200, result.text
        assert owner.get(endpoint + '/notifications').json()['new_count'] == 1
        assert operators[0].get(endpoint + '/notifications').json()['new_count'] == 0
        task = owner.get(endpoint + f"/{id}").json()["task"]
        assert task["status"] == "COMPLETED"
        wall = citizen.get(f"/api/public/appeals/wall/{id}").json()
        assert wall["response"] is None and "operator-result" not in json.dumps(wall)
        attachment_url = task["photos"][0]["url"]
        assert citizen.get(attachment_url).status_code == 404
        unapproved_url = f'/api/public/appeals/wall/{id}/results/{task["photos"][0]["id"]}'
        assert citizen.get(unapproved_url).status_code == 404
        invalid_close = multipart(owner, endpoint + f"/{id}/close", {"comment": "Публичный ответ", "expected_version": 3, "operator_photo_ids": [str(uuid4())]}, False)
        assert invalid_close.status_code == 422
        closed = multipart(owner, endpoint + f"/{id}/close", {"comment": "Урну очистили, спасибо за обращение.", "expected_version": 3, "operator_photo_ids": [task["photos"][0]["id"]]}, False)
        assert closed.status_code == 200, closed.text
        published = citizen.get(f"/api/public/appeals/wall/{id}").json()
        assert published["status"] == "RESOLVED" and published["response"]["comment"].startswith("Урну очистили")
        assert citizen.get(published["response"]["photos"][0]["url"]).status_code == 200
        inspected = inspectors[0].get(f"/api/inspection/organizations/{scope.id}/appeals/{id}")
        assert inspected.json()["status"] == "RESOLVED" and "private-instruction" not in inspected.text
        assert owner.patch(endpoint + f"/{id}", json={"status": "SPAM", "owner_note": "internal-spam-reason", "expected_version": 4}).status_code == 200
        assert citizen.get("/api/public/appeals/wall", params={"city": "Сургут"}).json()["total"] == 0
        for url in (f"/api/public/appeals/wall/{id}", published["photos"][0]["url"], published["response"]["photos"][0]["url"]):
            assert citizen.get(url).status_code == 404


def test_wall_filters_and_territory_deactivation_are_enforced_by_server(workflow):
    owner, scopes, _, _, addresses, _ = workflow
    with TestClient(public_app) as citizen:
        for scope, address in zip(scopes, addresses, strict=True):
            assert submit(citizen, metadata(scope, address)).status_code == 201
        for scope, city in zip(scopes, ("Сургут", "Тюмень"), strict=True):
            result = citizen.get("/api/public/appeals/wall", params={"city": city, "organization_id": scope.id, "sort": "organization"})
            assert result.status_code == 200 and result.json()["total"] == 1
            assert result.json()["items"][0]["organization_id"] == scope.id
        assert citizen.get("/api/public/appeals/wall", params={"city": "Сургут", "organization_id": scopes[1].id}).json()["total"] == 0
        with organization_scope(scopes[0]), Session(engine()) as tenant:
            tenant.get(District, addresses[0]["district_id"]).active = False
            tenant.commit()
        assert submit(citizen, metadata(scopes[0], addresses[0])).status_code == 422


def test_reassignment_preserves_history_rejects_stale_results_and_allows_admin_photos(workflow):
    owner, scopes, operators, operator_ids, addresses, _ = workflow
    endpoint = scopes[0].prefix + '/api/appeals'
    with TestClient(public_app) as citizen:
        assert submit(citizen, metadata(scopes[0], addresses[0])).status_code == 201
        id = owner.get(endpoint).json()['items'][0]['id']
        assignment = {'operator_id': operator_ids[0], 'instruction': 'Первая задача', 'expected_version': 1}
        assert owner.post(endpoint + f'/{id}/assign', json=assignment).status_code == 200
        assert multipart(owner, endpoint + f'/{id}/close', {'comment': 'Закрываем', 'expected_version': 2}).status_code == 409
        assert operators[0].post(endpoint + f'/{id}/start?expected_version=2').status_code == 200
        assert multipart(operators[0], endpoint + f'/{id}/result', {'status': 'REJECTED', 'comment': 'Нужна другая техника', 'expected_version': 3}).status_code == 200
        first = owner.get(endpoint + f'/{id}').json()['task']
        assert owner.post(endpoint + f'/{id}/assign', json={**assignment, 'instruction': 'Повторное назначение', 'expected_version': 4}).status_code == 200
        stale = multipart(operators[0], endpoint + f'/{id}/result', {'status': 'COMPLETED', 'comment': 'Запоздалый ответ', 'expected_version': 4})
        assert stale.status_code == 409
        assert multipart(operators[0], endpoint + f'/{id}/result', {'status': 'REJECTED', 'comment': 'Не удалось выполнить', 'expected_version': 5}).status_code == 200
        assert len(owner.get(endpoint + f'/{id}').json()['task_history']) == 2
        old_photos = multipart(owner, endpoint + f'/{id}/close', {'comment': 'Результат', 'operator_photo_ids': [first['photos'][0]['id']], 'expected_version': 6}, False)
        assert old_photos.status_code == 422
        own = multipart(owner, endpoint + f'/{id}/close', {'comment': 'Организация устранила проблему своими силами', 'expected_version': 6})
        assert own.status_code == 200, own.text
        public = citizen.get(f'/api/public/appeals/wall/{id}').json()
        assert public['status'] == 'RESOLVED' and len(public['response']['photos']) == 1


def inspector_metadata(scope, address):
    body = metadata(scope, address)
    body.pop('capture_source')
    body.pop('public_consent')
    body.pop('contact')
    return {**body, 'client_id': str(uuid4())}


def test_inspector_can_create_only_private_appeals_in_accessible_organization(workflow):
    owner, scopes, operators, _, addresses, inspectors = workflow
    endpoint = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    body = inspector_metadata(scopes[0], addresses[0])
    assert inspectors[0].get(endpoint + '/catalog').json()['organization']['addresses'] == [addresses[0]]
    assert inspectors[1].get(endpoint + '/catalog').status_code == 404
    assert multipart(inspectors[1], endpoint, body).status_code == 404
    assert multipart(operators[0], endpoint, body).status_code == 401
    assert multipart(inspectors[0], endpoint, {**body, 'is_public': True}).status_code == 422
    assert multipart(inspectors[0], endpoint, {**body, 'public_consent': True}).status_code == 422
    assert multipart(inspectors[0], endpoint, {**body, 'submitted_by_inspector_id': 999}).status_code == 422
    assert multipart(inspectors[0], endpoint, {**body, 'organization_id': scopes[1].id}).status_code == 422
    assert multipart(inspectors[0], endpoint, {**body, 'longitude': 70}).status_code == 422
    assert multipart(inspectors[0], endpoint, body, False).status_code == 422
    created = multipart(inspectors[0], endpoint, body)
    assert created.status_code == 201, created.text
    assert created.json()['is_public'] is False
    id = created.json()['id']
    assert multipart(inspectors[0], endpoint, body).json() == created.json()
    assert inspectors[0].get(endpoint + '/submissions/' + body['client_id']).json() == created.json()
    assert inspectors[1].get(endpoint + '/submissions/' + body['client_id']).status_code == 404
    detail = owner.get(scopes[0].prefix + f'/api/appeals/{id}').json()
    assert detail['submitted_by_inspector_name'] == 'Проверяющий 0'
    assert detail['is_public'] is False and detail['submitted_by_inspector_id'] is not None
    assert owner.get(scopes[0].prefix + '/api/appeals/notifications').json()['new_count'] == 1
    with TestClient(public_app) as citizen:
        assert citizen.get('/api/public/appeals/wall', params={'city': 'Сургут'}).json()['total'] == 0
        assert citizen.get(f'/api/public/appeals/wall/{id}').status_code == 404
        assert citizen.get(f'/api/public/appeals/wall/{id}/photos/{detail["photos"][0]["id"]}').status_code == 404


def test_inspector_appeal_result_and_closure_stay_private(workflow):
    owner, scopes, operators, operator_ids, addresses, inspectors = workflow
    inspection_endpoint = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    created = multipart(inspectors[0], inspection_endpoint, inspector_metadata(scopes[0], addresses[0]))
    assert created.status_code == 201, created.text
    id = created.json()['id']
    endpoint = scopes[0].prefix + f'/api/appeals/{id}'
    assert owner.post(endpoint + '/assign', json={'operator_id': operator_ids[0], 'instruction': 'Служебный комментарий', 'expected_version': 1}).status_code == 200
    assert multipart(operators[0], endpoint + '/result', {'status': 'COMPLETED', 'comment': 'Исполнитель устранил нарушение', 'expected_version': 2}).status_code == 200
    task = owner.get(endpoint).json()['task']
    close = multipart(owner, endpoint + '/close', {'comment': 'Ответ проверяющему: нарушение устранено', 'operator_photo_ids': [task['photos'][0]['id']], 'expected_version': 3}, False)
    assert close.status_code == 200, close.text
    inspector_detail = inspectors[0].get(inspection_endpoint + f'/{id}')
    assert inspector_detail.json()['status'] == 'RESOLVED'
    assert inspector_detail.json()['is_public'] is False
    assert inspector_detail.json()['public_response'].startswith('Ответ проверяющему')
    assert 'Служебный комментарий' not in inspector_detail.text
    assert inspectors[0].get(inspector_detail.json()['response_photos'][0]['url']).status_code == 200
    with TestClient(public_app) as citizen:
        assert submit(citizen, metadata(scopes[0], addresses[0])).status_code == 201
        wall = citizen.get('/api/public/appeals/wall', params={'city': 'Сургут'}).json()
        assert wall['total'] == 1 and wall['items'][0]['id'] != id
        for url in (f'/api/public/appeals/wall/{id}', f'/api/public/appeals/wall/{id}/results/{task["photos"][0]["id"]}'):
            assert citizen.get(url).status_code == 404
    with control_session() as db:
        from sqlalchemy.exc import IntegrityError
        appeal = db.get(CitizenAppeal, id)
        appeal.is_public = True
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_inspector_concurrent_retries_create_one_private_appeal(workflow):
    owner, scopes, _, _, addresses, inspectors = workflow
    endpoint = f'/api/inspection/organizations/{scopes[0].id}/appeals'
    body = inspector_metadata(scopes[0], addresses[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: multipart(inspectors[0], endpoint, body), range(2)))
    assert all(result.status_code == 201 for result in results), [result.text for result in results]
    assert results[0].json() == results[1].json()
    assert owner.get(scopes[0].prefix + '/api/appeals').json()['total'] == 1


def test_questionnaire_uses_all_active_map_territories_without_an_address_book(workflow):
    _, scopes, _, _, addresses, inspectors = workflow
    from app.models import AppealAddress
    with control_session() as db:
        assert not list(db.scalars(select(AppealAddress.id)))
    geometry = from_shape(MultiPolygon([Polygon([(75, 61), (76, 61), (76, 62), (75, 62), (75, 61)])]), srid=4326)
    with organization_scope(scopes[0]), Session(engine()) as tenant:
        extra = District(name='11А мкр', active=True, geometry=geometry)
        tenant.add(extra)
        tenant.add(District(name='Скрытая территория', active=False, geometry=geometry))
        tenant.flush()
        extra_id = extra.id
        tenant.commit()
    with TestClient(public_app) as citizen:
        def catalog():
            return next(item for item in citizen.get('/api/public/appeals/catalog').json()['organizations'] if item['id'] == scopes[0].id)
        first = catalog()
        assert [(item['district_id'], item['label']) for item in first['addresses']] == [(area['id'], area['name']) for area in first['territories']]
        assert len(first['addresses']) == 2
        assert catalog()['addresses'] == first['addresses']
        private = inspectors[0].get(f'/api/inspection/organizations/{scopes[0].id}/appeals/catalog').json()['organization']
        assert private['addresses'] == first['addresses']
        choice = next(item for item in first['addresses'] if item['district_id'] == extra_id)
        body = {**metadata(scopes[0], choice), 'longitude': 75.5, 'latitude': 61.5}
        assert submit(citizen, body).status_code == 201
        assert submit(citizen, {**body, 'longitude': 72.6, 'latitude': 61.1}).status_code == 422
        assert submit(citizen, {**body, 'address_id': addresses[1]['id']}).status_code == 422
        with organization_scope(scopes[0]), Session(engine()) as tenant:
            tenant.get(District, extra_id).name = '11Б мкр'
            tenant.commit()
        renamed = next(item for item in catalog()['addresses'] if item['district_id'] == extra_id)
        assert renamed['id'] == choice['id'] and renamed['label'] == '11Б мкр'
        assert submit(citizen, body).status_code == 422
        assert submit(citizen, {**body, 'address': renamed['label']}).status_code == 201
