from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.appeal_sharing import card_font, card_lines, preview_card, share_links
from app.appeals_public import app
from app.config import settings
from app.domain import now
from app.models import AppealPhoto, CitizenAppeal, Organization
from app.organization_registry import bootstrap


def test_share_links_contain_only_the_url_without_a_prepared_message():
    url = "https://signal.example/a/123"
    links = dict(share_links(url))
    assert parse_qs(urlsplit(links["MAX"]).query) == {"text": [url]}
    assert parse_qs(urlsplit(links["Telegram"]).query) == {"url": [url]}
    assert parse_qs(urlsplit(links["ВКонтакте"]).query) == {"url": [url]}


def test_preview_handles_long_addresses_and_is_a_complete_social_card():
    image = preview_card({"city": "Очень длинное название города " * 10, "address": "Адрес без пробелов" * 40,
                          "status": "ASSIGNED", "number": "ОБ-000123"})
    with Image.open(BytesIO(image)) as card:
        assert card.format == "JPEG" and card.size == (1200, 630)
        assert card.getpixel((0, 0)) == (246, 248, 245)


def test_card_wraps_ordinary_words_whole():
    draw = ImageDraw.Draw(Image.new("RGB", (1200, 630)))
    font = card_font(23)
    lines = card_lines(draw, "Просим убрать территорию", font, draw.textlength("Просим убрать", font=font) + 1, 3)
    assert lines == ["Просим убрать", "территорию"]


@pytest.fixture
def shared(db, users, monkeypatch):
    organization = bootstrap("admin", "Организация", "sharing")
    monkeypatch.setenv("ORGANIZATIONS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_APPEALS_ORIGIN", "https://signal.example")
    settings.cache_clear()
    appeal = CitizenAppeal(organization_id=str(organization), organization_name="Организация", city="Нефтеюганск",
                           address='11 мкр, дом 12 " у входа', place="Во дворе", category="BIN_EMPTYING",
                           description='<script>alert("xss")</script> Урна переполнена',
                           contact="private-contact@example.org", owner_note="private-admin-note", photo_count=1,
                           status="NEW", is_public=True)
    db.add(appeal)
    db.flush()
    image = BytesIO()
    Image.new("RGB", (640, 480), "#678c58").save(image, "JPEG")
    photo = AppealPhoto(id=str(uuid4()), appeal_id=appeal.id, position=0, original=image.getvalue(),
                        stamped=image.getvalue(), preview=image.getvalue(), width=640, height=480,
                        captured_at=now(), position_at=now(), latitude=61.1, longitude=72.6, accuracy=10)
    db.add(photo)
    db.commit()
    return appeal


@pytest.mark.integration
def test_public_link_has_server_rendered_metadata_photo_and_no_private_fields(shared):
    with TestClient(app) as citizen:
        page = citizen.get(f"/a/{shared.id}", headers={"Host": "untrusted-host.example"})
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert 'property="og:image"' in page.text and 'property="og:title"' in page.text
        assert f'https://signal.example/a/{shared.id}/card.jpg' in page.text
        assert "private-" not in page.text and "untrusted-host" not in page.text
        assert '<script>alert' not in page.text and '&lt;script&gt;alert' in page.text
        assert "Поделиться в MAX" in page.text and "Ответ организации" not in page.text
        card = citizen.get(f"/a/{shared.id}/card.jpg")
        assert card.status_code == 200 and card.headers["content-type"] == "image/jpeg"
        assert "no-store" in card.headers["cache-control"]
        with Image.open(BytesIO(card.content)) as image:
            assert image.size == (1200, 630)
        detail = citizen.get(f"/api/public/appeals/wall/{shared.id}").json()
        assert detail["share_url"] == f"https://signal.example/a/{shared.id}"


@pytest.mark.integration
@pytest.mark.parametrize("hidden", ["private", "spam", "paused"])
def test_hidden_appeals_never_have_a_public_page_or_preview(shared, db, hidden):
    if hidden == "private":
        shared.is_public = False
    elif hidden == "spam":
        shared.status = "SPAM"
    else:
        db.get(Organization, shared.organization_id).status = "PAUSED"
    db.commit()
    with TestClient(app) as citizen:
        for path in (f"/a/{shared.id}", f"/a/{shared.id}/card.jpg", "/a/999999999"):
            response = citizen.get(path)
            assert response.status_code == 404
            assert "Урна" not in response.text and "private-" not in response.text


@pytest.mark.integration
def test_public_link_shows_only_a_published_response_and_current_status(shared, db):
    shared.public_response = "Это пока внутренний черновик ответа"
    db.commit()
    with TestClient(app) as citizen:
        assert shared.public_response not in citizen.get(f"/a/{shared.id}").text
        shared.status = "RESOLVED"
        shared.public_response = "Урну очистили"
        shared.resolved_at = now()
        db.commit()
        response = citizen.get(f"/a/{shared.id}")
        assert "Урну очистили" in response.text and "Закрыто" in response.text
