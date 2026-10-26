import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date, timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_organizations import companies as companies

from app.auth import digest
from app.db import engine
from app.domain import now
from app.media import media_path
from app.models import (
    AppealPhoto,
    Chat,
    CitizenAppeal,
    ExchangeState,
    Inbox,
    InspectionGrant,
    InspectionMessage,
    InspectionQR,
    Inspector,
    Photo,
    User,
    WorkType,
)
from app.organization_context import organization_scope
from app.organization_registry import control_session

pytestmark = pytest.mark.integration
PASSWORD = "inspector-password-123"
DAY = date(2026, 10, 18)


@pytest.fixture
def inspection(companies):
    from app.api import app

    owner, scopes, operators = companies
    agency = owner.post("/api/platform/inspection/agencies", json={"name": "Администрация"}).json()
    accounts = []
    with ExitStack() as stack:
        clients = []
        for index in range(2):
            result = owner.post(f'/api/platform/inspection/agencies/{agency["id"]}/accounts', json={
                "login": f"inspector{index}", "name": f"Проверяющий {index}", "password": PASSWORD})
            assert result.status_code == 201, result.text
            accounts.append(result.json())
            client = stack.enter_context(TestClient(app))
            response = client.post("/api/auth/login", json={"login": f"inspector{index}", "password": PASSWORD})
            assert response.status_code == 200 and response.json()["role"] == "INSPECTOR", response.text
            client.headers["X-CSRF-Token"] = client.cookies["inspection_csrf"]
            clients.append(client)
        yield owner, scopes, operators, agency, accounts, clients


def qr(owner, scope):
    result = owner.post(f"/api/platform/inspection/organizations/{scope.id}/qr")
    assert result.status_code == 200, result.text
    return parse_qs(urlsplit(result.json()["url"]).fragment)["invite"][0]


def grant(owner, client, scope):
    result = client.post("/api/inspection/redeem", json={"token": qr(owner, scope)})
    assert result.status_code == 200, result.text


def seed_photos(scope):
    with organization_scope(scope), Session(engine()) as db:
        db.get(ExchangeState, 1).intake_cohort = "production"
        db.add(Chat(max_chat_id=100, name="Секретный чат", active=True))
        db.add(WorkType(code="CLEAN", name="Уборка", filename_label="Уборка", model_index=0, sort_order=1))
        db.flush()
        for id in (10, 20):
            db.add(Inbox(id=id, max_chat_id=100, message_id=str(id), payload={}))
            db.flush()
            db.add(Photo(id=id, inbox_id=id, attachment_index=0, cohort="production", max_chat_id=100,
                         chat_name="Секретный чат", max_message_id="secret-message", sender_id=987654321,
                         photo_date=DAY, received_at=now(), latitude=61.1, longitude=72.6,
                         work_type="CLEAN", work_type_source="AI", status="ACCEPTED", analyzed_at=now(),
                         sha256=f"{id:064x}", is_spam=False, is_defect=False, storage_status="SYNCED",
                         stored_filename="secret-filename.jpg", yandex_disk_path="disk:/secret/path",
                         ai_result={"secret": "result"}, ocr_raw_text="secret-ocr"))
            media_path(id, True).write_bytes(b"safe preview")
        db.commit()


def close(owner, scope):
    url = scope.prefix + "/api/day-reviews/" + DAY.isoformat()
    summary = owner.get(url)
    assert summary.status_code == 200, summary.text
    result = owner.post(url + "/close", json={"snapshot": summary.json()["snapshot"]})
    assert result.status_code == 200, result.text


