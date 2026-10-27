from copy import deepcopy
from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from openpyxl import load_workbook
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import select
from test_organizations import companies as companies

from app.api import app
from app.daily_report_presets import shashko_config
from app.models import District, ExchangeState, Inbox, Photo, User

pytestmark = pytest.mark.integration
BASE = "/api/daily-reports"


@pytest.fixture
def reporting(admin, db):
    config = shashko_config(db).model_dump()
    config["works"] = [w for w in config["works"] if w["id"] in {"bins", "maf-inspection"}]
    for work in config["works"]:
        for assignment in work["assignments"]:
            assignment["quantity"] = 10
            assignment["resources"] = "Тестовая бригада"
    assert admin.put(BASE + "/settings", json={"version": 0, "config": config}).status_code == 200
    return admin, db, config


def create(client, day="2026-10-18"):
    response = client.post(BASE, json={"day": day})
    assert response.status_code == 201, response.text
    return response.json()


def complete(client, report, *, quantity=10):
    doc = deepcopy(report["document"])
    for kind in ("fact", "plan"):
        for row in doc[kind]:
            row["decision"], row["quantity"] = "include", quantity
    response = client.put(f"{BASE}/{report['id']}", json={"version": report["version"], "document": doc})
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, report):
    return client.post(f"{BASE}/{report['id']}/approve", json={"version": report["version"]})


def test_draft_approval_numbers_and_exports_are_persistent_and_idempotent(reporting):
    client, db, _ = reporting
    db.get(ExchangeState, 1).intake_cohort = "production"
    db.commit()
    report = create(client)
    assert report["fact_day"] == "2026-10-17" and len(report["document"]["fact"]) == 4
    assert approve(client, report).status_code == 422
    assert client.get(f"{BASE}/{report['id']}/xlsx").status_code == 409
    assert client.get(f"{BASE}/{report['id']}/xlsx?draft=true").status_code == 200
    assert create(client)["id"] == report["id"]
    report = complete(client, report)
    result = approve(client, report)
    assert result.status_code == 200, result.text
    report = result.json()
    assert report["letter_numbers"] == {"58": "МК-58-001", "60": "МК-60-001"}
    assert approve(client, report).json()["letter_numbers"] == report["letter_numbers"]
    for _ in range(2):
        response = client.get(f"{BASE}/{report['id']}/xlsx")
        wb = load_workbook(BytesIO(response.content))
        assert len(wb.worksheets) == 3
        assert "МК-58-001" in client.get(f"{BASE}/{report['id']}/print").text
    settings = client.get(BASE + "/settings").json()
    assert {c["next_number"] for c in settings["config"]["contracts"]} == {2}
    assert client.get(f"{BASE}/{report['id']}/history").json()[0]["action"] == "APPROVED"


def test_corrections_preserve_the_previous_approved_letter_until_approved_again(reporting):
    client, _, _ = reporting
    report = approve(client, complete(client, create(client))).json()
    settings = client.get(BASE + "/settings").json()
    settings["config"]["profile"]["company_name"] = "Новая редакция реквизитов"
    assert client.put(BASE + "/settings", json=settings).status_code == 200
    rebuilt = client.post(f"{BASE}/{report['id']}/rebuild", json={"version": report["version"]}).json()
    assert rebuilt["changed"]
    assert "Новая редакция реквизитов" not in client.get(f"{BASE}/{report['id']}/print").text
    assert "Новая редакция реквизитов" in client.get(f"{BASE}/{report['id']}/print?draft=true").text
    corrected = approve(client, rebuilt)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["letter_numbers"] == report["letter_numbers"]
    assert "Новая редакция реквизитов" in client.get(f"{BASE}/{report['id']}/print").text


def test_stale_edits_and_unknown_duplicate_or_injected_rows_are_rejected(reporting):
    client, _, _ = reporting
    old = create(client)
    current = complete(client, old)
    assert client.put(f"{BASE}/{old['id']}", json={"version": old["version"], "document": old["document"]}).status_code == 409
    assert approve(client, old).status_code == 409
    doc = deepcopy(current["document"])
    doc["fact"].append(doc["fact"][0])
    assert client.put(f"{BASE}/{old['id']}", json={"version": current["version"], "document": doc}).status_code == 422
    doc["fact"][-1] = {**doc["fact"][-1], "work_id": "foreign-work"}
    assert client.put(f"{BASE}/{old['id']}", json={"version": current["version"], "document": doc}).status_code == 422


def test_test_reports_never_consume_production_numbers_or_enter_the_production_archive(reporting):
    client, db, _ = reporting
    test = approve(client, complete(client, create(client))).json()
    assert all(n.startswith("ТЕСТ-") for n in test["letter_numbers"].values())
    assert {c["next_number"] for c in client.get(BASE + "/settings").json()["config"]["contracts"]} == {1}
    db.get(ExchangeState, 1).intake_cohort = "production"
    db.commit()
    assert client.get(BASE).json() == []
    assert client.get(f"{BASE}/{test['id']}").status_code == 404
    assert client.get(f"{BASE}/{test['id']}/print").status_code == 404
    prod = create(client)
    assert prod["id"] != test["id"] and prod["cohort"] == "production"


