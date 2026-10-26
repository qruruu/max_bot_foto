import json
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import JSON, Column, MetaData, Table, select
from sqlalchemy.dialects.postgresql import JSONB
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.api import app
from app.auth import digest
from app.domain import now
from app.models import (
    Audit,
    LoginSession,
    NewsArticle,
    NewsAsset,
    NewsLegacyAsset,
    NewsPublishedAsset,
    NewsRead,
    NewsRevision,
    User,
)
from app.news import CONTENT_DIR, get_news_db, load_posts, news_reader_key
from app.news_import import import_posts
from app.organization_context import OrganizationScope, organization_scope
from app.permissions import DEFAULT_OPERATOR_PERMISSIONS, Permission
from app.schemas import UserCreate


@pytest.fixture
def news_api(access_api):
    client, engine = access_api
    with AccessSession(engine) as db:
        db.get(User,2).permissions = ['photos_view']
        db.get(User,3).permissions = ['news_view']
        db.get(User,1).permissions = []
        db.commit()
    metadata = MetaData()
    for model in (NewsArticle, NewsAsset, NewsRevision, NewsPublishedAsset, NewsLegacyAsset, NewsRead):
        Table(model.__tablename__, metadata, *(Column(c.name, JSON(none_as_null=True) if isinstance(c.type, JSONB) else c.type, primary_key=c.primary_key) for c in model.__table__.columns))
    metadata.create_all(engine)
    with engine.begin() as connection:
        import_posts(connection)
    def news_database():
        with AccessSession(engine, expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_news_db] = news_database
    try:
        yield client, engine
    finally:
        app.dependency_overrides.pop(get_news_db, None)


def test_news_is_opt_in_and_has_no_unrelated_prerequisites(news_api):
    client, _ = news_api
    assert Permission.NEWS_VIEW not in DEFAULT_OPERATOR_PERMISSIONS
    assert Permission.NEWS_VIEW not in UserCreate(login='operator',name='Test',password='test-password-123').permissions
    actor(client,1)
    definition = next(item for item in client.get('/api/meta').json()['permission_catalog'] if item['code']=='news_view')
    assert definition['name'] == 'Просмотр новостей'
    assert definition['requires'] == [] and not definition['default_operator']


@pytest.mark.parametrize('path', [
    '/api/news', '/api/news/unread', '/api/news/2026-10-19-news',
    '/api/news/2026-10-19-news/screenshots/overview.png',
    '/api/news/unknown', '/api/news/unknown/screenshots/overview.png',
])
def test_news_and_screenshots_require_sign_in_and_permission(news_api,path):
    client, _ = news_api
    client.cookies.clear()
    assert client.get(path).status_code == 401
    actor(client,2)
    assert client.get(path).status_code == 403


@pytest.mark.parametrize('user_id', [1,3])
def test_admin_and_explicitly_enabled_operator_can_read_articles_and_images(news_api,user_id):
    client, _ = news_api
    actor(client,user_id)
    response = client.get('/api/news')
    assert response.status_code == 200
    summaries = response.json()
    assert summaries and all('sections' not in summary for summary in summaries)
    for summary in summaries:
        post = client.get('/api/news/'+summary['slug'])
        assert post.status_code == 200
        detail = post.json()
        assert all(detail[key] == value for key,value in summary.items())
        images = [image for section in detail['sections'] for image in section['screenshots']]
        assert images
        for image in images:
            assert image['alt'] and image['caption'] and 'file' not in image
            picture = client.get(image['src'])
            assert picture.status_code == 200 and picture.headers['content-type'].startswith('image/')
            assert 'no-store' in picture.headers['cache-control']
            with Image.open(BytesIO(picture.content)) as decoded:
                decoded.verify()
    if user_id==3:
        # News access does not grant photos, users, or any MAX chat.
        assert client.get('/api/photos').status_code == 403
        assert client.get('/api/users').status_code == 403
        assert client.patch('/api/users/2',json={'permissions':['news_view']}).status_code == 403


def test_admin_can_grant_and_revoke_news_with_audit_and_session_invalidation(news_api):
    client, engine = news_api
    actor(client,1)
    enabled = client.patch('/api/users/2',json={'permissions':['photos_view','news_view']})
    assert enabled.status_code == 200 and enabled.json()['permissions'] == ['photos_view','news_view']
    with AccessSession(engine) as db:
        assert db.scalar(select(LoginSession).where(LoginSession.user_id==2)) is None
        # Simulate the operator's next authenticated sign-in.
        db.add(LoginSession(user_id=2,token_hash=digest('news-enabled'),csrf_hash=digest('csrf'),
                            expires_at=now()+timedelta(hours=1),created_at=now(),last_seen_at=now()))
        db.commit()
    client.cookies.clear()
    client.cookies.set('session','news-enabled')
    assert client.get('/api/news').status_code == 200
    actor(client,1)
    assert client.patch('/api/users/2',json={'permissions':['photos_view']}).status_code == 200
    with AccessSession(engine) as db:
        history = list(db.scalars(select(Audit).where(Audit.action=='USER_UPDATED',Audit.object_id==2).order_by(Audit.id)))
        assert history[-2].new_value['permissions'] == ['photos_view','news_view']
        assert history[-1].new_value['permissions'] == ['photos_view']
    client.cookies.clear()
    client.cookies.set('session','news-enabled')
    assert client.get('/api/news').status_code == 401