def test_single_use_qr_is_personal_replaced_expired_and_atomic(inspection):
    owner, scopes, _, _, accounts, clients = inspection
    token = qr(owner, scopes[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda c: c.post("/api/inspection/redeem", json={"token": token}).status_code, clients))
    assert sorted(results) == [200, 409]
    winner, loser = results.index(200), results.index(409)
    assert len(clients[winner].get("/api/inspection/organizations").json()) == 1
    assert clients[loser].get("/api/inspection/organizations").json() == []
    assert clients[winner].post("/api/inspection/redeem", json={"token": token}).status_code == 409
    old, new = qr(owner, scopes[0]), qr(owner, scopes[0])
    assert clients[loser].post("/api/inspection/redeem", json={"token": old}).status_code == 409
    with control_session() as db:
        db.get(InspectionQR, digest(new)).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert clients[loser].post("/api/inspection/redeem", json={"token": new}).status_code == 409
    grant(owner, clients[loser], scopes[0])
    assert owner.delete(f'/api/platform/inspection/accounts/{accounts[winner]["id"]}/grants/{scopes[0].id}').status_code == 200
    assert clients[winner].get("/api/inspection/organizations").json() == []
    assert clients[winner].post("/api/inspection/redeem", json={"token": token}).status_code == 409


def test_closure_gates_every_photo_route_and_report_and_safe_export(inspection):
    owner, scopes, _, _, accounts, clients = inspection
    scope, client = scopes[0], clients[0]
    grant(owner, client, scope)
    seed_photos(scope)
    base = f"/api/inspection/organizations/{scope.id}"
    assert client.get(base + "/photos").json()["total"] == 0
    assert client.get(base + "/reports").json()["total"] == 0
    assert client.get(base + "/photos/map").json()["summary"]["total"] == 0
    assert client.get(base + "/photos/arrivals").json() == {"photo_ids": []}
    for suffix in ("", "/preview", "/original", "/navigation"):
        assert client.get(base + "/photos/10" + suffix).status_code == 404
    close(owner, scope)
    result = client.get(base + "/photos").json()
    assert result["total"] == 2
    assert client.get(base + "/photos/10/preview").content == b"safe preview"
    serialized = json.dumps(result) + client.get(base + "/photos/10").text + client.get(base + "/meta").text
    assert not any(secret in serialized for secret in ("chat", "sender", "operator", "source", "ai_", "ocr", "filename", "disk", "secret"))
    assert client.get(base + "/reports").json()["total"] == 2
    points = client.get(base + "/photos/map").json()
    assert points["summary"] == {"total": 2, "located": 2, "without_coordinates": 0}
    assert [p["id"] for p in points["items"]] == [10, 20]
    assert not any(key in str(points) for key in ("chat_name", "sender_id", "work_type_source", "secret"))
    assert client.get(base + "/photos/map?after_id=10&snapshot_id=20").json()["items"][0]["id"] == 20
    assert client.get(base + "/photos/arrivals").json() == {"photo_ids": [10, 20]}
    assert client.get(base + "/photos/20/navigation").json() == {"previous": None, "next": 10}
    assert client.get(base + "/photos/10/navigation?sort_order=asc").json() == {"previous": None, "next": 20}
    assert client.get(base + "/districts").json() == {"type": "FeatureCollection", "features": []}
    for route in ("/districts", "/photos/10", "/appeals/1"):
        assert client.patch(base + route, json={"name": "Forbidden"}).status_code == 405
    assert client.get(base + "/photos?photo_id=10").json()["total"] == 1
    with organization_scope(scope):
        media_path(10).write_bytes(b"private-original")
    original = client.get(base + "/photos/10/original")
    assert original.content == b"private-original" and "secret" not in str(original.headers)
    response = client.get(base + "/export.xlsx")
    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content))
    exported = str([[row for row in sheet.values] for sheet in workbook])
    assert not any(secret in exported for secret in ("Секретный", "Нейросеть", "Источник", "Оператор", "secret", "987654321"))
    with organization_scope(scope), Session(engine()) as db:
        db.get(Photo, 10).is_defect = True
        db.commit()
    assert client.get(base + "/photos").json()["total"] == 1
    assert client.get(base + "/photos/10/preview").status_code == 404
    assert client.get(base + "/photos/10/original").status_code == 404
    assert client.get(base + "/photos/map").json()["summary"]["total"] == 1
    close(owner, scope)
    assert client.get(base + "/photos?is_defect=true").json()["total"] == 1
    for hidden in ("chat_id", "operator_id", "sender_id", "day_ai_only"):
        assert client.get(base + "/photos", params={hidden: "1"}).status_code == 422
    other = f"/api/inspection/organizations/{scopes[1].id}"
    for suffix in ("/photos", "/photos/10", "/photos/10/preview", "/photos/map", "/districts", "/photos/10/original", "/reports", "/export.xlsx", "/meta", "/appeals"):
        assert client.get(other + suffix).status_code == 404
    assert client.get(scope.prefix + "/api/photos/10").status_code == 401
    assert client.get("/api/platform/organizations").status_code == 401
    # A mode switch never makes training photos available to an inspector.
    with organization_scope(scope), Session(engine()) as db:
        db.get(ExchangeState, 1).intake_cohort = "test"
        db.commit()
    assert client.get(base + "/photos").json()["total"] == 2
    owner.delete(f'/api/platform/inspection/accounts/{accounts[0]["id"]}/grants/{scope.id}')
    for suffix in ("/photos", "/photos/10", "/photos/10/preview", "/reports", "/export.xlsx", "/meta", "/appeals"):
        assert client.get(base + suffix).status_code == 404


