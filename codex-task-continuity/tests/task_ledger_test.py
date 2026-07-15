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
