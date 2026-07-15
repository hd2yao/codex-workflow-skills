import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repository-action-budget.py"


def load_module():
    spec = importlib.util.spec_from_file_location("repository_action_budget", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryActionBudgetTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "action-budget.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def good_run(self):
        return {
            "attempted": 3,
            "succeeded": 3,
            "unsafe_actions": 0,
            "conflicts": 0,
            "duration_seconds": 600,
            "api_remaining": 4500,
            "api_limit": 5000,
        }

    def test_starts_at_three_and_grows_after_seven_eligible_runs(self):
        state = self.module.load_state(self.path)
        self.assertEqual(3, state["current_limit"])

        for _ in range(6):
            state = self.module.record_run(self.path, self.good_run())
            self.assertEqual(3, state["current_limit"])
        state = self.module.record_run(self.path, self.good_run())

        self.assertEqual(5, state["current_limit"])
        self.assertEqual("growth", state["last_adjustment"]["reason"])

    def test_risk_event_regresses_to_previous_rung(self):
        state = self.module.load_state(self.path)
        state["current_limit"] = 8
        self.module.save_state(self.path, state)

        state = self.module.record_run(
            self.path,
            {
                **self.good_run(),
                "attempted": 5,
                "succeeded": 2,
                "conflicts": 1,
            },
        )

        self.assertEqual(5, state["current_limit"])
        self.assertEqual("regression", state["last_adjustment"]["reason"])

    def test_zero_attempt_runs_do_not_qualify_for_growth(self):
        for _ in range(10):
            state = self.module.record_run(
                self.path,
                {
                    **self.good_run(),
                    "attempted": 0,
                    "succeeded": 0,
                },
            )

        self.assertEqual(3, state["current_limit"])
        self.assertEqual(0, state["consecutive_eligible_runs"])


if __name__ == "__main__":
    unittest.main()
