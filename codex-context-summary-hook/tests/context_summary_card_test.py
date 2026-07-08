import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "context-summary-card.py"


def fake_openai_token():
    return "sk-proj-" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


def fake_github_token():
    return "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


def write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def run_hook(transcript_path, card_dir, extra_env=None):
    hook_input = {
        "session_id": "019f-test-session",
        "transcript_path": str(transcript_path),
        "cwd": "/Users/dysania/program/example",
        "trigger": "auto",
        "customInstructions": "summarize before compaction",
    }
    env = os.environ.copy()
    env["CODEX_CONTEXT_CARD_DIR"] = str(card_dir)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(hook_input, ensure_ascii=False),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class ContextSummaryCardTest(unittest.TestCase):
    def test_precompact_hook_writes_markdown_card_and_prints_system_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "session.jsonl"
            cards = tmp_path / "cards"
            openai_token = fake_openai_token()
            github_token = fake_github_token()
            write_jsonl(
                transcript,
                [
                    {
                        "timestamp": "2026-06-30T02:00:00.000Z",
                        "type": "turn_context",
                        "payload": {
                            "cwd": "/Users/dysania/program/example",
                            "model": "gpt-5.5",
                            "summary": "none",
                        },
                    },
                    {
                        "timestamp": "2026-06-30T02:01:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "帮我实现登录 Hook，并记得跑测试。",
                        },
                    },
                    {
                        "timestamp": "2026-06-30T02:02:00.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "phase": "commentary",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "我正在阅读仓库结构，准备写测试。",
                                }
                            ],
                        },
                    },
                    {
                        "timestamp": "2026-06-30T02:03:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "现在改成预压缩时保存摘要卡片。",
                        },
                    },
                ],
            )

            result = run_hook(transcript, cards)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertTrue(output["continue"])
            self.assertIn("摘要卡片已生成", output["systemMessage"])
            card_path = Path(output["summary_card_path"])
            self.assertTrue(card_path.exists())
            self.assertTrue(str(card_path).startswith(str(cards)))

            card = card_path.read_text(encoding="utf-8")
            self.assertIn("# Codex 上下文摘要卡片", card)
            self.assertIn("/Users/dysania/program/example", card)
            self.assertIn("帮我实现登录 Hook", card)
            self.assertIn("现在改成预压缩时保存摘要卡片", card)
            self.assertIn("我正在阅读仓库结构", card)

    def test_redacts_common_secret_shapes_before_writing_card_or_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "session.jsonl"
            cards = tmp_path / "cards"
            openai_token = fake_openai_token()
            github_token = fake_github_token()
            write_jsonl(
                transcript,
                [
                    {
                        "timestamp": "2026-06-30T02:01:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": (
                                f"token {openai_token} "
                                f"github {github_token} "
                                "AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz1234567890"
                            ),
                        },
                    }
                ],
            )

            result = run_hook(transcript, cards)

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            card_path = Path(output["summary_card_path"])
            combined = result.stdout + card_path.read_text(encoding="utf-8")
            self.assertNotIn(openai_token, combined)
            self.assertNotIn(github_token, combined)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz1234567890", combined)
            self.assertIn("[REDACTED]", combined)

    def test_filters_codex_instruction_boilerplate_from_summary_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "session.jsonl"
            cards = tmp_path / "cards"
            write_jsonl(
                transcript,
                [
                    {
                        "timestamp": "2026-06-30T02:00:00.000Z",
                        "type": "turn_context",
                        "payload": {"summary": "auto"},
                    },
                    {
                        "timestamp": "2026-06-30T02:00:01.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "<permissions instructions>Filesystem sandboxing...",
                                }
                            ],
                        },
                    },
                    {
                        "timestamp": "2026-06-30T02:00:02.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "# AGENTS.md instructions for /tmp/project\n<INSTRUCTIONS>...</INSTRUCTIONS>",
                        },
                    },
                    {
                        "timestamp": "2026-06-30T02:00:03.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "请保留这个真实请求。",
                        },
                    },
                ],
            )

            result = run_hook(transcript, cards)

            self.assertEqual(result.returncode, 0, result.stderr)
            card_path = Path(json.loads(result.stdout)["summary_card_path"])
            card = card_path.read_text(encoding="utf-8")
            self.assertIn("请保留这个真实请求", card)
            self.assertNotIn("permissions instructions", card)
            self.assertNotIn("AGENTS.md instructions", card)
            self.assertNotIn("## 已有上下文摘要", card)

    def test_includes_active_task_ledger_items_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "session.jsonl"
            cards = tmp_path / "cards"
            ledger = tmp_path / "task-ledger"
            ledger.mkdir()
            (ledger / "index.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "tasks": {
                            "task-1": {
                                "id": "task-1",
                                "title": "继续 Program 工作区整理",
                                "status": "todo",
                                "next_action": "运行 program-curator apply",
                                "project": {"name": "Program"},
                            },
                            "task-2": {
                                "id": "task-2",
                                "title": "已完成任务",
                                "status": "done",
                                "next_action": "",
                                "project": {"name": "Program"},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            write_jsonl(
                transcript,
                [
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "继续处理任务连续性。"},
                    }
                ],
            )

            result = run_hook(transcript, cards, {"CODEX_TASK_LEDGER_DIR": str(ledger)})

            self.assertEqual(result.returncode, 0, result.stderr)
            card_path = Path(json.loads(result.stdout)["summary_card_path"])
            card = card_path.read_text(encoding="utf-8")
            self.assertIn("## 未完成任务", card)
            self.assertIn("继续 Program 工作区整理", card)
            self.assertIn("运行 program-curator apply", card)
            self.assertNotIn("已完成任务", card)

    def test_includes_program_manifest_candidates_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transcript = tmp_path / "session.jsonl"
            cards = tmp_path / "cards"
            governance = tmp_path / "program-governance"
            artifact_dir = governance / "artifacts" / "2026-07-03"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "019f-test-session.json").write_text(
                json.dumps(
                    {
                        "session_id": "019f-test-session",
                        "candidate_count": 1,
                        "candidates": [
                            {
                                "path": "/Users/dysania/program/_inbox/needs-review/loose-summary.md",
                                "exists": True,
                                "suggested_action": "curator_plan",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            write_jsonl(
                transcript,
                [
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "总结本轮产物。"},
                    }
                ],
            )

            result = run_hook(
                transcript,
                cards,
                {"CODEX_PROGRAM_GOVERNANCE_DIR": str(governance)},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            card_path = Path(json.loads(result.stdout)["summary_card_path"])
            card = card_path.read_text(encoding="utf-8")
            self.assertIn("## 本轮产物和归档建议", card)
            self.assertIn("/Users/dysania/program/_inbox/needs-review/loose-summary.md", card)


if __name__ == "__main__":
    unittest.main()
