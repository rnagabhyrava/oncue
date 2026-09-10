import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oncue import service
from oncue.store import Store, process_start_ticks
from oncue.tasks import save_task


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.prefix = self.home/'.local'
        self.data = self.prefix/'share/oncue/data'
        self.bundle = self.prefix/'share/oncue/bin'
        self.bundle.mkdir(parents=True)
        (self.bundle/'oncue').write_text('executable')
        (self.bundle/'install.sh').touch()
        (self.prefix/'bin').mkdir()
        for name in ('oncue', 'codex-local-scheduler'):
            (self.prefix/'bin'/name).symlink_to(self.bundle/'oncue')
        self.store = Store(self.data/'scheduler.sqlite3')
        self.store.initialize()
        self.home_patch = patch('pathlib.Path.home', return_value=self.home)
        self.home_patch.start()

    def tearDown(self):
        self.store.close()
        self.home_patch.stop()
        self.temp.cleanup()

    def test_uninstall_preserves_history_and_unrelated_commands(self):
        slug = save_task(self.store, {'instructions':'saved', 'enabled':False})
        service.install_launcher(self.data, self.prefix)
        alias = self.prefix/'bin/codex-local-scheduler'
        alias.unlink()
        alias.write_text('unrelated')
        service.uninstall(self.data, self.prefix)
        self.assertFalse(self.bundle.exists())
        self.assertFalse((self.prefix/'bin/oncue').is_symlink())
        self.assertFalse((self.prefix/'share/applications/oncue.desktop').exists())
        self.assertEqual(alias.read_text(), 'unrelated')
        self.assertIsNotNone(self.store.job(slug))
        self.assertTrue((self.data/'scheduler.sqlite3').exists())

    def test_purge_removes_default_data_and_legacy_alias_only(self):
        legacy = self.prefix/'share/codex-local-scheduler'
        legacy.symlink_to(self.data)
        shared = self.home/'.codex'
        shared.mkdir(); (shared/'auth.json').write_text('provider-owned')
        self.store.close()
        service.uninstall(self.data, self.prefix, purge_data=True)
        self.assertFalse(self.data.exists())
        self.assertFalse(legacy.is_symlink())
        self.assertTrue((shared/'auth.json').exists())

    def test_active_run_blocks_removal(self):
        slug = save_task(self.store, {'instructions':'saved', 'enabled':False})
        self.store.start_run(self.store.job(slug)['id'], 'manual:test', os.getpid(), process_start_ticks(os.getpid()))
        with self.assertRaisesRegex(ValueError, 'still running'):
            service.uninstall(self.data, self.prefix)
        self.assertTrue(self.bundle.exists())

    def test_custom_purge_refused_before_mutation(self):
        with self.assertRaisesRegex(ValueError, 'default data'):
            service.uninstall(self.home, self.prefix, purge_data=True)
        self.assertTrue(self.bundle.exists())

    def test_launcher_does_not_require_systemd(self):
        with patch('subprocess.run') as run:
            path = service.install_launcher(self.data, self.prefix)
        run.assert_not_called()
        self.assertIn('Name=OnCue', Path(path).read_text())
        self.assertIn('"open"', Path(path).read_text())

    def test_installer_does_not_overwrite_unrelated_binary(self):
        source = self.home/'source'; source.mkdir()
        (source/'oncue').write_text('#!/bin/sh\nexit 0\n')
        (source/'oncue').chmod(0o700)
        script = Path(__file__).resolve().parents[1]/'scripts/install_portable.sh'
        (source/'install.sh').write_text(script.read_text())
        command = self.prefix/'bin/oncue'
        command.unlink(); command.write_text('keep me')
        result = subprocess.run(['sh',str(source/'install.sh'),'--prefix',str(self.prefix)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unrelated command',result.stderr)
        self.assertEqual(command.read_text(),'keep me')

    def test_start_failure_rolls_back_existing_bundle(self):
        old = self.bundle/'oncue'
        old.write_text('#!/bin/sh\nexit 0\n'); old.chmod(0o700)
        source = self.home/'source'; source.mkdir()
        new = source/'oncue'
        new.write_text('#!/bin/sh\ncase "$1" in start) exit 9;; esac\nexit 0\n')
        new.chmod(0o700)
        script = Path(__file__).resolve().parents[1]/'scripts/install_portable.sh'
        (source/'install.sh').write_text(script.read_text())
        result = subprocess.run(['sh',str(source/'install.sh'),'--prefix',str(self.prefix),'--no-open'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Previous app restored',result.stderr)
        self.assertEqual(old.read_text(),'#!/bin/sh\nexit 0\n')
        self.assertTrue((self.data/'scheduler.sqlite3').exists())
        self.assertFalse((self.bundle.parent/'.install-lock').exists())

    def test_corrupt_archive_rejected_before_installation(self):
        archive = self.home/'oncue-linux-x86_64.tar.gz'
        archive.write_bytes(b'corrupt download')
        Path(str(archive)+'.sha256').write_text('0'*64+'  '+archive.name+'\n')
        script = Path(__file__).resolve().parents[1]/'install.sh'
        result = subprocess.run(['sh',str(script),'--archive',str(archive),'--prefix',str(self.prefix)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Checksum mismatch',result.stderr)
        self.assertEqual((self.bundle/'oncue').read_text(),'executable')

    def test_uninstall_disables_startup(self):
        unit = self.home/'.config/systemd/user/oncue.service'
        unit.parent.mkdir(parents=True); unit.write_text('[Service]\n')
        with patch('subprocess.run') as run:
            service.uninstall(self.data,self.prefix)
        self.assertFalse(unit.exists())
        self.assertEqual(run.call_args_list[0].args[0],['systemctl','--user','disable','oncue.service'])
        self.assertEqual(run.call_args_list[1].args[0],['systemctl','--user','daemon-reload'])

    def test_frozen_custom_prefix_is_inferred(self):
        custom = self.home/'my apps'
        with patch.object(service.sys,'frozen',True,create=True), patch.object(service.sys,'executable',str(custom/'share/oncue/bin/oncue')):
            self.assertEqual(service.installation_prefix(),custom)
            launcher=service.install_launcher(self.data)
        self.assertEqual(Path(launcher),custom/'share/applications/oncue.desktop')
