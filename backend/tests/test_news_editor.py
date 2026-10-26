"""Real platform sessions, isolated company databases and durable global news lifecycle."""

from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_organizations import companies as companies

from app.api import app
from app.db import engine
from app.models import NewsArticle, NewsAsset, NewsRead, NewsRevision, User
from app.news import load_posts
from app.news_import import import_posts
from app.organization_context import organization_scope
from app.organization_registry import control_session

BASE = "/api/platform/news"


def image_bytes(format="PNG"):
    image = Image.new("RGB", (640, 360), "#237366")
    buffer = BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


def make(owner):
    response = owner.post(BASE, json={"template": "update"})
    assert response.status_code == 201, response.text
    return response.json()


def save(owner, post, *, title="Проверка дня без повторной работы", asset=None):
    snapshot = {
        **post["draft"],
        "title": title,
        "summary": "Проверьте только новые фотографии.",
        "category": "Обновление",
    }
    if asset:
        snapshot["document"]["content"].append(
            {
                "type": "image",
                "attrs": {
                    "asset_id": asset["id"],
                    "alt": "Пример проверки на тестовых данных",
                    "caption": "Откройте выбранную дату.",
                },
            }
        )
        snapshot["cover_id"] = asset["id"]
    response = owner.put(BASE + "/" + post["id"], json={**snapshot, "expected_version": post["version"]})
    assert response.status_code == 200, response.text
    return response.json()


def action(owner, post, kind):
    response = owner.post(BASE + "/" + post["id"] + "/" + kind, json={"expected_version": post["version"]})
    assert response.status_code == 200, response.text
    return response.json()


def allow_news(scopes):
    for scope in scopes:
        with organization_scope(scope), Session(engine()) as db:
            db.scalar(select(User).where(User.login == "same-login")).permissions = ["news_view"]
            db.commit()


@pytest.mark.integration
def test_news_notifications_stay_with_the_account_across_organizations_and_publications(companies):
    owner, scopes, clients = companies
    allow_news(scopes)
    post = action(owner, save(owner, make(owner)), 'publish')
    paths = [scope.prefix + '/api/news' for scope in scopes]
    for path, client in zip(paths, clients, strict=True):
        assert client.get(path + '/unread').json() == {'unread': 1}
        assert client.get(path + '/' + post['slug']).json()['unread']
    assert clients[0].post(paths[0] + '/' + post['slug'] + '/read').status_code == 200
    assert clients[0].get(paths[0] + '/unread').json() == {'unread': 0}
    assert clients[1].get(paths[1] + '/unread').json() == {'unread': 1}
    with TestClient(app) as another_device:
        another_device.cookies.update(clients[0].cookies)
        assert another_device.get(paths[0] + '/unread').json() == {'unread': 0}
    # A verified owner has one global identity, even when using a tenant's local actor.
    assert owner.get(paths[0] + '/unread').json() == {'unread': 1}
    assert owner.post(paths[1] + '/' + post['slug'] + '/read').status_code == 200
    assert owner.get(paths[1] + '/unread').json() == {'unread': 0}
    assert owner.get(paths[0] + '/unread').json() == {'unread': 0}
    assert clients[1].get(paths[1] + '/unread').json() == {'unread': 1}
    for scope in scopes:
        with organization_scope(scope), Session(engine()) as db:
            assert db.scalar(select(func.count()).select_from(NewsRead)) == 0
    with control_session() as db:
        assert db.scalar(select(func.count()).select_from(NewsRead)) == 2
    draft = save(owner, make(owner), title='Следующая новость')
    assert clients[0].get(paths[0] + '/unread').json() == {'unread': 0}
    draft = action(owner, draft, 'publish')
    assert clients[0].get(paths[0] + '/unread').json() == {'unread': 1}
    assert clients[1].get(paths[1] + '/unread').json() == {'unread': 2}
    action(owner, draft, 'unpublish')
    assert clients[0].get(paths[0] + '/unread').json() == {'unread': 0}
    assert clients[1].get(paths[1] + '/unread').json() == {'unread': 1}
    action(owner, post, 'trash')
    assert clients[1].get(paths[1] + '/unread').json() == {'unread': 0}


