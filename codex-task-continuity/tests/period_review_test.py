import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "period-review.py"


class PeriodReviewTest(unittest.TestCase):
    def test_builds_project_specific_weekly_review_with_harness_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "task-ledger"
            activity = ledger / "activity"
            weekly = ledger / "digests" / "weekly"
            activity.mkdir(parents=True)
            weekly.mkdir(parents=True)

            self.write_activity(
                activity / "2026-07-14.json",
                "2026-07-14",
                [
                    {
                        "project_name": "GEO 智能诊断平台",
                        "project_path": "/Users/test/projects/GEO",
                        "thread_id": "thread-geo",
                        "title": "研究核心重构",
                        "status": "in_progress",
                        "summary": "完成研究数据契约。",
                        "next_action": "完成真实品牌研究快照。",
                    }
                ],
            )
            self.write_activity(
                activity / "2026-07-17.json",
                "2026-07-17",
                [
                    {
                        "project_name": "GEO 智能诊断平台",
                        "project_path": "/Users/test/projects/GEO",
                        "thread_id": "thread-geo",
                        "title": "工作台交付",
                        "status": "delivered_pending_trial",
                        "summary": "工作台已交付并完成浏览器验收。",
                        "next_action": "实际浏览蔚来案例并反馈业务问题。",
                    },
                    {
                        "project_name": "YA FundMind",
                        "project_path": "/Users/test/projects/ya-fundmind",
                        "thread_id": "thread-fund",
                        "title": "V2 Final",
                        "status": "in_progress",
                        "summary": "v2.0.0 已发布，前端轨道继续开发。",
                        "next_action": "完成 v2.1.0 合并前验证。",
                    },
                ],
            )
            (activity / "2026-07-10.json").write_text(
                json.dumps({"date": "2026-07-10", "activities": {"old": {
                    "project_name": "旧项目", "status": "completed", "summary": "旧周内容"
                }}}),
                encoding="utf-8",
            )

            (weekly / "2026-07-13_to_2026-07-19.md").write_text(
                """# Codex 周归档

## 周期任务运行状态

- **正常**：YA FundMind / 每日投研运行
  判断：2026-07-17 已取得新鲜成功证据
  下次计划：2026-07-18T21:30:00+08:00
""",
                encoding="utf-8",
            )

            operation_ledger = root / "operation-ledger.jsonl"
            workflow_events = [
                {
                    "occurred_at": "2026-07-16T08:00:00+08:00",
                    "scope": "global_workflow",
                    "category": "skill",
                    "action": "skill_updated",
                    "actor": {"label": "codex-context-summary-hook"},
                    "title": "Skill 已更新",
                    "summary": "补充上下文压缩后的任务恢复信息。",
                },
                {
                    "occurred_at": "2026-07-16T09:00:00+08:00",
                    "scope": "global_workflow",
                    "category": "automation",
                    "action": "automation_updated",
                    "actor": {"label": "codex"},
                    "title": "Automation 已更新",
                    "summary": (
                        "codex：执行计划由「RRULE:FREQ=DAILY」改为「RRULE:FREQ=DAILY」；"
                        "设置投递目标为「019f3b58-217f-74b1-923e-ae10bf0e9ad0」；"
                        "前一日工作采集；临时图片安全清理。"
                    ),
                },
                {
                    "occurred_at": "2026-07-16T10:00:00+08:00",
                    "scope": "global_workflow",
                    "category": "hook",
                    "action": "hook_updated",
                    "actor": {"label": "task-continuity-hook"},
                    "title": "Hook 已更新",
                    "summary": "等待条件与续作监控；自动恢复动作；用途与可识别能力未变化。",
                },
                {
                    "occurred_at": "2026-07-16T11:00:00+08:00",
                    "scope": "global_workflow",
                    "category": "automation",
                    "action": "automation_added",
                    "actor": {"label": "temporary-rc-monitor"},
                    "title": "Automation 已新增",
                    "summary": "任务台账管理。",
                },
                {
                    "occurred_at": "2026-07-17T11:00:00+08:00",
                    "scope": "global_workflow",
                    "category": "automation",
                    "action": "automation_deleted",
                    "actor": {"label": "temporary-rc-monitor"},
                    "title": "Automation 已删除",
                    "summary": "设置投递目标为「thread-internal-id」。",
                },
            ]
            operation_ledger.write_text(
                "".join(
                    json.dumps(event, ensure_ascii=False) + "\n"
                    for event in workflow_events
                ),
                encoding="utf-8",
            )

            learning = root / "error-learning"
            learning.mkdir()
            observations = {
                "version": 1,
                "observations": {
                    "one": {
                        "date": "2026-07-15",
                        "thread_id": "thread-a",
                        "categories": ["user_visibility_gap"],
                    },
                    "two": {
                        "date": "2026-07-16",
                        "thread_id": "thread-b",
                        "categories": ["user_visibility_gap"],
                    },
                },
            }
            (learning / "observations.json").write_text(
                json.dumps(observations, ensure_ascii=False), encoding="utf-8"
            )
            candidates = {
                "version": 1,
                "candidates": {
                    "user_visibility_gap": {
                        "title": "内部产物缺少用户可见交付",
                        "root_cause": "完成标准停留在内部产物生成。",
                        "status": "monitoring",
                        "thread_ids": ["thread-a", "thread-b"],
                        "next_action": "补充投递与消费回归场景。",
                        "next_check_at": "2026-07-27",
                        "periods": ["2026-07-13_to_2026-07-19"],
                    }
                },
            }
            (learning / "candidates.json").write_text(
                json.dumps(candidates, ensure_ascii=False), encoding="utf-8"
            )

            patterns = root / "patterns"
            patterns.mkdir()
            (patterns / "candidates.json").write_text(
                json.dumps(
                    {
                        "candidates": {
                            "thread-continuity": {
                                "title": "线程接续与项目空间迁移",
                                "status": "observed",
                                "periods": ["2026-07-13_to_2026-07-19"],
                                "weeks_seen": 1,
                                "existing_skills": ["codex-task-continuity"],
                                "recommended_action": "update_existing",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output = root / "reviews"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--today",
                    "2026-07-20",
                    "--previous-week",
                    "--task-ledger-dir",
                    str(ledger),
                    "--operation-ledger",
                    str(operation_ledger),
                    "--error-learning-dir",
                    str(learning),
                    "--workflow-pattern-dir",
                    str(patterns),
                    "--output-dir",
                    str(output),
                    "--stdout",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            card = result.stdout
            self.assertIn("2026-07-13 至 2026-07-19", card)
            self.assertIn("GEO 智能诊断平台", card)
            self.assertIn("实际浏览蔚来案例", card)
            self.assertIn("YA FundMind / 每日投研运行", card)
            self.assertIn("codex-context-summary-hook", card)
            self.assertIn("Codex 每日摘要 Automation", card)
            self.assertIn("日报事实采集、临时产物清理与历史去重", card)
            self.assertIn("codex-task-continuity（Skill + 配套 Hook）", card)
            self.assertIn("等待目标监控、自动续作与安全并行", card)
            self.assertIn("2 个独立任务", card)
            self.assertIn("完成标准停留在内部产物生成", card)
            self.assertIn("已有承载 `codex-task-continuity`", card)
            self.assertNotIn("旧周内容", card)
            self.assertNotIn("/projects/GEO", card)
            self.assertNotIn("证据不足", card)
            self.assertNotIn("RRULE", card)
            self.assertNotIn("019f3b58", card)
            self.assertNotIn("temporary-rc-monitor", card)
            self.assertNotIn("用途与可识别能力未变化", card)
            self.assertNotIn("内容已调整", card)
            self.assertTrue((output / "2026-07-13_to_2026-07-19.md").exists())
            payload = json.loads(
                (output / "2026-07-13_to_2026-07-19.json").read_text(encoding="utf-8")
            )
            self.assertEqual(2, len(payload["projects"]))

    @staticmethod
    def write_activity(path, date, activities):
        payload = {
            "date": date,
            "activities": {str(index): item for index, item in enumerate(activities)},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
