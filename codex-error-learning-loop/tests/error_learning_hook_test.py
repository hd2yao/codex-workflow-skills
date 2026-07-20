import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).resolve().parents[1] / "scripts" / "error-learning-hook.py"


def transcript_record(timestamp, role, text):
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        },
    }


class ErrorLearningHookTest(unittest.TestCase):
    def run_hook(self, root, transcript, thread_id="thread-a"):
        env = os.environ.copy()
        env["CODEX_ERROR_LEARNING_DIR"] = str(root / "ledger")
        env["CODEX_ERROR_LEARNING_SKILL_DIR"] = str(HOOK.parents[1])
        payload = {
            "hook_event_name": "Stop",
            "session_id": thread_id,
            "transcript_path": str(transcript),
            "cwd": "/tmp/codex-workflow",
        }
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )

    def test_records_explicit_correction_and_stays_silent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "rollout.jsonl"
            transcript.write_text(
                json.dumps(
                    transcript_record(
                        "2026-07-20T01:00:00Z",
                        "user",
                        "你还是没有把周总结投递给我，不能只生成内部文档。",
                    ),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.run_hook(root, transcript)
            self.assertEqual("", result.stdout)
            observations = json.loads(
                (root / "ledger" / "observations.json").read_text(encoding="utf-8")
            )["observations"]
            self.assertEqual(1, len(observations))
            item = next(iter(observations.values()))
            self.assertIn("user_visibility_gap", item["categories"])

            self.run_hook(root, transcript)
            observations = json.loads(
                (root / "ledger" / "observations.json").read_text(encoding="utf-8")
            )["observations"]
            self.assertEqual(1, len(observations))

    def test_ignores_normal_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "rollout.jsonl"
            transcript.write_text(
                json.dumps(
                    transcript_record(
                        "2026-07-20T01:00:00Z",
                        "user",
                        "请帮我生成今天的项目摘要。",
                    ),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.run_hook(root, transcript)
            self.assertEqual("", result.stdout)
            self.assertFalse((root / "ledger" / "observations.json").exists())

    def test_ignores_new_preference_without_correction_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "rollout.jsonl"
            transcript.write_text(
                json.dumps(
                    transcript_record(
                        "2026-07-20T01:00:00Z",
                        "user",
                        "我希望每周摘要按项目展示，并在周一生成。",
                    ),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.run_hook(root, transcript)
            self.assertEqual("", result.stdout)
            self.assertFalse((root / "ledger" / "observations.json").exists())


if __name__ == "__main__":
    unittest.main()
