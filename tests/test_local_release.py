import json
import shutil
import tempfile
import unittest
from pathlib import Path
from scripts.build_local_release import build
from scripts.update_local_release import update,verify_package

class LocalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';(self.source/'memory_hub').mkdir(parents=True)
        (self.source/'launch.py').write_text('print("v2")\n',encoding='utf-8')
        (self.source/'memory_hub/a.py').write_text('version=2\n',encoding='utf-8')
        (self.source/'local-settings.json').write_text('{"private":true}',encoding='utf-8')
        (self.source/'demo-data').mkdir();(self.source/'demo-data/notes.md').write_text('private',encoding='utf-8')
        (self.source/'workbench/web/data').mkdir(parents=True);(self.source/'workbench/web/data/operations_snapshot.json').write_text('{}',encoding='utf-8')
        self.package=self.root/'new release';build(self.package,self.source)
        self.target=self.root/'installed';self.target.mkdir();(self.target/'launch.py').write_text('print("v1")\n',encoding='utf-8')
        self.vault=self.root/'outside-vault';self.vault.mkdir();(self.vault/'my-note.md').write_text('Keep my note',encoding='utf-8')
        (self.target/'local-settings.json').write_text(json.dumps(dict(mode='real',vault=str(self.vault))),encoding='utf-8')
    def test_source_package_excludes_settings_demo_and_runtime(self):
        manifest=verify_package(self.package)
        self.assertEqual({f['path'] for f in manifest['files']},{'launch.py','memory_hub/a.py'})
        self.assertFalse((self.package/'local-settings.json').exists())
        with self.assertRaises(ValueError):build(self.package,self.source)
    def test_verified_update_retains_settings_vault_and_has_usable_rollback(self):
        settings=(self.target/'local-settings.json').read_bytes();note=(self.vault/'my-note.md').read_bytes()
        receipt=update(self.package,self.target)
        self.assertEqual((self.target/'launch.py').read_text(encoding='utf-8'),'print("v2")\n')
        self.assertEqual(settings,(self.target/'local-settings.json').read_bytes());self.assertEqual(note,(self.vault/'my-note.md').read_bytes())
        update(Path(receipt['backup']),self.target)
        self.assertEqual((self.target/'launch.py').read_text(encoding='utf-8'),'print("v1")\n')
        self.assertEqual(settings,(self.target/'local-settings.json').read_bytes())
    def test_tampered_source_refused_before_replacing_any_file(self):
        before=(self.target/'launch.py').read_bytes();(self.package/'launch.py').write_text('tampered',encoding='utf-8')
        with self.assertRaises(ValueError):update(self.package,self.target)
        self.assertEqual(before,(self.target/'launch.py').read_bytes())
    def test_manifest_cannot_target_user_settings_or_parent_paths(self):
        for name in ('local-settings.json','../outside-vault/my-note.md','/outside.py'):
            manifest=json.loads((self.package/'release-files.json').read_text(encoding='utf-8'))
            manifest['files'][0]['path']=name;(self.package/'release-files.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaises(ValueError):verify_package(self.package)
    def test_mixed_vault_and_running_service_block_code_upgrade(self):
        marker=self.vault/'.memory-hub/server.json';marker.parent.mkdir();marker.write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):update(self.package,self.target)
        marker.unlink();(self.target/'20-Projects').mkdir()
        with self.assertRaises(ValueError):update(self.package,self.target)
