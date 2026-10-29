#!/usr/bin/env python3
"""Consistent, encrypted backups of one Docker Compose deployment.

Configuration and credentials live outside the application checkout. Never log
resolved Compose configuration, database contents, or credential values.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

CONFIG = Path('/etc/max-foto-backup/config.json')


class BackupError(RuntimeError):
    pass


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def command(args, *, cwd=None, env=None, data=None, output=None,
            timeout=600, allowed=(0,)):
    result = subprocess.run(args, cwd=cwd, env=env, input=data,
                            stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode not in allowed:
        # Commands never contain secrets. Do not include stdout in exceptions.
        error = result.stderr.decode(errors='replace')[-2000:].strip()
        raise BackupError(f'{args[0]} exited {result.returncode}: {error}')
    return result


class Backup:
    def __init__(self, config_path=CONFIG):
        self.config_path = Path(config_path)
        self.config = json.loads(self.config_path.read_text())
        self.project = Path(self.config['project_dir'])
        self.state = Path(self.config['state_dir'])
        if not self.project.is_absolute() or not self.state.is_absolute():
            raise BackupError('Absolute deployment and state paths required')
        if self.state == self.project or self.project in self.state.parents:
            raise BackupError('Backup staging must be outside the application')
        self.stage = self.state / 'staging'
        self.resume_file = self.state / 'resume.json'
        self.compose = ['docker', 'compose', '--profile', '*', '-f',
                        str(self.project / 'compose.yaml'), '-p',
                        self.config['compose_project']]
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state, 0o700)

    def dc(self, args, **kwargs):
        return command(self.compose + args, cwd=self.project, **kwargs)

    def psql(self, query, *, container=None):
        if container:
            args = ['docker', 'exec', '-i', container, 'psql', '-X', '-v',
                    'ON_ERROR_STOP=1', '-U', 'backup_verify', '-d',
                    self.config['database'], '-Atc', query]
        else:
            args = self.compose + ['exec', '-T', 'db', 'psql', '-X', '-v',
                    'ON_ERROR_STOP=1', '-U', self.config['database_user'],
                    '-d', self.config['database'], '-Atc', query]
        return command(args, cwd=self.project).stdout.decode().strip()

    def table_counts(self, container=None):
        tables = json.loads(self.psql("""
            SELECT COALESCE(json_agg(json_build_array(n.nspname,c.relname)), '[]')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%'
              AND n.nspname <> 'information_schema'
            """, container=container))
        def ident(value):
            return '"' + value.replace('"', '""') + '"'
        def literal(value):
            return "'" + value.replace("'", "''") + "'"
        unions = [f'SELECT {literal(s+"."+t)} AS name, count(*) AS n '
                  f'FROM {ident(s)}.{ident(t)}' for s, t in tables]
        if not unions:
            return {}
        query = 'SELECT json_object_agg(name,n) FROM (' + ' UNION ALL '.join(unions) + ') t'
        return json.loads(self.psql(query, container=container))

    def restic_env(self):
        credentials = json.loads(Path(self.config['credentials_file']).read_text())
        password = Path(self.config['password_file'])
        if not password.is_file() or password.stat().st_mode & 0o077:
            raise BackupError('Repository password file must exist with mode 0600')
        env = os.environ.copy()
        env.update(AWS_ACCESS_KEY_ID=credentials['access_key'],
                   AWS_SECRET_ACCESS_KEY=credentials['secret_key'],
                   AWS_DEFAULT_REGION=self.config['region'],
                   RESTIC_REPOSITORY=self.config['repository'],
                   RESTIC_PASSWORD_FILE=str(password),
                   RESTIC_CACHE_DIR=str(self.state / 'cache'),
                   GOMAXPROCS='2')
        return env

    def restic(self, args, **kwargs):
        return command(['restic', '-o', 's3.bucket-lookup=dns', '-o',
                        's3.connections=2'] + args, env=self.restic_env(),
                       timeout=2700, **kwargs)

    def containers(self):
        ids = command(['docker', 'ps', '-q', '--filter',
                       'label=com.docker.compose.project=' +
                       self.config['compose_project']]).stdout.decode().split()
        if not ids:
            raise BackupError('No running application containers found')
        raw = json.loads(command(['docker', 'inspect'] + ids).stdout)
        return raw

    def resume(self):
        if not self.resume_file.exists():
            return
        state = json.loads(self.resume_file.read_text())
        if state['project'] != self.config['compose_project']:
            raise BackupError('Resume state belongs to a different project')
        for cid in state['containers']:
            if not re.fullmatch('[a-f0-9]{64}', cid):
                raise BackupError('Invalid container ID in resume state')
            result = command(['docker', 'inspect', cid], allowed=(0, 1))
            if result.returncode:
                # A deployment may have replaced a saved container.
                continue
            info = json.loads(result.stdout)[0]
            if info['Config']['Labels'].get('com.docker.compose.project') != state['project']:
                raise BackupError('Refusing to start an unrelated container')
            command(['docker', 'start', cid], timeout=180)
        self.resume_file.unlink()

    @staticmethod
    def sync(source, target, excludes=(), live=False):
        source, target = Path(source), Path(target)
        if not source.is_absolute() or not target.is_absolute():
            raise BackupError('rsync requires absolute source and staging paths')
        if source == target or source in target.parents or target in source.parents:
            raise BackupError('Source and staging must not overlap')
        if target.is_symlink():
            raise BackupError('Refusing to synchronize into a symlink')
        target.mkdir(parents=True, exist_ok=True)
        args = ['rsync', '-aH', '--delete', '--delete-excluded']
        args += ['--exclude=' + pattern for pattern in excludes]
        command(args + [str(source) + '/', str(target) + '/'],
                allowed=(0, 24) if live else (0,), timeout=900)

    def wait_healthy(self, ids, timeout=120):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            info = json.loads(command(['docker', 'inspect'] + ids).stdout)
            if all(c['State']['Running'] and
                   c['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
                   for c in info):
                return
            time.sleep(2)
        raise BackupError('Application did not become healthy after backup capture')

    def capture(self):
        info = self.containers()
        database = [c for c in info if c['Config']['Labels'].get(
            'com.docker.compose.service') == 'db']
        if len(database) != 1:
            raise BackupError('Exactly one running database container is required')
        writers = [c for c in info if c not in database]
        service_names = sorted({c['Config']['Labels']['com.docker.compose.service']
                                for c in writers})
        ids = [c['Id'] for c in writers]
        volume = json.loads(command(['docker', 'volume', 'inspect',
                                     self.config['photo_volume']]).stdout)[0]
        photo_source = Path(volume['Mountpoint'])
        if volume['Driver'] != 'local' or not photo_source.is_dir():
            raise BackupError('Expected a local photo_data Docker volume')
        free = shutil.disk_usage(self.state).free
        data_bytes = int(command(['du', '-sb', str(photo_source)]).stdout.split()[0])
        if free < data_bytes + 2 * 1024**3:
            raise BackupError('Insufficient free space for a safe staging copy')
        self.stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        project_excludes = ('/backups/', '/.venv/', '/backend/.venv/',
                            '/frontend/node_modules/', '/frontend/dist/',
                            '/frontend/dist-citizens/', '__pycache__/',
                            '.pytest_cache/', '.ruff_cache/', '*.log')
        self.sync(self.project, self.stage / 'project', project_excludes)
        # Copy most bytes while the application is running; repeat once quiet.
        self.sync(photo_source, self.stage / 'photo_data', live=True)
        self.resume()
        paused_at = time.monotonic()
        atomic_json(self.resume_file, {'project': self.config['compose_project'],
                                      'containers': ids, 'created_at': utcnow()})
        metadata = {}
        try:
            if service_names:
                self.dc(['stop'] + service_names, timeout=420)
                stopped = json.loads(command(['docker', 'inspect'] + ids).stdout)
                if any(c['State']['Running'] for c in stopped):
                    raise BackupError('Not all application writers stopped')
                if any(c['State']['ExitCode'] == 137 or c['State'].get('OOMKilled')
                       for c in stopped):
                    raise BackupError('A writer did not shut down gracefully; capture cancelled')
            self.sync(photo_source, self.stage / 'photo_data')
            self.sync(self.project, self.stage / 'project', project_excludes)
            for args, name in [(['pg_dump', '-U', self.config['database_user'],
                                 '-Fc', self.config['database']], 'postgres.dump'),
                               (['pg_dumpall', '-U', self.config['database_user'],
                                 '--globals-only'], 'postgres-roles.sql')]:
                target = self.stage / name
                temporary = target.with_suffix(target.suffix + '.part')
                with temporary.open('wb') as stream:
                    self.dc(['exec', '-T', 'db'] + args, output=stream, timeout=600)
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
            metadata['table_counts'] = self.table_counts()
            metadata['captured_at'] = utcnow()
            resolved = self.dc(['config', '--format', 'json']).stdout
            atomic_json(self.stage / 'compose.resolved.json', json.loads(resolved))
        finally:
            self.resume()
        metadata['capture_pause_seconds'] = round(time.monotonic() - paused_at, 2)
        if ids:
            self.wait_healthy(ids)
        metadata.update(schema=1, project=self.config['compose_project'],
                        project_dir=str(self.project),
                        database_image_id=database[0]['Image'],
                        database_image_name=database[0]['Config']['Image'],
                        photo_volume=self.config['photo_volume'],
                        git_revision=command(['git', '-C', str(self.project),
                                              'rev-parse', 'HEAD']).stdout.decode().strip(),
                        containers=[{'service':c['Config']['Labels']['com.docker.compose.service'],
                                     'image':c['Config']['Image'], 'image_id':c['Image']}
                                    for c in info])
        for source, name in [('/etc/nginx', 'nginx'),
                             ('/etc/letsencrypt', 'letsencrypt'),
                             ('/etc/max-foto-backup', 'backup-config'),
                             ('/usr/local/lib/max-foto-backup', 'backup-program')]:
            if Path(source).is_dir():
                self.sync(Path(source), self.stage / 'server' / name)
        units = self.stage / 'server' / 'systemd'
        units.mkdir(parents=True, exist_ok=True)
        for pattern in ('max-foto-backup*', 'max-foto-yandex-backup*'):
            for source in Path('/etc/systemd/system').glob(pattern):
                if source.is_file():
                    shutil.copy2(source, units / source.name)
        atomic_json(self.stage / 'manifest.json', metadata)
        hashes, links = {}, {}
        for path in sorted(self.stage.rglob('*')):
            relative = str(path.relative_to(self.stage))
            if relative == 'file-checksums.json':
                continue
            if path.is_symlink():
                links[relative] = os.readlink(path)
            elif path.is_file():
                hashes[relative] = file_hash(path)
        atomic_json(self.stage / 'file-checksums.json', {'sha256': hashes, 'symlinks': links})
        return metadata

    def backup(self):
        self.resume()
        # Prove the repository can be opened before pausing application writers.
        self.restic(['snapshots', '--json'])
        started = utcnow()
        metadata = self.capture()
        result = self.restic(['backup', '--host', self.config['host'], '--tag',
                              'max-foto-candidate', '--json', str(self.stage)])
        summaries = [json.loads(line) for line in result.stdout.decode().splitlines()
                     if line.startswith('{')]
        summaries = [item for item in summaries if item.get('message_type') == 'summary']
        if len(summaries) != 1 or not summaries[0].get('snapshot_id'):
            raise BackupError('restic did not report a successful snapshot')
        summary = summaries[0]
        self.restic(['tag', '--remove', 'max-foto-candidate', '--add',
                     'max-foto-complete', summary['snapshot_id']])
        snapshots = json.loads(self.restic(['snapshots', '--json', '--host',
                    self.config['host'], '--tag', 'max-foto-complete']).stdout)
        latest = max(snapshots, key=lambda item: item['time'])
        # Retention is scoped to this repository, host, and completed snapshots.
        self.restic(['forget', '--host', self.config['host'], '--tag',
                     'max-foto-complete', '--group-by', 'host', '--keep-last',
                     str(self.config['keep_last']), '--prune'])
        status = {'success': True, 'started_at': started, 'finished_at': utcnow(),
                  'snapshot_id': latest['id'],
                  'capture_pause_seconds': metadata['capture_pause_seconds'],
                  'total_bytes_processed': summary.get('total_bytes_processed'),
                  'data_added': summary.get('data_added'),
                  'files': summary.get('total_files_processed')}
        atomic_json(self.state / 'last-success.json', status)
        atomic_json(self.state / 'last-attempt.json', status)
        print(json.dumps(status), flush=True)

    def verify(self):
        self.cleanup_verification()
        status = json.loads((self.state / 'last-success.json').read_text())
        snapshot = status['snapshot_id']
        self.restic(['check', '--read-data'])
        verify_root = self.state / 'verification'
        verify_root.mkdir(mode=0o700, exist_ok=True)
        name = 'max-foto-backup-verify-' + uuid.uuid4().hex[:12]
        created = False
        with tempfile.TemporaryDirectory(dir=verify_root) as temporary:
            target = Path(temporary)
            try:
                self.restic(['restore', snapshot, '--target', str(target)])
                restored = target / str(self.stage).lstrip('/')
                checksums = json.loads((restored / 'file-checksums.json').read_text())
                for relative, expected in checksums['sha256'].items():
                    path = restored / relative
                    if path.is_symlink() or not path.is_file() or file_hash(path) != expected:
                        raise BackupError('Restored file checksum mismatch')
                for relative, expected in checksums['symlinks'].items():
                    path = restored / relative
                    if not path.is_symlink() or os.readlink(path) != expected:
                        raise BackupError('Restored symlink mismatch')
                metadata = json.loads((restored / 'manifest.json').read_text())
                command(['docker', 'run', '-d', '--rm', '--pull=never', '--name', name,
                         '--label', 'max-foto.backup.verify=true', '--network', 'none',
                         '--memory', '768m', '--cpus', '0.5', '--tmpfs',
                         '/var/lib/postgresql/data:rw,size=384m',
                         '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
                         '-e', 'POSTGRES_USER=backup_verify', '-e',
                         'POSTGRES_DB=postgres',
                         metadata['database_image_id']])
                created = True
                end = time.monotonic() + 90
                while time.monotonic() < end:
                    ready = command(['docker', 'exec', name, 'pg_isready', '-U',
                                      'backup_verify', '-d', 'postgres'],
                                     allowed=(0, 1, 2))
                    if ready.returncode == 0:
                        # Wait for the final post-init server, not its temporary
                        # initialization server that uses a different PID 1.
                        pid1 = command(['docker', 'exec', name, 'cat',
                                        '/proc/1/comm']).stdout.decode().strip()
                        if pid1 == 'postgres':
                            break
                    time.sleep(2)
                else:
                    raise BackupError('Isolated verification database did not start')
                # PostGIS' image entrypoint prepopulates its default database
                # and template1 with tiger/topology schemas. A custom-format
                # dump contains those schemas, so restore into template0.
                command(['docker', 'exec', name, 'createdb', '-U', 'backup_verify',
                         '--template=template0', self.config['database']])
                with (restored / 'postgres.dump').open('rb') as stream:
                    result = subprocess.run(['docker', 'exec', '-i', name,
                             'pg_restore', '--exit-on-error', '--no-owner',
                             '--no-privileges', '-U', 'backup_verify', '-d',
                             self.config['database']], stdin=stream,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             timeout=600)
                if result.returncode:
                    raise BackupError('Isolated database restore failed: ' +
                                      result.stderr.decode(errors='replace')[-1500:])
                actual = self.table_counts(container=name)
                if actual != metadata['table_counts']:
                    raise BackupError('Restored database table counts differ')
                verification = {'success': True, 'snapshot_id': snapshot,
                                'verified_at': utcnow(), 'database_restored': True,
                                'tables_checked': len(actual),
                                'files_checked': len(checksums['sha256'])}
                atomic_json(self.state / 'last-verification.json', verification)
                print(json.dumps(verification), flush=True)
            finally:
                if created:
                    command(['docker', 'rm', '-f', name], allowed=(0, 1))

    def cleanup_verification(self):
        ids = command(['docker', 'ps', '-aq', '--filter',
                       'label=max-foto.backup.verify=true']).stdout.decode().split()
        for cid in ids:
            info = json.loads(command(['docker', 'inspect', cid]).stdout)[0]
            if (not re.fullmatch(r'/max-foto-backup-verify-[a-f0-9]{12}', info['Name'])
                    or info['HostConfig']['NetworkMode'] != 'none'
                    or info['Config']['Labels'].get('max-foto.backup.verify') != 'true'):
                raise BackupError('Refusing to remove a container outside isolated verification')
            command(['docker', 'rm', '-f', cid])


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def interrupted(signum, frame):
    raise BackupError('Backup interrupted by signal ' + str(signum))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'resume', 'verify', 'init',
                                           'restic', 'status', 'cleanup-verification'])
    parser.add_argument('rest', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    app = Backup()
    if args.action == 'resume':
        app.resume()
        return
    if args.action == 'status':
        for name in ['last-success.json', 'last-attempt.json', 'last-verification.json',
                     'yandex-last-success.json', 'yandex-last-attempt.json',
                     'yandex-last-verification.json']:
            path = app.state / name
            if path.exists():
                print(name + ': ' + path.read_text())
        return
    with (app.state / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError('Another backup operation is already running')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            if args.action == 'backup':
                app.backup()
            elif args.action == 'verify':
                app.verify()
            elif args.action == 'init':
                result = app.restic(['init'])
                print(result.stdout.decode().strip())
            elif args.action == 'restic':
                result = app.restic(args.rest)
                sys.stdout.buffer.write(result.stdout)
            elif args.action == 'cleanup-verification':
                app.cleanup_verification()
        except BaseException as error:
            if args.action in ('backup', 'verify'):
                result_file = ('last-attempt.json' if args.action == 'backup'
                               else 'last-verification.json')
                atomic_json(app.state / result_file, {
                    'success': False, 'action': args.action,
                    'failed_at': utcnow(), 'error': str(error)})
            raise


if __name__ == '__main__':
    try:
        main()
    except (BackupError, OSError, subprocess.SubprocessError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
