import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "task-ledger.py"


def run_ledger(args, ledger_dir):
    env = os.environ.copy()
    env["CODEX_TASK_LEDGER_DIR"] = str(ledger_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def load_json(stdout):
    return json.loads(stdout)


def fake_openai_token():
    return "sk-proj-" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


def fake_github_token():
    return "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


class TaskLedgerTest(unittest.TestCase):
    def test_repository_resolution_upserts_and_lists_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            base_args = [
                "record-repository-resolution",
                "--date",
                "2026-07-16",
                "--finding-id",
                "RC-EXAMPLE001",
                "--repository",
                "hd2yao/example",
                "--project-name",
                "示例项目",
                "--branch",
                "feature/demo",
                "--status",
                "active_deferred",
                "--stage",
                "功能仍在开发",
                "--summary",
                "对应任务今天仍在实现 API",
                "--next-action",
                "任务完成后自动创建 PR 并合并",
                "--thread-id",
                "thread-example",
                "--thread-title",
                "实现示例 API",
                "--evidence",
                "/internal/report.json",
                "--format",
                "json",
            ]

            first = run_ledger(base_args, ledger_dir)
            second = run_ledger(
                [
                    *base_args[:-4],
                    "--summary",
                    "API 和测试仍在同一任务中推进",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            listed = run_ledger(
                ["list-repository-resolutions", "--date", "2026-07-16", "--format", "json"],
                ledger_dir,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            resolutions = load_json(listed.stdout)["resolutions"]
            self.assertEqual(1, len(resolutions))
            self.assertEqual("active_deferred", resolutions[0]["status"])
            self.assertIn("仍在同一任务", resolutions[0]["summary"])
            self.assertEqual("/internal/report.json", resolutions[0]["evidence"])

    def test_repository_resolution_date_cannot_escape_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_ledger(
                [
                    "record-repository-resolution",
                    "--date",
                    "../escape",
                    "--finding-id",
                    "RC-1",
                    "--repository",
                    "example",
                    "--status",
                    "failed",
                    "--summary",
                    "失败",
                    "--format",
                    "json",
                ],
                Path(tmp) / "ledger",
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("invalid resolution date", result.stderr)

    def test_track_follow_up_upserts_by_thread_and_can_update_check_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            base_args = [
                "track-follow-up",
                "--thread-id",
                "thread-ya-fundmind",
                "--title",
                "YA FundMind V2 Final 观察",
                "--goal",
                "完成 3 次 post-RC 真实运行后发布 v2.0.0",
                "--wait-condition",
                "等待每日 21:30 scheduler run，当前 1/3",
                "--resume-mode",
                "auto",
                "--resume-action",
                "达到 3/3 后继续 Final 发布",
                "--parallel-action",
                "在独立 worktree 开发 Web Console",
                "--monitor-automation-id",
                "ya-fundmind-v2-rc-final",
                "--monitor-schedule",
                "每天 22:15",
                "--next-check-at",
                "2026-07-16T22:15:00+08:00",
                "--recurring-task-id",
                "ya-fundmind-daily",
                "--project-name",
                "YA FundMind",
                "--project-path",
                "/Users/dysania/program/AI/agent/ya-fundmind",
                "--format",
                "json",
            ]

            first = run_ledger(base_args, ledger_dir)
            second = run_ledger(
                [
                    *base_args[:-2],
                    "--parallel-action",
                    "继续 Web Console TDD 与响应式验收",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_item = load_json(first.stdout)["follow_up"]
            second_item = load_json(second.stdout)["follow_up"]
            self.assertEqual(first_item["id"], second_item["id"])

            listed = run_ledger(
                ["list-follow-ups", "--status", "watching", "--format", "json"],
                ledger_dir,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            follow_ups = load_json(listed.stdout)["follow_ups"]
            self.assertEqual(1, len(follow_ups))
            self.assertEqual("auto", follow_ups[0]["resume_mode"])
            self.assertEqual("ya-fundmind-v2-rc-final", follow_ups[0]["monitor"]["automation_id"])
            self.assertIn("响应式验收", follow_ups[0]["parallel_action"])

            updated = run_ledger(
                [
                    "update-follow-up",
                    first_item["id"],
                    "--status",
                    "ready",
                    "--last-checked-at",
                    "2026-07-16T22:16:00+08:00",
                    "--next-check-at",
                    "2026-07-17T22:15:00+08:00",
                    "--evidence",
                    "readiness 2/3",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
            updated_item = load_json(updated.stdout)["follow_up"]
            self.assertEqual("ready", updated_item["status"])
            self.assertEqual("2026-07-16T22:16:00+08:00", updated_item["last_checked_at"])
            self.assertEqual("readiness 2/3", updated_item["evidence"])

    def test_follow_up_check_times_require_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            result = run_ledger(
                [
                    "track-follow-up",
                    "--thread-id",
                    "thread-1",
                    "--title",
                    "等待外部任务",
                    "--goal",
                    "继续目标",
                    "--wait-condition",
                    "等待任务完成",
                    "--resume-action",
                    "恢复执行",
                    "--next-check-at",
                    "2026-07-16T22:15:00",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("timezone", result.stderr)

    def test_record_activity_upserts_by_thread_and_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            base_args = [
                "record-activity",
                "--date",
                "2026-07-14",
                "--thread-id",
                "thread-recipe",
                "--title",
                "设计菜谱库存系统",
                "--status",
                "delivered_pending_trial",
                "--summary",
                "PWA 已部署并通过测试",
                "--next-action",
                "使用真实食材试运行 1-3 天",
                "--project-path",
                "/Users/dysania/program/env/pantry-recipe-pwa",
                "--format",
                "json",
            ]

            first = run_ledger(base_args, ledger_dir)
            second = run_ledger(
                [
                    *base_args[:-2],
                    "--summary",
                    "PWA 已部署，等待真实使用反馈",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            listed = run_ledger(
                ["list-activity", "--date", "2026-07-14", "--format", "json"],
                ledger_dir,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            activities = load_json(listed.stdout)["activities"]
            self.assertEqual(1, len(activities))
            self.assertEqual("thread-recipe", activities[0]["thread_id"])
            self.assertEqual("delivered_pending_trial", activities[0]["status"])
            self.assertIn("真实使用反馈", activities[0]["summary"])

    def test_clear_activity_removes_only_requested_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            for day in ("2026-07-13", "2026-07-14"):
                result = run_ledger(
                    [
                        "record-activity",
                        "--date",
                        day,
                        "--thread-id",
                        f"thread-{day}",
                        "--title",
                        "示例任务",
                        "--status",
                        "completed",
                        "--summary",
                        "完成",
                        "--format",
                        "json",
                    ],
                    ledger_dir,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            cleared = run_ledger(
                ["clear-activity", "--date", "2026-07-14", "--format", "json"],
                ledger_dir,
            )
            remaining = run_ledger(
                ["list-activity", "--date", "2026-07-13", "--format", "json"],
                ledger_dir,
            )

            self.assertEqual(cleared.returncode, 0, cleared.stderr)
            self.assertEqual(1, load_json(cleared.stdout)["removed_count"])
            self.assertEqual(1, len(load_json(remaining.stdout)["activities"]))

    def test_activity_date_must_be_iso_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            result = run_ledger(
                [
                    "record-activity",
                    "--date",
                    "../escape",
                    "--title",
                    "示例",
                    "--status",
                    "completed",
                    "--summary",
                    "完成",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("invalid activity date", result.stderr)

    def test_add_list_and_update_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"

            added = run_ledger(
                [
                    "add",
                    "--title",
                    "整理 Program 临时项目",
                    "--next-action",
                    "扫描 _inbox 并归类",
                    "--project-name",
                    "Program",
                    "--project-path",
                    "/Users/dysania/program",
                    "--session-id",
                    "session-001",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            self.assertEqual(added.returncode, 0, added.stderr)
            task = load_json(added.stdout)["task"]
            self.assertEqual(task["status"], "todo")
            self.assertEqual(task["title"], "整理 Program 临时项目")
            self.assertEqual(task["project"]["name"], "Program")
            self.assertEqual(task["source"]["session_id"], "session-001")
            self.assertTrue((ledger_dir / "tasks.jsonl").exists())
            self.assertTrue((ledger_dir / "index.json").exists())

            listed = run_ledger(["list", "--status", "todo", "--format", "json"], ledger_dir)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            tasks = load_json(listed.stdout)["tasks"]
            self.assertEqual([item["id"] for item in tasks], [task["id"]])

            updated = run_ledger(
                [
                    "update",
                    task["id"],
                    "--status",
                    "waiting_user",
                    "--next-action",
                    "等待用户决定是否保留",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
            updated_task = load_json(updated.stdout)["task"]
            self.assertEqual(updated_task["status"], "waiting_user")
            self.assertEqual(updated_task["next_action"], "等待用户决定是否保留")

    def test_digest_writes_daily_markdown_for_active_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            run_ledger(
                [
                    "add",
                    "--title",
                    "上下文摘要卡片 Hook",
                    "--status",
                    "in_progress",
                    "--next-action",
                    "补充任务摘要联动",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            run_ledger(
                [
                    "add",
                    "--title",
                    "隔离区清理确认",
                    "--status",
                    "cleanup_candidate",
                    "--next-action",
                    "询问是否永久删除",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            result = run_ledger(["digest", "--date", "2026-07-03", "--format", "json"], ledger_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            digest_path = Path(load_json(result.stdout)["digest_path"])
            self.assertTrue(digest_path.exists())
            digest = digest_path.read_text(encoding="utf-8")
            self.assertIn("# Codex 任务摘要 2026-07-03", digest)
            self.assertIn("上下文摘要卡片 Hook", digest)
            self.assertIn("隔离区清理确认", digest)
            self.assertIn("补充任务摘要联动", digest)
            self.assertIn("询问是否永久删除", digest)

    def test_import_curator_creates_review_and_cleanup_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            needs_review = tmp_path / "needs-review"
            trash_candidates = tmp_path / "trash-candidates"
            needs_review.mkdir()
            trash_candidates.mkdir()
            (needs_review / "loose-doc.md").write_text("# loose", encoding="utf-8")
            (trash_candidates / "old-experiment").mkdir()

            result = run_ledger(
                [
                    "import-curator",
                    "--needs-review-dir",
                    str(needs_review),
                    "--trash-candidates-dir",
                    str(trash_candidates),
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            imported = load_json(result.stdout)["tasks"]
            self.assertEqual({task["status"] for task in imported}, {"needs_review", "cleanup_candidate"})
            self.assertTrue(any("loose-doc.md" in task["title"] for task in imported))
            self.assertTrue(any("old-experiment" in task["title"] for task in imported))

    def test_import_artifacts_creates_tasks_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            manifest = tmp_path / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "title": "整理摘要卡片文档",
                                "status": "todo",
                                "project_name": "Codex工作台",
                                "project_path": "/Users/dysania/program/codex-workflow-skills",
                                "next_action": "决定是否回流到 Obsidian",
                                "artifacts": [{"path": "/tmp/card.md"}],
                                "tags": ["context-summary"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_ledger(
                ["import-artifacts", "--manifest", str(manifest), "--format", "json"],
                ledger_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            imported = load_json(result.stdout)["tasks"]
            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["title"], "整理摘要卡片文档")
            self.assertEqual(imported[0]["project"]["name"], "Codex工作台")
            self.assertEqual(imported[0]["next_action"], "决定是否回流到 Obsidian")

    def test_redacts_common_secret_shapes_from_stdout_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            openai_token = fake_openai_token()
            github_token = fake_github_token()
            secret_title = (
                f"token {openai_token} "
                f"github {github_token} "
                "AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz1234567890"
            )

            result = run_ledger(
                [
                    "add",
                    "--title",
                    secret_title,
                    "--next-action",
                    "检查 Cookie: sessionid=abcdefghijklmnopqrstuvwxyz1234567890",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            combined = result.stdout
            combined += (ledger_dir / "tasks.jsonl").read_text(encoding="utf-8")
            combined += (ledger_dir / "index.json").read_text(encoding="utf-8")
            self.assertNotIn(openai_token, combined)
            self.assertNotIn(github_token, combined)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz1234567890", combined)
            self.assertNotIn("sessionid=abcdefghijklmnopqrstuvwxyz1234567890", combined)
            self.assertIn("[REDACTED]", combined)


if __name__ == "__main__":
    unittest.main()