@pytest.mark.integration
def test_news_full_lifecycle_snapshots_history_and_images_are_durable(companies):
    owner, scopes, clients = companies
    allow_news(scopes)
    path = scopes[0].prefix + "/api/news"
    post = make(owner)
    assert clients[0].get(path).json() == []
    uploaded = owner.post(BASE + "/assets", content=image_bytes(), headers={"content-type": "image/png"})
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    assert owner.get(asset["src"]).headers["content-type"] == "image/webp"
    private = scopes[0].prefix + "/api/news/assets/" + asset["id"]
    assert clients[0].get(private).status_code == 404
    post = save(owner, post, asset=asset)
    preview = owner.post(BASE + "/" + post["id"] + "/preview", json={"expected_version": post["version"]})
    assert preview.status_code == 200
    assert preview.json()["document"]["content"][-1]["attrs"]["src"] == asset["src"]
    post = action(owner, post, "publish")
    slug = post["slug"]
    assert len(clients[0].get(path).json()) == 1
    assert clients[0].get(private).status_code == 200
    for scope, client in zip(scopes, clients, strict=True):
        article = client.get(scope.prefix + "/api/news/" + slug).json()
        assert article["title"] == post["published"]["title"]
        assert article["document"]["content"][-1]["attrs"]["src"].startswith(scope.prefix + "/api/")
        with organization_scope(scope), Session(engine()) as db:
            assert db.scalar(select(func.count()).select_from(NewsArticle)) == 0
    old_title = post["published"]["title"]
    post = save(owner, post, title="Исправленный заголовок")
    assert clients[0].get(path + "/" + slug).json()["title"] == old_title
    versions = owner.get(BASE + "/" + post["id"] + "/revisions").json()
    original = next(r for r in versions if r["action"] == "PUBLISH")
    post = action(owner, post, "publish")
    assert clients[0].get(path + "/" + slug).json()["title"] == "Исправленный заголовок"
    # Restoring an old snapshot changes the draft; it does not republish the previous edition.
    restored = owner.post(
        BASE + "/" + post["id"] + "/revisions/" + original["id"] + "/restore",
        json={"expected_version": post["version"]},
    )
    assert restored.status_code == 200
    post = restored.json()
    assert post["draft"]["title"] == old_title
    assert clients[0].get(path + "/" + slug).json()["title"] == "Исправленный заголовок"
    post = action(owner, post, "unpublish")
    assert clients[0].get(path + "/" + slug).status_code == 404
    assert clients[0].get(private).status_code == 404
    post = action(owner, post, "publish")
    post = action(owner, post, "trash")
    assert clients[0].get(path + "/" + slug).status_code == 404
    assert clients[0].get(private).status_code == 404
    assert owner.get(BASE + "?state=trash").json()[0]["id"] == post["id"]
    post = action(owner, post, "restore")
    assert not post["published"] and not post["deleted_at"]
    assert clients[0].get(path + "/" + slug).status_code == 404
    post = action(owner, post, "publish")
    # Re-open database connections and the application, simulating a process restart.
    engine().dispose()
    with control_session() as db:
        assert db.get(NewsArticle, post["id"]).published["title"] == old_title
        assert db.get(NewsAsset, asset["id"]).content
        assert (
            db.scalar(
                select(func.count()).select_from(NewsRevision).where(NewsRevision.article_id == post["id"])
            )
            >= 10
        )
    assert clients[0].get(private).status_code == 200


