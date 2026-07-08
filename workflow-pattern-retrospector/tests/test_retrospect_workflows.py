import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retrospect_workflows.py"


class RetrospectWorkflowsTest(unittest.TestCase):
    def test_detects_repeated_skill_governance_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "task-ledger" / "digests" / "daily"
            cards = root / "context-cards"
            work = root / "work-ledger"
            obsidian = root / "obsidian"
            out = root / "reports"
            for directory in (task, cards, work, obsidian):
                directory.mkdir(parents=True)

            (task / "2026-07-07.md").write_text(
                "新增 skill，更新 SKILL.md，合并 template，并记录 Codex 变更日志。",
                encoding="utf-8",
            )
            (task / "2026-07-08.md").write_text(
                "继续处理技能安装、agents/openai.yaml、Obsidian Skills 搜索索引。",
                encoding="utf-8",
            )
            (cards / "20260708-skills.md").write_text(
                "用户要求评估哪些技能重复，哪些模板应该归档或合并。",
                encoding="utf-8",
            )
            (work / "index.md").write_text("完成 workflow skill 治理。", encoding="utf-8")
            (obsidian / "Codex 变更日志.md").write_text(
                "Skill 治理、安装和归档记录。", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--today",
                    "2026-07-08",
                    "--days",
                    "7",
                    "--task-ledger-dir",
                    str(root / "task-ledger"),
                    "--context-card-dir",
                    str(cards),
                    "--work-ledger-dir",
                    str(work),
                    "--obsidian-codex-dir",
                    str(obsidian),
                    "--output-dir",
                    str(out),
                    "--stdout",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("Skill/模板治理与归档", result.stdout)
            self.assertIn("不自动创建", result.stdout)
            self.assertTrue((out / "2026-07-08-workflow-patterns.md").exists())


if __name__ == "__main__":
    unittest.main()