def test_reports_require_explicit_access_all_chats_and_csrf(reporting):
    client, db, _ = reporting
    report = create(client)
    user = db.scalar(select(User).where(User.login == "operator"))
    user.permissions = ["daily_reports_view"]
    user.allowed_chat_ids = []
    db.commit()
    with TestClient(app) as operator:
        assert operator.post("/api/auth/login", json={"login": "operator", "password": "test-password-123"}).status_code == 200
        assert operator.get(BASE).status_code == 403
        user.allowed_chat_ids = None
        db.commit()
        assert operator.get(BASE).status_code == 200
        operator.headers["X-CSRF-Token"] = operator.cookies["csrf"]
        assert operator.post(BASE, json={"day": "2026-10-20"}).status_code == 403
        assert operator.put(BASE + "/settings", json={"version": 1, "config": {}}).status_code == 403
    assert client.post(f"{BASE}/{report['id']}/approve", json={"version": 1}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.get(BASE, headers={"Origin": "https://other.test"}).status_code == 200
    assert client.post(BASE, json={"day": "2026-10-20"}, headers={"Origin": "https://other.test"}).status_code == 403


def test_photo_evidence_matches_exact_date_area_and_cohort_but_never_sets_work_volume(reporting):
    client, db, _ = reporting
    district = District(name="1 мкр", geometry=from_shape(MultiPolygon([Polygon([(0,0),(0,1),(1,1),(1,0),(0,0)])]), srid=4326))
    db.add(district)
    db.commit()
    settings = client.get(BASE + "/settings").json()
    settings["config"]["areas"][0]["district_ids"] = [district.id]
    assert client.put(BASE + "/settings", json=settings).status_code == 200
    inbox = Inbox(max_chat_id=100, message_id="evidence", payload={})
    db.add(inbox)
    db.flush()
    photos = []
    for i, (cohort, day, status, spam) in enumerate([
        ("test", date(2026,10,17), "ACCEPTED", False),
        ("test", date(2026,10,17), "NEEDS_REVIEW", False),
        ("test", date(2026,10,17), "DUPLICATE", False),
        ("test", date(2026,10,17), "ACCEPTED", True),
        ("production", date(2026,10,17), "ACCEPTED", False),
        ("test", date(2026,10,18), "ACCEPTED", False),
        ("test", None, "ACCEPTED", False),
    ]):
        p = Photo(inbox_id=inbox.id, attachment_index=i, max_chat_id=100, max_message_id="evidence", chat_name="Тест",
                  cohort=cohort, photo_date=day, status=status, is_spam=spam, work_type="BIN_EMPTYING", district_id=district.id)
        db.add(p)
        photos.append(p)
    db.commit()
    report = create(client)
    assert report["evidence"]["rows"]["bins:area58"] == {"total": 2, "needs_review": 1}
    assert all(r["quantity"] == 10 and r["decision"] == "pending" for r in report["document"]["fact"])
    page = client.get(f"{BASE}/{report['id']}/photos?work_id=bins&area_id=area58").json()
    assert {p["id"] for p in page["items"]} == {photos[0].id, photos[1].id}
    assert approve(client, complete(client, report)).status_code == 200
    photos[0].version += 1
    db.add(Photo(inbox_id=inbox.id, attachment_index=10, max_chat_id=100, max_message_id="late", chat_name="Тест",
                 cohort="test", photo_date=date(2026,10,17), status="ACCEPTED", work_type="BIN_EMPTYING", district_id=district.id))
    db.commit()
    refreshed = client.get(f"{BASE}/{report['id']}").json()
    assert refreshed["new_photos"] == 1 and refreshed["changed_photos"] == 1


def test_annual_limit_checks_corrections_without_double_counting_the_same_report(reporting):
    client, _, _ = reporting
    settings = client.get(BASE + "/settings").json()
    for work in settings["config"]["works"]:
        for assignment in work["assignments"]:
            assignment["annual_limit"] = 15
    assert client.put(BASE + "/settings", json=settings).status_code == 200
    first = complete(client, create(client), quantity=8)
    assert approve(client, first).status_code == 200
    # Eight replaces eight; it must not count the same shift twice.
    first = complete(client, first, quantity=8)
    assert approve(client, first).status_code == 200
    second = complete(client, create(client,"2026-10-19"), quantity=8)
    assert approve(client, second).status_code == 422
    second = complete(client, second, quantity=7)
    assert approve(client, second).status_code == 200


def test_concurrent_approvals_cannot_spend_the_same_remaining_limit(reporting):
    from concurrent.futures import ThreadPoolExecutor

    client, _, _ = reporting
    settings = client.get(BASE + "/settings").json()
    for w in settings["config"]["works"]:
        for assignment in w["assignments"]:
            assignment["annual_limit"] = 10
    assert client.put(BASE + "/settings", json=settings).status_code == 200
    reports = [complete(client, create(client, day), quantity=6) for day in ("2026-10-18", "2026-10-19")]
    def submit(report):
        with TestClient(app) as separate:
            separate.cookies.update(client.cookies)
            separate.headers["X-CSRF-Token"] = client.cookies["csrf"]
            return approve(separate, report).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, reports)) == [200, 422]