def test_owner_created_accounts_only_can_delegate_without_inheriting_grants(inspection):
    from app.api import app

    owner, scopes, _, agency, accounts, clients = inspection
    grant(owner, clients[0], scopes[0])
    body = {"login": "subordinate", "name": "Сотрудник", "password": PASSWORD}
    assert owner.post(f'/api/platform/inspection/agencies/{agency["id"]}/accounts', json={**body, "login": "same-login"}).status_code == 409
    assert owner.post(scopes[0].prefix + "/api/users", json={**body, "login": "inspector0"}).status_code == 409
    assert clients[0].post("/api/inspection/accounts", json={**body, "can_create_accounts": True}).status_code == 422
    created = clients[0].post("/api/inspection/accounts", json=body)
    assert created.status_code == 201 and not created.json()["can_create_accounts"], created.text
    assert created.json()["created_by"] == accounts[0]["id"]
    assert clients[1].get("/api/inspection/accounts").json() == []
    with TestClient(app) as child:
        assert child.post("/api/auth/login", json={"login": body["login"], "password": PASSWORD}).status_code == 200
        child.headers["X-CSRF-Token"] = child.cookies["inspection_csrf"]
        assert child.get("/api/inspection/organizations").json() == []
        assert child.post("/api/inspection/accounts", json={**body, "login": "grandchild"}).status_code == 403
        assert child.get("/api/inspection/accounts").status_code == 403
        grant(owner, child, scopes[0])
        assert len(child.get("/api/inspection/organizations").json()) == 1
    listed = owner.get(f'/api/platform/inspection/agencies/{agency["id"]}/accounts').json()
    assert len(listed) == 3
    assert owner.patch(f'/api/platform/inspection/accounts/{accounts[0]["id"]}', json={"active": False}).status_code == 200
    assert clients[0].get("/api/inspection/me").status_code == 401
    with control_session() as db:
        assert db.get(Inspector, created.json()["id"]).active


