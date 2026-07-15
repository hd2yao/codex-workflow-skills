import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "recurring-task-audit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("recurring_task_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecurringTaskAuditTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def write_manifest(self, tasks):
        codex_dir = self.root / ".codex"
        codex_dir.mkdir(parents=True)
        path = codex_dir / "continuity.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project": {"name": "Example", "path": ".."},
                    "recurring_tasks": tasks,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_daily_task_is_success_only_with_fresh_success_evidence(self):
        outputs = self.root / "outputs"
        logs = outputs / "logs"
        logs.mkdir(parents=True)
        status = outputs / "ops_status.json"
        status.write_text(
            json.dumps(
                {
                    "generated_at": "2026-07-14T13:31:01Z",
                    "daily": {"as_of": "2026-07-14", "status": "success", "data_quality_grade": "normal"},
                }
            ),
            encoding="utf-8",
        )
        log = logs / "daily-ops-2026-07-14.log"
        log.write_text("daily ops log: outputs/logs/daily-ops-2026-07-14.log\n", encoding="utf-8")
        manifest = self.write_manifest(
            [
                {
                    "id": "daily",
                    "name": "每日任务",
                    "schedule": {"type": "daily", "hour": 21, "minute": 30, "timezone": "Asia/Shanghai", "grace_minutes": 120},
                    "runner": {"type": "launchd", "label": "com.example.daily"},
                    "evidence": {
                        "status_json": "outputs/ops_status.json",
                        "status_pointer": "/daily/status",
                        "run_date_pointer": "/daily/as_of",
                        "observed_at_pointer": "/generated_at",
                        "success_values": ["success"],
                        "log_glob": "outputs/logs/daily-ops-*.log",
                        "success_pattern": "daily ops log:",
                        "detail_pointers": {"数据质量": "/daily/data_quality_grade"},
                    },
                }
            ]
        )
        now = datetime(2026, 7, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        report = self.module.audit_manifests(
            [manifest],
            now=now,
            launchctl_reader=lambda _label: {"loaded": True, "runs": 2, "last_exit_code": 0},
        )

        task = report["tasks"][0]
        self.assertEqual("success", task["status"])
        self.assertEqual("2026-07-14", task["run_date"])
        self.assertEqual("normal", task["details"]["数据质量"])
        self.assertEqual(1, report["counts"]["success"])

    def test_stale_daily_evidence_is_overdue(self):
        outputs = self.root / "outputs"
        outputs.mkdir()
        (outputs / "ops_status.json").write_text(
            json.dumps({"daily": {"as_of": "2026-07-12", "status": "success"}}),
            encoding="utf-8",
        )
        manifest = self.write_manifest(
            [
                {
                    "id": "daily",
                    "name": "每日任务",
                    "schedule": {"type": "daily", "hour": 21, "minute": 30, "timezone": "Asia/Shanghai", "grace_minutes": 60},
                    "runner": {"type": "launchd", "label": "com.example.daily"},
                    "evidence": {
                        "status_json": "outputs/ops_status.json",
                        "status_pointer": "/daily/status",
                        "run_date_pointer": "/daily/as_of",
                        "success_values": ["success"],
                    },
                }
            ]
        )

        report = self.module.audit_manifests(
            [manifest],
            now=datetime(2026, 7, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            launchctl_reader=lambda _label: {"loaded": True, "runs": 2, "last_exit_code": 0},
        )

        self.assertEqual("overdue", report["tasks"][0]["status"])
        self.assertIn("2026-07-14", report["tasks"][0]["reason"])

    def test_fresh_manual_success_does_not_hide_unloaded_scheduler(self):
        logs = self.root / "outputs" / "logs"
        logs.mkdir(parents=True)
        log = logs / "daily-ops-2026-07-14.log"
        log.write_text("daily complete\n", encoding="utf-8")
        timestamp = datetime(2026, 7, 14, 21, 31, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        import os

        os.utime(log, (timestamp, timestamp))
        manifest = self.write_manifest(
            [
                {
                    "id": "daily",
                    "name": "每日任务",
                    "schedule": {"type": "daily", "hour": 21, "minute": 30, "timezone": "Asia/Shanghai"},
                    "runner": {"type": "launchd", "label": "com.example.daily"},
                    "evidence": {"log_glob": "outputs/logs/daily-ops-*.log", "success_pattern": "daily complete"},
                }
            ]
        )

        report = self.module.audit_manifests(
            [manifest],
            now=datetime(2026, 7, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            launchctl_reader=lambda _label: {"loaded": False, "runs": 0, "last_exit_code": None},
        )

        self.assertEqual("failed", report["tasks"][0]["status"])
        self.assertIn("未加载", report["tasks"][0]["reason"])

    def test_weekly_manual_success_after_expected_schedule_counts_as_success(self):
        logs = self.root / "outputs" / "logs"
        logs.mkdir(parents=True)
        log = logs / "weekly-ops-2026-07-13.log"
        log.write_text("weekly ops log: outputs/logs/weekly-ops-2026-07-13.log\n", encoding="utf-8")
        timestamp = datetime(2026, 7, 13, 10, 40, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        log.touch()
        import os

        os.utime(log, (timestamp, timestamp))
        manifest = self.write_manifest(
            [
                {
                    "id": "weekly",
                    "name": "每周任务",
                    "schedule": {"type": "weekly", "iso_weekdays": [6], "hour": 10, "minute": 0, "timezone": "Asia/Shanghai", "grace_minutes": 180},
                    "runner": {"type": "launchd", "label": "com.example.weekly"},
                    "evidence": {"log_glob": "outputs/logs/weekly-ops-*.log", "success_pattern": "weekly ops log:"},
                }
            ]
        )

        report = self.module.audit_manifests(
            [manifest],
            now=datetime(2026, 7, 15, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            launchctl_reader=lambda _label: {"loaded": True, "runs": 0, "last_exit_code": None},
        )

        task = report["tasks"][0]
        self.assertEqual("success", task["status"])
        self.assertIn("2026-07-13", task["reason"])
        self.assertIn("2026-07-18", task["next_expected_at"])


if __name__ == "__main__":
    unittest.main()
