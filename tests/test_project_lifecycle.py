import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import project_lifecycle as lifecycle


class ProjectLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(memory_hub_root=str(self.root), snapshot_output=str(self.root / 'snapshot.json'))
        self.project = dict(project='真实项目的测试副本', path='D:/work/项目', status='活跃',
            current_brief=dict(project='真实项目的测试副本', project_state='活跃', task_state='待验收',
                notice='独立任务', continuation='历史原文', sources=[], recent_tasks=[dict(receipt_id='MC-1')]))
        self.key = lifecycle.project_key(self.project)
        self.base = dict(projects=[self.project], recent_focus=[copy.deepcopy(self.project)],
            discovered_projects=[], activity_discovery=dict(confirmed=[], discovered=[], review=[]),
            metrics={}, decision_entries=[dict(receipt_id='MC-1'), dict(receipt_id='MC-other')],
            task_register=[dict(task='未验收任务', state='open')],
            confirmation_queue=[dict(key_files='D:/work/项目/file.md')])
        self.save(self.base)

    def save(self, snapshot):
        Path(self.config['snapshot_output']).write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')

    def change(self, state, revision=''):
        return lifecycle.change_state(self.config, dict(project_key=self.key, state=state, revision=revision))

    def projected(self, base=None):
        result = copy.deepcopy(base or self.base)
        lifecycle.apply_lifecycle(result, self.config)
        self.save(result)
        return result

    def test_pause_end_restore_is_persistent_and_preserves_unaccepted_tasks(self):
        pause = self.change('paused')
        result = self.projected()
        self.assertFalse(result['projects'])
        self.assertFalse(result['recent_focus'])
        self.assertEqual(result['archived_projects'][0]['current_brief']['task_state'], '待验收')
        self.assertEqual(result['task_register'], self.base['task_register'])
        end = self.change('ended', pause['event_id'])
        self.assertEqual(self.projected()['archived_projects'][0]['lifecycle']['state'], 'ended')
        self.change('active', end['event_id'])
        result = self.projected()
        self.assertEqual(len(result['projects']), 1)
        self.assertFalse(result['archived_projects'])
        self.assertTrue(list(lifecycle.ledger_path(self.config).parent.glob('write-snapshots/*.md')))

    def test_new_activity_does_not_reactivate_and_archive_outlives_activity_window(self):
        self.change('ended')
        self.assertFalse(self.projected()['recent_focus'])
        self.base['projects'] = []
        self.base['recent_focus'] = []
        result = self.projected()
        self.assertEqual(len(result['archived_projects']), 1)
        event = lifecycle.load_events(self.config)[self.key]
        self.change('active', event['event_id'])
        result = self.projected()
        self.assertEqual(result['discovered_projects'][0]['path'], self.project['path'])

    def test_stale_click_unknown_project_and_invalid_action_never_write(self):
        self.change('paused')
        before = lifecycle.ledger_path(self.config).read_bytes()
        for request in [dict(project_key=self.key, state='ended', revision=''),
                        dict(project_key='unknown', state='ended', revision=''),
                        dict(project_key=self.key, state='completed', revision='')]:
            with self.assertRaises(ValueError):
                lifecycle.change_state(self.config, request)
        self.assertEqual(before, lifecycle.ledger_path(self.config).read_bytes())

    def test_reminders_are_filtered_but_unrelated_decisions_remain(self):
        self.change('ended')
        result = self.projected()
        self.assertEqual(result['decision_entries'], [dict(receipt_id='MC-other')])
        self.assertFalse(result['confirmation_queue'])

    def test_corrupt_record_fails_closed(self):
        self.change('ended')
        path = lifecycle.ledger_path(self.config)
        path.write_text(path.read_text(encoding='utf-8').replace('ended', 'active'), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.projected()

    def test_concurrent_lock_rejected_and_preserved(self):
        path = lifecycle.ledger_path(self.config)
        path.parent.mkdir(parents=True)
        lock = path.with_suffix('.lock')
        lock.touch()
        with self.assertRaises(FileExistsError):
            self.change('ended')
        self.assertTrue(lock.exists())
        self.assertFalse(path.exists())

    def test_atomic_replace_failure_keeps_formal_record(self):
        self.change('paused')
        path = lifecycle.ledger_path(self.config)
        before = path.read_bytes()
        event = lifecycle.load_events(self.config)[self.key]
        with patch.object(lifecycle.os, 'replace', side_effect=OSError('write denied')):
            with self.assertRaises(OSError):
                self.change('ended', event['event_id'])
        self.assertEqual(before, path.read_bytes())
        self.assertFalse(path.with_suffix('.lock').exists())

    def test_path_aliases_share_decision_but_other_directory_does_not(self):
        self.assertEqual(self.key, lifecycle.project_key(dict(path='d:\\WORK\\项目\\')))
        self.assertEqual(self.key, lifecycle.project_key(dict(path='`D:/work/项目`')))
        self.assertNotEqual(self.key, lifecycle.project_key(dict(path='D:/work/项目2')))

    def test_index_pause_is_respected_but_phase_completion_is_not_archived(self):
        self.project['status'] = '阶段完成'
        self.assertFalse(self.projected()['archived_projects'])
        self.project['status'] = '暂停'
        self.assertEqual(self.projected()['archived_projects'][0]['lifecycle']['state'], 'paused')
        self.change('active')
        result = self.projected()
        self.assertEqual(result['projects'][0]['current_brief']['project_state'], '跟进中（本人恢复）')
        self.assertFalse(result['archived_projects'])

    def test_related_receipt_does_not_hide_another_projects_decision(self):
        self.project['current_brief']['basis'] = '关联成果回执（不改变本项目状态）'
        self.save(self.base)
        self.change('ended')
        self.assertEqual(self.projected()['decision_entries'], self.base['decision_entries'])

    def test_synthetic_project_full_builder_roundtrip_in_isolated_ledger(self):
        from test_build_operations_dashboard import dashboard
        from scripts import demo_server
        with patch.object(demo_server, 'ROOT', self.root / 'portable'):
            config = demo_server.initialize()
        initial = dashboard.build_snapshot(config)
        pages = [Path(config['project_index_file']), Path(config['current_tasks_file'])]
        before = [p.read_bytes() for p in pages]
        for name in ('团队月报',):
            row = next(p for p in initial['projects'] + initial['recent_focus'] + initial.get('archived_projects', []) if p['project'] == name)
            key = lifecycle.project_key(row)
            self.save(initial)
            ended = lifecycle.change_state(self.config, dict(project_key=key, state='ended', revision=''))
            with patch.object(dashboard, 'apply_lifecycle', side_effect=lifecycle.apply_lifecycle), patch.object(lifecycle, 'load_events', return_value=lifecycle.load_events(self.config)):
                closed = dashboard.build_snapshot(config)
            for group in ('projects', 'recent_focus', 'discovered_projects', 'recently_completed_projects'):
                self.assertFalse(any(lifecycle.project_key(p) == key for p in closed[group]), (name, group))
            self.assertTrue(any(lifecycle.project_key(p) == key for p in closed['archived_projects']))
            self.assertEqual(closed['task_register'], initial['task_register'])
            self.save(closed)
            lifecycle.change_state(self.config, dict(project_key=key, state='active', revision=ended['event_id']))
            with patch.object(dashboard, 'apply_lifecycle', side_effect=lifecycle.apply_lifecycle), patch.object(lifecycle, 'load_events', return_value=lifecycle.load_events(self.config)):
                restored = dashboard.build_snapshot(config)
            self.assertTrue(any(lifecycle.project_key(p) == key for p in restored['projects'] + restored['recent_focus']))
        self.assertEqual(before, [p.read_bytes() for p in pages])


if __name__ == '__main__':
    unittest.main()