def test_admin_chats_hide_operators_are_personal_and_revoke_access(inspection):
    owner, scopes, operators, _, accounts, clients = inspection
    scope, client, admin = scopes[0], clients[0], operators[0]
    assert admin.post(scope.prefix + "/api/inspection-admin/qr").status_code == 403
    with organization_scope(scope), Session(engine()) as db:
        user = db.scalar(select(User).where(User.login == "same-login"))
        user.role = "ADMIN_OPERATOR"
        admin_id = user.id
        db.add(User(login="hidden", name="Скрытый оператор", role="OPERATOR", password_hash="unused", active=True))
        db.commit()
    response = admin.post(scope.prefix + "/api/inspection-admin/qr")
    assert response.status_code == 200, response.text
    token = parse_qs(urlsplit(response.json()["url"]).fragment)["invite"][0]
    assert client.post("/api/inspection/redeem", json={"token": token}).status_code == 200
    contacts = client.get("/api/inspection/contacts").json()
    admins = [c for c in contacts if c["key"].startswith("a:")]
    assert len(admins) == 1 and admins[0]["name"] == "Operator 0"
    assert "Скрытый" not in str(contacts)
    peer = admins[0]["key"]
    body = {"body": "Проверьте уборку", "client_id": str(uuid4())}
    result = client.post("/api/inspection/messages", params={"peer": peer}, json=body)
    assert result.status_code == 201, result.text
    assert client.post("/api/inspection/messages", params={"peer": peer}, json=body).json()["id"] == result.json()["id"]
    assert client.post("/api/inspection/messages", params={"peer": peer}, json={**body, "body": "Другое"}).status_code == 409
    assert clients[1].get("/api/inspection/messages", params={"peer": peer}).status_code == 404
    assert client.get("/api/inspection/messages", params={"peer": f"a:{scope.id}:{admin_id + 1}"}).status_code == 404
    contact = admin.get(scope.prefix + "/api/inspection-admin/contacts").json()[0]
    assert contact["key"] == f'i:{accounts[0]["id"]}' and contact["unread"] == 1
    message = admin.get(scope.prefix + "/api/inspection-admin/messages", params={"peer": contact["key"]}).json()["items"][0]
    assert message["body"] == body["body"] and not message["outgoing"]
    response = admin.post(scope.prefix + "/api/inspection-admin/messages", params={"peer": contact["key"]},
                          json={"body": "Проверим", "client_id": str(uuid4())})
    assert response.status_code == 201
    monitor = owner.get(f'/api/platform/inspection/accounts/{accounts[0]["id"]}/messages').json()
    assert len(monitor["items"]) == 2
    assert operators[1].get(scopes[1].prefix + "/api/inspection-admin/contacts").status_code == 403
    owner.delete(f'/api/platform/inspection/accounts/{accounts[0]["id"]}/grants/{scope.id}')
    assert client.get("/api/inspection/messages", params={"peer": peer}).status_code == 404
    assert admin.get(scope.prefix + "/api/inspection-admin/messages", params={"peer": contact["key"]}).status_code == 404
    peer = f'i:{accounts[1]["id"]}'
    assert client.post("/api/inspection/messages", params={"peer": peer}, json={"body": "Привет", "client_id": str(uuid4())}).status_code == 201
    assert clients[1].get("/api/inspection/messages", params={"peer": f'i:{accounts[0]["id"]}'}).json()["items"][0]["body"] == "Привет"


def test_chat_history_cursors_read_receipts_and_contact_avatars(inspection):
    owner, scopes, admins, _, accounts, clients = inspection
    scope, client, colleague = scopes[0], clients[0], clients[1]
    grant(owner, client, scope)
    actor, peer = f'i:{accounts[0]["id"]}', f'i:{accounts[1]["id"]}'
    with control_session() as db:
        db.get(Inspector, accounts[0]["id"]).avatar_image = b"inspector-avatar"
        db.get(Inspector, accounts[1]["id"]).avatar_image = b"colleague-avatar"
        rows = [InspectionMessage(sender_key=actor, recipient_key=peer, client_id=str(uuid4()),
                                  body=f"Сообщение {index}") for index in range(110)]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    with organization_scope(scope), Session(engine()) as db:
        admin = db.scalar(select(User).where(User.login == "same-login"))
        admin.role, admin.avatar_image = "ADMIN_OPERATOR", b"admin-avatar"
        admin_peer = f"a:{scope.id}:{admin.id}"
        db.commit()

    contacts = client.get("/api/inspection/contacts").json()
    preview = next(c for c in contacts if c["key"] == peer)
    assert preview["last_message"] == "Сообщение 109" and preview["last_message_outgoing"]
    assert preview["last_message_at"] and client.get(preview["avatar_url"]).content == b"colleague-avatar"
    admin_avatar = next(c["avatar_url"] for c in contacts if c["key"] == admin_peer)
    assert client.get(admin_avatar).content == b"admin-avatar"
    assert colleague.get(admin_avatar).status_code == 404
    assert client.get("/api/inspection/contact-avatar", params={"peer": "a:invalid:1"}).status_code == 404
    admin_contacts = admins[0].get(scope.prefix + "/api/inspection-admin/contacts").json()
    assert len(admin_contacts) == 1
    assert admins[0].get(admin_contacts[0]["avatar_url"]).content == b"inspector-avatar"

    endpoint = "/api/inspection/messages"
    latest = client.get(endpoint, params={"peer": peer}).json()
    assert [m["id"] for m in latest["items"]] == ids[60:]
    older = client.get(endpoint, params={"peer": peer, "before_id": latest["next_before_id"]}).json()
    assert [m["id"] for m in older["items"]] == ids[10:60]
    first = client.get(endpoint, params={"peer": peer, "before_id": older["next_before_id"]}).json()
    assert [m["id"] for m in first["items"]] == ids[:10] and first["next_before_id"] is None
    received, cursor = [], 0
    while True:
        page = client.get(endpoint, params={"peer": peer, "after_id": cursor}).json()
        received.extend(m["id"] for m in page["items"])
        if not page["has_newer"]:
            break
        cursor = received[-1]
    assert received == ids
    assert client.get(endpoint, params={"peer": peer, "before_id": ids[-1], "after_id": 0}).status_code == 422
    assert colleague.get("/api/inspection/contacts").json()[0]["unread"] == 110
    assert colleague.get("/api/inspection/unread").json() == {"unread": 110}
    assert colleague.post(endpoint + "/read", params={"peer": actor}, json={"through_id": ids[-1]}).status_code == 200
    receipt = client.get(endpoint, params={"peer": peer, "after_id": ids[-1]}).json()
    assert receipt["items"] == [] and receipt["peer_read_through_id"] == ids[-1]
    assert colleague.get("/api/inspection/contacts").json()[0]["unread"] == 0
    assert colleague.get("/api/inspection/unread").json() == {"unread": 0}
    owner.delete(f'/api/platform/inspection/accounts/{accounts[0]["id"]}/grants/{scope.id}')
    assert client.get(admin_avatar).status_code == 404
    assert admins[0].get(admin_contacts[0]["avatar_url"]).status_code == 404


