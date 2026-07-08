import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "scripts" / "program-curator.py"


def run_curator(args):
    return subprocess.run(
        [sys.executable, str(CURATOR), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def load_json(stdout):
    return json.loads(stdout)


class ProgramCuratorTest(unittest.TestCase):
    def test_scan_classifies_loose_docs_experiments_trash_and_protected_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "program"
            docs_codex = tmp_path / "Documents" / "Codex"
            root.mkdir(parents=True)
            docs_codex.mkdir(parents=True)
            (root / "loose-summary.md").write_text("# summary", encoding="utf-8")
            (root / "experiment-login").mkdir()
            (root / "experiment-login" / "probe.py").write_text("print('ok')", encoding="utf-8")
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            (root / ".DS_Store").write_text("cache", encoding="utf-8")
            (docs_codex / "conversation-output.md").write_text("# output", encoding="utf-8")
            git_project = root / "existing-project"
            git_project.mkdir()
            subprocess.run(["git", "init"], cwd=git_project, text=True, capture_output=True, check=True)

            result = run_curator(
                [
                    "scan",
                    "--root",
                    str(root),
                    "--documents-codex",
                    str(docs_codex),
                    "--format",
                    "json",
                ]
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            candidates = load_json(result.stdout)["candidates"]
            by_name = {Path(item["source"]).name: item for item in candidates}
            self.assertEqual(by_name["loose-summary.md"]["category"], "needs_review")
            self.assertEqual(by_name["conversation-output.md"]["category"], "needs_review")
            self.assertEqual(by_name["experiment-login"]["category"], "experiment")
            self.assertEqual(by_name[".DS_Store"]["category"], "trash_candidate")
            self.assertEqual(by_name[".env"]["action"], "skip")
            self.assertEqual(by_name["existing-project"]["action"], "skip")

    def test_plan_and_apply_move_only_preauthorized_low_risk_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "program"
            output_dir = tmp_path / "plans"
            root.mkdir()
            loose_doc = root / "loose-summary.md"
            experiment = root / "tmp-analysis"
            trash = root / "__pycache__"
            sensitive = root / "private.key"
            loose_doc.write_text("# summary", encoding="utf-8")
            experiment.mkdir()
            (experiment / "probe.txt").write_text("data", encoding="utf-8")
            trash.mkdir()
            (trash / "cache.pyc").write_text("cache", encoding="utf-8")
            sensitive.write_text("secret", encoding="utf-8")

            planned = run_curator(
                [
                    "plan",
                    "--root",
                    str(root),
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-03",
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            plan_path = Path(load_json(planned.stdout)["plan_path"])
            self.assertTrue(plan_path.exists())

            applied = run_curator(["apply", "--plan", str(plan_path), "--format", "json"])

            self.assertEqual(applied.returncode, 0, applied.stderr)
            result = load_json(applied.stdout)
            self.assertEqual(result["moved_count"], 3)
            self.assertFalse(loose_doc.exists())
            self.assertFalse(experiment.exists())
            self.assertFalse(trash.exists())
            self.assertTrue(sensitive.exists())
            self.assertTrue((root / "_inbox" / "needs-review" / "loose-summary.md").exists())
            self.assertTrue((root / "_experiments" / "tmp-analysis").exists())
            self.assertTrue(
                (root / "_archive" / "trash-candidates" / "2026-07-03" / "__pycache__").exists()
            )
            self.assertTrue(Path(result["move_log_path"]).exists())

    def test_apply_refuses_tracked_files_even_if_plan_contains_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "program"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, text=True, capture_output=True, check=True)
            tracked = root / "tracked.md"
            tracked.write_text("# tracked", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.md"], cwd=root, text=True, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "track file"],
                cwd=root,
                text=True,
                capture_output=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"},
                check=True,
            )
            plan = root / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "root": str(root),
                        "date": "2026-07-03",
                        "operations": [
                            {
                                "source": str(tracked),
                                "destination": str(root / "_inbox" / "needs-review" / "tracked.md"),
                                "action": "move",
                                "category": "needs_review",
                                "risk": "low",
                                "reason": "synthetic plan",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_curator(["apply", "--plan", str(plan), "--format", "json"])

            self.assertEqual(result.returncode, 0, result.stderr)
            output = load_json(result.stdout)
            self.assertEqual(output["moved_count"], 0)
            self.assertTrue(tracked.exists())
            self.assertEqual(output["skipped"][0]["reason"], "protected_tracked_file")


if __name__ == "__main__":
    unittest.main()
