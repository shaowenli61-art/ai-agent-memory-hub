import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from test_build_operations_dashboard import dashboard


class ProjectDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '10-Daily').mkdir()
        self.config = dict(memory_hub_root=str(self.root), recent_work_days=7,
            discovery_project_roots=[str(self.root / 'projects')], focus_projects=[])
        self.now = datetime(2026, 10, 3, 16, tzinfo=timezone(timedelta(hours=8)))

    def packet(self, day, items):
        (self.root / '10-Daily' / f'{day}-ai-activity.json').write_text(
            json.dumps(dict(date=day, activities=items)), encoding='utf-8')

    def item(self, cwd, **extra):
        return dict(tool='Codex', cwd=cwd, titles=['session-one'], source='one.jsonl',
            user_prompts=['实现新功能'], assistant_notes=['新增功能已实现，待验收'],
            updated_at='2026-10-03T06:00:00Z', records=1, **extra)

    def project(self, name='测试项目', path='D:/known', status='活跃'):
        return dict(project=name, path=path, status=status, wikilink=name)

    def discover(self, projects=None, worklogs=None):
        return dashboard.discover_projects(self.config, self.now, projects or [], worklogs or [])

    def test_unknown_existing_workspace_is_discovered_and_subdirectories_merge(self):
        root = self.root / 'projects' / 'new-project'; root.mkdir(parents=True)
        self.packet('2026-10-03', [self.item(str(root / 'src')), self.item(str(root / '.worktrees' / 'fix'))])
        found = self.discover()['discovered']
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]['new_project'])
        self.assertEqual(found[0]['task'], 'new-project')
        self.assertEqual(found[0]['activity_days'], 1)

    def test_confirmed_focus_survives_no_recent_activity(self):
        self.config['focus_projects'] = [dict(name='手动重点', path='D:/known', order=0)]
        result = self.discover()
        self.assertEqual(result['confirmed'][0]['task'], '手动重点')
        self.assertEqual(result['confirmed'][0]['updated_at'], '')
        self.assertIn('暂无近期证据', result['confirmed'][0]['status'])

    def test_archive_alias_and_worktree_merge_into_current_project(self):
        projects = [self.project('旧别名', status='legacy'), self.project('当前项目')]
        self.packet('2026-10-03', [self.item('d:/known/.worktrees/fix'), self.item('D:\\KNOWN\\src')])
        found = self.discover(projects)['discovered']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['task'], '当前项目')
        self.assertEqual(len(found[0]['evidence']), 1)

    def test_noise_future_and_tool_only_records_do_not_create_activity(self):
        noise = dict(tool='MemPalace', cwd='身份与配置', titles=['身份与配置'], assistant_notes=['USER.md'])
        tool_only = dict(self.item('D:/known'), user_prompts=[], assistant_notes=[], tool_counts={'read':1000})
        future = dict(self.item('D:/known'), updated_at='2026-10-03T18:00:00+08:00')
        self.packet('2026-10-03', [noise, tool_only, future])
        self.packet('2026-10-04', [self.item('D:/known')])
        self.assertEqual(self.discover([self.project()])['discovered'], [])

    def test_paused_project_activity_is_reviewed_without_automatic_resume(self):
        self.packet('2026-10-03', [self.item('D:/known')])
        result = self.discover([self.project(status='暂停')])
        self.assertEqual(result['discovered'], [])
        self.assertIn('生命周期待核对', result['review'][0]['reason'])

    def test_antigravity_title_overrides_stale_photo_workspace(self):
        self.config['focus_projects'] = [dict(name='数字孪生', path='D:/twin', aliases=['Digital Twin']),
            dict(name='个人写真', path='D:/photo', aliases=['写真'])]
        item = dict(self.item('D:/photo'), tool='Gemini Antigravity', titles=['Digital Twin Video'], assistant_notes=['巡览完成'])
        self.packet('2026-10-03', [item])
        result = self.discover()
        rows = {row['task']: row for row in result['confirmed']}
        twin, photo = rows['数字孪生'], rows['个人写真']
        self.assertTrue(twin['evidence'])
        self.assertIn('冲突', twin['evidence'][0]['assignment'])
        self.assertEqual(photo['evidence'], [])

    def test_raw_message_volume_and_duplicate_sessions_do_not_raise_rank(self):
        item = self.item('D:/known')
        self.packet('2026-10-03', [item])
        first = self.discover([self.project()])['discovered'][0]['score']
        self.packet('2026-10-03', [dict(item, records=100000)] * 50)
        second = self.discover([self.project()])['discovered'][0]
        self.assertEqual(first, second['score'])
        self.assertEqual(len(second['evidence']), 1)

    def test_completed_formal_delivery_without_new_activity_is_not_active(self):
        log = dict(date='2026-10-03', updated_at='2026-10-03T15:00:00+08:00',
            title='测试项目版本封存', key_files='D:/known/report.md', evidence='', source='worklog.md',
            status='已完成', completed='已封存', unfinished='未来开发未启动', next_action='未来明确提出再开发')
        row = self.discover([self.project()], [log])['discovered'][0]
        self.assertFalse(row['active_candidate'])
        self.assertIn('暂无新推进', row['status'])

    def test_corrupt_packet_is_visible_and_does_not_destroy_other_results(self):
        self.packet('2026-10-03', [self.item('D:/known')])
        (self.root / '10-Daily' / '2026-10-02-ai-activity.json').write_text('{broken', encoding='utf-8')
        result = self.discover([self.project()])
        self.assertEqual(len(result['discovered']), 1)
        self.assertEqual(len(result['warnings']), 1)

    def test_timezones_are_compared_as_instants_and_multiday_support_is_counted(self):
        self.packet('2026-10-02', [dict(self.item('D:/known'), updated_at='2026-10-02T12:00:00+08:00')])
        self.packet('2026-10-03', [dict(self.item('D:/known'), updated_at='2026-10-03T14:00:00+08:00'),
            dict(self.item('D:/known'), source='two.jsonl', titles=['session-two'], updated_at='2026-10-03T07:00:00Z', assistant_notes=['最新进展'])])
        row = self.discover([self.project()])['discovered'][0]
        self.assertEqual(row['activity_days'], 2)
        self.assertEqual(row['progress'], '最新进展')
        self.assertIn('持续跟进', row['status'])

    def test_duplicate_session_retains_newest_instant_across_timezones(self):
        self.packet('2026-10-03', [dict(self.item('D:/known'), updated_at='2026-10-03T14:00:00+08:00', assistant_notes=['较早记录']),
            dict(self.item('D:/known'), updated_at='2026-10-03T07:00:00Z', assistant_notes=['最新记录'])])
        row = self.discover([self.project()])['discovered'][0]
        self.assertEqual(len(row['evidence']), 1)
        self.assertEqual(row['progress'], '最新记录')