def test_appeals_and_photos_are_scoped_to_personal_organization_grant(inspection):
    owner, scopes, _, _, _, clients = inspection
    grant(owner, clients[0], scopes[0])
    records = []
    with control_session() as db:
        for scope in scopes:
            appeal = CitizenAppeal(organization_id=scope.id, organization_name=scope.name, city="Город",
                address="Улица", place="Двор", category="CLEAN", work_type_name="Уборка", description="Жалоба",
                contact="private-contact", owner_note="private-note", photo_count=1)
            db.add(appeal)
            db.flush()
            photo = AppealPhoto(id=str(uuid4()), appeal_id=appeal.id, position=0, original=b"original",
                preview=b"preview", stamped=b"stamped", width=100, height=100, captured_at=now(),
                latitude=61.1, longitude=72.6, accuracy=10, position_at=now())
            db.add(photo)
            records.append((appeal.id, photo.id))
        db.commit()
    base = f"/api/inspection/organizations/{scopes[0].id}/appeals"
    result = clients[0].get(base).json()
    assert result["total"] == 1 and result["items"][0]["organization_name"] == scopes[0].name
    assert "private" not in str(result)
    assert clients[0].get(result["items"][0]["photos"][0]["url"]).content == b"stamped"
    assert clients[0].get(base + '/' + str(records[0][0])).json()["photos"][0]["original_url"].endswith('variant=original')
    assert clients[0].get(base + '?status=RESOLVED').json()["total"] == 0
    assert clients[0].patch(base + '/' + str(records[0][0]), json={"status": "RESOLVED"}).status_code == 405
    assert clients[0].get(base + f"/{records[1][0]}/photos/{records[1][1]}").status_code == 404
    assert clients[1].get(result["items"][0]["photos"][0]["url"]).status_code == 404