@pytest.mark.integration
def test_only_owner_can_author_global_news_and_csrf_is_required(companies):
    owner, scopes, clients = companies
    post = make(owner)
    asset = owner.post(BASE + "/assets", content=image_bytes(), headers={"content-type": "image/png"}).json()
    paths = [BASE, BASE + "/" + post["id"], BASE + "/" + post["id"] + "/revisions", asset["src"]]
    with TestClient(app) as anonymous:
        for path in paths:
            assert anonymous.get(path).status_code == 401
        assert anonymous.post(BASE, json={}).status_code == 401
    for scope, client in zip(scopes, clients, strict=True):
        with organization_scope(scope), Session(engine()) as db:
            db.scalar(select(User).where(User.login == "same-login")).role = "ADMIN_OPERATOR"
            db.commit()
        for path in paths:
            assert client.get(path).status_code in {401, 403}
            assert client.get(scope.prefix + path).status_code == 404
        assert client.post(BASE, json={}).status_code in {401, 403}
        assert client.get(scope.prefix + "/api/news/assets/" + asset["id"]).status_code == 404
    assert owner.post(BASE, json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert owner.post(BASE, json={}, headers={"Origin": "https://untrusted.test"}).status_code == 403
    assert (
        owner.post(
            BASE + "/assets",
            content=image_bytes(),
            headers={"content-type": "image/png", "X-CSRF-Token": "wrong"},
        ).status_code
        == 403
    )
    assert owner.get(scopes[0].prefix + "/api/photos").status_code == 200


@pytest.mark.integration
def test_concurrent_edits_actions_and_revision_restore_never_overwrite_newer_versions(companies):
    owner, _, _ = companies
    post = make(owner)
    updated = save(owner, post)
    assert updated["version"] == post["version"] + 1
    assert (
        owner.put(
            BASE + "/" + post["id"], json={**post["draft"], "expected_version": post["version"]}
        ).status_code
        == 409
    )
    for kind in ["publish", "preview", "unpublish", "trash", "restore"]:
        response = owner.post(
            BASE + "/" + post["id"] + "/" + kind, json={"expected_version": post["version"]}
        )
        assert response.status_code == 409 and response.json()["detail"]["code"] == "NEWS_CONFLICT"
    revision = owner.get(BASE + "/" + post["id"] + "/revisions").json()[-1]
    assert (
        owner.post(
            BASE + "/" + post["id"] + "/revisions/" + revision["id"] + "/restore",
            json={"expected_version": post["version"]},
        ).status_code
        == 409
    )
    other = make(owner)
    assert (
        owner.post(
            BASE + "/" + other["id"] + "/revisions/" + revision["id"] + "/restore",
            json={"expected_version": other["version"]},
        ).status_code
        == 404
    )
    assert owner.get(BASE + "/" + post["id"]).json()["draft"] == updated["draft"]
    # Identical autosaves neither bump versions nor manufacture history entries.
    unchanged = save(owner, updated)
    assert unchanged["version"] == updated["version"]


@pytest.mark.integration
def test_import_preserves_all_legacy_content_and_never_resurrects_trash_or_unpublished_posts(companies):
    owner, scopes, _ = companies
    with engine().begin() as connection:
        import_posts(connection)
        import_posts(connection)
    posts = owner.get(BASE).json()
    assert len(posts) == len(load_posts())
    for legacy in load_posts():
        item = next(p for p in posts if p["slug"] == legacy.slug)
        response = owner.get(scopes[0].prefix + "/api/news/" + legacy.slug)
        assert response.status_code == 200, response.text
        imported = response.json()
        assert imported["publishedAt"] == legacy.publishedAt.isoformat()
        assert (imported["title"], imported["summary"], imported["category"]) == (
            legacy.title,
            legacy.summary,
            legacy.category,
        )
        assert len(imported["sections"]) == len(legacy.sections)
        for old, new in zip(legacy.sections, imported["sections"], strict=True):
            assert (
                old.title == new["title"]
                and old.paragraphs == new["paragraphs"]
                and old.steps == new["steps"]
            )
            for screenshot in old.screenshots:
                picture = owner.get(
                    scopes[0].prefix + "/api/news/" + legacy.slug + "/screenshots/" + screenshot.file
                )
                assert picture.status_code == 200 and "no-store" in picture.headers["cache-control"]
        assert owner.get(BASE + "/" + item["id"] + "/revisions").json()[0]["action"] == "IMPORT"
    post = owner.get(BASE + "/" + posts[0]["id"]).json()
    post = action(owner, post, "trash")
    second = owner.get(BASE + "/" + posts[1]["id"]).json()
    second = action(owner, second, "unpublish")
    with engine().begin() as connection:
        import_posts(connection)
    assert owner.get(BASE + "/" + post["id"]).json()["deleted_at"]
    assert not owner.get(BASE + "/" + second["id"]).json()["published"]
    assert len(owner.get(BASE).json()) == len(load_posts()) - 1


@pytest.mark.integration
def test_assets_reused_across_posts_and_revisions_survive_replacement_and_trash(companies):
    owner, scopes, _ = companies
    asset = owner.post(BASE + "/assets", content=image_bytes(), headers={"content-type": "image/png"}).json()
    first = action(owner, save(owner, make(owner), asset=asset), "publish")
    second = action(owner, save(owner, make(owner), asset=asset), "publish")
    first = action(owner, first, "trash")
    path = scopes[0].prefix + "/api/news/assets/" + asset["id"]
    assert owner.get(path).status_code == 200
    second = save(
        owner,
        {
            **second,
            "draft": {
                **second["draft"],
                "cover_id": None,
                "document": {
                    "type": "doc",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Новый текст"}]}],
                },
            },
        },
    )
    # Replacing a draft image does not remove the last published image.
    assert owner.get(path).status_code == 200
    second = action(owner, second, "publish")
    assert owner.get(path).status_code == 404
    assert owner.get(asset["src"]).status_code == 200
    revisions = owner.get(BASE + "/" + second["id"] + "/revisions").json()
    earlier = next(r for r in revisions if r["action"] == "PUBLISH" and r["snapshot"]["cover_id"])
    result = owner.post(
        BASE + "/" + second["id"] + "/revisions/" + earlier["id"] + "/restore",
        json={"expected_version": second["version"]},
    )
    assert result.status_code == 200
    second = action(owner, result.json(), "publish")
    assert owner.get(path).status_code == 200


@pytest.mark.integration
def test_upload_and_publish_validate_untrusted_content(companies):
    owner, _, _ = companies
    assert (
        owner.post(BASE + "/assets", content=b"<svg/>", headers={"content-type": "image/svg+xml"}).status_code
        == 415
    )
    assert (
        owner.post(BASE + "/assets", content=b"invalid", headers={"content-type": "image/png"}).status_code
        == 422
    )
    assert (
        owner.post(
            BASE + "/assets", content=image_bytes(), headers={"content-type": "image/jpeg"}
        ).status_code
        == 422
    )
    assert (
        owner.post(
            BASE + "/assets", content=b"0" * (8 * 1024 * 1024 + 1), headers={"content-type": "image/png"}
        ).status_code
        == 413
    )
    with Image.new("RGB", (10001, 1)) as wide:
        output = BytesIO()
        wide.save(output, format="PNG")
    assert (
        owner.post(
            BASE + "/assets", content=output.getvalue(), headers={"content-type": "image/png"}
        ).status_code
        == 422
    )
    post = make(owner)
    assert (
        owner.post(
            BASE + "/" + post["id"] + "/publish", json={"expected_version": post["version"]}
        ).status_code
        == 422
    )
    unknown = {**post["draft"], "cover_id": str(uuid4())}
    assert (
        owner.put(BASE + "/" + post["id"], json={**unknown, "expected_version": post["version"]}).status_code
        == 422
    )
    post = save(owner, post)
    asset = owner.post(BASE + "/assets", content=image_bytes(), headers={"content-type": "image/png"}).json()
    bad = deepcopy(post["draft"])
    bad["document"]["content"].append(
        {"type": "image", "attrs": {"asset_id": asset["id"], "alt": "", "caption": ""}}
    )
    response = owner.put(BASE + "/" + post["id"], json={**bad, "expected_version": post["version"]})
    assert response.status_code == 200
    assert (
        owner.post(
            BASE + "/" + post["id"] + "/publish", json={"expected_version": response.json()["version"]}
        ).status_code
        == 422
    )
