"""Run the real public Signal API against a dedicated, persistent local PostGIS database."""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'signal_flutter/.local'
CONFIG = STATE / 'backend.json'
CONTAINER = 'signal-flutter-local-db'
VOLUME = 'signal_flutter_local_postgres'
DATABASE = 'signal_flutter_local'


def private_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    path.chmod(0o600)


def local_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('Use a loopback HTTP URL for local development')
    return value.rstrip('/')


def configure():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if CONFIG.exists():
        config = json.loads(CONFIG.read_text())
    else:
        config = {'password': secrets.token_hex(32), 'admin_password': secrets.token_urlsafe(24)}
        private_json(CONFIG, config)
    env_file = STATE / 'postgres.env'
    env_file.write_text(f'POSTGRES_DB={DATABASE}\nPOSTGRES_USER=signal_local\nPOSTGRES_PASSWORD={config["password"]}\n')
    env_file.chmod(0o600)
    exists = subprocess.run(['docker', 'container', 'inspect', CONTAINER], capture_output=True).returncode == 0
    if exists:
        subprocess.run(['docker', 'start', CONTAINER], check=True, stdout=subprocess.DEVNULL)
    else:
        subprocess.run(['docker', 'run', '-d', '--name', CONTAINER, '--platform', 'linux/amd64',
                        '--label', 'app=signal-local', '--env-file', str(env_file),
                        '--publish', '127.0.0.1::5432', '--volume', VOLUME + ':/var/lib/postgresql/data',
                        'postgis/postgis:16-3.5'], check=True, stdout=subprocess.DEVNULL)
    endpoint = subprocess.check_output(['docker', 'port', CONTAINER, '5432/tcp'], text=True).strip()
    config['database_url'] = f'postgresql+psycopg://signal_local:{config["password"]}@{endpoint}/{DATABASE}'
    private_json(CONFIG, config)
    for _ in range(60):
        ready = subprocess.run(['docker', 'exec', CONTAINER, 'pg_isready', '-h', '127.0.0.1', '-U', 'signal_local', '-d', DATABASE],
                               capture_output=True)
        if ready.returncode == 0:
            return config
        time.sleep(.5)
    raise RuntimeError('Local PostGIS did not become ready')


def environment(config):
    result = os.environ.copy()
    result.update({
        'DATABASE_URL': config['database_url'], 'APP_ENV': 'development', 'COOKIE_SECURE': 'false',
        'APP_ORIGIN': config['origin'], 'PUBLIC_APPEALS_ORIGIN': config['origin'],
        'APP_TIMEZONE': 'Asia/Yekaterinburg', 'ORGANIZATIONS_ENABLED': 'true',
        'DATA_DIR': str(STATE / 'data'), 'YANDEX_MAPS_API_KEY': config.get('map_key', ''),
        'MAX_BOT_TOKEN': '', 'MAX_WEBHOOK_SECRET': secrets.token_urlsafe(40),
        'YANDEX_DISK_TOKEN': '', 'ML_AUTO_TRAIN': 'false', 'ML_DOWNLOAD_BACKBONE': 'false',
    })
    return result


