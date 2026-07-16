import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import datetime as dt
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "task-continuity-hook.py"
LEDGER = ROOT / "scripts" / "task-ledger.py"


def load_hook_module():
    spec = importlib.util.spec_from_file_location("task_continuity_hook", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def run_hook(hook_input, ledger_dir, extra_env=None, hook_path=HOOK):
    env = os.environ.copy()
    env["CODEX_TASK_LEDGER_DIR"] = str(ledger_dir)
    env["CODEX_OPERATION_LEDGER_PATH"] = str(Path(ledger_dir) / "operation-ledger" / "events.jsonl")
    env["CODEX_REPOSITORY_SCAN_ROOTS"] = str(Path(ledger_dir) / "repositories")
    env["CODEX_REPOSITORY_CLOSURE_INCLUDE_GITHUB"] = "0"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(hook_input, ensure_ascii=False),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def write_work_index(work_dir, works):
    work_dir.mkdir(parents=True)
    work_dir.joinpath("index.json").write_text(
        json.dumps({"version": 1, "works": {work["id"]: work for work in works}}, ensure_ascii=False),
        encoding="utf-8",
    )


def digest_daily_path(ledger_dir, day=None):
    day = day or dt.date.today()
    return ledger_dir / "digests" / "daily" / f"{day.isoformat()}.md"


def previous_week_dates(today=None):
    today = today or dt.date.today()
    start = today - dt.timedelta(days=today.weekday() + 7)
    return [start + dt.timedelta(days=offset) for offset in range(7)]


def previous_month(today=None):
    today = today or dt.date.today()
    first_this_month = today.replace(day=1)
    last_prev_month = first_this_month - dt.timedelta(days=1)
    return last_prev_month.strftime("%Y-%m"), last_prev_month


def run_ledger(args, ledger_dir):
    env = os.environ.copy()
    env["CODEX_TASK_LEDGER_DIR"] = str(ledger_dir)
    return subprocess.run(
        [sys.executable, str(LEDGER), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class TaskContinuityHookTest(unittest.TestCase):
    def test_stop_hook_extracts_explicit_task_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            transcript = tmp_path / "session.jsonl"
            write_jsonl(
                transcript,
                [
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "TODO: 继续整理 Program 临时项目",
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "等待确认：是否删除隔离区 old-experiment",
                                }
                            ],
                        },
                    },
                ],
            )

            result = run_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-002",
                    "cwd": "/Users/dysania/program",
                    "transcript_path": str(transcript),
                },
                ledger_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertTrue(output["continue"])
            self.assertEqual(output["added_task_count"], 2)
            self.assertIn("任务连续性", output["systemMessage"])

            listed = run_ledger(["list", "--format", "json"], ledger_dir)
            tasks = json.loads(listed.stdout)["tasks"]
            self.assertEqual(len(tasks), 2)
            self.assertEqual({task["status"] for task in tasks}, {"todo", "waiting_user"})

    def test_stop_hook_does_not_duplicate_active_marker_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            transcript = tmp_path / "session.jsonl"
            write_jsonl(
                transcript,
                [
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "TODO: 明天继续任务账本",
                        },
                    }
                ],
            )
            hook_input = {
                "hook_event_name": "stop",
                "session_id": "session-003",
                "cwd": "/Users/dysania/program",
                "transcript_path": str(transcript),
            }

            first = run_hook(hook_input, ledger_dir)
            second = run_hook(hook_input, ledger_dir)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(first.stdout)["added_task_count"], 1)
            self.assertEqual(json.loads(second.stdout)["added_task_count"], 0)
            listed = run_ledger(["list", "--format", "json"], ledger_dir)
            tasks = json.loads(listed.stdout)["tasks"]
            self.assertEqual(len(tasks), 1)

    def test_session_start_prints_active_task_summary_once_per_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            add = run_ledger(
                [
                    "add",
                    "--title",
                    "继续任务连续性 Hook",
                    "--next-action",
                    "补充 SessionStart 展示",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            first = run_hook({"hook_event_name": "SessionStart"}, ledger_dir)
            second = run_hook({"hook_event_name": "SessionStart"}, ledger_dir)

            self.assertEqual(first.returncode, 0, first.stderr)
            first_output = json.loads(first.stdout)
            self.assertTrue(first_output["continue"])
            self.assertFalse(first_output["suppressOutput"])
            self.assertIn("继续任务连续性 Hook", first_output["systemMessage"])
            self.assertIn("补充 SessionStart 展示", first_output["systemMessage"])
            self.assertEqual(first_output["digest_path"], str(digest_daily_path(ledger_dir)))
            self.assertTrue(digest_daily_path(ledger_dir).exists())

            self.assertEqual(second.returncode, 0, second.stderr)
            second_output = json.loads(second.stdout)
            self.assertTrue(second_output["continue"])
            self.assertTrue(second_output["suppressOutput"])
            self.assertEqual(second_output["skipped_reason"], "daily_summary_already_shown")

    def test_daily_digest_event_persists_daily_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            add = run_ledger(
                [
                    "add",
                    "--title",
                    "整理候选继续项",
                    "--next-action",
                    "查看每日摘要",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            result = run_hook({"hook_event_name": "DailyDigest"}, ledger_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertTrue(output["continue"])
            self.assertFalse(output["suppressOutput"])
            self.assertIn("整理候选继续项", output["systemMessage"])
            self.assertEqual(output["digest_path"], str(digest_daily_path(ledger_dir)))
            self.assertTrue(digest_daily_path(ledger_dir).exists())
            self.assertIn("整理候选继续项", digest_daily_path(ledger_dir).read_text(encoding="utf-8"))

    def test_daily_digest_reports_git_closure_and_does_not_equate_empty_ledger_with_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            repo = tmp_path / "program" / "demo"
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.name", "Codex Test"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "codex-test@example.invalid"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            repo.joinpath("tracked.txt").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
            repo.joinpath("tracked.txt").write_text("unfinished\n", encoding="utf-8")

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {"CODEX_REPOSITORY_SCAN_ROOTS": str(tmp_path / "program")},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(0, output["task_count"])
            self.assertEqual(1, output["repository_closure_count"])
            self.assertEqual(1, output["repository_closure_counts"]["in_progress"])
            self.assertIn("账本为 0 不代表所有 Codex 任务都已完成", output["systemMessage"])
            self.assertIn("## 仓库收尾", output["systemMessage"])
            self.assertIn("demo", output["systemMessage"])
            self.assertIn("当前分支 main 有 1 个已跟踪改动", output["systemMessage"])
            self.assertNotIn("证据不足", output["systemMessage"])
            self.assertNotIn("RC-", output["systemMessage"])
            self.assertNotIn("repository-closure", output["systemMessage"])
            self.assertTrue(Path(output["repository_closure_report_path"]).exists())

    def test_session_start_reuses_today_repository_closure_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            closure_dir = ledger_dir / "repository-closure"
            closure_dir.mkdir(parents=True)
            report = {
                "schema_version": 1,
                "generated_at": f"{dt.date.today().isoformat()}T08:00:00+08:00",
                "generated_on": dt.date.today().isoformat(),
                "repository_count": 1,
                "finding_count": 1,
                "counts": {
                    "in_progress": 0,
                    "awaiting_integration": 1,
                    "pr_pending": 0,
                    "legacy": 0,
                    "merged_cleanup": 0,
                },
                "findings": [
                    {
                        "id": "RC-EXAMPLE001",
                        "category": "awaiting_integration",
                        "repository": "demo",
                        "worktree": "/tmp/demo",
                        "branch": "feature/ready",
                        "tracked_change_count": 0,
                        "untracked_count": 0,
                        "ahead_count": 1,
                        "behind_count": 0,
                        "reason": "分支含有尚未进入默认分支的提交",
                    }
                ],
                "warnings": [],
            }
            closure_dir.joinpath("latest.json").write_text(
                json.dumps(report, ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "SessionStart"},
                ledger_dir,
                {
                    "CODEX_REPOSITORY_CLOSURE_DIR": str(closure_dir),
                    "CODEX_REPOSITORY_CLOSURE_SCANNER": str(tmp_path / "missing-scanner.py"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(1, output["repository_closure_count"])
            self.assertEqual([], output["repository_closure_warnings"])
            self.assertIn("feature/ready", output["systemMessage"])
            self.assertEqual("feature/ready", output["repository_closure_findings"][0]["branch"])
            self.assertIn("分支含有尚未进入默认分支的提交", output["systemMessage"])
            self.assertNotIn("自动收尾候选", output["systemMessage"])

    def test_daily_digest_removes_old_persisted_markdown_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            daily_dir = ledger_dir / "daily"
            daily_dir.mkdir(parents=True)
            old_digest = daily_dir / "2000-01-01.md"
            recent_digest = daily_dir / dt.date.today().isoformat()
            recent_digest = recent_digest.with_suffix(".md")
            old_digest.write_text("# old", encoding="utf-8")
            recent_digest.write_text("# recent", encoding="utf-8")

            result = run_hook({"hook_event_name": "DailyDigest"}, ledger_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["cleanup_deleted_daily_digest_count"], 1)
            self.assertFalse(old_digest.exists())
            self.assertTrue(recent_digest.exists())

    def test_daily_digest_is_not_suppressed_by_session_start_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            add = run_ledger(
                [
                    "add",
                    "--title",
                    "每日自动化必须发到当前线程",
                    "--next-action",
                    "验证 DailyDigest 不被 SessionStart 抢先拦截",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            fallback = run_hook({"hook_event_name": "SessionStart"}, ledger_dir)
            digest = run_hook({"hook_event_name": "DailyDigest"}, ledger_dir)

            self.assertEqual(fallback.returncode, 0, fallback.stderr)
            self.assertEqual(digest.returncode, 0, digest.stderr)
            output = json.loads(digest.stdout)
            self.assertTrue(output["continue"])
            self.assertFalse(output["suppressOutput"])
            self.assertIn("每日自动化必须发到当前线程", output["systemMessage"])

    def test_daily_digest_force_reruns_after_today_was_already_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            first = run_hook({"hook_event_name": "DailyDigest"}, ledger_dir)
            forced = run_hook({"hook_event_name": "DailyDigest", "force": True}, ledger_dir)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(forced.returncode, 0, forced.stderr)
            output = json.loads(forced.stdout)
            self.assertFalse(output["suppressOutput"])
            self.assertIn("## Codex 每日任务摘要", output["systemMessage"])

    def test_daily_digest_includes_previous_artifacts_and_review_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            manifest_dir = governance_dir / "artifacts" / yesterday
            manifest_dir.mkdir(parents=True)
            manifest_dir.joinpath("session-artifacts.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-artifacts",
                        "candidates": [
                            {
                                "path": str(program_root / "loose-summary.md"),
                                "exists": True,
                                "suggested_action": "curator_plan",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            needs_review = program_root / "_inbox" / "needs-review"
            trash = program_root / "_archive" / "trash-candidates" / yesterday
            needs_review.mkdir(parents=True)
            trash.mkdir(parents=True)
            (program_root / "loose-summary.md").write_text("# loose summary", encoding="utf-8")
            needs_review.joinpath("draft-report.md").write_text("# draft", encoding="utf-8")
            trash.joinpath("old-experiment").mkdir()

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertTrue(output["continue"])
            self.assertIn("前日产物", output["systemMessage"])
            self.assertIn("loose-summary.md", output["systemMessage"])
            self.assertIn("draft-report.md", output["systemMessage"])
            self.assertIn("old-experiment", output["systemMessage"])
            self.assertIn("## Codex 每日任务摘要", output["systemMessage"])
            self.assertNotIn("[!summary]", output["systemMessage"])
            self.assertIn(f"[loose-summary.md]({program_root / 'loose-summary.md'})", output["systemMessage"])
            self.assertIn(f"[draft-report.md]({needs_review / 'draft-report.md'})", output["systemMessage"])
            self.assertIn("A01", output["systemMessage"])
            self.assertIn("内容：Markdown 文档", output["systemMessage"])
            self.assertIn("选择原因：它来自会话产物记录", output["systemMessage"])
            self.assertIn("操作：`删除 A01` / `暂放 A01` / `移到待办 A01`", output["systemMessage"])
            self.assertEqual(output["artifact_summary_count"], 3)
            self.assertEqual(output["digest_path"], str(digest_daily_path(ledger_dir)))
            self.assertEqual(len(output["artifact_actions"]), 3)
            self.assertIn("selection_reason", output["artifact_actions"][0])
            self.assertIn("来自会话产物记录", output["artifact_actions"][0]["selection_reason"])
            pending_text = Path(output["pending_artifacts_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("选择原因：它来自会话产物记录", pending_text)

    def test_daily_digest_filters_managed_files_and_cleans_transient_screenshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            codex_home = home / ".codex"
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            manifest_dir = governance_dir / "artifacts" / dt.date.today().isoformat()
            manifest_dir.mkdir(parents=True)

            codex_home.mkdir(parents=True)
            codex_agents = codex_home / "AGENTS.md"
            codex_agents.write_text("# Codex 全局规则", encoding="utf-8")
            skill_file = program_root / "skills" / "codex-task-continuity" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("---\nname: codex-task-continuity\n---\n", encoding="utf-8")
            loose_summary = program_root / "loose-summary.md"
            loose_summary.parent.mkdir(parents=True, exist_ok=True)
            loose_summary.write_text("# loose summary", encoding="utf-8")
            temp_screenshot = tmp_path / "codex-clipboard-12345678.png"
            temp_screenshot.write_bytes(b"png")
            attachment = program_root / "documents" / "obsidian_vault" / "07_Attachments" / "knowledge-map-preview.png"
            attachment.parent.mkdir(parents=True)
            attachment.write_bytes(b"png")
            tools_container = program_root / "tools"
            tools_container.mkdir(parents=True)

            project = program_root / "tools" / "agent-tools" / "kept-tool"
            project.mkdir(parents=True)
            tracked_file = project / "main.py"
            tracked_file.write_text("print('kept')\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "main.py"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            manifest_dir.joinpath("mixed-session.json").write_text(
                json.dumps(
                    {
                        "session_id": "mixed-session",
                        "candidates": [
                            {"path": str(codex_home)},
                            {"path": str(codex_agents)},
                            {"path": str(skill_file)},
                            {"path": str(tracked_file)},
                            {"path": str(loose_summary)},
                            {"path": str(program_root)},
                            {"path": str(tools_container)},
                            {"path": str(temp_screenshot)},
                            {"path": str(attachment)},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "HOME": str(home),
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["artifact_summary_count"], 1)
            self.assertEqual(output["new_artifact_candidate_count"], 1)
            self.assertIn("loose-summary.md", output["systemMessage"])
            self.assertNotIn("AGENTS.md", output["systemMessage"])
            self.assertNotIn("codex-task-continuity", output["systemMessage"])
            self.assertNotIn("main.py", output["systemMessage"])
            self.assertNotIn(str(program_root), [action["path"] for action in output["artifact_actions"]])
            self.assertNotIn(str(tools_container), [action["path"] for action in output["artifact_actions"]])
            self.assertNotIn("codex-clipboard-12345678.png", output["systemMessage"])
            self.assertFalse(temp_screenshot.exists())
            self.assertFalse(attachment.exists())

    def test_daily_digest_auto_deletes_images_from_posix_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            manifest_dir = governance_dir / "artifacts" / dt.date.today().isoformat()
            manifest_dir.mkdir(parents=True)

            with tempfile.NamedTemporaryFile(
                prefix="codex-wake-test-",
                suffix=".png",
                dir="/tmp",
                delete=False,
            ) as handle:
                handle.write(b"png")
                transient_image = Path(handle.name)
            self.addCleanup(transient_image.unlink, missing_ok=True)

            manifest_dir.joinpath("tmp-image-session.json").write_text(
                json.dumps({"candidates": [{"path": str(transient_image)}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["artifact_summary_count"], 0)
            self.assertEqual(output["new_artifact_candidate_count"], 0)
            self.assertFalse(transient_image.exists())

    def test_daily_digest_filters_files_inside_nongit_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            manifest_dir = governance_dir / "artifacts" / dt.date.today().isoformat()
            manifest_dir.mkdir(parents=True)

            project = program_root / "GEO"
            source_file = project / "backend" / "app" / "services" / "geo_core_pipeline.py"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("def run():\n    return 'ok'\n", encoding="utf-8")
            (project / "README.md").write_text("# GEO\n", encoding="utf-8")
            (project / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            frontend = project / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text("{}\n", encoding="utf-8")
            manifest_dir.joinpath("geo-session.json").write_text(
                json.dumps({"candidates": [{"path": str(source_file)}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(0, output["artifact_summary_count"])
            self.assertEqual(0, output["new_artifact_candidate_count"])
            self.assertNotIn("geo_core_pipeline.py", output["systemMessage"])

    def test_daily_digest_auto_deletes_wechat_rwtemp_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transient_image = (
                tmp_path
                / "Library"
                / "Containers"
                / "com.tencent.xinWeChat"
                / "Data"
                / "Documents"
                / "xwechat_files"
                / "temp"
                / "RWTemp"
                / "preview.png"
            )
            transient_image.parent.mkdir(parents=True)
            transient_image.write_bytes(b"png")

            hook = load_hook_module()
            with mock.patch.object(hook.tempfile, "gettempdir", return_value="/not-a-temp-root"):
                self.assertTrue(hook.auto_delete_transient_path(transient_image))
            self.assertFalse(transient_image.exists())

    def test_daily_digest_filters_system_temp_root_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            governance_dir = tmp_path / "program-governance"
            manifest_dir = governance_dir / "artifacts" / dt.date.today().isoformat()
            manifest_dir.mkdir(parents=True)
            manifest_dir.joinpath("session-artifacts.json").write_text(
                json.dumps(
                    {
                        "session_id": "session-temp-root",
                        "candidates": [{"path": "/private/tmp", "exists": True}],
                    }
                ),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                    "CODEX_RECURRING_TASK_MANIFESTS": str(tmp_path / "missing.json"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(0, output["artifact_summary_count"])
            self.assertNotIn("/private/tmp", output["systemMessage"])

    def test_daily_digest_filters_git_history_subtree_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            old_day = (dt.date.today() - dt.timedelta(days=4)).isoformat()
            manifest_dir = governance_dir / "artifacts" / old_day
            manifest_dir.mkdir(parents=True)

            repo_root = program_root / "tools" / "agent-tools"
            source_dir = repo_root / "codex-thread-bridge"
            source_dir.mkdir(parents=True)
            tracked_file = source_dir / "codex_thread_bridge.py"
            tracked_file.write_text("print('bridge')\n", encoding="utf-8")
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "codex-thread-bridge/codex_thread_bridge.py"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                ["git", "-c", "user.name=Codex", "-c", "user.email=codex@example.invalid", "commit", "-m", "add bridge"],
                cwd=repo_root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(["git", "branch", "codex-thread-bridge-mvp"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "rm", "codex-thread-bridge/codex_thread_bridge.py"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            source_dir.mkdir()
            (source_dir / "__pycache__").mkdir()
            (source_dir / "__pycache__" / "codex_thread_bridge.cpython-313.pyc").write_bytes(b"cache")
            subprocess.run(
                ["git", "-c", "user.name=Codex", "-c", "user.email=codex@example.invalid", "commit", "-m", "remove bridge from main"],
                cwd=repo_root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            manifest_dir.joinpath("branch-residue.json").write_text(
                json.dumps({"candidates": [{"path": str(source_dir)}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["artifact_summary_count"], 0)
            self.assertEqual(output["new_artifact_candidate_count"], 0)
            self.assertNotIn("codex-thread-bridge", output["systemMessage"])

    def test_daily_digest_filters_canonical_workflow_source_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            old_day = (dt.date.today() - dt.timedelta(days=10)).isoformat()
            manifest_dir = governance_dir / "artifacts" / old_day
            manifest_dir.mkdir(parents=True)

            workflow_repo = program_root / "codex-workflow-skills"
            workflow_repo.mkdir(parents=True)
            (workflow_repo / ".git").mkdir()
            (workflow_repo / "README.md").write_text("# workflow skills", encoding="utf-8")
            (workflow_repo / "codex-task-continuity").mkdir()
            manifest_dir.joinpath("workflow-session.json").write_text(
                json.dumps({"candidates": [{"path": str(workflow_repo)}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["artifact_summary_count"], 0)
            self.assertEqual(output["new_artifact_candidate_count"], 0)
            self.assertNotIn("codex-workflow-skills", output["systemMessage"])

    def test_project_aging_counts_workdays_instead_of_weekend_days(self):
        hook = load_hook_module()
        real_date = dt.date

        class Monday(real_date):
            @classmethod
            def today(cls):
                return cls(2026, 7, 13)

        try:
            hook.dt.date = Monday
            self.assertEqual(hook.manifest_age_days("2026-07-10"), 1)
        finally:
            hook.dt.date = real_date

    def test_daily_digest_delays_project_like_manifest_candidates_until_aged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            young_day = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            old_day = (dt.date.today() - dt.timedelta(days=7)).isoformat()
            young_manifest_dir = governance_dir / "artifacts" / young_day
            old_manifest_dir = governance_dir / "artifacts" / old_day
            young_manifest_dir.mkdir(parents=True)
            old_manifest_dir.mkdir(parents=True)

            young_project = program_root / "_external" / "young-demo"
            old_project = program_root / "_external" / "old-demo"
            for project in (young_project, old_project):
                project.mkdir(parents=True)
                (project / ".git").mkdir()
                (project / "README.md").write_text("# demo", encoding="utf-8")

            young_manifest_dir.joinpath("young-session.json").write_text(
                json.dumps({"candidates": [{"path": str(young_project)}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            old_manifest_dir.joinpath("old-session.json").write_text(
                json.dumps({"candidates": [{"path": str(old_project)}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["artifact_summary_count"], 1)
            self.assertEqual(output["new_artifact_candidate_count"], 1)
            self.assertIn("old-demo", output["systemMessage"])
            self.assertNotIn("young-demo", output["systemMessage"])

    def test_daily_digest_keeps_unconfirmed_artifacts_until_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            program_root = tmp_path / "program"
            governance_dir = tmp_path / "program-governance"
            older_day = (dt.date.today() - dt.timedelta(days=2)).isoformat()
            manifest_dir = governance_dir / "artifacts" / older_day
            manifest_dir.mkdir(parents=True)
            artifact = program_root / "older-summary.md"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("# older summary", encoding="utf-8")
            manifest_dir.joinpath("older-session.json").write_text(
                json.dumps(
                    {
                        "session_id": "older-session",
                        "candidates": [{"path": str(artifact), "exists": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            first = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_output = json.loads(first.stdout)
            self.assertEqual(first_output["artifact_summary_count"], 1)
            self.assertIn("A01", first_output["systemMessage"])
            self.assertIn("older-summary.md", first_output["systemMessage"])
            pending_path = Path(first_output["pending_artifacts_path"])
            pending_markdown_path = Path(first_output["pending_artifacts_markdown_path"])
            self.assertTrue(pending_path.exists())
            self.assertTrue(pending_markdown_path.exists())

            manifest_dir.joinpath("older-session.json").unlink()
            (ledger_dir / "state.json").write_text("{}", encoding="utf-8")
            second = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(program_root),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(governance_dir),
                },
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            second_output = json.loads(second.stdout)
            self.assertEqual(second_output["artifact_summary_count"], 1)
            self.assertIn("A01", second_output["systemMessage"])
            self.assertIn("older-summary.md", second_output["systemMessage"])

    def test_daily_digest_keeps_completed_work_index_internal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            work_dir = tmp_path / "work-ledger"
            write_work_index(
                work_dir,
                [
                    {
                        "id": "work_20260706_digest",
                        "title": "实现每日摘要待确认池",
                        "status": "completed",
                        "summary": "每日摘要展示所有未确认产物，而不是只看昨天。",
                        "updated_at": "2026-07-06T01:00:00Z",
                        "usage": "查看 Codex 每日摘要线程。",
                        "project": {"name": "Codex 工作台", "path": "/Users/dysania/program/codex-workflow-skills"},
                    }
                ],
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_WORK_LEDGER_DIR": str(work_dir),
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertNotIn("## 历史成果索引", output["systemMessage"])
            self.assertNotIn(str(work_dir / "index.md"), output["systemMessage"])
            self.assertNotIn("实现每日摘要待确认池", output["systemMessage"])
            self.assertNotIn("每日摘要展示所有未确认产物", output["systemMessage"])
            self.assertEqual(output["recent_completed_work_count"], 1)

    def test_daily_digest_prioritizes_yesterday_activity_and_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            activity_dir = ledger_dir / "activity"
            activity_dir.mkdir(parents=True)
            yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            activity_dir.joinpath(f"{yesterday}.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "date": yesterday,
                        "activities": {
                            "thread-geo": {
                                "thread_id": "thread-geo",
                                "title": "调研 GEO 核心模块",
                                "status": "delivered_pending_trial",
                                "summary": "上下文卡片记录的最近进展：可运行 V1 已完成，Demo 已验证；" + "不应展示的长尾" * 30,
                                "next_action": "连接一个真实平台并试运行",
                                "project_name": "GEO 智能诊断平台",
                                "project_path": "/Users/dysania/program/GEO",
                                "evidence": "/Users/dysania/.codex/context-cards/private-evidence.md",
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                    "CODEX_RECURRING_TASK_MANIFESTS": str(tmp_path / "missing.json"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(1, output["previous_day_activity_count"])
            self.assertIn("## 昨日实际工作与后续", output["systemMessage"])
            self.assertIn("已交付待试用", output["systemMessage"])
            self.assertIn("GEO 智能诊断平台", output["systemMessage"])
            self.assertIn("连接一个真实平台并试运行", output["systemMessage"])
            self.assertNotIn("上下文卡片记录的最近进展", output["systemMessage"])
            self.assertNotIn("private-evidence", output["systemMessage"])
            self.assertNotIn("不应展示的长尾不应展示的长尾不应展示的长尾", output["systemMessage"])

    def test_daily_digest_groups_repository_resolutions_without_internal_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            today = dt.date.today().isoformat()
            for finding_id, project, status, stage, summary, next_action in (
                ("RC-DONE", "OpenClaw", "completed", "已合并", "PR 已合并并清理 6 条旧分支", "无需操作"),
                ("RC-ACTIVE", "YA FundMind", "active_deferred", "近期仍在开发", "Web Console 分支今天仍在实现", "原任务完成后自动合并"),
                ("RC-FAILED", "旧商城", "failed", "合并测试", "测试失败在订单模块", "对应任务继续修复失败测试"),
            ):
                recorded = run_ledger(
                    [
                        "record-repository-resolution",
                        "--date",
                        today,
                        "--finding-id",
                        finding_id,
                        "--repository",
                        project,
                        "--project-name",
                        project,
                        "--branch",
                        "feature/example",
                        "--status",
                        status,
                        "--stage",
                        stage,
                        "--summary",
                        summary,
                        "--next-action",
                        next_action,
                        "--evidence",
                        "/internal/closure-report.json",
                        "--format",
                        "json",
                    ],
                    ledger_dir,
                )
                self.assertEqual(recorded.returncode, 0, recorded.stderr)

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            message = json.loads(result.stdout)["systemMessage"]
            self.assertIn("今日已处理", message)
            self.assertIn("近期开发暂不合并", message)
            self.assertIn("需要关注", message)
            self.assertIn("PR 已合并并清理 6 条旧分支", message)
            self.assertIn("Web Console 分支今天仍在实现", message)
            self.assertIn("测试失败在订单模块", message)
            self.assertNotIn("/internal/closure-report.json", message)
            self.assertNotIn("RC-DONE", message)

    def test_installed_hook_uses_skill_companion_scripts_instead_of_stale_hook_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            hooks_dir = tmp_path / "hooks"
            hooks_dir.mkdir()
            installed_hook = hooks_dir / "task-continuity-hook.py"
            shutil.copy2(HOOK, installed_hook)
            recorded = run_ledger(
                [
                    "record-repository-resolution",
                    "--date",
                    dt.date.today().isoformat(),
                    "--finding-id",
                    "RC-INSTALLED",
                    "--repository",
                    "example/repo",
                    "--project-name",
                    "安装副本测试",
                    "--status",
                    "completed",
                    "--summary",
                    "已处理",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(0, recorded.returncode, recorded.stderr)

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_TASK_CONTINUITY_SKILL_DIR": str(ROOT),
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                },
                hook_path=installed_hook,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(1, output["repository_resolution_count"])
            self.assertIn("安装副本测试", output["systemMessage"])

    def test_daily_digest_falls_back_to_operation_ledger_and_hides_stale_work_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            work_dir = tmp_path / "work-ledger"
            operation_ledger = tmp_path / "operation-ledger" / "events.jsonl"
            operation_ledger.parent.mkdir(parents=True)
            yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            context_card = tmp_path / "context.md"
            context_card.write_text(
                "# Codex 上下文摘要卡片\n\n"
                "## 最近助手进展\n\n"
                "- `2026-07-15T03:00:00Z` **助手**: GEO 研究核心已完成真实来源核验。\n"
                "- `2026-07-15T04:00:00Z` **助手**: GEO API 与浏览器验收通过，下一步连接真实平台试运行。\n\n"
                "## 压缩前时间线\n",
                encoding="utf-8",
            )
            write_jsonl(
                operation_ledger,
                [
                    {
                        "id": "evt-context",
                        "action": "context_compacted",
                        "occurred_at": f"{yesterday}T04:00:00Z",
                        "status": "success",
                        "importance": "routine",
                        "project": {"name": "GEO", "path": str(tmp_path / "program" / "GEO")},
                        "thread": {"id": "thread-geo", "title": "更新 GEO 核心模块"},
                        "evidence": [{"kind": "context_card", "path": str(context_card)}],
                    },
                    {
                        "id": "evt-skill",
                        "action": "skill_updated",
                        "occurred_at": f"{yesterday}T05:00:00Z",
                        "status": "success",
                        "importance": "important",
                        "actor": {"id": "workflow-file-monitor", "label": "codex-context-summary-hook"},
                        "summary": "上下文压缩 Skill：新增结构化压缩证据。",
                        "changes": [{"label": "新增能力", "summary": "结构化压缩证据"}],
                    },
                    {
                        "id": "evt-hook",
                        "action": "hook_updated",
                        "occurred_at": f"{yesterday}T05:05:00Z",
                        "status": "success",
                        "importance": "important",
                        "actor": {"id": "workflow-file-monitor", "label": "context-summary-card"},
                        "summary": "上下文压缩 Hook：补充项目活动回流。",
                    },
                ],
            )
            write_work_index(
                work_dir,
                [
                    {
                        "id": "stale-work",
                        "title": "几天前的旧成果",
                        "status": "completed",
                        "summary": "不应每天重复展示",
                        "updated_at": "2026-07-08T00:00:00Z",
                    }
                ],
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_OPERATION_LEDGER_PATH": str(operation_ledger),
                    "CODEX_WORK_LEDGER_DIR": str(work_dir),
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual("operation_ledger_fallback", output["previous_day_activity_source"])
            self.assertEqual(1, output["previous_day_activity_count"])
            self.assertEqual(2, output["previous_day_change_count"])
            self.assertIn("活动记录使用操作日志补全", output["systemMessage"])
            self.assertIn("更新 GEO 核心模块", output["systemMessage"])
            self.assertIn("GEO API 与浏览器验收通过", output["systemMessage"])
            self.assertIn("## 昨日成果与系统变更", output["systemMessage"])
            self.assertIn("codex-context-summary-hook", output["systemMessage"])
            self.assertIn("context-summary-card", output["systemMessage"])
            self.assertNotIn("## 最近成果记录", output["systemMessage"])
            self.assertNotIn("几天前的旧成果", output["systemMessage"])

    def test_daily_digest_includes_recurring_task_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            scanner = tmp_path / "recurring-scanner.py"
            scanner.write_text(
                """#!/usr/bin/env python3
import json
print(json.dumps({
    'schema_version': 1,
    'counts': {'success': 1, 'overdue': 0, 'failed': 0, 'unknown': 0},
    'tasks': [{
        'id': 'ya-fundmind-daily',
        'project': 'YA FundMind',
        'name': '每日投研',
        'status': 'success',
        'reason': '2026-07-14 按计划成功',
        'run_date': '2026-07-14',
        'next_expected_at': '2026-07-15T21:30:00+08:00',
        'details': {'数据质量': 'normal'}
    }],
    'warnings': []
}, ensure_ascii=False))
""",
                encoding="utf-8",
            )

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                    "CODEX_RECURRING_TASK_SCANNER": str(scanner),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(1, output["recurring_task_count"])
            self.assertIn("## 周期任务运行状态", output["systemMessage"])
            self.assertIn("YA FundMind", output["systemMessage"])
            self.assertIn("2026-07-14 按计划成功", output["systemMessage"])
            self.assertIn("数据质量：normal", output["systemMessage"])

    def test_daily_digest_links_follow_up_monitor_recurring_task_and_parallel_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            scanner = tmp_path / "recurring-scanner.py"
            scanner.write_text(
                """#!/usr/bin/env python3
import json
print(json.dumps({
    'schema_version': 1,
    'counts': {'success': 1, 'overdue': 0, 'failed': 0, 'unknown': 0},
    'tasks': [{
        'id': 'ya-fundmind-daily',
        'project': 'YA FundMind',
        'name': '每日投研运行',
        'status': 'success',
        'reason': '最近一次 scheduler run 成功',
        'next_expected_at': '2099-07-16T21:30:00+08:00'
    }],
    'warnings': []
}, ensure_ascii=False))
""",
                encoding="utf-8",
            )
            automations_dir = tmp_path / "automations"
            automation_dir = automations_dir / "ya-fundmind-v2-rc-final"
            automation_dir.mkdir(parents=True)
            automation_dir.joinpath("automation.toml").write_text(
                'version = 1\nid = "ya-fundmind-v2-rc-final"\nkind = "heartbeat"\n'
                'name = "YA FundMind V2 RC 观察"\nstatus = "ACTIVE"\n'
                'target_thread_id = "thread-ya-fundmind"\n',
                encoding="utf-8",
            )
            tracked = run_ledger(
                [
                    "track-follow-up",
                    "--thread-id",
                    "thread-ya-fundmind",
                    "--title",
                    "YA FundMind V2 Final 观察与并行前端轨道",
                    "--goal",
                    "完成 3 次 post-RC 真实运行并发布 v2.0.0",
                    "--wait-condition",
                    "等待每日 21:30 scheduler run，当前 1/3",
                    "--resume-mode",
                    "auto",
                    "--resume-action",
                    "达到 3/3 后继续 Final 发布",
                    "--parallel-action",
                    "在隔离 worktree 继续 Web Console",
                    "--monitor-automation-id",
                    "ya-fundmind-v2-rc-final",
                    "--monitor-schedule",
                    "每天 22:15",
                    "--next-check-at",
                    "2099-07-16T22:15:00+08:00",
                    "--recurring-task-id",
                    "ya-fundmind-daily",
                    "--project-name",
                    "YA FundMind",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(tracked.returncode, 0, tracked.stderr)

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_AUTOMATIONS_DIR": str(automations_dir),
                    "CODEX_RECURRING_TASK_SCANNER": str(scanner),
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(1, output["follow_up_count"])
            self.assertEqual(0, output["follow_up_attention_count"])
            self.assertIn("## 等待条件与续作监控", output["systemMessage"])
            self.assertIn("自动监控中", output["systemMessage"])
            self.assertIn("当前 1/3", output["systemMessage"])
            self.assertIn("每天 22:15", output["systemMessage"])
            self.assertIn("达到 3/3 后继续 Final 发布", output["systemMessage"])
            self.assertIn("在隔离 worktree 继续 Web Console", output["systemMessage"])
            self.assertIn("每日投研运行：success", output["systemMessage"])
            self.assertIn("用户操作：无需", output["systemMessage"])

    def test_daily_digest_reports_inactive_and_overdue_follow_up_monitors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_dir = tmp_path / "ledger"
            automations_dir = tmp_path / "automations"
            automation_dir = automations_dir / "paused-monitor"
            automation_dir.mkdir(parents=True)
            automation_dir.joinpath("automation.toml").write_text(
                'version = 1\nid = "paused-monitor"\nkind = "heartbeat"\n'
                'name = "暂停监控"\nstatus = "PAUSED"\n'
                'target_thread_id = "thread-paused"\n',
                encoding="utf-8",
            )
            incomplete_automation_dir = automations_dir / "incomplete-monitor"
            incomplete_automation_dir.mkdir(parents=True)
            incomplete_automation_dir.joinpath("automation.toml").write_text(
                'version = 1\nid = "incomplete-monitor"\nkind = "heartbeat"\n'
                'name = "配置不完整监控"\nstatus = "ACTIVE"\n'
                'target_thread_id = "thread-incomplete"\n',
                encoding="utf-8",
            )
            for thread_id, title, automation_id, next_check in (
                ("thread-paused", "停用监控目标", "paused-monitor", "2099-07-16T22:15:00+08:00"),
                ("thread-overdue", "逾期监控目标", "missing-monitor", "2020-07-16T22:15:00+08:00"),
            ):
                tracked = run_ledger(
                    [
                        "track-follow-up",
                        "--thread-id",
                        thread_id,
                        "--title",
                        title,
                        "--goal",
                        "等待后继续",
                        "--wait-condition",
                        "等待外部条件",
                        "--resume-mode",
                        "auto",
                        "--resume-action",
                        "自动恢复",
                        "--monitor-automation-id",
                        automation_id,
                        "--next-check-at",
                        next_check,
                        "--format",
                        "json",
                    ],
                    ledger_dir,
                )
                self.assertEqual(tracked.returncode, 0, tracked.stderr)
            incomplete = run_ledger(
                [
                    "track-follow-up",
                    "--thread-id",
                    "thread-incomplete",
                    "--title",
                    "缺少检查点与周期任务目标",
                    "--goal",
                    "等待后继续",
                    "--wait-condition",
                    "等待外部条件",
                    "--resume-mode",
                    "auto",
                    "--resume-action",
                    "自动恢复",
                    "--monitor-automation-id",
                    "incomplete-monitor",
                    "--recurring-task-id",
                    "missing-recurring-task",
                    "--format",
                    "json",
                ],
                ledger_dir,
            )
            self.assertEqual(incomplete.returncode, 0, incomplete.stderr)

            result = run_hook(
                {"hook_event_name": "DailyDigest"},
                ledger_dir,
                {
                    "CODEX_AUTOMATIONS_DIR": str(automations_dir),
                    "CODEX_PROGRAM_ROOT": str(tmp_path / "program"),
                    "CODEX_PROGRAM_GOVERNANCE_DIR": str(tmp_path / "program-governance"),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(3, output["follow_up_attention_count"])
            self.assertIn("监控 Automation 未处于 ACTIVE", output["systemMessage"])
            self.assertIn("监控 Automation 不存在", output["systemMessage"])
            self.assertIn("下次检查已逾期", output["systemMessage"])
            self.assertIn("未登记下次检查时间", output["systemMessage"])
            self.assertIn("关联周期任务未找到", output["systemMessage"])
            self.assertIn("用户操作：需要处理监控", output["systemMessage"])

    def test_daily_digest_rolls_completed_week_and_removes_daily_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            daily_dir = ledger_dir / "digests" / "daily"
            daily_dir.mkdir(parents=True)
            week_dates = previous_week_dates()
            for day in week_dates:
                (daily_dir / f"{day.isoformat()}.md").write_text(
                    f"# Daily {day.isoformat()}\n\ncontent {day.isoformat()}\n",
                    encoding="utf-8",
                )

            result = run_hook({"hook_event_name": "DailyDigest"}, ledger_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(len(output["weekly_rollup_paths"]), 1)
            weekly_path = Path(output["weekly_rollup_paths"][0])
            self.assertTrue(weekly_path.exists())
            self.assertIn("Codex 周摘要", weekly_path.read_text(encoding="utf-8"))
            for day in week_dates:
                self.assertFalse((daily_dir / f"{day.isoformat()}.md").exists())
            self.assertTrue(digest_daily_path(ledger_dir).exists())

    def test_daily_digest_rolls_completed_month_and_removes_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_dir = Path(tmp) / "ledger"
            year_month, last_prev_month = previous_month()
            first_prev_month = last_prev_month.replace(day=1)
            weekly_dir = ledger_dir / "digests" / "weekly"
            daily_dir = ledger_dir / "digests" / "daily"
            weekly_dir.mkdir(parents=True)
            daily_dir.mkdir(parents=True)
            weekly_path = weekly_dir / f"{first_prev_month.isoformat()}_to_{last_prev_month.isoformat()}.md"
            daily_path = daily_dir / f"{last_prev_month.isoformat()}.md"
            weekly_path.write_text("# Codex 周摘要\n\nweekly content\n", encoding="utf-8")
            daily_path.write_text("# Codex 每日任务摘要\n\ndaily content\n", encoding="utf-8")

            result = run_hook({"hook_event_name": "DailyDigest"}, ledger_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(len(output["monthly_rollup_paths"]), 1)
            monthly_path = Path(output["monthly_rollup_paths"][0])
            self.assertEqual(monthly_path.name, f"{year_month}.md")
            self.assertTrue(monthly_path.exists())
            text = monthly_path.read_text(encoding="utf-8")
            self.assertIn("Codex 月摘要", text)
            self.assertIn("weekly content", text)
            self.assertIn("daily content", text)
            self.assertFalse(weekly_path.exists())
            self.assertFalse(daily_path.exists())


if __name__ == "__main__":
    unittest.main()