def test_unread_news_is_per_account_durable_and_only_read_explicitly(news_api):
    client, engine = news_api
    actor(client, 3)
    posts = client.get('/api/news').json()
    count = len(posts)
    slug = posts[0]['slug']
    assert count > 0 and all(post['unread'] for post in posts)
    assert client.get('/api/news/unread').json() == {'unread': count}
    assert client.get('/api/news/' + slug).json()['unread']
    assert client.get('/api/news/unread').json()['unread'] == count
    for _ in range(2):
        assert client.post('/api/news/' + slug + '/read').json() == {'ok': True}
    assert client.get('/api/news/unread').json()['unread'] == count - 1
    assert not client.get('/api/news/' + slug).json()['unread']
    assert not next(post for post in client.get('/api/news').json() if post['slug'] == slug)['unread']
    with AccessSession(engine) as db:
        assert len(list(db.scalars(select(NewsRead)))) == 1
    actor(client, 1)
    assert client.get('/api/news/unread').json()['unread'] == count
    actor(client, 3)
    assert client.get('/api/news/unread').json()['unread'] == count - 1


def test_unread_news_counts_only_published_live_articles(news_api):
    client, engine = news_api
    actor(client, 3)
    initial = client.get('/api/news/unread').json()['unread']
    with AccessSession(engine) as db:
        snapshot = deepcopy(db.scalar(select(NewsArticle)).draft)
        post = NewsArticle(id=str(uuid4()), slug='new-notification', version=1, draft=snapshot,
                           published=None, author_name='Owner')
        db.add(post)
        db.commit()
        id = post.id
    assert client.get('/api/news/unread').json()['unread'] == initial
    assert client.post('/api/news/new-notification/read').status_code == 404
    with AccessSession(engine) as db:
        post = db.get(NewsArticle, id)
        post.published, post.published_at = snapshot, now()
        db.commit()
    assert client.get('/api/news/unread').json()['unread'] == initial + 1
    with AccessSession(engine) as db:
        db.get(NewsArticle, id).deleted_at = now()
        db.commit()
    assert client.get('/api/news/unread').json()['unread'] == initial
    assert client.post('/api/news/new-notification/read').status_code == 404
    with AccessSession(engine) as db:
        post = db.get(NewsArticle, id)
        post.deleted_at, post.published = None, None
        db.commit()
    assert client.get('/api/news/unread').json()['unread'] == initial


def test_reading_news_requires_permission_sign_in_and_csrf(news_api):
    client, _ = news_api
    actor(client, 3)
    slug = client.get('/api/news').json()[0]['slug']
    path = '/api/news/' + slug + '/read'
    client.cookies.clear()
    assert client.post(path).status_code == 401
    actor(client, 2)
    assert client.post(path).status_code == 403
    actor(client, 3)
    client.headers['X-CSRF-Token'] = 'wrong'
    assert client.post(path).status_code == 403
    client.headers['X-CSRF-Token'] = 'csrf'
    client.headers['Origin'] = 'https://foreign.invalid'
    assert client.post(path).status_code == 403
    client.headers['Origin'] = 'http://testserver'
    assert client.post('/api/news/no-such-article/read').status_code == 404
    assert client.post(path).status_code == 200


def test_news_identity_separates_tenants_and_shares_only_the_verified_owner():
    from types import SimpleNamespace

    user = SimpleNamespace(id=7)
    first = OrganizationScope('first', 'First', 'postgresql://unused', Path('/tmp/first'), 1)
    second = OrganizationScope('second', 'Second', 'postgresql://unused', Path('/tmp/second'), 1)
    with organization_scope(first):
        key = news_reader_key(user)
    with organization_scope(second):
        assert news_reader_key(user) != key
        user._platform_owner, user._platform_user_id = True, 42
        owner_key = news_reader_key(user)
    with organization_scope(None):
        assert news_reader_key(SimpleNamespace(id=42, _platform_owner=True)) == owner_key
        assert news_reader_key(SimpleNamespace(id=7)) != key


def test_unknown_articles_and_undeclared_files_are_not_served(news_api):
    client, _ = news_api
    actor(client,1)
    for path in ['/api/news/missing','/api/news/missing/screenshots/overview.png',
                 '/api/news/2026-10-19-news/screenshots/posts.json',
                 '/api/news/2026-10-19-news/screenshots/missing.png']:
        assert client.get(path).status_code == 404


def test_published_posts_have_real_local_screenshots_and_stable_links():
    posts = load_posts()
    assert len({post.slug for post in posts}) == len(posts)
    for post in posts:
        images = [image for section in post.sections for image in section.screenshots]
        assert images
        for image in images:
            path = CONTENT_DIR/post.slug/image.file
            assert path.is_file()
            with Image.open(path) as decoded:
                assert decoded.width >= 600 and decoded.height >= 300
                assert (image.width,image.height) == decoded.size
                decoded.verify()


def test_new_posts_are_sorted_first_without_changing_existing_slugs(tmp_path,monkeypatch):
    import app.news as news
    template = load_posts()[0].model_dump(mode='json')
    values = [{**template,'slug':'earlier','publishedAt':'2026-10-18'},
              {**template,'slug':'later','publishedAt':'2026-10-20'}, template]
    (tmp_path/'posts.json').write_text(json.dumps(values))
    monkeypatch.setattr(news,'CONTENT_DIR',tmp_path)
    load_posts.cache_clear()
    try:
        assert [post.slug for post in load_posts()] == ['later',template['slug'],'earlier']
    finally:
        load_posts.cache_clear()
