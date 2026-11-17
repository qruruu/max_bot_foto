import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
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

    def test_command_timeout_allows_child_to_remove_its_lock(self):
        ready = self.root / 'ready'
        released = self.root / 'released'
        script = '''
import os, pathlib, signal, sys, time
ready, released = map(pathlib.Path, sys.argv[1:])
def stop(signum, frame):
    released.write_text('lock removed')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
ready.write_text(str(os.getpid()))
while True: time.sleep(.02)
'''
        with self.assertRaises(subprocess.TimeoutExpired):
            module.run_process([sys.executable, '-c', script, str(ready), str(released)],
                               timeout=.8, termination_grace=2)
        self.assertTrue(released.is_file())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)

    def test_restic_timeout_uses_sigint_for_old_versions_lock_cleanup(self):
        ready = self.root / 'restic-ready'
        released = self.root / 'restic-unlocked'
        executable = self.root / 'restic'
        executable.write_text('#!' + sys.executable + '\n' + '''
import os,pathlib,signal,sys,time
ready,released=map(pathlib.Path,sys.argv[1:])
def stop(signum,frame):
    released.write_text('SIGINT removed repository lock')
    raise SystemExit(1)
signal.signal(signal.SIGINT,stop)
ready.write_text(str(os.getpid()))
while True:time.sleep(.02)
''')
        executable.chmod(0o700)
        with self.assertRaises(subprocess.TimeoutExpired):
            module.run_process([str(executable), str(ready), str(released)],
                               timeout=2, termination_grace=2)
        self.assertTrue(released.is_file())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(ready.read_text()), 0)

    def test_parent_sigterm_waits_for_child_cleanup_and_reaps_it(self):
        ready = self.root / 'ready'
        released = self.root / 'released'
        child = '''
import os, pathlib, signal, sys, time
ready, released = map(pathlib.Path, sys.argv[1:])
def stop(signum, frame):
    time.sleep(.15)
    released.write_text('lock removed')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
ready.write_text(str(os.getpid()))
while True: time.sleep(.02)
'''
        parent = '''
import signal, sys
sys.path.insert(0, sys.argv[1])
from max_foto_backup import BackupError, interrupted, run_process
signal.signal(signal.SIGTERM, interrupted)
try:
    run_process([sys.executable, '-c', sys.argv[2], sys.argv[3], sys.argv[4]],
                timeout=30, termination_grace=2)
except BackupError:
    raise SystemExit(1)
'''
        process = subprocess.Popen([sys.executable, '-c', parent, str(Path(__file__).parent),
                                    child, str(ready), str(released)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists(), 'Child did not start')
            process.terminate()
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1)
            self.assertTrue(released.is_file())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(ready.read_text()), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_unresponsive_child_is_killed_after_grace_and_reaped(self):
        script = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            module.run_process([sys.executable, '-c', script], timeout=.8, termination_grace=.1)
        self.assertLess(time.monotonic() - started, 4)

    def test_restic_full_check_has_separate_configurable_time_limit(self):
        self.app.restic_env = dict
        with patch.object(module, 'command', return_value=self.result()) as run:
            self.app.restic(['check', '--read-data'])
            self.assertEqual(run.call_args.kwargs['timeout'], 10800)
            self.app.config['restic_check_timeout_seconds'] = 14400
            self.app.restic(['check', '--read-data'])
            self.assertEqual(run.call_args.kwargs['timeout'], 14400)
            self.app.restic(['snapshots', '--json'])
            self.assertEqual(run.call_args.kwargs['timeout'], 600)

    def test_verification_database_cannot_mount_live_data_or_symlink_outside_temp(self):
        name = 'max-foto-backup-verify-0123456789ab'
        for path in (self.source, self.app.state / 'verification'):
            with self.assertRaises(module.BackupError):
                self.app.verification_database_args(name, 'test-image', path)
        directory = self.app.state / 'verification' / 'test'
        directory.mkdir(parents=True)
        (directory / 'escape').symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(module.BackupError):
            self.app.verification_database_args(name, 'test-image', directory / 'escape')
        with self.assertRaises(module.BackupError):
            self.app.verification_database_args(name, 'test-image', directory / 'escape' / 'child')
        args = self.app.verification_database_args(name, 'test-image', directory / 'postgres')
        self.assertEqual(args[args.index('--network') + 1], 'none')
        self.assertNotIn('--tmpfs', args)
        self.assertIn('type=bind,src=' + str(directory / 'postgres') +
                      ',dst=/var/lib/postgresql/data', args)


if __name__ == '__main__':
    unittest.main()
