"""Exercise real API, ORM and exports across operator chat boundaries."""
from datetime import UTC, date, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy import JSON, Column, MetaData, Table, create_engine, event, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, attributes
from sqlalchemy.pool import StaticPool

from app.api import app
from app.auth import digest
from app.db import get_db
from app.domain import now
from app.models import (
    Audit,
    Chat,
    DayClosure,
    DayClosureChat,
    DayPhotoReview,
    DiskFolderSettings,
    ExchangeState,
    Inbox,
    Job,
    LoginSession,
    Photo,
    User,
    WorkType,
)
from app.permissions import PERMISSIONS
from app.schemas import UserCreate, UserUpdate


class AccessSession(Session):
    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if sql.startswith("SELECT pg_advisory_xact_lock") or sql.startswith("SET TRANSACTION"):
            statement = text("SELECT 1")
            args, kwargs = (), {}
        return super().execute(statement, *args, **kwargs)

    def get(self, entity, ident, **kwargs):
        result = super().get(entity, ident, **kwargs)
        if isinstance(result, LoginSession):
            for key in ("expires_at", "last_seen_at", "created_at"):
                value = getattr(result, key)
                if value and value.tzinfo is None:
                    attributes.set_committed_value(result, key, value.replace(tzinfo=UTC))
        return result


