import pytest
from sqlalchemy import select
from test_integration import FakeDisk, FakeMax, GoodAI, GoodOCR, intake_photo, setup_chat, setup_district

from app.exchange import record
from app.models import Job
from app.processing import process_photo, regeo_all, sync_photo

pytestmark = pytest.mark.integration


class NoCoordinatesOCR(GoodOCR):
    def recognize(self, path):
        return "16 окт. 2026 г. 10:30:07"


def test_manual_choice_without_gps_persists_moves_file_and_reaches_exchange(admin, db, monkeypatch):
    setup_chat(db)
    district = setup_district(db)
    photo = intake_photo(db)
    disk = FakeDisk()
    process_photo(photo.id, FakeMax(), disk, NoCoordinatesOCR(), GoodAI())
    db.refresh(photo)
    assert photo.latitude is photo.longitude is photo.district_id is None
    old_path = photo.yandex_disk_path
    response = admin.patch(f"/api/photos/{photo.id}", json={"version": photo.version, "district_id": district.id})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACCEPTED"
    detail = admin.get(f"/api/photos/{photo.id}").json()
    assert detail["district_id"] == district.id and detail["district_source"] == "OPERATOR"
    assert detail["latitude"] is detail["longitude"] is None
    assert detail["history"][0]["new_value"]["district_source"] == "OPERATOR"
    db.refresh(photo)
    assert db.scalar(select(Job.id).where(Job.kind == "SYNC", Job.object_id == photo.id))
    monkeypatch.setattr("app.processing.YandexDisk", lambda: disk)
    sync_photo(photo.id)
    regeo_all()
    sync_photo(photo.id)
    db.refresh(photo)
    assert photo.district_id == district.id and photo.district_source == "OPERATOR"
    assert "/12_мкр/" in photo.yandex_disk_path and old_path not in disk.files
    assert photo.storage_status == "SYNCED" and photo.status == "ACCEPTED"
    exported = record(photo)
    assert exported.district_id == str(district.id) and exported.district_name == district.name
    assert exported.latitude is exported.longitude is None
    assert admin.get(f"/api/photos?district_id={district.id}").json()["total"] == 1
    assert admin.get("/api/photos/map").json()["summary"]["without_coordinates"] == 1


def test_return_to_coordinates_and_unknown_district_do_not_invent_location(admin, db):
    setup_chat(db)
    district = setup_district(db)
    photo = intake_photo(db)
    process_photo(photo.id, FakeMax(), FakeDisk(), NoCoordinatesOCR(), GoodAI())
    db.refresh(photo)
    response = admin.patch(f"/api/photos/{photo.id}", json={"version": photo.version, "district_id": 999999})
    assert response.status_code == 422
    response = admin.patch(f"/api/photos/{photo.id}", json={"version": photo.version, "district_id": district.id})
    assert response.status_code == 200
    response = admin.patch(f"/api/photos/{photo.id}", json={"version": response.json()["version"], "district_id": None})
    assert response.status_code == 200
    assert response.json()["district_id"] is response.json()["district_source"] is None
    assert response.json()["review_reason"] == ["COORDINATES_MISSING"]
    assert response.json()["status"] == "NEEDS_REVIEW"
