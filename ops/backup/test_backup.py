import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('max_foto_backup', Path(__file__).with_name('max_foto_backup.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.source = self.root / 'volume'
        self.source.mkdir()
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({
            'project_dir': str(self.project), 'state_dir': str(self.root / 'state'),
            'compose_project': 'max-photos', 'database': 'maxphotos',
            'database_user': 'maxphotos', 'photo_volume': 'max-photos_photo_data',
            'host': 'LogosIT', 'keep_last': 7,
            'credentials_file': str(self.root / 'credentials.json'),
            'password_file': str(self.root / 'password'), 'region': 'ru-1',
            'repository': 's3:https://example.invalid/test/repository'}))
        self.app = module.Backup(self.config)
        self.writer_id = 'a' * 64
        self.database_id = 'b' * 64
        self.calls = []

    def result(self, value=b'', code=0):
        if not isinstance(value, bytes):
            value = json.dumps(value).encode()
        return subprocess.CompletedProcess([], code, value, b'')

    def container(self, cid, name, running):
        return {'Id': cid, 'Config': {'Labels': {
                'com.docker.compose.project': 'max-photos',
                'com.docker.compose.service': name}, 'Image': 'test-image'},
                'Image': 'sha256:test', 'State': {'Running': running,
                'ExitCode': 0, 'OOMKilled': False}}

    def fake_command(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] == ['docker', 'volume', 'inspect']:
            return self.result([{'Mountpoint': str(self.source), 'Driver': 'local'}])
        if args[:2] == ['du', '-sb']:
            return self.result(b'1024 data')
        if args[:2] == ['docker', 'inspect']:
            return self.result([self.container(self.writer_id, 'api', False)])
        if args[:2] == ['docker', 'start']:
            return self.result()
        raise AssertionError(args)

    def capture_fixture(self):
        self.app.containers = lambda: [self.container(self.writer_id, 'api', True),
                                      self.container(self.database_id, 'db', True)]
        self.app.sync = lambda *args, **kwargs: None

    def test_failed_dump_always_restarts_only_saved_application_containers(self):
        self.capture_fixture()
        def dc(args, **kwargs):
            if args[0] == 'stop':
                return self.result()
            raise module.BackupError('dump failed')
        self.app.dc = dc
        with patch.object(module, 'command', self.fake_command):
            with self.assertRaisesRegex(module.BackupError, 'dump failed'):
                self.app.capture()
        self.assertIn(['docker', 'start', self.writer_id], self.calls)
        self.assertNotIn(['docker', 'start', self.database_id], self.calls)
        self.assertFalse(self.app.resume_file.exists())

    def test_failed_live_copy_never_stops_application(self):
        self.capture_fixture()
        def fail_sync(*args, **kwargs):
            raise module.BackupError('disk unavailable')
        self.app.sync = fail_sync
        self.app.dc = lambda *a, **k: self.fail('Application must remain running')
        with patch.object(module, 'command', self.fake_command):
            with self.assertRaisesRegex(module.BackupError, 'disk unavailable'):
                self.app.capture()
        self.assertFalse(self.app.resume_file.exists())

    def test_upload_failure_never_runs_retention(self):
        operations = []
        self.app.capture = lambda: {'capture_pause_seconds': 1}
        def restic(args, **kwargs):
            operations.append(args[0])
            if args[0] == 'snapshots':
                return self.result([])
            raise module.BackupError('upload failed')
        self.app.restic = restic
        with self.assertRaisesRegex(module.BackupError, 'upload failed'):
            self.app.backup()
        self.assertEqual(operations, ['snapshots', 'backup'])

    def test_resume_refuses_unrelated_project(self):
        module.atomic_json(self.app.resume_file, {'project': 'other-project',
                                                  'containers': [self.writer_id]})
        with patch.object(module, 'command', self.fake_command):
            with self.assertRaisesRegex(module.BackupError, 'different project'):
                self.app.resume()
        self.assertEqual(self.calls, [])

    def test_sync_refuses_source_and_destination_overlap(self):
        with self.assertRaisesRegex(module.BackupError, 'must not overlap'):
            module.Backup.sync(self.project, self.project / 'backup')

    def test_password_must_not_be_world_readable(self):
        (self.root / 'credentials.json').write_text(json.dumps({
            'access_key': 'test-access', 'secret_key': 'test-secret'}))
        password = self.root / 'password'
        password.write_text('test-password')
        password.chmod(0o644)
        with self.assertRaisesRegex(module.BackupError, '0600'):
            self.app.restic_env()

    def test_verification_cleanup_refuses_any_networked_container(self):
        calls = []
        def fake(args, **kwargs):
            calls.append(args)
            if args[:3] == ['docker', 'ps', '-aq']:
                return self.result(self.writer_id.encode())
            if args[:2] == ['docker', 'inspect']:
                return self.result([{'Name': '/max-foto-backup-verify-0123456789ab',
                     'HostConfig': {'NetworkMode': 'bridge'},
                     'Config': {'Labels': {'max-foto.backup.verify': 'true'}}}])
            self.fail('Unrelated container must not be removed')
        with patch.object(module, 'command', fake):
            with self.assertRaisesRegex(module.BackupError, 'outside isolated verification'):
                self.app.cleanup_verification()
        self.assertFalse(any(call[:2] == ['docker', 'rm'] for call in calls))


if __name__ == '__main__':
    unittest.main()
