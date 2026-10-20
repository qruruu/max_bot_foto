import hashlib
import runpy
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from test_chat_access import AccessSession, actor
from test_chat_access import access_api as access_api

from app.disk_folders import (
    OWNER_FILE,
    claim_folders,
    company_roots,
    current_disk_roots,
    environment_roots,
    roots_for_photo,
)
from app.domain import audit, storage_path
from app.exchange import exchange_root
from app.integrations import OriginalMissing
from app.media import media_path
from app.models import Audit, DiskFolderSettings, ExchangeState, Photo
from app.processing import _synchronize


class CompanyDisk:
    def __init__(self):
        self.dirs = set()
        self.files = {}
        self.uploaded = []
        self.fail_at = None

    def metadata(self, path):
        if path in self.dirs:
            return {'type':'dir'}
        if path in self.files:
            return {'type':'file','sha256':hashlib.sha256(self.files[path]).hexdigest()}
        return None

    def matches(self, path, digest):
        meta = self.metadata(path)
        if not meta:
            return False
        if meta.get('sha256') != digest:
            raise RuntimeError('YANDEX_DESTINATION_CONFLICT')
        return True

    def upload(self, source, target, digest):
        if self.fail_at == len(self.uploaded)+1:
            raise RuntimeError('temporary outage with secret URL')
        if self.metadata(target):
            self.matches(target,digest)
            return
        content = source.read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
        self.dirs.add(target.rsplit('/',1)[0])
        self.files[target] = content
        self.uploaded.append(target)

    def move(self, source, target, digest):
        if self.matches(target,digest):
            return
        if not self.matches(source,digest):
            raise OriginalMissing('ORIGINAL_MISSING')
        self.files[target] = self.files.pop(source)


@pytest.fixture
def folders_api(access_api,monkeypatch):
    client, engine = access_api
    with AccessSession(engine) as db:
        state = db.get(ExchangeState, 1)
        state.instance_id = '11111111-1111-4111-8111-111111111111'
        state.intake_cohort = 'test'
        db.commit()
    disk = CompanyDisk()
    monkeypatch.setattr('app.disk_folders.YandexDisk',lambda: disk)
    monkeypatch.setattr('app.exchange_housekeeping.publisher_lock',lambda: nullcontext())
    monkeypatch.setattr('app.processing.storage_lock',lambda **kwargs: nullcontext())
    actor(client,1)
    return client,engine,disk


def save(client,name='КОМПАНИЯ_А',version=1):
    return client.put('/api/storage-folders',json={'photo_root':name,'version':version})


def test_settings_are_admin_only_even_with_exchange_permission(folders_api):
    client, _, disk = folders_api
    actor(client,2)
    assert client.get('/api/storage-folders').status_code == 403
    assert save(client).status_code == 403
    assert not disk.uploaded


def test_changes_are_persisted_for_every_process_and_audited_without_moving_old_data(folders_api):
    client, engine, disk = folders_api
    before = client.get('/api/storage-folders').json()
    assert before == {'version':1,**asdict(environment_roots())}
    with AccessSession(engine) as db:
        photo = db.get(Photo,10)
        photo.yandex_disk_path = storage_path(photo,None)
        original_path = photo.yandex_disk_path
        db.commit()
    result = save(client)
    assert result.status_code == 200, result.text
    assert result.json() == {'version':2,**asdict(company_roots('КОМПАНИЯ_А'))}
    assert len(disk.uploaded) == 4 and all(path.endswith(OWNER_FILE) for path in disk.uploaded)
    with AccessSession(engine) as db:
        assert current_disk_roots(db) == company_roots('КОМПАНИЯ_А')
        assert db.get(DiskFolderSettings,1).folder_sets == [asdict(environment_roots()),asdict(company_roots('КОМПАНИЯ_А'))]
        assert db.get(Photo,10).yandex_disk_path == original_path
        entry = db.scalar(select(Audit).where(Audit.action=='DISK_FOLDERS_CHANGED'))
        assert entry.old_value == before and entry.new_value == result.json()
        state = db.get(ExchangeState,1)
        assert exchange_root(state,'production',current_disk_roots(db)).startswith('disk:/КОМПАНИЯ_А_ARM_EXCHANGE/production/')
    assert client.get('/api/storage-folders').json() == result.json()


