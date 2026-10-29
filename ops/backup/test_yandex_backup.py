import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location('max_foto_yandex_backup',
                                              Path(__file__).with_name('max_foto_yandex_backup.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class YandexArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.app = SimpleNamespace(state=self.state, config={'host': 'LogosIT'}, restic=Mock())
        self.archive = module.YandexBackup(self.app)
        self.sources = [{'id': 'default', 'token': 'secret-test-token', 'roots': ['PHOTOS']}]

    def test_configuration_cannot_escape_archive_or_select_entire_disk(self):
        for root in ('..', '.', '', '/personal', 'service/../personal', 'x:y', 'x\\y', 'a\nb'):
            with self.subTest(root=root), self.assertRaises(module.BackupError):
                module.YandexBackup.validate_sources([dict(self.sources[0], roots=[root])])
        with self.assertRaises(module.BackupError):
            module.YandexBackup.validate_sources([dict(self.sources[0], id='../outside')])

    def test_capture_preserves_deleted_files_and_excludes_auth_config(self):
        target = self.archive.files / 'default' / 'PHOTOS'
        target.mkdir(parents=True)
        (target / 'deleted.jpg').write_bytes(b'old photo')
        actions = []

        def transfer(config, action, source, destination=None, *options):
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertIn('secret-test-token', config.read_text())
            actions.append(action)
            if action == 'lsjson':
                return b'[{"Name":"PHOTOS","IsDir":true}]'
            if action == 'size':
                return b'{"count":1,"bytes":3}'
            if action == 'copy':
                Path(destination, 'new.jpg').write_bytes(b'new')
                self.assertIn('--checksum', options)
            if action == 'check':
                self.assertIn('--one-way', options)
            return b''

        with patch.object(self.archive, 'rclone', side_effect=transfer):
            manifest = self.archive.capture(self.sources)
        self.assertEqual(actions, ['lsjson', 'size', 'copy', 'check'])
        self.assertEqual((target / 'deleted.jpg').read_bytes(), b'old photo')
        self.assertEqual(manifest['files'], 2)
        self.assertNotIn('secret-test-token', (self.archive.stage / 'manifest.json').read_text())
        self.assertEqual(list(self.state.glob('.yandex-auth-*')), [])

    def test_failed_copy_cannot_upload_or_prune(self):
        self.app.restic.return_value = SimpleNamespace(stdout=b'[]')
        with patch.object(self.archive, 'discover', return_value=self.sources), \
                patch.object(self.archive, 'capture', side_effect=module.BackupError('copy failed')):
            with self.assertRaises(module.BackupError):
                self.archive.backup()
        self.assertEqual(self.app.restic.call_args_list[0].args[0], ['snapshots', '--json'])
        self.assertEqual(self.app.restic.call_count, 1)

    def test_failed_upload_never_prunes_previous_versions(self):
        self.app.restic.side_effect = [SimpleNamespace(stdout=b'[]'), module.BackupError('upload failed')]
        with patch.object(self.archive, 'discover', return_value=self.sources), \
                patch.object(self.archive, 'capture', return_value={'files': 2, 'bytes': 6}):
            with self.assertRaises(module.BackupError):
                self.archive.backup()
        self.assertFalse(any('forget' in call.args[0] for call in self.app.restic.call_args_list))

    def test_retention_is_separate_from_project_snapshots(self):
        self.app.restic.side_effect = [SimpleNamespace(stdout=b'[]'),
            SimpleNamespace(stdout=b'{"message_type":"summary","snapshot_id":"1234abcd"}\n'),
            SimpleNamespace(stdout=b''),
            SimpleNamespace(stdout=b'[{"time":"2026-10-29","id":"snapshot-full-id"}]'),
            SimpleNamespace(stdout=b'')]
        with patch.object(self.archive, 'discover', return_value=self.sources), \
                patch.object(self.archive, 'capture', return_value={'files': 2, 'bytes': 6, 'sources': []}):
            self.archive.backup()
        policy = self.app.restic.call_args_list[-1].args[0]
        self.assertEqual(policy, ['forget', '--host', 'LogosIT', '--tag', 'max-foto-yandex-complete',
                                  '--group-by', 'host', '--keep-last', '7', '--prune'])

    def test_only_read_actions_and_local_destinations_are_allowed(self):
        for action, destination in [('delete', None), ('sync', '/tmp/local'), ('copy', 'other:remote')]:
            with self.subTest(action=action), self.assertRaises(module.BackupError), \
                    patch.object(module.subprocess, 'run') as run:
                module.YandexBackup.rclone('config', action, 'account:PHOTOS', destination)
                run.assert_not_called()

    def test_remote_errors_do_not_expose_token_or_signed_download_url(self):
        result = subprocess.CompletedProcess([], 1, b'', b'https://private/?token=secret-test-token')
        with patch.object(module.subprocess, 'run', return_value=result):
            with self.assertRaises(module.BackupError) as raised:
                module.YandexBackup.rclone('config', 'copy', 'account:PHOTOS', '/tmp/local')
        self.assertNotIn('secret-test-token', str(raised.exception))

    def test_restore_detects_corrupted_photo(self):
        (self.state / 'yandex-last-success.json').write_text(json.dumps(
            {'snapshot_id': 'snapshot', 'bytes': 3}))

        def restore(args):
            root = Path(args[-1]) / str(self.archive.stage).lstrip('/')
            (root / 'files').mkdir(parents=True)
            (root / 'files/photo.jpg').write_bytes(b'bad')
            (root / 'manifest.json').write_text(json.dumps(
                {'sha256': {'files/photo.jpg': '0' * 64}}))

        self.app.restic.side_effect = restore
        with self.assertRaisesRegex(module.BackupError, 'checksum'):
            self.archive.verify()
        self.assertFalse((self.state / 'yandex-last-verification.json').exists())
        self.assertEqual(list(self.archive.root.glob('verify-*')), [])


if __name__ == '__main__':
    unittest.main()
