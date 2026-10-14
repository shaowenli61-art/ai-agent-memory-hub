import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from test_build_operations_dashboard import dashboard


class RecentFocusTests(unittest.TestCase):
    def test_topic_evidence_overrides_stale_workspace_and_excludes_future(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); daily = root / '10-Daily'; daily.mkdir()
            item = dict(tool='Gemini Antigravity', source='conversation.db',
                        cwd='D:/photo', titles=['Digital Twin'], user_prompts=['优化合成氨巡览'],
                        assistant_notes=['高清巡览已生成'], updated_at='2026-10-03T14:00:00+08:00')
            (daily / '2026-10-03-ai-activity.json').write_text(json.dumps({'activities':[item]}),encoding='utf-8')
            (daily / '2026-10-04-ai-activity.json').write_text(json.dumps({'activities':[dict(item,titles=['写真'],assistant_notes=['写真完成'])]}),encoding='utf-8')
            config = dict(memory_hub_root=str(root),recent_work_days=7,focus_projects=[
                dict(name='数字孪生',path='D:/twin',aliases=['Digital Twin','合成氨','巡览']),
                dict(name='个人写真',path='D:/photo',aliases=['写真','头像'])])
            focus = dashboard.load_recent_focus(config,datetime(2026,10,3,15,tzinfo=timezone.utc),(root,))
            self.assertEqual([row['task'] for row in focus],['数字孪生'])
            self.assertEqual(focus[0]['status'],'近期跟进·待核实')
            self.assertTrue(focus[0]['activity_signal'])
            self.assertEqual(focus[0]['progress'],'高清巡览已生成')