def test_csrf_group_pause_password_reset_and_logout_revoke_sessions(inspection):
    owner, scopes, _, agency, accounts, clients = inspection
    client = clients[0]
    token = qr(owner, scopes[0])
    assert client.post("/api/inspection/redeem", json={"token": token}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/inspection/redeem", json={"token": token}, headers={"Origin": "https://wrong.example"}).status_code == 403
    assert client.post("/api/inspection/redeem", json={"token": token}).status_code == 200
    assert owner.patch(f'/api/platform/inspection/accounts/{accounts[0]["id"]}', json={"password": "new-inspector-password"}).status_code == 200
    assert client.get("/api/inspection/me").status_code == 401
    assert client.post("/api/auth/login", json={"login": "inspector0", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"login": "inspector0", "password": "new-inspector-password"}).status_code == 200
    assert client.get("/api/auth/entry").json()["user"]["role"] == "INSPECTOR"
    client.headers["X-CSRF-Token"] = client.cookies["inspection_csrf"]
    assert client.post("/api/inspection/logout").status_code == 200
    assert client.get("/api/inspection/me").status_code == 401
    assert owner.patch(f'/api/platform/inspection/agencies/{agency["id"]}', json={"name": "Администрация", "active": False}).status_code == 200
    assert clients[1].get("/api/inspection/me").status_code == 401
    with control_session() as db:
        assert db.get(InspectionGrant, (accounts[0]["id"], scopes[0].id))


def test_inspector_avatar_sidebar_and_device_sessions_are_personal(inspection):
    from PIL import Image

    from app.api import app

    _, _, _, _, _, clients = inspection
    client, other = clients
    buffer = BytesIO()
    Image.new('RGB', (40, 60), 'green').save(buffer, format='PNG')
    response = client.put('/api/inspection/avatar', content=buffer.getvalue(), headers={'Content-Type': 'image/png'})
    assert response.status_code == 200, response.text
    avatar_url = response.json()['avatar_url']
    assert client.get(avatar_url).status_code == 200
    assert other.get(avatar_url).status_code == 404
    assert client.put('/api/inspection/avatar', content=b'invalid').status_code == 422
    assert client.put('/api/inspection/sidebar-order', json={'sidebar_order': ['/photos', '/districts', '/']}).status_code == 200
    assert client.get('/api/inspection/me').json()['sidebar_order'] == ['/photos', '/districts', '/']
    assert other.get('/api/inspection/me').json()['sidebar_order'] != ['/photos', '/districts', '/']
    assert client.put('/api/inspection/sidebar-order', json={'sidebar_order': ['/forbidden']}).status_code == 422
    with TestClient(app) as second:
        assert second.post('/api/auth/login', json={'login': 'inspector0', 'password': PASSWORD},
                           headers={'User-Agent': 'Mozilla/5.0 (iPhone) Version/18.0 Safari/605.1'}).status_code == 200
        second.headers['X-CSRF-Token'] = second.cookies['inspection_csrf']
        sessions = client.get('/api/inspection/sessions').json()['items']
        assert len(sessions) == 2
        current = next(s for s in sessions if s['current'])
        remote = next(s for s in sessions if not s['current'])
        assert remote['device_type'] == 'phone' and remote['created_at']
        assert other.delete('/api/inspection/sessions/' + remote['id']).status_code == 404
        assert client.delete('/api/inspection/sessions/' + current['id']).status_code == 409
        assert client.delete('/api/inspection/sessions/' + remote['id']).status_code == 200
        assert second.get('/api/inspection/me').status_code == 401
    assert client.delete('/api/inspection/avatar').status_code == 200
    assert client.get(avatar_url).status_code == 404


def test_inspector_password_change_revokes_only_own_sessions_and_checks_csrf(inspection):
    from app.api import app

    _, _, _, _, _, clients = inspection
    client, other = clients
    with TestClient(app) as second:
        second.post('/api/auth/login', json={'login': 'inspector0', 'password': PASSWORD})
        second.headers['X-CSRF-Token'] = second.cookies['inspection_csrf']
        assert client.post('/api/inspection/sessions/revoke-others').json() == {'revoked': 1}
        assert second.get('/api/inspection/me').status_code == 401
    body = {'current_password': PASSWORD, 'new_password': 'changed-inspector-password'}
    assert client.post('/api/inspection/password', json=body, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert client.post('/api/inspection/password', json={**body, 'current_password': 'wrong'}).status_code == 400
    assert client.post('/api/inspection/password', json=body).status_code == 200
    assert client.get('/api/inspection/me').status_code == 401
    assert other.get('/api/inspection/me').status_code == 200
    assert client.post('/api/auth/login', json={'login': 'inspector0', 'password': body['new_password']}).status_code == 200
