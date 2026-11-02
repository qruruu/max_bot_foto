from datetime import date, time

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, box
from sqlalchemy import select

from app.models import Chat, District, Inbox, Photo, User


def setup(db):
    district = District(name="Территория", geometry=from_shape(MultiPolygon([box(72.59, 61.09, 72.61, 61.11)]), srid=4326))
    db.add_all([district, Chat(max_chat_id=123, name="Выбранный"), Chat(max_chat_id=456, name="Другой")])
    db.flush()
    return district.id


def plan(**changes):
    return {"version": 0, "enabled": True, "chat_ids": [1],
            "paths": [[[72.6, 61.1], [72.601, 61.1]]], "buildings": [],
            "buildings_checked": True, **changes}


def add_photo(db, index, longitude=72.6, **changes):
    inbox = Inbox(max_chat_id=123, message_id=str(index), payload={})
    db.add(inbox)
    db.flush()
    values = {"photo_date": date(2026, 11, 2), "photo_time": time(10, index),
              "latitude": 61.1, "longitude": longitude, "sender_id": 10,
              "status": "ACCEPTED", "max_chat_id": 123, **changes}
    photo = Photo(inbox_id=inbox.id, attachment_index=0, max_message_id=str(index), chat_name="Чат", **values)
    db.add(photo)
    db.flush()
    return photo


def report(client, district, **changes):
    return client.get(f"/api/photo-routes/{district}/coverage", params={"date_from": "2026-11-02", "date_to": "2026-11-02", **changes})


def test_plans_are_opt_in_and_require_authorization(client, users, db):
    district = setup(db)
    db.commit()
    assert client.get('/api/photo-routes').status_code == 401
    client.post('/api/auth/login', json={"login": "operator", "password": "test-password-123"})
    client.headers['X-CSRF-Token'] = client.cookies['csrf']
    assert client.get('/api/photo-routes').json() == {"plans": [], "chats": [], "territories": []}
    assert report(client, district).status_code == 404
    assert client.put(f'/api/photo-routes/{district}', json=plan()).status_code == 403


def test_save_validate_conflicts_and_coverage(admin, db):
    district = setup(db)
    add_photo(db, 1)
    add_photo(db, 2, 72.6005)
    add_photo(db, 3, 72.601, max_chat_id=456)  # not selected for the feature
    add_photo(db, 4, 72.601, status="REJECTED")
    db.commit()
    url = f'/api/photo-routes/{district}'
    assert admin.put(url, json=plan(buildings_checked=False)).status_code == 422
    assert admin.put(url, json=plan(paths=[[[72.6, 61.1], [72.7, 61.1]]])).status_code == 422
    assert admin.put(url, json=plan(buildings=[box(72.6002, 61.099, 72.6003, 61.101).__geo_interface__])).status_code == 422
    assert admin.put(url, json=plan()).status_code == 200
    assert admin.put(url, json=plan()).status_code == 409
    result = report(admin, district)
    assert result.status_code == 200, result.text
    assert result.json()['remaining_percent'] == 50
    assert result.json()['photo_count'] == 2
    assert report(admin, district, chat_id=2).status_code == 404
    assert report(admin, district, date_to='2026-12-30').status_code == 422
    assert report(admin, district, date_from='2026-11-03').status_code == 422
    assert admin.put(url, json=plan(version=1, enabled=False)).status_code == 200
    assert report(admin, district).status_code == 404


def test_chat_access_and_photo_permission(client, admin, db):
    district = setup(db)
    db.commit()
    assert admin.put(f'/api/photo-routes/{district}', json=plan()).status_code == 200
    user = db.scalar(select(User).where(User.login == 'operator'))
    user.allowed_chat_ids = [2]
    user.permissions = ['photos_view']
    db.commit()
    client.post('/api/auth/login', json={"login": "operator", "password": "test-password-123"})
    assert client.get('/api/photo-routes').json() == {"plans": [], "chats": [], "territories": []}
    assert report(client, district).status_code == 404
    user.allowed_chat_ids = [1]
    db.commit()
    catalogue = client.get('/api/photo-routes').json()
    assert len(catalogue['plans']) == 1
    assert catalogue['chats'] == [{'id': 1, 'name': 'Выбранный'}]
    assert len(catalogue['territories']) == 1
    assert report(client, district).status_code == 200
    user.permissions = []
    db.commit()
    assert report(client, district).status_code == 403


def test_date_range_unions_coverage_without_connecting_days(admin, db):
    district = setup(db)
    add_photo(db, 1)
    add_photo(db, 2, 72.6005)
    add_photo(db, 3, 72.601, photo_date=date(2026, 11, 3))
    db.commit()
    admin.put(f'/api/photo-routes/{district}', json=plan())
    assert report(admin, district, date_to='2026-11-03').json()['remaining_percent'] == 50
    assert report(admin, district, date_from='2026-11-03', date_to='2026-11-03').json()['remaining_percent'] == 100


def test_unknown_time_does_not_bridge_observations(admin, db):
    district = setup(db)
    add_photo(db, 1)
    add_photo(db, 2, 72.7, photo_time=None)
    add_photo(db, 3, 72.601)
    db.commit()
    admin.put(f'/api/photo-routes/{district}', json=plan())
    result = report(admin, district).json()
    assert result['remaining_percent'] == 100
    assert result['unknown_time'] == 1
