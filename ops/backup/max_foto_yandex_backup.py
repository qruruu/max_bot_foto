#!/usr/bin/env python3
"""Read service-owned Yandex folders into a cumulative, encrypted photo archive."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

from max_foto_backup import Backup, BackupError, atomic_json, file_hash, interrupted, utcnow


# Executed inside the existing API container. Tokens go only to a private pipe,
# then a temporary 0600 rclone config; never to arguments, journals or snapshots.
SOURCE_DISCOVERY = '''
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import base_settings
from app.db import engine
from app.disk_folders import folder_sets

sources = {}
def collect(key, token):
    if not token:
        raise RuntimeError("Yandex token is not configured")
    with Session(engine()) as db:
        roots = {name for group in folder_sets(db) for name in vars(group).values()}
    source = sources.setdefault(key, {"id": key, "token": token, "roots": set()})
    if source["token"] != token:
        raise RuntimeError("Conflicting Yandex account configuration")
    source["roots"].update(roots)

cfg = base_settings()
if cfg.yandex_disk_token:
    collect("default", cfg.yandex_disk_token)
if cfg.organizations_enabled:
    from app.disk_accounts import configured_token
    from app.models import Organization
    from app.organization_context import organization_scope
    from app.organization_registry import control_session, scope_for
    with control_session() as control:
        records = list(control.scalars(select(Organization).where(
            Organization.status.in_(["ACTIVE", "PAUSED"]))))
        for record in records:
            with organization_scope(scope_for(record)):
                collect(record.disk_account_id or "default", configured_token())
for source in sources.values():
    source["roots"] = sorted(source["roots"])
print(json.dumps(list(sources.values()), ensure_ascii=False))
'''


class YandexBackup:
    tag = 'max-foto-yandex-complete'
    candidate_tag = 'max-foto-yandex-candidate'

    def __init__(self, app):
        self.app = app
        self.root = app.state / 'yandex-disk'
        self.stage = self.root / 'staging'
        self.files = self.stage / 'files'
        for path in (self.root, self.stage, self.files):
            if path.is_symlink():
                raise BackupError('Yandex archive must not be a symlink')
            path.mkdir(mode=0o700, parents=True, exist_ok=True)

    @staticmethod
    def validate_sources(sources):
        if not isinstance(sources, list) or not sources:
            raise BackupError('No configured Yandex sources')
        seen = set()
        for source in sources:
            key = source.get('id', '')
            roots = source.get('roots')
            if (not isinstance(key, str) or not re.fullmatch(r'[a-z0-9-]{1,64}', key)
                    or key in seen or not isinstance(source.get('token'), str)
                    or not source['token'] or not isinstance(roots, list) or not roots):
                raise BackupError('Invalid Yandex account configuration')
            seen.add(key)
            for root in roots:
                if (not isinstance(root, str) or not root or root in ('.', '..')
                        or any(c in root for c in '/\\:')
                        or any(ord(c) < 32 or ord(c) == 127 for c in root)):
                    raise BackupError('Invalid Yandex service folder')
        return sources

    def discover(self):
        try:
            raw = self.app.dc(['exec', '-T', 'api', 'python', '-c', SOURCE_DISCOVERY])
            sources = json.loads(raw.stdout)
        except (BackupError, ValueError, subprocess.SubprocessError):
            # Child errors may contain sensitive URLs; do not echo them.
            raise BackupError('Cannot read Yandex configuration from the API container') from None
        return self.validate_sources(sources)

    @staticmethod
    def rclone(config, action, source, destination=None, *options):
        if action not in ('lsjson', 'size', 'copy', 'check') or not source.startswith('account:'):
            raise BackupError('Only read operations on Yandex are permitted')
        if action in ('copy', 'check'):
            if destination is None or not Path(destination).is_absolute():
                raise BackupError('Yandex destination must be a local absolute path')
        args = ['rclone', '--config', str(config), '--log-level', 'ERROR',
                '--retries', '3', '--low-level-retries', '5', '--contimeout', '20s',
                '--timeout', '2m', '--tpslimit', '32', action, source]
        if destination is not None:
            args.append(str(destination))
        args.extend(options)
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=7200)
        if result.returncode:
            raise BackupError(f'Yandex {action} failed (code {result.returncode}); previous copies kept')
        return result.stdout

    def capture(self, sources):
        inventory = []
        # copy deliberately preserves files removed remotely. There is no sync,
        # delete, purge or write operation against Yandex in this program.
        with tempfile.TemporaryDirectory(prefix='.yandex-auth-', dir=self.app.state) as temporary:
            config = Path(temporary) / 'rclone.conf'
            for source in sources:
                # This application already has a static OAuth token, without a
                # refresh token. rclone's Yandex backend insists on a nonempty
                # refresh field even for zero-expiry tokens. The sentinel is
                # never used: OAuth2 treats zero expiry as non-expiring. A
                # revoked access token still fails the backup normally.
                token = json.dumps({'access_token': source['token'], 'token_type': 'OAuth',
                                    'refresh_token': 'unused-with-static-access-token',
                                    'expiry': '0001-01-01T00:00:00Z'})
                config.write_text('[account]\ntype = yandex\ntoken = ' + token + '\n')
                os.chmod(config, 0o600)
                listing = json.loads(self.rclone(config, 'lsjson', 'account:', None, '--dirs-only'))
                present = {item['Name'] for item in listing if item.get('IsDir')}
                for name in source['roots']:
                    entry = {'account': source['id'], 'folder': name, 'present': name in present}
                    inventory.append(entry)
                    if name not in present:
                        continue
                    destination = self.files / source['id'] / name
                    for ancestor in (destination.parent, destination):
                        if ancestor.is_symlink():
                            raise BackupError('Refusing a symlink in the photo archive')
                    remote = 'account:' + name
                    size = json.loads(self.rclone(config, 'size', remote, None, '--json'))
                    # Reserve an extra complete source copy plus 2 GiB so that a
                    # growing archive cannot fill the application's filesystem.
                    if shutil.disk_usage(self.root).free < size['bytes'] + 2 * 1024**3:
                        raise BackupError('Insufficient free space for the Yandex archive')
                    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                    print(json.dumps({'copying_folder': name, 'files': size['count'],
                                      'bytes': size['bytes']}), flush=True)
                    self.rclone(config, 'copy', remote, destination, '--checksum',
                                '--transfers', '32', '--checkers', '8',
                                '--buffer-size', '1M', '--bwlimit', '6M')
                    # One-way check allows retained deleted files locally, while
                    # proving that current source files match their MD5 hashes.
                    self.rclone(config, 'check', remote, destination, '--one-way', '--checkers', '4')
                    entry.update(source_files=size['count'], source_bytes=size['bytes'])
                    print(json.dumps({'copied_folder': name, 'files': size['count'],
                                      'bytes': size['bytes']}), flush=True)
        if not any(entry['present'] for entry in inventory):
            raise BackupError('None of the service folders exist on Yandex; previous copies kept')
        hashes = {}
        for path in sorted(self.files.rglob('*')):
            if path.is_symlink():
                raise BackupError('Unexpected symlink in the photo archive')
            if path.is_file():
                hashes[str(path.relative_to(self.stage))] = file_hash(path)
        if not hashes:
            raise BackupError('The Yandex photo archive is empty; previous copies kept')
        manifest = {'schema': 1, 'captured_at': utcnow(), 'mode': 'cumulative-copy',
                    'sources': inventory, 'sha256': hashes,
                    'files': len(hashes),
                    'bytes': sum(path.stat().st_size for path in self.files.rglob('*') if path.is_file())}
        recovery = self.app.state / 'yandex-recovered-originals.json'
        if recovery.is_file():
            manifest['recovered_originals'] = [
                {'path': row['path'], 'sha256': row['sha256'], 'source': 'MAX original'}
                for row in json.loads(recovery.read_text()) if row.get('success')
                and hashes.get('files/default/' + row['path'].removeprefix('disk:/')) == row['sha256']]
        atomic_json(self.stage / 'manifest.json', manifest)
        return manifest

    def backup(self):
        self.app.restic(['snapshots', '--json'])
        started = utcnow()
        manifest = self.capture(self.discover())
        result = self.app.restic(['backup', '--host', self.app.config['host'], '--tag',
                                 self.candidate_tag, '--json', str(self.stage)])
        summaries = [json.loads(line) for line in result.stdout.decode().splitlines()
                     if line.startswith('{')]
        summaries = [row for row in summaries if row.get('message_type') == 'summary']
        if len(summaries) != 1 or not summaries[0].get('snapshot_id'):
            raise BackupError('No successful Yandex snapshot reported')
        summary = summaries[0]
        self.app.restic(['tag', '--remove', self.candidate_tag, '--add', self.tag,
                         summary['snapshot_id']])
        snapshots = json.loads(self.app.restic(['snapshots', '--json', '--host',
                               self.app.config['host'], '--tag', self.tag]).stdout)
        latest = max(snapshots, key=lambda row: row['time'])
        self.app.restic(['forget', '--host', self.app.config['host'], '--tag', self.tag,
                         '--group-by', 'host', '--keep-last',
                         str(self.app.config.get('yandex_keep_last', 7)), '--prune'])
        status = {'success': True, 'started_at': started, 'finished_at': utcnow(),
                  'snapshot_id': latest['id'], 'files': manifest['files'], 'bytes': manifest['bytes'],
                  'data_added': summary.get('data_added'), 'sources': manifest['sources'],
                  'recovered_originals': len(manifest.get('recovered_originals', []))}
        atomic_json(self.app.state / 'yandex-last-success.json', status)
        atomic_json(self.app.state / 'yandex-last-attempt.json', status)
        print(json.dumps(status, ensure_ascii=False), flush=True)

    def verify(self):
        status = json.loads((self.app.state / 'yandex-last-success.json').read_text())
        if shutil.disk_usage(self.root).free < status['bytes'] + 2 * 1024**3:
            raise BackupError('Insufficient free space for an isolated photo restore')
        with tempfile.TemporaryDirectory(prefix='verify-', dir=self.root) as temporary:
            self.app.restic(['restore', status['snapshot_id'], '--target', temporary])
            restored = Path(temporary) / str(self.stage).lstrip('/')
            manifest = json.loads((restored / 'manifest.json').read_text())
            actual = {str(path.relative_to(restored)) for path in restored.rglob('*') if path.is_file()}
            if actual != set(manifest['sha256']) | {'manifest.json'}:
                raise BackupError('Restored photo file set differs from the manifest')
            for relative, expected in manifest['sha256'].items():
                path = restored / relative
                if (not path.is_relative_to(restored) or '..' in Path(relative).parts
                        or path.is_symlink() or not path.is_file() or file_hash(path) != expected):
                    raise BackupError('Restored photo checksum mismatch')
        result = {'success': True, 'snapshot_id': status['snapshot_id'],
                  'verified_at': utcnow(), 'files_checked': len(manifest['sha256'])}
        atomic_json(self.app.state / 'yandex-last-verification.json', result)
        print(json.dumps(result), flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'verify', 'status'])
    action = parser.parse_args().action
    app = Backup()
    if action == 'status':
        for name in ('yandex-last-success.json', 'yandex-last-attempt.json', 'yandex-last-verification.json'):
            path = app.state / name
            if path.exists():
                print(name + ': ' + path.read_text())
        return
    with (app.state / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError('Another backup operation is already running') from None
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            archive = YandexBackup(app)
            getattr(archive, action)()
        except BaseException:
            name = 'yandex-last-attempt.json' if action == 'backup' else 'yandex-last-verification.json'
            atomic_json(app.state / name, {'success': False, 'action': action, 'failed_at': utcnow(),
                                         'error': 'Yandex backup operation failed; see service result'})
            raise


if __name__ == '__main__':
    try:
        main()
    except (BackupError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('ERROR: ' + str(error), flush=True)
        raise SystemExit(1)