def test_fact_year_controls_limits_and_new_year_does_not_reuse_the_previous_fact(reporting):
    client, _, _ = reporting
    settings = client.get(BASE + "/settings").json()
    for w in settings["config"]["works"]:
        for assignment in w["assignments"]:
            assignment["annual_limit"] = 10
    assert client.put(BASE + "/settings", json=settings).status_code == 200
    # Letter on January 1 reports December 31, not work in the new year's allowance.
    first = complete(client, create(client,"2027-01-01"), quantity=8)
    assert approve(client, first).status_code == 200
    next_year = complete(client, create(client,"2027-01-02"), quantity=8)
    assert approve(client, next_year).status_code == 200


def test_no_example_reports_or_historical_quantities_are_created(admin, db):
    config = shashko_config(db).model_dump()
    assert admin.put(BASE + "/settings", json={"version":0,"config":config}).status_code == 200
    assert admin.post(BASE, json={"day":"2026-10-18","example":True}).status_code == 422
    for cohort in ("test", "production"):
        db.get(ExchangeState, 1).intake_cohort = cohort
        db.commit()
        report = create(admin)
        assert all(r["quantity"] is None and not r["resources"] and r["decision"] == "pending"
                   for r in report["document"]["fact"])


def test_setup_reuses_exact_company_districts_and_renames_only_new_snapshots(admin, db):
    names = ["1 мкр", "11 мкр", "Набережная", "Киевская", "ПНМК-6, ОБТОик", "Полигон Снежный"]
    shape = from_shape(MultiPolygon([Polygon([(0,0),(0,1),(1,1),(1,0),(0,0)])]), srid=4326)
    db.add_all(District(name=name, active=True, geometry=shape) for name in names)
    db.commit()
    districts = {d.name: d for d in db.scalars(select(District))}
    config = shashko_config(db).model_dump()
    assert config["areas"][0]["district_ids"] == [districts[n].id for n in ["1 мкр", "Набережная"]]
    assert set(config["areas"][1]["district_ids"]) == {districts[n].id for n in ["11 мкр", "Киевская", "ПНМК-6, ОБТОик"]}
    assert admin.put(BASE + "/settings", json={"version":0,"config":config}).status_code == 200
    first = create(admin)
    districts["1 мкр"].name = "1 микрорайон"
    db.commit()
    current = admin.get(BASE + "/settings").json()["config"]
    assert "1 микрорайон" in current["areas"][0]["name"]
    assert first["config"]["areas"][0]["name"] == "1 мкр, Набережная"
    next_day = create(admin, "2026-10-19")
    assert "1 микрорайон" in next_day["config"]["areas"][0]["name"]


def test_company_settings_reports_and_letter_numbers_are_in_separate_databases(companies):
    owner, scopes, clients = companies
    paths = [scope.prefix + BASE for scope in scopes]
    fresh = owner.get(paths[0] + "/settings").json()
    assert fresh["config"]["profile"]["company_name"] == "Alpha"
    assert fresh["config"]["profile"]["city"] == "Сургут"
    preset = shashko_config().model_dump()
    types = {w["code"] for w in owner.get(scopes[0].prefix + "/api/meta").json()["work_types"]}
    for work in preset["works"]:
        work["photo_codes"] = [code for code in work["photo_codes"] if code in types]
    assert owner.put(paths[0] + "/settings", json={"version": 0, "config": preset}).status_code == 200
    assert owner.get(paths[0] + "/settings").json()["config"]["profile"]["short_name"] == "ИП Шашко А. Д."
    assert owner.get(paths[1] + "/settings").json()["version"] == 0
    result = owner.post(paths[0], json={"day":"2026-10-18"})
    assert result.status_code == 201, result.text
    id = result.json()["id"]
    assert owner.get(paths[1] + f"/{id}").status_code == 404
    assert owner.get(paths[1]).json() == []
    assert clients[0].get(paths[0]).status_code == 403
    assert clients[0].get(paths[1]).status_code == 401


def test_initial_fill_command_targets_shashko_only_and_never_overwrites_settings(companies, monkeypatch):
    from app.cli import main

    owner, scopes, _ = companies
    args = ["metka", "configure-daily-reports", "--organization", scopes[0].id, "--preset", "shashko"]
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit, match="выберите организацию ИП Шашко"):
        main()
    assert owner.patch("/api/platform/organizations/" + scopes[0].id,
                     json={"name":"ИП Шашко", "status":"ACTIVE"}).status_code == 200
    main()
    path = scopes[0].prefix + BASE
    settings = owner.get(path + "/settings").json()
    assert settings["version"] == 1 and len(settings["config"]["works"]) == 15
    assert owner.get(path).json() == []
    assert owner.get(scopes[1].prefix + BASE + "/settings").json()["version"] == 0
    main()
    assert owner.get(path + "/settings").json() == settings