@pytest.mark.parametrize('name',['','   ','.','..','a/b','a\\b','a:b','a\nb','a"b','x'*101])
def test_invalid_names_never_touch_disk(folders_api,name):
    client, _, disk = folders_api
    assert save(client,name).status_code == 422
    assert not disk.uploaded


def test_stale_updates_and_reusing_any_historical_root_are_rejected(folders_api):
    client, _, disk = folders_api
    assert save(client).status_code == 200
    assert save(client,'КОМПАНИЯ_Б',1).status_code == 409
    assert save(client,environment_roots().photo_root,2).status_code == 409
    assert save(client,environment_roots().training_root,2).status_code == 409
    assert save(client,'КОМПАНИЯ_Б',2).status_code == 200
    assert save(client,'компания_а',3).status_code == 409
    assert len(disk.uploaded) == 8


def test_existing_unowned_folder_blocks_the_entire_change_before_creating_anything(folders_api):
    client, _, disk = folders_api
    disk.dirs.add('disk:/КОМПАНИЯ_А_ARM_EXCHANGE')
    result = save(client)
    assert result.status_code == 409
    assert not disk.uploaded
    assert client.get('/api/storage-folders').json()['version'] == 1


def test_two_companies_cannot_claim_the_same_folders():
    disk = CompanyDisk()
    roots = company_roots('Общая папка')
    claim_folders(disk,roots,'first-instance')
    before = dict(disk.files)
    with pytest.raises(RuntimeError,match='YANDEX_DESTINATION_CONFLICT'):
        claim_folders(disk,roots,'second-instance')
    assert disk.files == before
    claim_folders(disk,company_roots('Другая компания'),'second-instance')
    assert len(disk.files) == 8


def test_partial_remote_setup_is_resumable_and_does_not_activate_half_created_settings(folders_api):
    client, _, disk = folders_api
    disk.fail_at = 3
    response = save(client)
    assert response.status_code == 503 and 'secret' not in response.text
    assert client.get('/api/storage-folders').json()['version'] == 1
    disk.fail_at = None
    assert save(client).status_code == 200
    assert len(disk.files) == 4


def test_edits_and_spam_transitions_keep_old_photos_in_their_original_company_archive(folders_api):
    client, engine, disk = folders_api
    content = b'old-original'
    with AccessSession(engine) as db:
        photo = db.get(Photo,10)
        photo.sha256 = hashlib.sha256(content).hexdigest()
        photo.yandex_disk_path = storage_path(photo,None)
        disk.files[photo.yandex_disk_path] = content
        db.commit()
    assert save(client).status_code == 200
    with AccessSession(engine) as db:
        photo = db.get(Photo,10)
        photo.work_type = 'SWEEPING'
        _synchronize(db,photo,disk)
        assert photo.yandex_disk_path.startswith('disk:/'+environment_roots().photo_root+'/')
        photo.is_spam = True
        _synchronize(db,photo,disk)
        assert photo.yandex_disk_path.startswith('disk:/'+environment_roots().spam_root+'/production/')
        photo.is_spam = False
        _synchronize(db,photo,disk)
        assert photo.yandex_disk_path.startswith('disk:/'+environment_roots().photo_root+'/')
        assert disk.files[photo.yandex_disk_path] == content


