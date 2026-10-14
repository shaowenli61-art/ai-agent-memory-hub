import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.project_brief import build_brief, load_receipts, no_remaining, enrich_briefs


class ProjectBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = self.root / '20-Projects' / '测试项目.md'
        self.page.parent.mkdir()
        self.page.write_text('---\nproject_id: test\n---\n## 目标\n- 交付可复用成果\n', encoding='utf-8')
        self.project = dict(project='测试项目', path=str(self.root / 'work'), status='活跃',
                            project_page=str(self.page), next_step='索引下一步')
        self.now = datetime(2026, 10, 10, tzinfo=timezone.utc)

    def receipt(self, **changes):
        row = dict(schema_version=3, task_id='TK-1', project_id='test', scope='project:test',
            receipt_id='MC-1', timestamp='2026-10-09T10:00:00+08:00', project_page=str(self.page),
            task='本次工作', state='已完成', completed='完成可追溯交付',
            remaining='无本轮必须遗留项；后续扩展另行安排。', next_action='按反馈继续',
            risks='不得覆盖原文件', avoid_repeat='发布需另行授权', files='', evidence='')
        row.update(changes)
        row['record_hash'] = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        return row

    def write(self, rows):
        path = self.root / '50-Agent-Workflows' / '90-Logs' / 'memory-close-receipts.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
        return load_receipts(self.root, self.now)

    def target(self, path):
        return dict(path=str(path), uri='', exists=path.exists())

    def brief(self, rows=None, activities=None, project=None):
        receipts, _ = self.write(rows or [self.receipt()])
        return build_brief(project or self.project, activities or [], receipts, self.root, self.now, self.target)

    def test_task_completion_does_not_complete_project_and_preserves_boundaries(self):
        brief = self.brief()
        self.assertEqual(brief['project_state'], '活跃')
        self.assertEqual(brief['task_state'], '已完成')
        self.assertIn('无必须遗留', brief['remaining_kind'])
        self.assertIn('发布需另行授权', brief['continuation'])
        self.assertIn('MC-1', brief['continuation'])
        self.assertIn('不是执行授权', brief['continuation'])

    def test_absence_of_work_is_not_inferred_from_no_deploy_or_mixed_remaining(self):
        self.assertTrue(no_remaining('本次视觉确认无未完成项；发布另行安排。'))
        self.assertTrue(no_remaining('无本轮必须遗留项；扩展后续安排'))
        self.assertFalse(no_remaining('无需部署，但仍需验收'))
        self.assertFalse(no_remaining('无外部数据，需补齐数据'))
        self.assertFalse(no_remaining('无；但仍需补验收'))
        self.assertFalse(no_remaining(''))

    def test_corrupt_future_and_unversioned_receipts_do_not_become_facts(self):
        bad = self.receipt(); bad['completed'] = '篡改后的成功'
        future = self.receipt(timestamp='2027-01-01T00:00:00+08:00')
        old = self.receipt(schema_version=2)
        rows, warnings = self.write([bad, future, old, self.receipt()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(warnings), 1)

    def test_related_file_does_not_transfer_project_acceptance(self):
        row = self.receipt(project_page=str(self.page.parent / '另一个项目.md'),
                           files=str(self.root / 'work' / '未找到.mp4'))
        brief = self.brief([row])
        self.assertIn('关联成果', brief['basis'])
        self.assertEqual(brief['next_action'], '索引下一步')
        self.assertIn('不代表本项目已验收', brief['continuation'])
        self.assertFalse(brief['artifacts'][0]['exists'])

    def test_new_chat_cannot_override_formal_completion(self):
        activities = [dict(kind='conversation', updated_at='2026-10-10T01:00:00Z',
                           progress='我认为所有任务都已完成', source='activity.md')]
        brief = self.brief(activities=activities)
        self.assertEqual(brief['summary'], '完成可追溯交付')
        self.assertIn('未确认活动', brief['continuation'])

    def test_protocol_noise_does_not_become_progress(self):
        activities = [dict(kind='conversation', updated_at='2026-10-10T01:00:00Z',
                           progress='我非常清楚记忆中枢同步规范，执行 memory_close.py', source='activity.md')]
        self.assertIsNone(self.brief(activities=activities)['activity'])

    def test_paused_project_only_prepares_review_and_multiple_tasks_stay_separate(self):
        brief = self.brief([self.receipt(), self.receipt(task_id='TK-2', task='其他任务',
            receipt_id='MC-2', state='受阻', timestamp='2026-10-08T10:00:00+08:00')],
            project=dict(self.project, status='暂停'))
        self.assertIn('不恢复项目', brief['next_action'])
        self.assertEqual(len(brief['recent_tasks']), 2)
        self.assertIn('受阻', brief['continuation'])

    def test_formal_source_is_unchanged_and_focus_uses_same_brief(self):
        self.write([self.receipt()])
        original = self.page.read_bytes()
        focus = [dict(path=self.project['path'], activity_evidence=[])]
        enrich_briefs([self.project], focus, dict(memory_hub_root=str(self.root)), self.now, self.target)
        self.assertEqual(original, self.page.read_bytes())
        self.assertIs(focus[0]['current_brief'], self.project['current_brief'])
        self.assertNotIn('memory_close.py', focus[0]['progress'])

    def test_missing_receipts_and_goals_stay_explicit(self):
        project = dict(project='新项目', path='/missing', status='未登记')
        brief = build_brief(project, [], [], self.root, self.now, self.target)
        self.assertIn('尚未提取', brief['goal'])
        self.assertIn('未找到', brief['summary'])
        self.assertEqual(brief['project_state'], '未登记')

    def test_project_goal_alias_and_project_boundaries_are_carried_forward(self):
        self.page.write_text('---\nproject_id: test\n---\n## 项目目标\n面向真实工作\n'
                             '## 当前阻塞与边界\n- 正式版本内容不变\n', encoding='utf-8')
        brief = self.brief()
        self.assertEqual(brief['goal'], '面向真实工作')
        self.assertIn('正式版本内容不变', brief['continuation'])

    def test_packet_keeps_full_result_even_when_card_is_shortened(self):
        completed = '已完成界面和验证；' * 50 + '最终限制：不能代替真实用户验收。'
        brief = self.brief([self.receipt(completed=completed)])
        self.assertLess(len(brief['summary']), len(completed))
        self.assertIn(completed, brief['continuation'])


if __name__ == '__main__':
    unittest.main()