@pytest.fixture
def access_api(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    metadata = MetaData()
    for model in (User, Chat, Photo, Audit, Job, Inbox, LoginSession, DiskFolderSettings, DayClosure, DayClosureChat, DayPhotoReview, ExchangeState):
        Table(model.__tablename__, metadata, *(
            Column(c.name, JSON(none_as_null=True) if isinstance(c.type, JSONB) else c.type,
                   primary_key=c.primary_key)
            for c in model.__table__.columns
        ))
    Table("districts", metadata, Column("id", Photo.__table__.c.district_id.type, primary_key=True),
          Column("name", Chat.__table__.c.name.type), Column("active", Chat.__table__.c.active.type))

    @event.listens_for(engine, "connect")
    def functions(connection, _):
        connection.create_function("timezone", 2, lambda zone, value: value)

    metadata.create_all(engine)
    WorkType.__table__.create(engine)
    with AccessSession(engine) as db:
        db.add(DiskFolderSettings(id=1,version=1,folder_sets=[]))
        db.add(ExchangeState(id=1, instance_id=str(uuid4()), source_timezone="Asia/Yekaterinburg",
                             intake_cohort="production"))
        from app.catalog import WORK_TYPE_DISPLAY_ORDER, WORK_TYPES
        db.add_all([WorkType(code=code, name=names[0], filename_label=names[1],
                             model_index=i, sort_order=WORK_TYPE_DISPLAY_ORDER.index(code)+1)
                     for i, (code, names) in enumerate(WORK_TYPES.items())])
        for id, role, ids in [(1, "ADMIN_OPERATOR", [2]), (2, "OPERATOR", [1]),
                              (3, "OPERATOR", []), (4, "OPERATOR", None)]:
            db.add(User(id=id, login=f"user{id}", name=f"Оператор {id}", password_hash="unused",
                        active=True, role=role, permissions=list(PERMISSIONS), allowed_chat_ids=ids))
            db.add(LoginSession(id=str(uuid4()), user_id=id, token_hash=digest(f"user{id}"),
                                csrf_hash=digest("csrf"), expires_at=now()+timedelta(hours=1),
                                last_seen_at=now(), created_at=now()))
        db.add_all([Chat(id=1, name="Разрешённый", max_chat_id=100, active=False),
                    Chat(id=2, name="Закрытый", max_chat_id=200, active=True)])
        for id, cid, spam in [(10,100,False), (20,200,False), (30,100,True), (40,200,True),
                              (50,100,False), (60,999,False)]:
            db.add(Inbox(id=id, max_chat_id=cid, message_id=str(id), payload={}))
            db.add(Photo(id=id, inbox_id=id, attachment_index=0, version=1, cohort="production",
                         is_spam=spam, is_defect=False, status="SPAM" if spam else "ACCEPTED",
                         storage_status="SYNCED", photo_date=date(2026,10,18), received_at=now(),
                         max_chat_id=cid, chat_name="Разрешённый" if cid==100 else "Закрытый",
                         max_message_id=str(id), district_id=None, latitude=61.1, longitude=72.6,
                         work_type="BIN_EMPTYING", work_type_source="AI", sha256=f"{id:064x}",
                         review_reason=[], analyzed_at=now(), extension=".jpg"))
            db.add(Audit(id=id, user_id=1, action="PHOTO_EDIT", object_type="photo", object_id=id,
                         photo_id=id, old_value={}, new_value={}))
            db.add(Job(id=id, kind="SYNC", object_id=id, status="BLOCKED", attempts=0,
                       dedupe_key=f"sync:{id}", next_run_at=now(), last_error="ORIGINAL_MISSING"))
            db.add(Job(id=id+100, kind="BATCH", object_id=id, status="PENDING", attempts=0,
                       dedupe_key=f"batch:{id}", next_run_at=now()))
        db.add(Audit(id=99, user_id=1, action="USER_UPDATED", object_type="user", object_id=4,
                     old_value={}, new_value={}))
        db.add(Job(id=999, kind="TRAIN", object_id=1, status="PENDING", attempts=0,
                   dedupe_key="train", next_run_at=now()))
        db.commit()

    def database():
        with AccessSession(engine, expire_on_commit=False) as db:
            yield db
    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    with TestClient(app) as client:
        actor(client, 2)
        yield client, engine
    engine.dispose()


def actor(client, id):
    client.cookies.clear()
    client.cookies.set("session", f"user{id}")
    client.headers["X-CSRF-Token"] = "csrf"


def test_lists_meta_filters_map_reports_and_notifications_share_the_chat_scope(access_api):
    client, _ = access_api
    result = client.get("/api/photos").json()
    assert result["total"] == 2 and {p["id"] for p in result["items"]} == {10,50}
    assert client.get("/api/photos?chat_id=200").json()["total"] == 0
    assert [c["id"] for c in client.get("/api/meta").json()["chats"]] == [1]
    assert [c["id"] for c in client.get("/api/chats").json()] == [1]
    report = client.get("/api/reports").json()
    assert report["total"] == 2 and [c["id"] for c in report["chats"]] == ["100"]
    assert client.get("/api/photos/arrivals").json()["photo_ids"] == [10,50]
    mapped = client.get("/api/photos/map").json()
    assert mapped["summary"]["total"] == 2 and {p["id"] for p in mapped["items"]} == {10,50}
    counts = client.get("/api/photos/filter-counts?chat_id=200").json()
    assert counts["chat_id"] == {"total":2, "values":{"100":2}}
    assert counts["work_type"]["total"] == 0
    assert client.get("/api/photos?status=SPAM").json()["total"] == 1


def test_large_max_chat_ids_survive_reports_and_photo_links_without_rounding(access_api):
    client, engine = access_api
    large_ids = {100: 9007199254740992, 200: 9007199254740993}
    with AccessSession(engine) as db:
        for old, exact in large_ids.items():
            db.scalar(select(Chat).where(Chat.max_chat_id == old)).max_chat_id = exact
            for model in (Photo, Inbox):
                for row in db.scalars(select(model).where(model.max_chat_id == old)):
                    row.max_chat_id = exact
        db.commit()
    actor(client, 1)
    report = client.get("/api/reports").json()
    expected = {str(value) for value in large_ids.values()}
    assert expected.issubset({chat["id"] for chat in report["chats"]})
    assert expected.issubset({row["chat_id"] for row in report["matrix"]})
    for exact in expected:
        photos = client.get("/api/photos", params={"chat_id": exact}).json()
        assert photos["total"] > 0
        assert {photo["max_chat_id"] for photo in photos["items"]} == {exact}


@pytest.mark.parametrize("method,path,body", [
    ("GET","/api/photos/20",None), ("GET","/api/photos/20/preview",None),
    ("GET","/api/photos/20/original",None), ("GET","/api/photos/20/next",None),
    ("PATCH","/api/photos/20",{"version":1,"is_defect":True}),
    ("POST","/api/photos/20/retry",None),
    ("POST","/api/photos/20/remove-missing-preview",{"version":1}),
    ("POST","/api/jobs/20/retry",None), ("POST","/api/jobs/120/retry",None),
    ("POST","/api/jobs/999/retry",None),
])
def test_direct_access_and_mutations_to_other_chats_are_denied(access_api, method, path, body):
    client, engine = access_api
    assert client.request(method,path,json=body).status_code == 404
    with AccessSession(engine) as db:
        assert db.get(Photo,20).version == 1
        assert not db.get(Photo,20).is_defect
        assert db.get(Job,20).status == "BLOCKED"


def test_next_photo_and_list_anchor_cannot_cross_the_boundary(access_api):
    client, _ = access_api
    assert client.get("/api/photos/50/next").json() == {"id":10}
    assert client.get("/api/photos/10/next").json() == {"id":None}
    data = client.get("/api/photos?anchor_id=20&page_size=1").json()
    assert data["page"] == 1 and data["focus_id"] is None


def test_save_and_next_finishes_the_review_list_before_revisiting_unresolved_photos(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        for id in [50,30,10]:
            photo = db.get(Photo,id)
            photo.status, photo.is_spam = "NEEDS_REVIEW", False
            photo.latitude = photo.longitude = photo.work_type = None
        db.commit()
    query = "status=NEEDS_REVIEW&chat_id=100"
    assert [p["id"] for p in client.get('/api/photos?'+query).json()["items"]] == [50,30,10]
    for id, expected in [(50,30),(30,10),(10,50)]:
        # The UI resolves navigation before saving. An uncertain category stays
        # unresolved, but must not pull the next click back to the first row.
        assert client.get(f'/api/photos/{id}/next?'+query).json() == {"id":expected}
        saved = client.patch(f'/api/photos/{id}',json={"version":1,"work_type":None})
        assert saved.status_code == 200 and saved.json()["status"] == "NEEDS_REVIEW"
    with AccessSession(engine) as db:
        assert all(db.get(Photo,id).version == 2 for id in [50,30,10])


def test_review_wrap_still_hides_unassigned_chats(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        for id in [50,20,10]:
            db.get(Photo,id).status = "NEEDS_REVIEW"
        db.commit()
    assert client.get('/api/photos/10/next?status=NEEDS_REVIEW').json() == {"id":50}
    actor(client,3)
    assert client.get('/api/photos/10/next?status=NEEDS_REVIEW').status_code == 404


def test_excel_all_sheets_are_scoped(access_api):
    client, _ = access_api
    result = client.get("/api/export.xlsx")
    assert result.status_code == 200, result.text
    book = load_workbook(BytesIO(result.content))
    assert {row[0] for row in list(book["Все фото"].values)[1:]} == {10,50}
    assert list(book["По чатам"].values)[1:] == [("Разрешённый",2)]


def test_allowed_photo_remains_readable_and_editable(access_api, monkeypatch):
    client, engine = access_api
    assert client.get("/api/photos/10").json()["id"] == 10
    assert client.get("/api/photos/10/original").status_code == 409  # Fixture has no uploaded original.
    monkeypatch.setattr("app.domain.resolve_district", lambda *_: (None,"OUTSIDE_DISTRICTS"))
    result = client.patch("/api/photos/10",json={"version":1,"is_defect":True})
    assert result.status_code == 200 and result.json()["is_defect"] is True
    with AccessSession(engine) as db:
        assert db.get(Photo,10).version == 2
        assert db.get(Job,10).status == "PENDING"


def test_audit_and_job_views_omit_other_chats_and_global_objects(access_api):
    client, _ = access_api
    assert {a["photo_id"] for a in client.get("/api/audit").json()["items"]} == {10,30,50}
    assert {j["id"] for j in client.get("/api/jobs").json()} == {10,30,50,110,130,150}


@pytest.mark.parametrize("id,total,spam_total", [(1,4,2),(3,0,0),(4,4,2)])
def test_administrators_legacy_operators_and_empty_selection(access_api,id,total,spam_total):
    client, _ = access_api
    actor(client,id)
    assert client.get("/api/photos").json()["total"] == total
    assert client.get("/api/photos?status=SPAM").json()["total"] == spam_total
    if id == 3:
        assert client.get("/api/meta").json()["chats"] == []
        assert client.get("/api/reports").json()["total"] == 0
        assert client.get("/api/photos/map").json()["items"] == []
        assert client.get("/api/photos/arrivals").json()["photo_ids"] == []
        assert client.get("/api/photos/10").status_code == 404


@pytest.mark.parametrize("path", ["/api/ml","/api/exchange","/api/chats/discovered","/api/max/status"])
def test_global_data_requires_all_chat_access(access_api,path):
    client, _ = access_api
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("method,path,body", [
    ("POST","/api/ml/train",None), ("PUT","/api/exchange/mode",{"cohort":"test"}),
    ("POST","/api/exchange/publish",{"cohort":"test"}), ("POST","/api/exchange/organize",None),
    ("POST","/api/chats",{"max_chat_id":300,"name":"Новый чат"}),
    ("PATCH","/api/users/2",{"allowed_chat_ids":None}),
])
def test_limited_operator_cannot_expand_scope_or_start_global_operations(access_api,method,path,body):
    client, _ = access_api
    assert client.request(method,path,json=body).status_code == 403


def test_chat_settings_are_editable_only_for_assigned_chats(access_api):
    client, _ = access_api
    assert client.put("/api/chats/2",json={"max_chat_id":200,"name":"Изменено"}).status_code == 404
    assert client.put("/api/chats/1",json={"max_chat_id":100,"name":"Изменено"}).status_code == 200


def test_partial_user_edits_preserve_scope_and_explicit_null_restores_all(access_api):
    client, engine = access_api
    actor(client,1)
    response = client.patch("/api/users/2",json={"name":"Новое имя"})
    assert response.status_code == 200 and response.json()["allowed_chat_ids"] == [1]
    with AccessSession(engine) as db:
        assert db.get(LoginSession,digest("user2")) is not None
    response = client.patch("/api/users/2",json={"allowed_chat_ids":None})
    assert response.status_code == 200 and response.json()["allowed_chat_ids"] is None
    with AccessSession(engine) as db:
        assert db.get(LoginSession,digest("user2")) is None
        audit = db.scalar(select(Audit).where(Audit.action=="USER_UPDATED").order_by(Audit.id.desc()))
        assert audit.old_value["allowed_chat_ids"] == [1]
        assert audit.new_value["allowed_chat_ids"] is None
    actor(client,2)
    assert client.get("/api/auth/me").status_code == 401


def test_same_selection_does_not_revoke_session_but_empty_selection_does(access_api):
    client, engine = access_api
    actor(client,1)
    assert client.patch("/api/users/2",json={"allowed_chat_ids":[1,1]}).status_code == 200
    with AccessSession(engine) as db:
        assert db.get(LoginSession,digest("user2")) is not None
    assert client.patch("/api/users/2",json={"allowed_chat_ids":[]}).json()["allowed_chat_ids"] == []
    with AccessSession(engine) as db:
        assert db.get(LoginSession,digest("user2")) is None


def test_unknown_chats_rejected_without_changing_account(access_api):
    client, engine = access_api
    actor(client,1)
    assert client.patch("/api/users/2",json={"allowed_chat_ids":[999]}).status_code == 422
    assert client.post("/api/users",json={"login":"new-user","name":"New","password":"long-password-123","allowed_chat_ids":[999]}).status_code == 422
    with AccessSession(engine) as db:
        assert db.get(User,2).allowed_chat_ids == [1]
        assert db.get(LoginSession,digest("user2")) is not None


def test_create_limited_operator_and_promote_to_admin(access_api):
    client, engine = access_api
    actor(client,1)
    response = client.post("/api/users",json={"login":"new-user","name":"New","password":"long-password-123","allowed_chat_ids":[2,1,1]})
    assert response.status_code == 201 and response.json()["allowed_chat_ids"] == [1,2]
    id = response.json()["id"]
    assert client.patch(f"/api/users/{id}",json={"role":"ADMIN_OPERATOR","allowed_chat_ids":[]}).json()["allowed_chat_ids"] is None
    with AccessSession(engine) as db:
        assert db.get(User,id).allowed_chat_ids is None


@pytest.mark.parametrize("value", [[0],[-1],[True],[1.2],["1"],"all",{}])
def test_access_schema_rejects_invalid_chat_ids(value):
    with pytest.raises(ValidationError):
        UserUpdate(allowed_chat_ids=value)


def test_legacy_inputs_and_explicit_scope_are_distinct():
    assert "allowed_chat_ids" not in UserUpdate(name="New").model_dump(exclude_unset=True)
    assert UserUpdate(allowed_chat_ids=None).model_dump(exclude_unset=True) == {"allowed_chat_ids":None}
    assert UserCreate(login="new",name="New",password="long-password-123").allowed_chat_ids is None