def test_new_uploads_use_the_new_company_folders(folders_api):
    client, engine, disk = folders_api
    assert save(client).status_code == 200
    for id,cohort,spam,root in [(10,'production',False,'КОМПАНИЯ_А'),(20,'test',False,'КОМПАНИЯ_А_TRAINING'),
                                (30,'production',True,'КОМПАНИЯ_А_SPAM')]:
        content = f'new-original-{id}'.encode()
        with AccessSession(engine) as db:
            photo = db.get(Photo,id)
            photo.cohort,photo.is_spam = cohort,spam
            photo.sha256 = hashlib.sha256(content).hexdigest()
            path = media_path(id)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
            _synchronize(db,photo,disk)
            assert photo.yandex_disk_path.startswith(f'disk:/{root}/')
            assert disk.files[photo.yandex_disk_path] == content
            assert not path.exists()


def test_interrupted_old_upload_resumes_after_company_folder_change(folders_api):
    client, engine, disk = folders_api
    content = b'interrupted-original'
    with AccessSession(engine) as db:
        photo = db.get(Photo,10)
        photo.sha256 = hashlib.sha256(content).hexdigest()
        target = storage_path(photo,None)
        disk.files[target] = content
        audit(db,None,'STORAGE_TRANSFER_PLANNED','photo',10,{'path':None},{'path':target,'sha256':photo.sha256})
        db.commit()
    assert save(client).status_code == 200
    with AccessSession(engine) as db:
        photo = db.get(Photo,10)
        assert roots_for_photo(db,photo) == environment_roots()
        _synchronize(db,photo,disk)
        assert photo.yandex_disk_path == target and disk.files[target] == content


def test_new_migration_only_adds_empty_settings_without_changing_the_archive():
    migration = runpy.run_path(str(Path(__file__).parents[1]/'alembic/versions/0026_disk_folder_settings.py'))
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE photos (id INTEGER PRIMARY KEY, path TEXT)'))
        connection.execute(text("INSERT INTO photos VALUES (1,'disk:/MAX_PHOTOS/old.jpg')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration['upgrade']()
        assert connection.execute(text('SELECT version,folder_sets FROM disk_folder_settings')).first() == (1,'[]')
        assert connection.execute(text('SELECT path FROM photos')).scalar() == 'disk:/MAX_PHOTOS/old.jpg'
    with pytest.raises(RuntimeError,match='preserved'):
        migration['downgrade']()
    engine.dispose()


def test_prepared_exchange_snapshot_keeps_its_old_root_after_settings_change(db):
    from app.exchange import prepare
    from app.models import Publication
    original = Publication(cohort='production',status='PENDING')
    db.add(original)
    db.commit()
    prepare(original.id)
    db.refresh(original)
    old_payload = original.payload
    db.get(DiskFolderSettings,1).folder_sets = [asdict(environment_roots()),asdict(company_roots('ДРУГАЯ_КОМПАНИЯ'))]
    db.commit()
    prepare(original.id)
    db.refresh(original)
    assert original.payload == old_payload
    following = Publication(cohort='production',status='PENDING')
    db.add(following)
    db.commit()
    prepare(following.id)
    db.refresh(following)
    assert following.payload['root'].startswith('disk:/ДРУГАЯ_КОМПАНИЯ_ARM_EXCHANGE/')


def test_real_database_admin_change_is_used_by_the_storage_worker(admin,db,monkeypatch):
    from app.processing import synchronize
    from tests.test_integration import intake_photo, setup_chat
    disk = CompanyDisk()
    monkeypatch.setattr('app.disk_folders.YandexDisk',lambda: disk)
    response = admin.put('/api/storage-folders',json={'photo_root':'НОВАЯ_КОМПАНИЯ','version':1})
    assert response.status_code == 200, response.text
    setup_chat(db)
    photo = intake_photo(db)
    content = b'worker-original-bytes'
    photo.sha256 = hashlib.sha256(content).hexdigest()
    db.commit()
    file = media_path(photo.id)
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_bytes(content)
    synchronize(db,photo,disk)
    assert photo.yandex_disk_path.startswith('disk:/НОВАЯ_КОМПАНИЯ_TRAINING/')
    assert disk.files[photo.yandex_disk_path] == content