def seed(config, catalog_path, wall_path, media_base):
    # Import only after setting all development settings; never inherit the working database.
    os.environ.update(environment(config))
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.appeal_images import prepare_upload
    from app.auth import hasher
    from app.db import engine
    from app.models import (
        AppealAttachment,
        AppealPhoto,
        CitizenAppeal,
        District,
        Organization,
        PlatformOwner,
        User,
        WorkType,
    )
    from geoalchemy2.shape import from_shape
    from shapely.geometry import MultiPolygon, shape
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session

    catalog = json.loads(catalog_path.read_text())
    owners = catalog['organizations']
    if len(owners) != 1:
        raise ValueError('This local snapshot importer requires exactly one organization')
    owner = owners[0]
    instant = datetime.now(timezone.utc)

    def date(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else instant

    def photograph(photo):
        parsed = urlsplit(photo['url'])
        if not parsed.path.startswith('/api/public/appeals/wall/'):
            raise ValueError('Expected a public appeal photograph')
        with urlopen(media_base + parsed.path, timeout=40) as response:
            return prepare_upload(response.read())

    with Session(engine(), expire_on_commit=False) as db:
        admin = db.scalar(select(User).where(User.login == 'signal-local-admin'))
        if admin is None:
            admin = User(login='signal-local-admin', name='Локальный администратор', role='ADMIN_OPERATOR',
                         password_hash=hasher.hash(config['admin_password']), active=True)
            db.add(admin)
            db.flush()
        if db.get(PlatformOwner, admin.id) is None:
            db.add(PlatformOwner(user_id=admin.id))
        record = db.get(Organization, owner['id'])
        if record is None:
            record = Organization(id=owner['id'], slug='signal-local', name=owner['name'], city=owner['city'],
                                  status='ACTIVE', legacy=True, owner_user_id=admin.id)
            db.add(record)
            db.flush()
        for index, work in enumerate(owner['work_types']):
            if db.scalar(select(WorkType.id).where(WorkType.code == work['code'])) is None:
                db.add(WorkType(code=work['code'], name=work['name'], filename_label=work['name'],
                                model_index=index, sort_order=index + 1))
        for area in owner['territories']:
            if db.get(District, area['id']) is None:
                geometry = shape(area['geometry'])
                if geometry.geom_type == 'Polygon':
                    geometry = MultiPolygon([geometry])
                db.add(District(id=area['id'], name=area['name'], active=True,
                                geometry=from_shape(geometry, srid=4326)))
        db.flush()
        wall = json.loads(wall_path.read_text()) if wall_path else {'items': []}
        imported = 0
        for item in wall['items']:
            if db.get(CitizenAppeal, item['id']) is not None:
                continue
            if item['organization_id'] != owner['id']:
                raise ValueError('Snapshot organization mismatch')
            response = item.get('response')
            address = next((row for row in owner['addresses'] if row['label'] == item['address']), None)
            point = shape(owner['territories'][0]['geometry']).representative_point()
            latitude = item.get('latitude') or point.y
            longitude = item.get('longitude') or point.x
            appeal = CitizenAppeal(id=item['id'], organization_id=owner['id'], organization_name=owner['name'],
                work_type_name=item.get('work_type_name', ''), city=owner['city'], address=item['address'],
                address_id=address['id'] if address else None, place=item.get('place', ''), category=item.get('category', ''),
                subject=item.get('subject') or '', description=item['description'], photo_count=len(item['photos']),
                status=item['status'], latitude=latitude, longitude=longitude, is_public=True,
                public_response=response['comment'] if response else '', resolved_at=date(response['at']) if response else None,
                created_at=date(item['created_at']), updated_at=date(item.get('updated_at')))
            db.add(appeal)
            db.flush()
            for index, photo in enumerate(item['photos']):
                db.add(AppealPhoto(id=photo['id'], appeal_id=appeal.id, position=index, **photograph(photo),
                    captured_at=appeal.created_at, position_at=appeal.created_at,
                    latitude=latitude, longitude=longitude, accuracy=0))
            for photo in (response or {}).get('photos', []):
                image = photograph(photo)
                db.add(AppealAttachment(id=photo['id'], appeal_id=appeal.id, content=image['original'],
                    preview=image['preview'], width=image['width'], height=image['height'], published=True))
            imported += 1
        for table in ('districts', 'citizen_appeals'):
            db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT max(id) FROM {table}), 1), EXISTS(SELECT 1 FROM {table}))"))
        db.commit()
        print(f'Local database ready: {len(owner["territories"])} territories; imported {imported} public appeals.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('setup')
    setup.add_argument('--catalog', type=Path, required=True)
    setup.add_argument('--wall', type=Path)
    setup.add_argument('--media-base', type=local_url, default='http://127.0.0.1:5181')
    setup.add_argument('--origin', type=local_url, default='http://127.0.0.1:5181')
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    if args.command == 'setup':
        config = configure()
        catalog = json.loads(args.catalog.read_text())
        config.update(origin=args.origin, map_key=catalog.get('yandex_maps_api_key', ''))
        private_json(CONFIG, config)
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'backend',
                       env=environment(config), check=True)
        seed(config, args.catalog, args.wall, args.media_base)
    else:
        config = json.loads(CONFIG.read_text())
        database = urlsplit(config['database_url'])
        if database.hostname not in {'127.0.0.1', 'localhost'} or database.path != '/' + DATABASE:
            raise ValueError('Refusing to run the development server on a non-local database')
        os.chdir(ROOT / 'backend')
        os.execve(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.appeals_public:app',
                                  '--host', '127.0.0.1', '--port', str(args.port)], environment(config))


if __name__ == '__main__':
    main()
