import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "thread-health-guard.py"
SPEC = importlib.util.spec_from_file_location("thread_health_guard", SCRIPT)
thread_health_guard = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["thread_health_guard"] = thread_health_guard
SPEC.loader.exec_module(thread_health_guard)


class ThreadHealthGuardTest(unittest.TestCase):
    def snapshot(self, *, tokens=0, cards=0, messages=None):
        return thread_health_guard.ThreadSnapshot(
            thread_id="abc123456789",
            title="实现上下文迁移判断",
            cwd="/Users/dysania/program/codex-workflow-skills",
            workspace_hint="/Users/dysania/program/codex-workflow-skills",
            tokens_used=tokens,
            context_card_count=cards,
            rollout_path="/tmp/thread.jsonl",
            messages=messages or [],
        )

    def test_high_risk_requires_context_pressure_and_pollution_or_struggle(self):
        result = thread_health_guard.score_snapshot(
            self.snapshot(
                tokens=130_000,
                cards=2,
                messages=[
                    ("用户", "不是这个，你理解错了，先别管前面的方案。"),
                    ("助手", "验证失败，测试 failed。"),
                    ("用户", "还是不对，重来。"),
                ],
            )
        )

        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["should_create_new_thread"])
        self.assertEqual(result["recommended_action"], "create_clean_continuation_thread")
        self.assertEqual(result["migration_kind"], "clean_continuation")

    def test_long_context_alone_is_not_high_risk(self):
        result = thread_health_guard.score_snapshot(
            self.snapshot(tokens=130_000, cards=2, messages=[("用户", "继续推进当前实现。")])
        )

        self.assertEqual(result["risk_level"], "medium")
        self.assertFalse(result["should_create_new_thread"])

    def test_pollution_without_context_pressure_is_not_high_risk(self):
        result = thread_health_guard.score_snapshot(
            self.snapshot(
                tokens=10_000,
                cards=0,
                messages=[
                    ("用户", "不是这个，搞错了。"),
                    ("用户", "重来，前面不算。"),
                ],
            )
        )

        self.assertEqual(result["risk_level"], "medium")
        self.assertFalse(result["should_create_new_thread"])

    def test_phase_transition_after_commit_triggers_clean_continuation(self):
        result = thread_health_guard.score_snapshot(
            self.snapshot(
                tokens=20_000,
                cards=0,
                messages=[
                    ("用户", "M1 阶段已完成并 commit，接下来进入 M2 核心功能实现。"),
                ],
            )
        )

        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["should_create_new_thread"])
        self.assertGreaterEqual(result["scores"]["phase_transition"], 4)
        self.assertIn("docs/HANDOFF.md", result["handoff_first_files"])
        self.assertIn("README.md", result["new_thread_prompt_suffix"])

    def test_migration_blockers_defer_otherwise_high_risk_migration(self):
        result = thread_health_guard.score_snapshot(
            self.snapshot(
                tokens=130_000,
                cards=2,
                messages=[
                    ("用户", "M1 阶段已完成并 commit，接下来进入 M2。"),
                    ("助手", "测试还在跑，等待输出。"),
                ],
            )
        )

        self.assertEqual(result["risk_level"], "medium")
        self.assertFalse(result["should_create_new_thread"])
        self.assertEqual(result["recommended_action"], "finish_current_closure_before_migration")
        self.assertTrue(result["migration_blockers"])

    def test_meta_guidance_does_not_trigger_phase_transition(self):
        result = thread_health_guard.score_snapshot(
            self.snapshot(
                tokens=20_000,
                cards=0,
                messages=[
                    (
                        "用户",
                        "评审一下这个建议：比如 M1 完成并 commit 后，下一阶段可以开新线程。",
                    ),
                ],
            )
        )

        self.assertEqual(result["risk_level"], "low")
        self.assertFalse(result["should_create_new_thread"])
        self.assertEqual(result["scores"]["phase_transition"], 0)

    def test_suggested_title_keeps_source_hint(self):
        title = thread_health_guard.title_for_continuation("一个很长的线程标题", "abcdef123456")

        self.assertEqual(title, "接续: 一个很长的线程标题 [from abcdef12]")


if __name__ == "__main__":
    unittest.main()
