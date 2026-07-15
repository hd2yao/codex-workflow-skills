#!/usr/bin/env python3
"""审计项目声明的周期任务是否按计划产生了新鲜成功证据。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_ROOT = Path("/Users/dysania/program")
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    "vendor",
}
STATUSES = ("success", "overdue", "failed", "unknown")


def discover_manifests(roots):
    found = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.exists():
            continue
        direct = root / ".codex" / "continuity.json"
        if direct.is_file():
            found.add(direct.resolve())
        for current, dirnames, _filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
            candidate = Path(current) / ".codex" / "continuity.json"
            if candidate.is_file():
                found.add(candidate.resolve())
                if ".codex" in dirnames:
                    dirnames.remove(".codex")
    return sorted(found, key=lambda path: str(path).lower())


def json_pointer(data, pointer):
    if not pointer:
        return None
    current = data
    for raw_part in str(pointer).lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def parse_datetime(value, timezone):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def parse_date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def schedule_points(schedule, now):
    timezone = ZoneInfo(schedule.get("timezone") or "Asia/Shanghai")
    local_now = now.astimezone(timezone)
    hour = int(schedule.get("hour", 0))
    minute = int(schedule.get("minute", 0))
    schedule_type = schedule.get("type")
    if schedule_type == "daily":
        expected = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if expected > local_now:
            expected -= dt.timedelta(days=1)
        return expected, expected + dt.timedelta(days=1)
    if schedule_type == "weekly":
        weekdays = {int(day) for day in schedule.get("iso_weekdays", [])}
        if not weekdays:
            raise ValueError("weekly schedule requires iso_weekdays")
        expected = None
        for offset in range(8):
            day = local_now.date() - dt.timedelta(days=offset)
            candidate = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=timezone)
            if day.isoweekday() in weekdays and candidate <= local_now:
                expected = candidate
                break
        if expected is None:
            raise ValueError("unable to calculate previous weekly schedule")
        next_expected = None
        for offset in range(1, 8):
            day = expected.date() + dt.timedelta(days=offset)
            if day.isoweekday() in weekdays:
                next_expected = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=timezone)
                break
        return expected, next_expected
    raise ValueError(f"unsupported schedule type: {schedule_type}")


def read_launchctl(label):
    if not label:
        return {"loaded": False, "runs": 0, "last_exit_code": None}
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode:
        return {"loaded": False, "runs": 0, "last_exit_code": None}
    runs_match = re.search(r"^\s*runs\s*=\s*(\d+)\s*$", result.stdout, re.MULTILINE)
    exit_match = re.search(r"^\s*last exit code\s*=\s*(-?\d+)\s*$", result.stdout, re.MULTILINE)
    return {
        "loaded": True,
        "runs": int(runs_match.group(1)) if runs_match else 0,
        "last_exit_code": int(exit_match.group(1)) if exit_match else None,
    }


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def latest_log(project_root, glob_pattern, success_pattern):
    if not glob_pattern:
        return None
    matches = [path for path in project_root.glob(glob_pattern) if path.is_file()]
    if not matches:
        return None
    path = max(matches, key=lambda item: item.stat().st_mtime)
    matched = not success_pattern
    if success_pattern:
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 65536))
                tail = handle.read().decode("utf-8", errors="replace")
            matched = success_pattern in tail
        except OSError:
            matched = False
    return {
        "path": str(path),
        "observed_at": dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc),
        "success": matched,
    }


def resolve_project_root(manifest_path, project):
    configured = project.get("path") if isinstance(project, dict) else None
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = manifest_path.parent / path
        return path.resolve()
    return manifest_path.parent.parent.resolve()


def audit_task(manifest_path, project, task, now, launchctl_reader):
    schedule = task.get("schedule") or {}
    expected, next_expected = schedule_points(schedule, now)
    timezone = expected.tzinfo
    grace = dt.timedelta(minutes=max(0, int(schedule.get("grace_minutes", 120))))
    evidence = task.get("evidence") or {}
    project_root = resolve_project_root(manifest_path, project)
    runner = task.get("runner") or {}
    launch_state = (
        launchctl_reader(runner.get("label"))
        if runner.get("type") == "launchd"
        else {"loaded": None, "runs": None, "last_exit_code": None}
    )

    status_data = None
    status_path = None
    if evidence.get("status_json"):
        status_path = (project_root / evidence["status_json"]).resolve()
        status_data = load_json(status_path)
    status_value = json_pointer(status_data, evidence.get("status_pointer")) if status_data else None
    run_date_value = json_pointer(status_data, evidence.get("run_date_pointer")) if status_data else None
    observed_value = json_pointer(status_data, evidence.get("observed_at_pointer")) if status_data else None
    run_date = parse_date(run_date_value)
    observed_at = parse_datetime(observed_value, timezone)
    success_values = set(evidence.get("success_values") or ["success", "ok"])
    fresh_status = bool(run_date and run_date >= expected.date() and status_value in success_values)

    log = latest_log(project_root, evidence.get("log_glob"), evidence.get("success_pattern"))
    log_observed = log["observed_at"].astimezone(timezone) if log else None
    fresh_log = bool(log and log["success"] and log_observed >= expected)
    observed_candidates = [value for value in (observed_at, log_observed) if value]
    latest_observed = max(observed_candidates) if observed_candidates else None

    fresh_failure = bool(
        run_date
        and run_date >= expected.date()
        and status_value is not None
        and status_value not in success_values
    )
    exit_failure = bool(
        launch_state.get("last_exit_code") not in (None, 0)
        and latest_observed
        and latest_observed >= expected
    )
    scheduler_missing = runner.get("type") == "launchd" and launch_state.get("loaded") is False
    if scheduler_missing:
        status = "failed"
        reason = "launchd 调度器未加载；最近的手动运行证据不能证明后续会按计划触发"
    elif fresh_failure or exit_failure:
        status = "failed"
        reason = f"{expected.date().isoformat()} 计划运行已有失败证据"
    elif fresh_status or fresh_log:
        status = "success"
        if fresh_status:
            evidence_date = run_date
            success_observed = observed_at
        else:
            evidence_date = log_observed.date()
            success_observed = log_observed
        reason = f"{evidence_date.isoformat()} 已取得新鲜成功证据"
    elif now.astimezone(timezone) > expected + grace:
        status = "overdue"
        reason = f"未发现覆盖 {expected.date().isoformat()} 计划运行的新鲜成功证据"
    else:
        status = "unknown"
        reason = f"{expected.isoformat()} 的运行仍在宽限期内"
    if status != "success":
        success_observed = None

    details = {}
    for label, pointer in (evidence.get("detail_pointers") or {}).items():
        value = json_pointer(status_data, pointer) if status_data else None
        if value is not None:
            details[str(label)] = value

    project_name = project.get("name") if isinstance(project, dict) else None
    return {
        "id": str(task.get("id") or task.get("name") or "recurring-task"),
        "project": str(project_name or project_root.name),
        "project_path": str(project_root),
        "name": str(task.get("name") or task.get("id") or "周期任务"),
        "status": status,
        "reason": reason,
        "expected_at": expected.isoformat(),
        "next_expected_at": next_expected.isoformat() if next_expected else None,
        "run_date": run_date.isoformat() if run_date else None,
        "observed_at": (success_observed or latest_observed).isoformat() if (success_observed or latest_observed) else None,
        "scheduler_loaded": launch_state.get("loaded"),
        "scheduler_runs": launch_state.get("runs"),
        "last_exit_code": launch_state.get("last_exit_code"),
        "status_path": str(status_path) if status_path else None,
        "log_path": log.get("path") if log else None,
        "details": details,
    }


def audit_manifests(manifests, *, now=None, launchctl_reader=read_launchctl):
    now = now or dt.datetime.now(dt.timezone.utc)
    tasks = []
    warnings = []
    for raw_path in manifests:
        manifest_path = Path(raw_path).expanduser().resolve()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{manifest_path}: 周期任务声明无法读取：{exc}")
            continue
        project = manifest.get("project") or {}
        for task in manifest.get("recurring_tasks") or []:
            try:
                tasks.append(audit_task(manifest_path, project, task, now, launchctl_reader))
            except Exception as exc:
                warnings.append(f"{manifest_path}: {task.get('id') or task.get('name')}: {exc}")
    counts = {status: 0 for status in STATUSES}
    for task in tasks:
        counts[task["status"]] += 1
    return {
        "schema_version": 1,
        "generated_at": now.astimezone().isoformat(timespec="seconds"),
        "task_count": len(tasks),
        "counts": counts,
        "tasks": sorted(tasks, key=lambda item: (item["status"], item["project"], item["name"])),
        "warnings": sorted(set(warnings)),
    }


def render_markdown(report):
    labels = {"success": "正常", "overdue": "延迟", "failed": "失败", "unknown": "待确认"}
    lines = ["# 周期任务运行审计", ""]
    for task in report["tasks"]:
        lines.append(f"- **{labels[task['status']]}**：{task['project']} / {task['name']}")
        lines.append(f"  判断：{task['reason']}")
        lines.append(f"  下次计划：{task.get('next_expected_at') or '未记录'}")
    for warning in report["warnings"]:
        lines.append(f"- 警告：{warning}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", default=[])
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    manifests = [Path(path).expanduser() for path in args.manifest]
    if not manifests:
        configured = os.environ.get("CODEX_RECURRING_TASK_MANIFESTS")
        if configured:
            manifests = [Path(path).expanduser() for path in configured.split(os.pathsep) if path]
        else:
            roots = args.root or [str(DEFAULT_ROOT)]
            manifests = discover_manifests(roots)
    report = audit_manifests(manifests)
    if args.format == "markdown":
        sys.stdout.write(render_markdown(report))
    else:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
