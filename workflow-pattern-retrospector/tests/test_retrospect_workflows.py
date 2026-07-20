import json
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

    def test_previous_week_excludes_older_files_and_maps_existing_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / "task-ledger" / "digests" / "daily"
            cards = root / "context-cards"
            work = root / "work-ledger"
            obsidian = root / "obsidian"
            out = root / "reports"
            skills = root / "skills"
            for directory in (task, cards, work, obsidian, skills):
                directory.mkdir(parents=True)

            (task / "2026-07-10.md").write_text(
                "旧周出现 GitHub 项目初始化。", encoding="utf-8"
            )
            (task / "2026-07-15.md").write_text(
                "本周多次使用 GitHub 项目初始化和首次提交。", encoding="utf-8"
            )
            (skills / "github-project-bootstrap").mkdir()
            (skills / "github-project-bootstrap" / "SKILL.md").write_text(
                "---\nname: github-project-bootstrap\n---\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--today",
                    "2026-07-20",
                    "--previous-week",
                    "--task-ledger-dir",
                    str(root / "task-ledger"),
                    "--context-card-dir",
                    str(cards),
                    "--work-ledger-dir",
                    str(work),
                    "--obsidian-codex-dir",
                    str(obsidian),
                    "--existing-skills-dir",
                    str(skills),
                    "--output-dir",
                    str(out),
                    "--stdout",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("2026-07-13 至 2026-07-19", result.stdout)
            self.assertIn("更新已有能力", result.stdout)
            self.assertIn("github-project-bootstrap", result.stdout)
            self.assertNotIn("旧周出现", result.stdout)

            state = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
            candidate = state["candidates"]["github-bootstrap"]
            self.assertEqual(1, candidate["weeks_seen"])
            self.assertEqual(["2026-07-13_to_2026-07-19"], candidate["periods"])

    def test_multiple_cards_from_same_thread_count_as_one_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cards = root / "context-cards"
            cards.mkdir(parents=True)
            for index in range(6):
                (cards / f"20260715-120{index}00-tools-019faaaa-bbbb-cccc-dddd-eeeeeeeeeeee.md").write_text(
                    "重复讨论 Skill 安装、归档和 SKILL.md。", encoding="utf-8"
                )

            out = root / "reports"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--today",
                    "2026-07-20",
                    "--previous-week",
                    "--task-ledger-dir",
                    str(root / "task-ledger"),
                    "--context-card-dir",
                    str(cards),
                    "--work-ledger-dir",
                    str(root / "work-ledger"),
                    "--obsidian-codex-dir",
                    str(root / "obsidian"),
                    "--existing-skills-dir",
                    str(root / "skills"),
                    "--output-dir",
                    str(out),
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            state = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
            candidate = state["candidates"]["skill-governance"]
            self.assertEqual(1, candidate["latest_source_count"])
            self.assertEqual("observed", candidate["status"])


if __name__ == "__main__":
    unittest.main()
