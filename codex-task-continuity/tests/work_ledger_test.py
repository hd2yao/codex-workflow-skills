import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "work-ledger.py"


def fake_openai_token():
    return "sk-proj-" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


def fake_github_token():
    return "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


def run_work(args, work_dir, obsidian_path=None):
    env = os.environ.copy()
    env["CODEX_WORK_LEDGER_DIR"] = str(work_dir)
    if obsidian_path:
        env["CODEX_WORK_LEDGER_OBSIDIAN_PATH"] = str(obsidian_path)
    else:
        env["CODEX_WORK_LEDGER_OBSIDIAN_PATH"] = "-"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class WorkLedgerTest(unittest.TestCase):
    def test_add_list_and_write_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            work_dir = tmp_path / "work-ledger"
            obsidian_path = tmp_path / "vault" / "03_Resources" / "Codex工作台" / "Codex 工作成果账本.md"

            added = run_work(
                [
                    "add",
                    "--title",
                    "实现每日任务摘要自动化",
                    "--status",
                    "completed",
                    "--summary",
                    "每天生成任务、产物和最近完成项摘要。",
                    "--capability",
                    "北京时间每天 09:30 自动触发。",
                    "--usage",
                    "查看固定 Codex 摘要线程。",
                    "--verification",
                    "Hook 单元测试通过。",
                    "--limitation",
                    "不能识别当前聚焦线程。",
                    "--follow-up",
                    "后续可接入原生按钮。",
                    "--project-name",
                    "Codex 工作台",
                    "--project-path",
                    "/Users/dysania/program/codex-workflow-skills",
                    "--commit",
                    "abc1234",
                    "--file",
                    "/Users/dysania/program/codex-workflow-skills/codex-task-continuity/scripts/task-continuity-hook.py",
                    "--tag",
                    "codex,automation",
                    "--format",
                    "json",
                ],
                work_dir,
                obsidian_path,
            )

            self.assertEqual(added.returncode, 0, added.stderr)
            work = json.loads(added.stdout)["work"]
            self.assertEqual(work["status"], "completed")
            self.assertEqual(work["title"], "实现每日任务摘要自动化")
            self.assertEqual(work["capabilities"], ["北京时间每天 09:30 自动触发。"])
            self.assertTrue((work_dir / "work.jsonl").exists())
            self.assertTrue((work_dir / "index.json").exists())
            self.assertTrue((work_dir / "index.md").exists())
            self.assertTrue(obsidian_path.exists())
            index_text = (work_dir / "index.md").read_text(encoding="utf-8")
            obsidian_text = obsidian_path.read_text(encoding="utf-8")
            self.assertIn("实现每日任务摘要自动化", index_text)
            self.assertIn("如何使用", index_text)
            self.assertIn("实现每日任务摘要自动化", obsidian_text)

            listed = run_work(["list", "--format", "json"], work_dir, obsidian_path)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            works = json.loads(listed.stdout)["works"]
            self.assertEqual([item["id"] for item in works], [work["id"]])

    def test_redacts_common_secret_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp) / "work-ledger"
            openai_token = fake_openai_token()
            github_token = fake_github_token()
            secret = f"token {openai_token}"

            result = run_work(
                [
                    "add",
                    "--title",
                    secret,
                    "--summary",
                    f"github {github_token}",
                    "--format",
                    "json",
                ],
                work_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            combined = result.stdout
            combined += (work_dir / "work.jsonl").read_text(encoding="utf-8")
            combined += (work_dir / "index.json").read_text(encoding="utf-8")
            combined += (work_dir / "index.md").read_text(encoding="utf-8")
            self.assertNotIn(openai_token, combined)
            self.assertNotIn(github_token, combined)
            self.assertIn("[REDACTED]", combined)


if __name__ == "__main__":
    unittest.main()
