from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_operations_dashboard.py"
SPEC = importlib.util.spec_from_file_location("build_operations_dashboard", MODULE_PATH)
assert SPEC and SPEC.loader
dashboard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dashboard
SPEC.loader.exec_module(dashboard)


class OperationsDashboardTests(unittest.TestCase):
    def test_markdown_tables_extracts_named_columns(self) -> None:
        text = """
| 状态 | 任务 | 主 agent | 证据路径 |
| --- | --- | --- | --- |
| 进行中 | 测试任务 | Codex | [[证据]] |
"""
        rows = dashboard.table_with_columns(text, ("状态", "任务", "主 agent"))
        self.assertEqual(
            rows,
            [{"状态": "进行中", "任务": "测试任务", "主 agent": "Codex", "证据路径": "[[证据]]"}],
        )

    def test_markdown_table_preserves_aliased_wikilink_as_one_cell(self) -> None:
        text = """
| 项目 | 状态 | 下一步 |
| --- | --- | --- |
| [[销售看板Skill|销售看板]] | 活跃·持续改进 | 等待体验确认 |
"""
        rows = dashboard.table_with_columns(text, ("项目", "状态", "下一步"))
        self.assertEqual(
            rows,
            [
                {
                    "项目": "[[销售看板Skill|销售看板]]",
                    "状态": "活跃·持续改进",
                    "下一步": "等待体验确认",
                }
            ],
        )


    def test_recommendations_distinguish_fact_inference_and_hypothesis(self) -> None:
        snapshot = {
            "metrics": {
                "blocked_tasks": 1,
                "overdue_tasks": 1,
                "decision_queue": 2,
                "emerging_projects": 1,
                "projects_to_verify": 4,
                "meeting_actions_to_verify": 2,
            },
            "windows": {"recent_work_days": 7, "project_review_days": 21},
            "capability_gaps": [
                {"priority": "P0", "capability": "因果推断", "importance": "业务价值", "starting_point": ""}
            ],
            "sources": [],
        }
        result = dashboard.recommendation_rules(snapshot)
        self.assertGreaterEqual(
            {item["type"] for item in result},
            {"事实驱动", "推断", "证据驱动"},
        )






    def test_log_candidates_surface_unregistered_plan_and_unfinished_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            daily = memory_root / "10-Daily"
            daily.mkdir()
            (daily / "2026-08-29-plan.md").write_text(
                """
# 2026-08-29 今日计划

## 建议推进
- 进行中：未登记数据治理专项（主 agent：Codex，证据：D:\\evidence\\semantic.md）
- 进行中：已登记任务（主 agent：Codex，证据：D:\\evidence\\registered.md）
- 阶段完成：已经完成的旧事项（主 agent：Codex，证据：D:\\evidence\\old.md）
""".strip(),
                encoding="utf-8",
            )
            (daily / "2026-08-20-worklog.md").write_text(
                """
## 任务收工：公司语义层生产覆盖
- **当前状态**：阶段完成
- **尚未完成**：正式生产计划、质量/反料、逐月库存尚未接入
- **下一步动作**：补齐生产计划、质量/反料和库存语义并完成验收
""".strip(),
                encoding="utf-8",
            )

            worklogs = dashboard.load_worklog_entries(
                memory_root, datetime(2026, 8, 29, tzinfo=timezone.utc)
            )
            candidates = dashboard.load_log_candidates(
                memory_root,
                [],
                worklogs,
                [{"task": "已登记任务"}],
                [],
                datetime(2026, 8, 29, tzinfo=timezone.utc),
                45,
                8,
            )

            titles = {candidate["title"] for candidate in candidates}
            self.assertIn("未登记数据治理专项", titles)
            self.assertIn("公司语义层生产覆盖", titles)
            self.assertNotIn("已经完成的旧事项", titles)
            self.assertEqual(
                next(candidate for candidate in candidates if candidate["title"] == "未登记数据治理专项")["candidate_kind"],
                "计划候选",
            )
            self.assertEqual(
                next(candidate for candidate in candidates if candidate["title"] == "公司语义层生产覆盖")["candidate_kind"],
                "已完成任务的后续",
            )

    def test_worklog_parser_reads_active_progress_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            daily = memory_root / "10-Daily"
            daily.mkdir()
            (daily / "2026-08-30-worklog.md").write_text(
                """
## 任务推进：企业销售问答后续优化
- **当前状态**：进行中
- **尚未完成**：完成七天观察和首个业务场景写入
- **下一步动作**：继续观察并准备用户验收
""".strip(),
                encoding="utf-8",
            )

            worklogs = dashboard.load_worklog_entries(
                memory_root, datetime(2026, 8, 30, tzinfo=timezone.utc)
            )

            self.assertEqual(len(worklogs), 1)
            self.assertEqual(worklogs[0]["title"], "企业销售问答后续优化")
            self.assertEqual(worklogs[0]["status"], "进行中")

    def test_log_candidates_surface_follow_up_linked_to_existing_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            daily = memory_root / "10-Daily"
            daily.mkdir()
            (daily / "2026-08-29-worklog.md").write_text(
                """
## 任务收工：知识库部署与后续治理
- **收工回执**：MC-20260829-KB
- **当前状态**：已完成
- **尚未完成**：继续观察影子链路
- **下一步动作**：完成七天稳定观察
- **关键文件**：D:\\workspace\\enterprise-kb
""".strip(),
                encoding="utf-8",
            )

            worklogs = dashboard.load_worklog_entries(
                memory_root, datetime(2026, 8, 30, tzinfo=timezone.utc)
            )
            candidates = dashboard.load_log_candidates(
                memory_root,
                [{"project": "企业销售问答", "path": "D:\\workspace\\enterprise-kb"}],
                worklogs,
                [],
                [],
                datetime(2026, 8, 30, tzinfo=timezone.utc),
                45,
                8,
            )

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["candidate_kind"], "已完成任务的后续")
            self.assertEqual(candidates[0]["title"], "知识库部署与后续治理")

    def test_log_candidates_skip_follow_up_covered_by_open_task_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            daily = memory_root / "10-Daily"
            daily.mkdir()
            (daily / "2026-08-29-worklog.md").write_text(
                """
## 任务收工：知识库部署与后续治理
- **收工回执**：MC-20260829-KB
- **当前状态**：阶段完成
- **尚未完成**：继续观察影子链路
- **下一步动作**：完成七天稳定观察
- **关键文件**：D:\\workspace\\enterprise-kb
""".strip(),
                encoding="utf-8",
            )

            worklogs = dashboard.load_worklog_entries(
                memory_root, datetime(2026, 8, 30, tzinfo=timezone.utc)
            )
            candidates = dashboard.load_log_candidates(
                memory_root,
                [{"project": "企业销售问答", "path": "D:\\workspace\\enterprise-kb"}],
                worklogs,
                [
                    {
                        "task": "知识库稳定观察",
                        "status": "待接手",
                        "evidence": "MC-20260829-KB; D:\\evidence\\acceptance.md",
                    }
                ],
                [],
                datetime(2026, 8, 30, tzinfo=timezone.utc),
                45,
                8,
            )

            self.assertEqual(candidates, [])

    def test_task_ledger_preserves_original_scope_and_deferred_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "scope.md"
            source.write_text(
                """
---
title: 销售看板优化清单
tasks_total: 4
tasks_completed: 1
tasks_in_current_scope: 3
tasks_excluded_from_current_scope: 1
---

| 任务 | 工作项 | 当前状态 |
|---|---|---|
| T01 | 已闭环代码精简 | 已完成 |
| T02 | 非规则层性能优化 | 进行中 |
| T03 | 用户仓储迁移 | 不纳入本次 |
| T04 | 生产验收 | 本阶段已完成；跨阶段保留 |
""".strip(),
                encoding="utf-8",
            )
            task = {
                "task": "销售看板优化收尾",
                "evidence_targets": [dashboard.evidence_target(source, [])],
            }

            ledgers = dashboard.build_task_ledgers([task])

            self.assertEqual(len(ledgers), 1)
            ledger = ledgers[0]
            self.assertEqual(
                (ledger["total"], ledger["completed"], ledger["deferred"], ledger["open"]),
                (4, 1, 1, 2),
            )
            self.assertEqual(ledger["needs_review"], 1)
            self.assertTrue(ledger["conserved"])
            self.assertEqual(
                next(item for item in ledger["items"] if item["id"] == "T03")["ledger_state"],
                "deferred",
            )

    def test_omission_rules_feed_one_read_only_confirmation_queue(self) -> None:
        tasks = [
            {
                "task": "缺负责人任务",
                "status": "进行中",
                "agent": "—",
                "evidence": "",
                "source_path": "current.md",
                "source_target": {"path": "current.md", "exists": True},
                "evidence_targets": [],
                "open": True,
            }
        ]
        ledgers = [
            {
                "id": "ledger-1",
                "title": "范围不守恒清单",
                "total": 5,
                "completed": 1,
                "deferred": 1,
                "open": 2,
                "metadata_completed": 1,
                "metadata_deferred": 1,
                "current_scope": 4,
                "conserved": False,
                "source_target": {"path": "scope.md", "exists": True},
            }
        ]
        candidates = [
            {
                "date": "2026-09-07",
                "title": "阶段完成后的生产验收",
                "status": "阶段完成",
                "candidate_kind": "已完成任务的后续",
                "unfinished": "生产验收未完成",
                "next_action": "确认是否继续推进生产验收",
                "receipt_id": "MC-20260907-TEST",
                "source": "worklog.md",
                "source_target": {"path": "worklog.md", "exists": True},
                "evidence_targets": [],
            }
        ]

        worklogs = [
            {
                "title": "缺负责人任务",
                "status": "已完成",
                "unfinished": "无",
                "date": "2026-09-07",
                "updated_at": "2026-09-07T12:00:00+08:00",
            }
        ]
        findings = dashboard.build_omission_findings(tasks, ledgers, candidates, worklogs)
        decisions = [
            {
                "title": "同一正式决策",
                "receipt_id": "MC-20260907-NEW",
                "updated_at": "2026-09-07T13:00:00+08:00",
                "date": "2026-09-07",
                "status": "待确认",
                "next_action": "采用较新记录",
            },
            {
                "title": "同一正式决策",
                "receipt_id": "MC-20260907-OLD",
                "updated_at": "2026-09-07T12:00:00+08:00",
                "date": "2026-09-07",
                "status": "待确认",
                "next_action": "旧记录",
            },
        ]
        queue = dashboard.build_confirmation_queue(decisions, candidates, findings)

        rules = {item["rule"] for item in findings}
        self.assertGreaterEqual(
            rules,
            {"missing_owner", "missing_evidence", "scope_conservation", "phase_follow_up", "status_conflict"},
        )
        self.assertEqual(
            sum(item["title"] == "阶段完成后的生产验收" for item in queue),
            1,
        )
        deduplicated_decision = [item for item in queue if item["title"] == "同一正式决策"]
        self.assertEqual(len(deduplicated_decision), 1)
        self.assertEqual(deduplicated_decision[0]["next_action"], "采用较新记录")
        self.assertTrue(all(item["read_only"] for item in queue))



    def test_project_prefers_newer_path_match_over_older_title_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            project_dir = memory_root / "20-Projects"
            project_dir.mkdir()
            (project_dir / "销售看板Skill.md").write_text(
                "# 销售看板\n",
                encoding="utf-8",
            )
            project = {
                "project": "销售看板",
                "wikilink": "销售看板Skill",
                "status": "活跃·持续改进",
                "path": "D:\\workspace\\sales-dashboard-skill",
                "next_step": "旧下一步",
            }
            worklogs = [
                {
                    "date": "2026-09-06",
                    "updated_at": "2026-09-06T18:00:00+08:00",
                    "title": "销售看板安全审计",
                    "status": "阶段完成",
                    "unfinished": "后续实施安全整改",
                    "next_action": "执行旧整改",
                    "key_files": "",
                    "evidence": "",
                    "source": "older.md",
                },
                {
                    "date": "2026-09-07",
                    "updated_at": "2026-09-07T15:25:24+08:00",
                    "title": "客户归属更新联动",
                    "status": "等待外部归属更新",
                    "unfinished": "等待业务侧提供客户归属清单",
                    "next_action": "取得清单后更新销售看板",
                    "key_files": "D:\\workspace\\sales-dashboard-skill",
                    "evidence": "",
                    "source": "newer.md",
                },
            ]

            result = dashboard.classify_projects(
                [project],
                worklogs,
                memory_root,
                datetime(2026, 9, 7, tzinfo=timezone.utc),
                7,
                21,
            )[0]

            self.assertEqual(result["latest_evidence_date"], "2026-09-07")
            self.assertEqual(result["latest_worklog"], "newer.md")
            self.assertEqual(result["operating_state"], "待验收/待决策")
            self.assertEqual(result["decision"], "取得清单后更新销售看板")

    def test_phase_complete_with_meaningful_remaining_work_stays_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            project_dir = memory_root / "20-Projects"
            project_dir.mkdir()
            (project_dir / "销售看板Skill.md").write_text(
                "# 销售看板\n",
                encoding="utf-8",
            )
            project = {
                "project": "销售看板",
                "wikilink": "销售看板Skill",
                "status": "活跃·持续改进",
                "path": "D:\\workspace\\sales-dashboard-skill",
                "next_step": "旧下一步",
            }
            worklog = {
                "date": "2026-09-07",
                "updated_at": "2026-09-07T15:25:24+08:00",
                "title": "销售看板客户调整阶段提交",
                "status": "阶段完成",
                "unfinished": "等待业务侧补齐客户编码和生效日期",
                "next_action": "业务侧提供清单后继续更新",
                "key_files": "D:\\workspace\\sales-dashboard-skill",
                "evidence": "",
                "source": "worklog.md",
            }

            result = dashboard.classify_projects(
                [project],
                [worklog],
                memory_root,
                datetime(2026, 9, 7, tzinfo=timezone.utc),
                7,
                21,
            )[0]

            self.assertEqual(result["operating_state"], "待验收/待决策")
            self.assertEqual(result["decision"], "业务侧提供清单后继续更新")

    def test_project_receipt_index_prevents_cross_project_title_false_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_root = Path(temporary_directory)
            project_dir = memory_root / "20-Projects"
            project_dir.mkdir()
            (project_dir / "销售看板Skill.md").write_text(
                """
# 销售看板

## 收工回执索引
| 日期 | 回执 ID | 任务 |
| --- | --- | --- |
| 2026-09-07 | `MC-20260907-SALES` | 销售看板安全整改 |
""".strip(),
                encoding="utf-8",
            )
            project = {
                "project": "销售看板",
                "wikilink": "销售看板Skill",
                "status": "活跃·持续改进",
                "path": "D:\\workspace\\sales-dashboard-skill",
                "next_step": "旧下一步",
            }
            worklogs = [
                {
                    "date": "2026-09-07",
                    "updated_at": "2026-09-07T15:43:42+08:00",
                    "receipt_id": "MC-20260907-SALES",
                    "title": "销售看板安全整改实施",
                    "status": "待接手",
                    "unfinished": "实施生产安全整改",
                    "next_action": "按P0顺序实施安全整改",
                    "key_files": "D:\\workspace\\sales-dashboard-skill",
                    "evidence": "",
                    "source": "sales.md",
                },
                {
                    "date": "2026-09-07",
                    "updated_at": "2026-09-07T15:47:19+08:00",
                    "receipt_id": "MC-20260907-WORKBENCH",
                    "title": "桌面工作台销售看板待办进度修正",
                    "status": "已完成",
                    "unfinished": "无",
                    "next_action": "正常使用桌面工作台",
                    "key_files": "D:\\workspace\\global-workbench",
                    "evidence": "",
                    "source": "workbench.md",
                },
            ]

            result = dashboard.classify_projects(
                [project],
                worklogs,
                memory_root,
                datetime(2026, 9, 7, tzinfo=timezone.utc),
                7,
                21,
            )[0]

            self.assertEqual(result["latest_worklog"], "sales.md")
            self.assertEqual(result["decision"], "按P0顺序实施安全整改")








    def test_owner_alias_does_not_match_parenthetical_reminder(self) -> None:
        self.assertTrue(dashboard.owner_mentions_alias("体验用户 / 示例同事", "体验用户"))
        self.assertFalse(dashboard.owner_mentions_alias("示例同事（体验用户提醒）", "体验用户"))



if __name__ == "__main__":
    unittest.main()
