import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import datetime as dt
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


def run_hook(hook_input, ledger_dir, extra_env=None):
    env = os.environ.copy()
    env["CODEX_TASK_LEDGER_DIR"] = str(ledger_dir)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(HOOK)],
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

        hook.dt.date = Monday
        self.assertEqual(hook.manifest_age_days("2026-07-10"), 1)

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

    def test_daily_digest_includes_recent_completed_work(self):
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
            self.assertIn("## 最近完成", output["systemMessage"])
            self.assertIn("实现每日摘要待确认池", output["systemMessage"])
            self.assertIn("每日摘要展示所有未确认产物", output["systemMessage"])
            self.assertEqual(output["recent_completed_work_count"], 1)

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
