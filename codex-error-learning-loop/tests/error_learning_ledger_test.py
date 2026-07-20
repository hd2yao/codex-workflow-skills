import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "error-learning-ledger.py"


class ErrorLearningLedgerTest(unittest.TestCase):
    def run_cli(self, root, *args, check=True):
        env = os.environ.copy()
        env["CODEX_ERROR_LEARNING_DIR"] = str(root)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--format", "json"],
            text=True,
            capture_output=True,
            env=env,
            check=check,
        )

    def record(self, root, thread_id, occurred_at, summary, *categories):
        args = [
            "record-observation",
            "--thread-id",
            thread_id,
            "--occurred-at",
            occurred_at,
            "--project-name",
            "Codex Workflow",
            "--project-path",
            "/tmp/codex-workflow",
            "--summary",
            summary,
            "--expected",
            "先记录，再按周跨线程分析",
        ]
        for category in categories:
            args.extend(["--category", category])
        return json.loads(self.run_cli(root, *args).stdout)["observation"]

    def test_records_and_deduplicates_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.record(
                root,
                "thread-a",
                "2026-07-15T10:00:00+08:00",
                "周总结已经生成，但用户没有看到。",
                "user_visibility_gap",
            )
            second = self.record(
                root,
                "thread-a",
                "2026-07-15T10:00:00+08:00",
                "周总结已经生成，但用户没有看到。",
                "user_visibility_gap",
            )

            self.assertEqual(first["id"], second["id"])
            listed = json.loads(
                self.run_cli(
                    root,
                    "list-observations",
                    "--from-date",
                    "2026-07-14",
                    "--to-date",
                    "2026-07-20",
                ).stdout
            )
            self.assertEqual(1, len(listed["observations"]))
            self.assertEqual("observed", listed["observations"][0]["status"])

    def test_weekly_synthesis_counts_independent_threads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.record(
                root,
                "thread-a",
                "2026-07-14T10:00:00+08:00",
                "内部报告生成但没有投递。",
                "user_visibility_gap",
            )
            self.record(
                root,
                "thread-a",
                "2026-07-15T10:00:00+08:00",
                "另一个结果也没有展示。",
                "user_visibility_gap",
            )
            self.record(
                root,
                "thread-b",
                "2026-07-18T10:00:00+08:00",
                "产物只保存在文档，用户看不到。",
                "user_visibility_gap",
            )

            review = json.loads(
                self.run_cli(root, "synthesize-week", "--today", "2026-07-20").stdout
            )
            self.assertEqual("2026-07-13", review["period"]["start"])
            self.assertEqual("2026-07-19", review["period"]["end"])
            candidate = review["candidates"][0]
            self.assertEqual(2, candidate["independent_thread_count"])
            self.assertEqual("monitoring", candidate["status"])
            self.assertEqual(3, candidate["observation_count"])

    def test_trial_requires_cross_thread_evidence_regression_and_governance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for thread_id in ("thread-a", "thread-b"):
                self.record(
                    root,
                    thread_id,
                    "2026-07-18T10:00:00+08:00",
                    f"{thread_id} 中仍然没有用户可见投递。",
                    "user_visibility_gap",
                )
            self.run_cli(root, "synthesize-week", "--today", "2026-07-20")

            failed = self.run_cli(
                root,
                "update-candidate",
                "--key",
                "user_visibility_gap",
                "--status",
                "trial",
                check=False,
            )
            self.assertNotEqual(0, failed.returncode)

            updated = json.loads(
                self.run_cli(
                    root,
                    "update-candidate",
                    "--key",
                    "user_visibility_gap",
                    "--status",
                    "trial",
                    "--regression-scenario",
                    "生成内部产物后必须验证用户可见投递",
                    "--root-cause",
                    "完成门禁缺少用户可见投递与消费验证",
                    "--existing-capability",
                    "codex-task-continuity",
                    "--governance-approved",
                ).stdout
            )["candidate"]
            self.assertEqual("trial", updated["status"])
            self.assertEqual(
                ["codex-task-continuity"], updated["existing_capabilities"]
            )
            self.assertIn("用户可见投递", updated["root_cause"])


if __name__ == "__main__":
    unittest.main()
