from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.auth import digest, router
from app.avatars import MAX_AVATAR_BYTES, normalize_avatar
from app.db import get_db
from app.domain import now
from app.models import LoginSession, User


def picture(fmt="PNG", color="red", size=(160, 80), **save_options):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=fmt, **save_options)
    return output.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "GIF"])
def test_avatars_are_normalized_to_small_square_jpegs(fmt):
    data = normalize_avatar(picture(fmt))
    with Image.open(BytesIO(data)) as image:
        assert image.size == (256, 256)
        assert image.format == "JPEG"
        assert len(data) < 100_000


def test_avatar_respects_exif_orientation_and_removes_metadata():
    source = Image.new("RGB", (200, 100), "red")
    source.paste("blue", (100, 0, 200, 100))
    exif = Image.Exif()
    exif[274], exif[315] = 6, "Private camera metadata"
    output = BytesIO()
    source.save(output, format="JPEG", exif=exif)
    with Image.open(BytesIO(normalize_avatar(output.getvalue()))) as avatar:
        assert not avatar.getexif()
        assert avatar.getpixel((128, 32))[0] > 200
        assert avatar.getpixel((128, 224))[2] > 200


def test_transparent_avatar_has_a_light_background():
    output = BytesIO()
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(output, format="PNG")
    with Image.open(BytesIO(normalize_avatar(output.getvalue()))) as image:
        assert image.getpixel((128, 128)) == (255, 255, 255)


@pytest.mark.parametrize("data", [b"", b"not an image", b'<svg xmlns="http://www.w3.org/2000/svg"/>'])
def test_non_images_and_svg_are_rejected(data):
    with pytest.raises(ValueError, match="прочитать фотографию"):
        normalize_avatar(data)


def test_avatar_checks_encoded_size_and_pixel_count(monkeypatch):
    with pytest.raises(ValueError, match="5 МБ"):
        normalize_avatar(b"0" * (MAX_AVATAR_BYTES + 1))
    monkeypatch.setattr("app.avatars.MAX_AVATAR_PIXELS", 100)
    with pytest.raises(ValueError, match="мегапикселей"):
        normalize_avatar(picture(size=(11, 10)))


@pytest.fixture
def avatar_api():
    # Keep the actual session, CSRF and origin checks; only replace database IO.
    users = {
        1: User(id=1, login="operator", name="Operator", role="OPERATOR", active=True, permissions=[]),
        2: User(id=2, login="admin", name="Admin", role="ADMIN_OPERATOR", active=True, permissions=[]),
    }
    sessions = {
        digest(token): LoginSession(
            token_hash=digest(token), csrf_hash=digest("test-csrf"), user_id=user_id,
            expires_at=now() + timedelta(hours=1), last_seen_at=now(),
        )
        for token, user_id in [("operator-session", 1), ("admin-session", 2)]
    }
    logs = []
    db = SimpleNamespace(
        info={}, get=lambda model, key: (users if model is User else sessions).get(key),
        add=logs.append, commit=lambda: None,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.cookies.set("session", "operator-session")
        client.headers["X-CSRF-Token"] = "test-csrf"
        yield client, users, logs


def test_upload_replace_and_remove_own_avatar_without_function_permissions(avatar_api):
    client, users, logs = avatar_api
    assert client.get("/api/auth/me").json()["avatar_url"] is None
    uploaded = client.put("/api/auth/avatar", content=picture(), headers={"Content-Type": "image/png"})
    assert uploaded.status_code == 200
    url = uploaded.json()["avatar_url"]
    response = client.get(url)
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == users[1].avatar_image
    assert "avatar_image" not in client.get("/api/auth/me").json()
    replaced = client.put("/api/auth/avatar", content=picture(color="blue"))
    assert replaced.status_code == 200 and replaced.json()["avatar_url"] != url
    assert client.get("/api/auth/me").json()["avatar_url"] == replaced.json()["avatar_url"]
    removed = client.delete("/api/auth/avatar")
    assert removed.status_code == 200 and removed.json()["avatar_url"] is None
    assert client.get(url).status_code == 404
    assert [entry.action for entry in logs] == ["USER_AVATAR_UPDATED", "USER_AVATAR_UPDATED", "USER_AVATAR_REMOVED"]
    assert all(set(entry.new_value) == {"has_avatar"} for entry in logs)


def test_avatar_is_private_and_updates_only_the_current_account(avatar_api):
    client, users, _ = avatar_api
    own = client.put("/api/auth/avatar", content=picture()).json()["avatar_url"]
    before = users[1].avatar_image
    client.cookies.set("session", "admin-session")
    assert client.get(own).status_code == 404
    admin = client.put("/api/auth/avatar", content=picture(color="blue")).json()["avatar_url"]
    assert client.get(admin).status_code == 200
    assert users[1].avatar_image == before
    client.delete("/api/auth/avatar")
    assert users[1].avatar_image == before and users[2].avatar_image is None


def test_avatar_requires_authentication_csrf_and_same_origin(avatar_api):
    client, users, _ = avatar_api
    client.headers.pop("X-CSRF-Token")
    assert client.put("/api/auth/avatar", content=picture()).status_code == 403
    assert client.delete("/api/auth/avatar").status_code == 403
    client.headers["X-CSRF-Token"] = "test-csrf"
    assert client.put("/api/auth/avatar", content=picture(), headers={"Origin": "https://foreign.invalid"}).status_code == 403
    client.cookies.clear()
    assert client.get("/api/auth/avatar/1").status_code == 401
    assert client.put("/api/auth/avatar", content=picture()).status_code == 401
    assert client.delete("/api/auth/avatar").status_code == 401
    assert users[1].avatar_image is None


def test_invalid_or_oversized_upload_keeps_existing_avatar(avatar_api):
    client, users, logs = avatar_api
    client.put("/api/auth/avatar", content=picture())
    before = users[1].avatar_image
    assert client.put("/api/auth/avatar", content=b"invalid", headers={"Content-Type": "image/png"}).status_code == 422
    assert client.put("/api/auth/avatar", content=b"0" * (MAX_AVATAR_BYTES + 1)).status_code == 413
    assert users[1].avatar_image == before
    assert len(logs) == 1
