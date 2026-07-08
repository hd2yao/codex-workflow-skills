import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "program-artifact-tracker.py"


def fake_openai_token():
    return "sk-proj-" + "abcdefghijklmnopqrstuvwxyz" + "1234567890"


def write_jsonl(path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def run_hook(hook_input, governance_dir):
    env = os.environ.copy()
    env["CODEX_PROGRAM_GOVERNANCE_DIR"] = str(governance_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(hook_input, ensure_ascii=False),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class ProgramArtifactTrackerTest(unittest.TestCase):
    def test_stop_hook_writes_manifest_and_markdown_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            governance_dir = tmp_path / "governance"
            transcript = tmp_path / "session.jsonl"
            artifact = tmp_path / "program" / "loose-summary.md"
            openai_token = fake_openai_token()
            artifact.parent.mkdir()
            artifact.write_text("# summary", encoding="utf-8")
            write_jsonl(
                transcript,
                [
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": f"请把总结保存到 {artifact}",
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
                                    "text": f"已生成文件 loose-summary.md；token {openai_token}",
                                }
                            ],
                        },
                    },
                ],
            )

            result = run_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session-004",
                    "cwd": str(artifact.parent),
                    "transcript_path": str(transcript),
                },
                governance_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertTrue(output["continue"])
            manifest_path = Path(output["manifest_path"])
            markdown_path = Path(output["markdown_path"])
            self.assertTrue(manifest_path.exists())
            self.assertTrue(markdown_path.exists())
            manifest_text = manifest_path.read_text(encoding="utf-8")
            markdown_text = markdown_path.read_text(encoding="utf-8")
            self.assertIn(str(artifact), manifest_text)
            self.assertNotIn(openai_token, manifest_text + markdown_text)
            manifest = json.loads(manifest_text)
            self.assertEqual(manifest["session_id"], "session-004")
            self.assertEqual(manifest["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
