#!/usr/bin/env python3
import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo


LEDGER = Path(__file__).with_name("task-ledger.py")
ACTIVE_STATUS = "idea,todo,in_progress,waiting_user,blocked,needs_review,cleanup_candidate"
MARKERS = [
    (re.compile(r"^\s*(?:TODO|待办|下一步|需要继续|继续任务)\s*[:：]\s*(.+?)\s*$", re.I), "todo"),
    (re.compile(r"^\s*(?:等待确认|待确认|需要确认)\s*[:：]\s*(.+?)\s*$", re.I), "waiting_user"),
    (re.compile(r"^\s*(?:BLOCKED|阻塞|卡住)\s*[:：]\s*(.+?)\s*$", re.I), "blocked"),
    (re.compile(r"^\s*(?:IDEA|想法)\s*[:：]\s*(.+?)\s*$", re.I), "idea"),
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)AWS_SECRET_ACCESS_KEY\s*=\s*\S+"),
    re.compile(r"(?i)(cookie|set-cookie)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(sessionid|password|secret|token|api[_-]?key)\s*=\s*\S+"),
]
WORKFLOW_CHANGE_LABELS = {
    "skill_added": "Skill 新增",
    "skill_updated": "Skill 更新",
    "skill_removed": "Skill 移除",
    "hook_added": "Hook 新增",
    "hook_updated": "Hook 更新",
    "hook_removed": "Hook 移除",
    "automation_added": "Automation 新增",
    "automation_updated": "Automation 更新",
    "automation_removed": "Automation 移除",
    "plugin_added": "Plugin 新增",
    "plugin_updated": "Plugin 更新",
    "plugin_removed": "Plugin 移除",
}


def redact(text):
    value = "" if text is None else str(text)
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def read_hook_input():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def local_today():
    return dt.date.today().isoformat()


def local_yesterday():
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def pending_project_aging_days():
    raw = os.environ.get("CODEX_PENDING_PROJECT_AGING_DAYS", "3")
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(0, value)


def ledger_root():
    return Path(os.environ.get("CODEX_TASK_LEDGER_DIR", "~/.codex/task-ledger")).expanduser()


def program_root():
    return Path(os.environ.get("CODEX_PROGRAM_ROOT", "/Users/dysania/program")).expanduser()


def governance_root():
    return Path(os.environ.get("CODEX_PROGRAM_GOVERNANCE_DIR", "~/.codex/program-governance")).expanduser()


def work_ledger_root():
    return Path(os.environ.get("CODEX_WORK_LEDGER_DIR", "~/.codex/work-ledger")).expanduser()


def operation_ledger_path():
    return Path(
        os.environ.get("CODEX_OPERATION_LEDGER_PATH", "~/.codex/operation-ledger/events.jsonl")
    ).expanduser()


def automations_root():
    return Path(os.environ.get("CODEX_AUTOMATIONS_DIR", "~/.codex/automations")).expanduser()


def local_timezone():
    name = os.environ.get("CODEX_LOCAL_TIMEZONE", "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo("Asia/Shanghai")


def repository_closure_root():
    return Path(
        os.environ.get(
            "CODEX_REPOSITORY_CLOSURE_DIR",
            ledger_root() / "repository-closure",
        )
    ).expanduser()


def repository_closure_scanner():
    return Path(
        os.environ.get(
            "CODEX_REPOSITORY_CLOSURE_SCANNER",
            Path(__file__).with_name("repository-closure-audit.py"),
        )
    ).expanduser()


def recurring_task_scanner():
    return Path(
        os.environ.get(
            "CODEX_RECURRING_TASK_SCANNER",
            Path(__file__).with_name("recurring-task-audit.py"),
        )
    ).expanduser()


def repository_scan_roots():
    configured = os.environ.get("CODEX_REPOSITORY_SCAN_ROOTS")
    if configured:
        return [Path(item).expanduser() for item in configured.split(os.pathsep) if item]
    return [program_root()]


def repository_closure_include_github():
    return os.environ.get("CODEX_REPOSITORY_CLOSURE_INCLUDE_GITHUB", "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def repository_closure_report_path(kind="json"):
    return repository_closure_root() / f"latest.{kind}"


def state_path():
    return ledger_root() / "state.json"


def pending_artifacts_path():
    return ledger_root() / "pending-artifacts.json"


def pending_artifacts_markdown_path():
    return ledger_root() / "pending-artifacts.md"


def digest_root():
    return Path(os.environ.get("CODEX_TASK_DIGEST_DIR", ledger_root() / "digests")).expanduser()


def digest_dir(kind):
    return digest_root() / kind


def daily_digest_archive_path(day=None):
    day = day or dt.date.today()
    return digest_dir("daily") / f"{day.isoformat()}.md"


def weekly_digest_archive_path(start, end):
    return digest_dir("weekly") / f"{start.isoformat()}_to_{end.isoformat()}.md"


def monthly_digest_archive_path(year_month):
    return digest_dir("monthly") / f"{year_month}.md"


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state():
    path = state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    root = ledger_root()
    root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="state.", suffix=".json", dir=str(root))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(state_path())
    finally:
        if temp_path.exists():
            temp_path.unlink()


def stable_artifact_key(path):
    return hashlib.sha1(redact(str(path)).encode("utf-8")).hexdigest()[:16]


def load_pending_artifacts():
    path = pending_artifacts_path()
    if not path.exists():
        return {"version": 1, "next_sequence": 1, "artifacts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "next_sequence": 1, "artifacts": {}}
    if not isinstance(data.get("artifacts"), dict):
        data["artifacts"] = {}
    if not isinstance(data.get("next_sequence"), int) or data["next_sequence"] < 1:
        data["next_sequence"] = 1
    data["version"] = 1
    return data


def save_pending_artifacts(data):
    root = ledger_root()
    root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="pending-artifacts.", suffix=".json", dir=str(root))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(pending_artifacts_path())
    finally:
        if temp_path.exists():
            temp_path.unlink()


def daily_summary_already_shown(source):
    state = load_state()
    if state.get("last_daily_summary_date") != local_today():
        return False
    normalized_source = source.lower()
    if normalized_source in {"dailydigest", "daily_digest"}:
        return state.get("last_daily_summary_source") in {"dailydigest", "daily_digest"}
    return True


def mark_daily_summary(source):
    state = load_state()
    state["last_daily_summary_date"] = local_today()
    state["last_daily_summary_source"] = source
    save_state(state)


def response(message, suppress_output=False, **extra):
    payload = {
        "continue": True,
        "suppressOutput": suppress_output,
        "systemMessage": redact(message),
    }
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def text_from_record(record):
    payload = record.get("payload", {})
    if payload.get("type") == "user_message":
        return [payload.get("message", "")]
    if payload.get("type") != "message":
        return []
    chunks = []
    for item in payload.get("content", []):
        if isinstance(item, dict) and item.get("type") == "output_text":
            chunks.append(item.get("text", ""))
    return chunks


def load_transcript(path):
    transcript_path = Path(path).expanduser()
    if not transcript_path.exists():
        return []
    records = []
    with transcript_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[-120:]


def extract_tasks(transcript_path):
    tasks = []
    seen = set()
    for record in load_transcript(transcript_path):
        for text in text_from_record(record):
            for line in str(text).splitlines():
                for pattern, status in MARKERS:
                    match = pattern.match(line)
                    if not match:
                        continue
                    title = redact(match.group(1)).strip()
                    if not title:
                        continue
                    key = (status, title)
                    if key in seen:
                        continue
                    seen.add(key)
                    tasks.append({"title": title[:160], "status": status})
    return tasks


def ledger_command(args):
    result = subprocess.run(
        [sys.executable, str(LEDGER), *args],
        text=True,
        capture_output=True,
        env=os.environ.copy(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if result.stdout.strip():
        return json.loads(result.stdout)
    return {}


def add_extracted_tasks(tasks, hook_input):
    added = []
    cwd = hook_input.get("cwd", "")
    project_name = Path(cwd).name if cwd else ""
    existing = {
        (task.get("status"), task.get("title"))
        for task in ledger_command(["list", "--status", ACTIVE_STATUS, "--format", "json"]).get("tasks", [])
    }
    for task in tasks:
        key = (task["status"], task["title"])
        if key in existing:
            continue
        result = ledger_command(
            [
                "add",
                "--title",
                task["title"],
                "--status",
                task["status"],
                "--next-action",
                task["title"],
                "--project-path",
                cwd,
                "--project-name",
                project_name,
                "--session-id",
                hook_input.get("session_id", ""),
                "--transcript-path",
                hook_input.get("transcript_path", ""),
                "--format",
                "json",
            ]
        )
        added.append(result["task"])
        existing.add(key)
    return added


def active_tasks(limit=8):
    result = ledger_command(["list", "--status", ACTIVE_STATUS, "--format", "json"])
    return result.get("tasks", [])[:limit]


def active_follow_ups(limit=20):
    result = ledger_command(
        ["list-follow-ups", "--status", "watching,ready,needs_attention", "--format", "json"]
    )
    return result.get("follow_ups", [])[:limit]


def parse_operation_time(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def automation_config(automation_id):
    if not automation_id or not re.fullmatch(r"[A-Za-z0-9._-]+", str(automation_id)):
        return None
    path = automations_root() / str(automation_id) / "automation.toml"
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(config, dict) or config.get("id") != automation_id:
        return None
    return config


def enrich_follow_ups(follow_ups, recurring_report):
    recurring_by_id = {
        item.get("id"): item
        for item in recurring_report.get("tasks", [])
        if isinstance(item, dict) and item.get("id")
    }
    now = dt.datetime.now(local_timezone())
    enriched = []
    for source in follow_ups:
        item = dict(source)
        monitor = dict(item.get("monitor") or {})
        item["monitor"] = monitor
        reasons = []
        automation_id = monitor.get("automation_id") or ""
        config = automation_config(automation_id) if automation_id else None
        automation_status = config.get("status") if config else ""
        item["automation_status"] = automation_status

        resume_mode = item.get("resume_mode") or "auto"
        if resume_mode in {"auto", "notify"}:
            if not item.get("next_check_at"):
                reasons.append("未登记下次检查时间")
            if not automation_id:
                reasons.append("未登记监控 Automation")
            elif config is None:
                reasons.append("监控 Automation 不存在")
            else:
                if automation_status != "ACTIVE":
                    reasons.append("监控 Automation 未处于 ACTIVE")
                target_thread_id = config.get("target_thread_id") or ""
                expected_thread_id = monitor.get("target_thread_id") or item.get("thread_id") or ""
                if expected_thread_id and target_thread_id != expected_thread_id:
                    reasons.append("监控 Automation 投递线程不匹配")

        next_check = parse_operation_time(item.get("next_check_at"))
        last_checked = parse_operation_time(item.get("last_checked_at"))
        if next_check is not None and next_check.astimezone(local_timezone()) < now:
            if last_checked is None or last_checked < next_check:
                reasons.append("下次检查已逾期且未回写")

        recurring_task_id = item.get("recurring_task_id") or ""
        recurring = recurring_by_id.get(recurring_task_id)
        if recurring:
            item["recurring_task"] = recurring
            if recurring.get("status") in {"failed", "overdue"}:
                reasons.append(f"关联周期任务状态为 {recurring.get('status')}")
        elif recurring_task_id:
            reasons.append("关联周期任务未找到")

        if item.get("status") == "needs_attention":
            reasons.append("续作记录已标记需要处理")

        item["monitor_reasons"] = list(dict.fromkeys(reasons))
        if reasons:
            item["monitor_state"] = "attention"
            item["monitor_label"] = "需要处理"
            item["user_action"] = "需要处理监控：" + "；".join(item["monitor_reasons"])
        elif item.get("status") == "ready":
            item["monitor_state"] = "ready"
            item["monitor_label"] = "条件已满足，待续作"
            item["user_action"] = "无需；自动续作会在绑定任务中继续，或由日报提示人工恢复。"
        elif resume_mode == "auto":
            item["monitor_state"] = "watching"
            item["monitor_label"] = "自动监控中"
            item["user_action"] = "无需；监控 Automation 会在条件检查后恢复原任务。"
        elif resume_mode == "notify":
            item["monitor_state"] = "watching"
            item["monitor_label"] = "监控后通知"
            item["user_action"] = "条件变化后查看通知并决定是否恢复。"
        else:
            item["monitor_state"] = "manual"
            item["monitor_label"] = "等待人工恢复"
            item["user_action"] = "条件满足后需要手动恢复原任务。"
        enriched.append(item)
    return enriched


def operation_event_score(event):
    return (
        len(event.get("changes") or []) * 100
        + len(event.get("related_threads") or []) * 20
        + (10 if event.get("project") else 0)
        + len(str(event.get("summary") or ""))
    )


def previous_day_operation_events(limit=5000):
    path = operation_ledger_path()
    if not path.exists():
        return []
    target_day = dt.date.fromisoformat(local_yesterday())
    events = []
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return []
    with handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("status") not in {None, "success"}:
                continue
            occurred_at = parse_operation_time(event.get("occurred_at"))
            if occurred_at is None or occurred_at.astimezone(local_timezone()).date() != target_day:
                continue
            events.append(event)
            if len(events) >= limit:
                break

    deduplicated = {}
    for event in events:
        actor = event.get("actor") or {}
        thread = event.get("thread") or {}
        key = (
            event.get("action") or "",
            actor.get("label") or actor.get("id") or "",
            thread.get("id") or "",
            event.get("occurred_at") or "",
        )
        existing = deduplicated.get(key)
        if existing is None or operation_event_score(event) > operation_event_score(existing):
            deduplicated[key] = event
    return sorted(deduplicated.values(), key=lambda item: item.get("occurred_at") or "")


def operation_evidence_label(event):
    for evidence in event.get("evidence") or []:
        if isinstance(evidence, dict) and evidence.get("path"):
            return evidence["path"]
    return event.get("occurred_at") or "操作日志"


def context_card_recent_progress(event, limit=2, max_chars=420):
    path = None
    for evidence in event.get("evidence") or []:
        if not isinstance(evidence, dict) or not evidence.get("path"):
            continue
        candidate = Path(evidence["path"]).expanduser()
        if evidence.get("kind") == "context_card" or "context-card" in candidate.name:
            path = candidate
            break
    if path is None or not path.is_file():
        return ""
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    progress = []
    in_progress_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## 最近助手进展":
            in_progress_section = True
            continue
        if in_progress_section and stripped.startswith("## "):
            break
        if not in_progress_section or not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        item = re.sub(r"^`[^`]+`\s+\*\*助手\*\*:\s*", "", item)
        item = re.sub(r"\s+", " ", redact(item)).strip()
        if item:
            progress.append(item)

    selected = "；".join(progress[-limit:])
    if len(selected) > max_chars:
        selected = selected[: max_chars - 1].rstrip() + "…"
    return selected


def previous_day_operation_changes(events=None, limit=12):
    events = events if events is not None else previous_day_operation_events()
    grouped = {}
    for event in events:
        action = event.get("action") or ""
        if action not in WORKFLOW_CHANGE_LABELS:
            continue
        actor = event.get("actor") or {}
        component = actor.get("label") or actor.get("id") or event.get("title") or "未知组件"
        grouped.setdefault((action, component), []).append(event)

    changes = []
    for (action, component), items in grouped.items():
        items = sorted(items, key=lambda item: item.get("occurred_at") or "")
        best = max(items, key=operation_event_score)
        summaries = []
        for item in items:
            summary = str(item.get("summary") or "").strip()
            if summary and summary not in summaries:
                summaries.append(summary)
        changes.append(
            {
                "action": action,
                "label": WORKFLOW_CHANGE_LABELS[action],
                "component": component,
                "summary": "；".join(summaries[-3:]) or f"{component} 已发生可核实变更。",
                "occurred_at": best.get("occurred_at") or "",
                "evidence": operation_evidence_label(best),
            }
        )
    return sorted(changes, key=lambda item: item.get("occurred_at") or "", reverse=True)[:limit]


def operation_fallback_activities(events=None, limit=12):
    events = events if events is not None else previous_day_operation_events()
    grouped = {}
    for event in events:
        if event.get("action") != "context_compacted":
            continue
        thread = event.get("thread") or {}
        project = event.get("project") or {}
        thread_id = thread.get("id") or ""
        title = thread.get("title") or ""
        project_name = project.get("name") or ""
        if not thread_id or not title:
            continue
        if project_name == "codex-digest-archive" or "摘要归档" in title:
            continue
        current = grouped.get(thread_id)
        if current is None or (event.get("occurred_at") or "") > (current.get("occurred_at") or ""):
            grouped[thread_id] = event

    activities = []
    for thread_id, event in grouped.items():
        thread = event.get("thread") or {}
        project = event.get("project") or {}
        progress = context_card_recent_progress(event)
        if progress:
            summary = f"上下文卡片记录的最近进展：{progress}（仅作为昨日进展证据，不据此推断任务完成。）"
        else:
            summary = "操作日志确认该任务昨日活跃并生成了上下文压缩卡片；线程接口采集失败，未据此推断完成状态。"
        activities.append(
            {
                "thread_id": thread_id,
                "title": thread.get("title") or "未命名任务",
                "status": "in_progress",
                "summary": summary,
                "next_action": "读取对应任务或项目证据，补齐实际结果与后续。",
                "project_name": project.get("name") or "",
                "project_path": project.get("path") or "",
                "evidence": operation_evidence_label(event),
                "source": "operation_ledger_fallback",
                "occurred_at": event.get("occurred_at") or "",
            }
        )
    return sorted(activities, key=lambda item: item.get("occurred_at") or "", reverse=True)[:limit]


def activity_ledger_activities():
    path = ledger_root() / "activity" / f"{local_yesterday()}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    activities = data.get("activities", {})
    if isinstance(activities, dict):
        activities = list(activities.values())
    if not isinstance(activities, list):
        return []
    return sorted(
        [item for item in activities if isinstance(item, dict)],
        key=lambda item: (item.get("status") or "", item.get("title") or "", item.get("thread_id") or ""),
    )


def previous_day_activity_bundle(operation_events=None):
    activities = activity_ledger_activities()
    if activities:
        return activities, "activity_ledger"
    fallback = operation_fallback_activities(operation_events)
    if fallback:
        return fallback, "operation_ledger_fallback"
    return [], "missing"


def previous_day_activities():
    return previous_day_activity_bundle()[0]


def recent_completed_work(limit=5):
    index = work_ledger_root() / "index.json"
    if not index.exists():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    works = [
        work
        for work in data.get("works", {}).values()
        if work.get("status") in {"completed", "partial", "shipped"}
    ]
    return sorted(works, key=lambda item: (item.get("updated_at") or "", item.get("title") or ""), reverse=True)[:limit]


def empty_repository_closure_report(warning=None):
    warnings = [warning] if warning else []
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "generated_on": local_today(),
        "repository_count": 0,
        "finding_count": 0,
        "counts": {
            "in_progress": 0,
            "awaiting_integration": 0,
            "pr_pending": 0,
            "legacy": 0,
            "merged_cleanup": 0,
        },
        "findings": [],
        "warnings": warnings,
    }


def empty_recurring_task_report(warning=None):
    return {
        "schema_version": 1,
        "task_count": 0,
        "counts": {"success": 0, "overdue": 0, "failed": 0, "unknown": 0},
        "tasks": [],
        "warnings": [warning] if warning else [],
    }


def run_recurring_task_audit():
    command = [
        sys.executable,
        str(recurring_task_scanner()),
        "--root",
        str(program_root()),
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return empty_recurring_task_report(f"周期任务扫描未完成：{exc}")
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
        return empty_recurring_task_report(f"周期任务扫描未完成：{detail}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return empty_recurring_task_report(f"周期任务扫描结果无法解析：{exc}")
    return report if isinstance(report, dict) else empty_recurring_task_report("周期任务扫描结果格式无效")


def load_repository_closure_report():
    path = repository_closure_report_path()
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) else None


def run_repository_closure_audit():
    command = [
        sys.executable,
        str(repository_closure_scanner()),
        "--format",
        "json",
        "--output-dir",
        str(repository_closure_root()),
    ]
    for root in repository_scan_roots():
        command.extend(["--root", str(root)])
    if repository_closure_include_github():
        command.append("--include-github")
    if os.environ.get("CODEX_REPOSITORY_CLOSURE_REFRESH_REMOTES", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        command.append("--refresh-remotes")
    try:
        timeout = max(10, int(os.environ.get("CODEX_REPOSITORY_CLOSURE_TIMEOUT_SECONDS", "180")))
    except ValueError:
        timeout = 180
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return empty_repository_closure_report(f"仓库收尾扫描未完成：{exc}")
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"退出码 {result.returncode}"
        return empty_repository_closure_report(f"仓库收尾扫描未完成：{detail}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return empty_repository_closure_report(f"仓库收尾扫描结果无法解析：{exc}")
    return report if isinstance(report, dict) else empty_repository_closure_report("仓库收尾扫描结果格式无效")


def repository_closure_report(source):
    cached = load_repository_closure_report()
    if source.lower() in {"sessionstart", "session_start"} and cached:
        if cached.get("generated_on") == local_today():
            return cached
    return run_repository_closure_audit()


def task_summary(tasks):
    if not tasks:
        return "任务连续性：当前没有记录到未完成任务。"
    lines = ["任务连续性：当前未完成任务摘要："]
    for task in tasks:
        title = task.get("title", "")
        status = task.get("status", "")
        next_action = task.get("next_action") or "未记录下一步"
        lines.append(f"- [{status}] {title}：{next_action}")
    return "\n".join(lines)


def safe_json_load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def path_entry(kind, path, source):
    return {
        "kind": kind,
        "path": redact(str(path)),
        "title": redact(Path(path).name or str(path)),
        "source": source,
    }


def cleanup_daily_digest_files(retention_days=7):
    daily_dir = ledger_root() / "daily"
    if not daily_dir.exists():
        return 0
    cutoff = dt.date.today() - dt.timedelta(days=retention_days)
    deleted = 0
    for item in daily_dir.glob("*.md"):
        try:
            item_date = dt.date.fromisoformat(item.stem)
        except ValueError:
            continue
        if item_date >= cutoff:
            continue
        try:
            item.unlink()
            deleted += 1
        except OSError:
            continue
    return deleted


def markdown_label(text):
    return redact(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def markdown_target(path):
    target = redact(str(path))
    if re.search(r"[\s)<>]", target):
        return f"<{target.replace('>', '%3E')}>"
    return target


def path_link(path, title=""):
    label = markdown_label(title or Path(path).name or str(path))
    return f"[{label}]({markdown_target(path)})"


def project_label(task):
    project = task.get("project", {})
    name = project.get("name") or project.get("path") or "无项目"
    path = project.get("path") or ""
    if path:
        return path_link(path, name)
    return markdown_label(name)


def is_broad_manifest_path(path):
    item = Path(path).expanduser()
    known_containers = {
        Path("~/.codex").expanduser(),
        Path(tempfile.gettempdir()),
        Path("/tmp"),
        Path("/private/tmp"),
        program_root(),
        program_root() / "tools",
        program_root() / "documents",
        program_root() / "env",
        program_root() / "AI",
        program_root() / "_inbox" / "needs-review",
        program_root() / "_archive" / "trash-candidates",
        program_root() / "skills",
        program_root() / "documents" / "obsidian_vault" / "03_Resources",
    }
    try:
        resolved = item.resolve()
    except OSError:
        resolved = item
    for container in known_containers:
        try:
            if resolved == container.expanduser().resolve():
                return True
        except OSError:
            if resolved == container.expanduser():
                return True
    return False


def is_relative_to_path(item, parent):
    try:
        item.resolve().relative_to(parent.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def codex_home():
    return Path("~/.codex").expanduser()


def obsidian_vault_root():
    return program_root() / "documents" / "obsidian_vault"


def git_root_for_path(path):
    item = Path(path).expanduser()
    search_dir = item if item.is_dir() else item.parent
    if not search_dir.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(search_dir), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).expanduser()


def git_relative_path(item, root):
    try:
        relative = item.expanduser().resolve().relative_to(root.expanduser().resolve())
    except (OSError, ValueError):
        return item.name
    value = relative.as_posix()
    return value or "."


def is_git_tracked_file(path):
    item = Path(path).expanduser()
    if not item.is_file():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(item.parent), "ls-files", "--error-unmatch", "--", item.name],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def is_git_managed_subtree(path):
    item = Path(path).expanduser()
    if not item.is_dir():
        return False
    root = git_root_for_path(item)
    if root is None:
        return False
    try:
        if item.resolve() == root.resolve():
            return False
    except OSError:
        return False
    relative = git_relative_path(item, root)
    try:
        current = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", relative],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
        if current.returncode == 0 and current.stdout.strip():
            return True
        historical = subprocess.run(
            ["git", "-C", str(root), "log", "--all", "--format=%H", "-n", "1", "--", relative],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return historical.returncode == 0 and bool(historical.stdout.strip())


def is_managed_artifact_path(path):
    item = Path(path).expanduser()
    managed_roots = [
        codex_home(),
        program_root() / "codex-workflow-skills",
        program_root() / "skills",
        obsidian_vault_root(),
    ]
    if any(is_relative_to_path(item, root) for root in managed_roots):
        return True
    return (
        is_git_tracked_file(item)
        or is_git_managed_subtree(item)
        or is_established_project_root(item)
        or project_member_root(item) is not None
    )


def is_established_project_root(path):
    item = Path(path).expanduser()
    if not item.is_dir():
        return False
    try:
        relative_parts = item.resolve().relative_to(program_root().resolve()).parts
    except (OSError, ValueError):
        return False
    if any(part in {"_external", "_inbox", "_archive", "needs-review", "trash-candidates"} for part in relative_parts):
        return False
    if not ((item / "README.md").exists() or (item / "readme.md").exists()):
        return False
    component_dirs = sum((item / name).is_dir() for name in ("backend", "frontend", "src", "docs", "tests"))
    return len(project_markers(item)) >= 2 or component_dirs >= 2


def project_member_root(path):
    item = Path(path).expanduser()
    try:
        root = program_root().resolve()
        current = item.resolve().parent
    except OSError:
        return None
    while current != root and is_relative_to_path(current, root):
        if is_project_like_directory(current) or is_established_project_root(current):
            return current
        current = current.parent
    return None


def is_project_like_directory(path):
    item = Path(path).expanduser()
    if not item.is_dir():
        return False
    return bool(project_markers(item))


def project_markers(path):
    item = Path(path).expanduser()
    if not item.is_dir():
        return []
    markers = {
        ".git",
        "README.md",
        "readme.md",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "requirements.txt",
        "Cargo.toml",
        "go.mod",
        "Gemfile",
    }
    return sorted(marker for marker in markers if (item / marker).exists())


def manifest_age_days(manifest_day):
    try:
        day = dt.date.fromisoformat(str(manifest_day))
    except ValueError:
        return pending_project_aging_days()
    today = dt.date.today()
    if day >= today:
        return 0
    return sum(
        1
        for offset in range(1, (today - day).days + 1)
        if (day + dt.timedelta(days=offset)).weekday() < 5
    )


def should_delay_project_candidate(path, manifest_day):
    if not is_project_like_directory(path):
        return False
    return manifest_age_days(manifest_day) < pending_project_aging_days()


def is_attachment_referenced(path):
    item = Path(path).expanduser()
    vault = obsidian_vault_root()
    if not is_relative_to_path(item, vault):
        return False
    try:
        relative = item.resolve().relative_to(vault.resolve()).as_posix()
    except (OSError, ValueError):
        relative = item.name
    needles = {item.name, relative}
    for markdown in vault.rglob("*.md"):
        try:
            text = markdown.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(needle in text for needle in needles):
            return True
    return False


def is_generated_preview_attachment(path):
    item = Path(path).expanduser()
    attachments = obsidian_vault_root() / "07_Attachments"
    name = item.name.lower()
    if not is_relative_to_path(item, attachments):
        return False
    if item.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return False
    if not re.search(r"(codex|clipboard|screenshot|preview|temp|tmp)", name):
        return False
    return not is_attachment_referenced(item)


def is_auto_deletable_transient_path(path):
    item = Path(path).expanduser()
    if not item.exists() or not item.is_file():
        return False
    if item.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return False
    name = item.name.lower()
    if name.startswith("codex-clipboard-"):
        return True
    normalized = item.as_posix().lower()
    if "com.tencent.xinwechat" in normalized and "/temp/rwtemp/" in normalized:
        return True
    temp_roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
    }
    try:
        if any(item.resolve().is_relative_to(root) for root in temp_roots):
            return True
    except OSError:
        pass
    return is_generated_preview_attachment(item)


def auto_delete_transient_path(path):
    item = Path(path).expanduser()
    if not is_auto_deletable_transient_path(item):
        return False
    try:
        item.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def is_daily_digest_path(path):
    item = Path(path).expanduser()
    daily_dirs = [
        ledger_root() / "daily",
        Path("~/.codex/task-ledger/daily").expanduser(),
    ]
    try:
        parent = item.resolve().parent
    except OSError:
        parent = item.parent
    for daily_dir in daily_dirs:
        try:
            if parent == daily_dir.resolve():
                return True
        except OSError:
            if parent == daily_dir:
                return True
    return False


def should_skip_manifest_path(path, manifest_day=""):
    item = Path(path).expanduser()
    if not item.exists():
        return True
    if auto_delete_transient_path(item):
        return True
    if is_daily_digest_path(item):
        return True
    if is_broad_manifest_path(item):
        return True
    if should_delay_project_candidate(item, manifest_day):
        return True
    return is_managed_artifact_path(item)


def previous_manifest_entries(limit=200):
    entries = []
    artifact_root = governance_root() / "artifacts"
    if not artifact_root.exists():
        return entries
    for artifact_dir in sorted((item for item in artifact_root.iterdir() if item.is_dir()), reverse=True):
        for manifest_path in sorted(artifact_dir.glob("*.json")):
            manifest = safe_json_load(manifest_path)
            for item in manifest.get("candidates", []):
                if not isinstance(item, dict) or not item.get("path"):
                    continue
                if should_skip_manifest_path(item["path"], artifact_dir.name):
                    continue
                entries.append(path_entry("manifest_candidate", item["path"], manifest_path.name))
                if len(entries) >= limit:
                    return entries
    return entries


def direct_children(path):
    if not path.exists():
        return []
    try:
        return [item for item in sorted(path.iterdir()) if not item.name.startswith(".")]
    except OSError:
        return []


def needs_review_entries(limit=12):
    root = program_root() / "_inbox" / "needs-review"
    return [path_entry("needs_review", item, "needs-review") for item in direct_children(root)[:limit]]


def trash_candidate_entries(limit=12):
    root = program_root() / "_archive" / "trash-candidates"
    entries = []
    for item in direct_children(root):
        if item.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.name):
            for child in direct_children(item):
                entries.append(path_entry("cleanup_candidate", child, f"trash-candidates/{item.name}"))
                if len(entries) >= limit:
                    return entries
        else:
            entries.append(path_entry("cleanup_candidate", item, "trash-candidates"))
            if len(entries) >= limit:
                return entries
    return entries


def artifact_summary_entries(limit=200):
    entries = []
    seen_paths = set()
    for entry in previous_manifest_entries() + needs_review_entries() + trash_candidate_entries():
        path = entry["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def artifact_summary_lines(entries):
    if not entries:
        return []
    kind_label = {
        "manifest_candidate": "前日候选",
        "needs_review": "待确认",
        "cleanup_candidate": "隔离候选",
    }
    lines = ["前日产物和待确认内容："]
    for entry in entries:
        label = kind_label.get(entry["kind"], entry["kind"])
        lines.append(f"- [{label}] {path_link(entry['path'], entry['title'])}")
    return lines


def kind_label(kind):
    labels = {
        "manifest_candidate": "前日候选",
        "needs_review": "待确认",
        "cleanup_candidate": "隔离候选",
    }
    return labels.get(kind, kind)


def artifact_action_id(index):
    return f"A{index:02d}"


def readable_size(path):
    try:
        size = Path(path).stat().st_size
    except OSError:
        return "大小未知"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def first_markdown_signal(path):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    for line in lines[:80]:
        text = redact(line).strip()
        if not text:
            continue
        if text.startswith("---"):
            continue
        if len(text) > 120:
            text = text[:117] + "..."
        return text.lstrip("#").strip() or text
    return ""


def summarize_directory(path):
    item = Path(path)
    children = direct_children(item)
    names = ", ".join(child.name for child in children[:3])
    suffix = f"；示例：{names}" if names else ""
    markers = project_markers(item)
    marker_detail = f"，项目标记：{', '.join(markers[:4])}" if markers else ""
    return f"目录，当前可见 {len(children)} 项{marker_detail}{suffix}"


def summarize_file(path):
    item = Path(path)
    suffix = item.suffix.lower()
    size = readable_size(item)
    if suffix in {".md", ".markdown"}:
        signal = first_markdown_signal(item)
        detail = f"，开头：{signal}" if signal else ""
        return f"Markdown 文档，{size}{detail}"
    if suffix in {".txt", ".log", ".csv"}:
        signal = first_markdown_signal(item)
        detail = f"，开头：{signal}" if signal else ""
        return f"文本文件，{size}{detail}"
    if suffix in {".json", ".jsonl"}:
        return f"JSON 数据文件，{size}"
    if suffix in {".py", ".js", ".ts", ".tsx", ".sh"}:
        signal = first_markdown_signal(item)
        detail = f"，开头：{signal}" if signal else ""
        return f"代码文件，{size}{detail}"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return f"图片文件，{size}"
    return f"文件，{size}"


def artifact_content_summary(path):
    item = Path(path).expanduser()
    if not item.exists():
        return "路径当前不存在，可能已移动或被清理"
    if item.is_dir():
        return summarize_directory(item)
    if item.is_file():
        return summarize_file(item)
    return "特殊文件，建议人工确认"


def suggested_action(entry):
    if entry["kind"] == "cleanup_candidate":
        return "确认是否永久删除；不确定就暂放。"
    if entry["kind"] == "needs_review":
        return "判断保留、归档、转项目或丢弃。"
    return "判断是否需要纳入待确认；如果只是容器目录或已处理文件，可忽略。"


def selection_reason(entry):
    kind = entry["kind"]
    path = entry["path"]
    if kind == "cleanup_candidate":
        return "它已经位于 trash-candidates 隔离区，通常表示之前被识别为缓存、构建产物或临时垃圾，需要确认是否永久删除。"
    if kind == "needs_review":
        return "它已经位于 needs-review 待确认区，表示整理流程无法自动判断归属，需要你决定保留、归档、转项目或丢弃。"
    if is_project_like_directory(path):
        return f"它来自会话产物记录，像一个独立项目或 demo，且已超过 {pending_project_aging_days()} 天 aging 期仍未归属到正式项目或工作流。"
    return "它来自会话产物记录，当前不属于已管理源码、Codex 配置、Obsidian 正式内容或顶级容器目录，因此需要确认是否保留、归档、转项目或丢弃。"


def artifact_actions(entries):
    actions = []
    for index, entry in enumerate(entries, start=1):
        actions.append(
            {
                "id": entry.get("action_id") or artifact_action_id(index),
                "kind": entry["kind"],
                "label": kind_label(entry["kind"]),
                "title": entry["title"],
                "path": entry["path"],
                "summary": artifact_content_summary(entry["path"]),
                "selection_reason": selection_reason(entry),
                "suggested_action": suggested_action(entry),
            }
        )
    return actions


def next_artifact_action_id(data):
    sequence = data.get("next_sequence", 1)
    data["next_sequence"] = sequence + 1
    return artifact_action_id(sequence)


def pending_record_from_entry(data, entry):
    now = now_iso()
    return {
        "action_id": next_artifact_action_id(data),
        "created_at": now,
        "updated_at": now,
        "status": "pending",
        "kind": entry["kind"],
        "path": entry["path"],
        "title": entry["title"],
        "source": entry.get("source", ""),
    }


def resolve_pending_record(record, status, reason):
    record["status"] = status
    record["resolved_at"] = now_iso()
    record["resolution_reason"] = reason


def reconcile_pending_artifacts(data):
    for record in data.get("artifacts", {}).values():
        if record.get("status", "pending") != "pending":
            continue
        item = Path(record.get("path", "")).expanduser()
        if not item.exists():
            resolve_pending_record(record, "resolved_missing", "路径已不存在，不再提醒。")
            continue
        if auto_delete_transient_path(item):
            resolve_pending_record(record, "deleted_transient", "临时过程截图已自动删除。")
            continue
        if is_daily_digest_path(item) or is_broad_manifest_path(item) or is_managed_artifact_path(item):
            resolve_pending_record(record, "resolved_managed", "已归属到源码、配置、项目、Obsidian 或顶级容器目录，不再作为待确认产物提醒。")


def pending_entry_from_record(record):
    return {
        "action_id": record.get("action_id", ""),
        "kind": record.get("kind", "manifest_candidate"),
        "path": record.get("path", ""),
        "title": record.get("title") or Path(record.get("path", "")).name,
        "source": record.get("source", ""),
    }


def active_pending_records(data):
    records = [
        record
        for record in data.get("artifacts", {}).values()
        if record.get("status", "pending") == "pending" and record.get("path")
    ]
    return sorted(records, key=lambda item: item.get("action_id", ""))


def active_pending_artifact_entries(limit=18):
    data = load_pending_artifacts()
    return [pending_entry_from_record(record) for record in active_pending_records(data)[:limit]]


def write_pending_artifacts_markdown(data):
    lines = [
        "# Codex 待确认产物池",
        "",
        "这里记录尚未确认去留的产物候选。只有确认删除、暂放、归档或转待办后，候选才应从 pending 状态退出。",
        "",
    ]
    records = active_pending_records(data)
    if not records:
        lines.append("- 当前没有待确认产物。")
    for record in records:
        entry = pending_entry_from_record(record)
        action = artifact_actions([entry])[0]
        lines.extend(
            [
                f"## {action['id']} · {action['label']} · {markdown_label(action['title'])}",
                "",
                f"- 状态：`pending`",
                f"- 内容：{markdown_label(action['summary'])}",
                f"- 位置：`{markdown_label(action['path'])}`",
                f"- 选择原因：{markdown_label(action['selection_reason'])}",
                f"- 建议：{markdown_label(action['suggested_action'])}",
                f"- 首次记录：{markdown_label(record.get('created_at', ''))}",
                f"- 最近更新：{markdown_label(record.get('updated_at', ''))}",
                "",
            ]
        )
    pending_artifacts_markdown_path().write_text(redact("\n".join(lines).rstrip() + "\n"), encoding="utf-8")


def upsert_pending_artifacts(entries):
    data = load_pending_artifacts()
    artifacts = data.setdefault("artifacts", {})
    reconcile_pending_artifacts(data)
    now = now_iso()
    for entry in entries:
        key = stable_artifact_key(entry["path"])
        existing = artifacts.get(key)
        if existing:
            if existing.get("status", "pending") == "pending":
                existing.update(
                    {
                        "updated_at": now,
                        "kind": entry["kind"],
                        "path": entry["path"],
                        "title": entry["title"],
                        "source": entry.get("source", ""),
                    }
                )
            continue
        artifacts[key] = pending_record_from_entry(data, entry)
    reconcile_pending_artifacts(data)
    save_pending_artifacts(data)
    write_pending_artifacts_markdown(data)
    return [pending_entry_from_record(record) for record in active_pending_records(data)]


def daily_card_markdown(
    tasks,
    artifacts,
    recent_work=None,
    repository_closure=None,
    previous_activity=None,
    recurring_tasks=None,
    daily_changes=None,
    activity_source="activity_ledger",
    follow_ups=None,
):
    recent_work = recent_work or []
    repository_closure = repository_closure or empty_repository_closure_report()
    previous_activity = previous_activity or []
    recurring_tasks = recurring_tasks or empty_recurring_task_report()
    daily_changes = daily_changes or []
    follow_ups = follow_ups or []
    actions = artifact_actions(artifacts)
    lines = [
        "## Codex 每日任务摘要",
        "",
        f"**日期**：{local_today()}  ",
        f"**账本已记录未完成**：{len(tasks)}  ",
        f"**昨日实际任务**：{len(previous_activity)}  ",
        f"**昨日已核实系统变更**：{len(daily_changes)}  ",
        f"**周期任务**：{recurring_tasks.get('task_count', len(recurring_tasks.get('tasks', [])))}  ",
        f"**续作监控**：{len(follow_ups)}  ",
        f"**Git / PR 待收尾**：{repository_closure.get('finding_count', 0)}  ",
        f"**产物待确认**：{len(actions)}",
        "",
        "## 昨日实际工作与后续",
        "",
    ]
    if not previous_activity:
        lines.append("- 尚未记录前一自然日的 Codex 任务活动；这表示活动采集缺失，不表示昨天没有工作。")
    else:
        if activity_source == "operation_ledger_fallback":
            lines.append("- 线程索引采集失败；以下使用操作日志降级证据，只确认任务昨日活跃，不把上下文压缩推断为任务完成。")
        activity_labels = {
            "completed": "已完成",
            "delivered_pending_trial": "已交付待试用",
            "research_pending_implementation": "调研完成待实施",
            "in_progress": "进行中",
            "waiting_user": "等待用户",
            "blocked": "阻塞",
        }
        for activity in previous_activity:
            status = activity_labels.get(activity.get("status"), activity.get("status") or "未知")
            title = markdown_label(activity.get("title") or "未命名任务")
            summary = markdown_label(activity.get("summary") or "未记录工作结果")
            next_action = markdown_label(activity.get("next_action") or "无后续动作")
            evidence = markdown_label(activity.get("evidence") or "未记录证据")
            lines.append(f"- **{status}**：{title}")
            lines.append(f"  结果：{summary}")
            lines.append(f"  下一步：{next_action}")
            lines.append(f"  证据：{evidence}")

    lines.extend(["", "## 昨日成果与系统变更", ""])
    if not daily_changes:
        lines.append("- 操作日志未记录昨日 Skill、Hook、Automation 或 Plugin 的已核实变更。")
    else:
        for change in daily_changes:
            label = markdown_label(change.get("label") or "系统变更")
            component = markdown_label(change.get("component") or "未知组件")
            summary = markdown_label(change.get("summary") or "未记录变更概要")
            evidence = markdown_label(change.get("evidence") or "操作日志")
            lines.append(f"- **{label}**：{component}")
            lines.append(f"  结果：{summary}")
            lines.append(f"  证据：{evidence}")

    lines.extend(["", "## 周期任务运行状态", ""])
    recurring_items = recurring_tasks.get("tasks", [])
    if not recurring_items:
        lines.append("- 当前没有发现项目声明的周期任务。")
    else:
        recurring_labels = {"success": "正常", "overdue": "延迟", "failed": "失败", "unknown": "待确认"}
        for item in recurring_items:
            status = recurring_labels.get(item.get("status"), item.get("status") or "未知")
            project = markdown_label(item.get("project") or "未知项目")
            name = markdown_label(item.get("name") or "周期任务")
            reason = markdown_label(item.get("reason") or "未记录判断")
            next_expected = markdown_label(item.get("next_expected_at") or "未记录")
            lines.append(f"- **{status}**：{project} / {name}")
            lines.append(f"  判断：{reason}")
            if item.get("details"):
                details = "；".join(
                    f"{markdown_label(label)}：{markdown_label(value)}"
                    for label, value in item["details"].items()
                )
                lines.append(f"  运行信息：{details}")
            if item.get("scheduler_loaded") is not None:
                loaded = "已加载" if item.get("scheduler_loaded") else "未加载"
                runs = item.get("scheduler_runs")
                exit_code = item.get("last_exit_code")
                lines.append(
                    f"  调度器：{loaded}；计划触发次数：{runs if runs is not None else '未知'}；"
                    f"最后退出码：{exit_code if exit_code is not None else '未记录'}"
                )
            lines.append(f"  下次计划：{next_expected}")
    for warning in recurring_tasks.get("warnings", [])[:5]:
        lines.append(f"- 扫描警告：{markdown_label(warning)}")

    lines.extend(["", "## 等待条件与续作监控", ""])
    if not follow_ups:
        lines.append("- 当前没有登记等待外部条件的续作目标。")
    else:
        for item in follow_ups:
            label = markdown_label(item.get("monitor_label") or "续作监控")
            title = markdown_label(item.get("title") or "未命名目标")
            goal = markdown_label(item.get("goal") or "未记录目标")
            wait_condition = markdown_label(item.get("wait_condition") or "未记录等待条件")
            resume_action = markdown_label(item.get("resume_action") or "未记录恢复动作")
            parallel_action = markdown_label(item.get("parallel_action") or "暂无安全并行工作")
            monitor = item.get("monitor") or {}
            automation_id = markdown_label(monitor.get("automation_id") or "未登记")
            automation_status = markdown_label(item.get("automation_status") or "未知")
            monitor_schedule = markdown_label(monitor.get("schedule") or "未记录计划")
            next_check_at = markdown_label(item.get("next_check_at") or "未记录")
            lines.append(f"- **{label}**：{title}")
            lines.append(f"  当前目标：{goal}")
            lines.append(f"  等待条件：{wait_condition}")
            lines.append(
                f"  监控：{automation_id}（{automation_status}；{monitor_schedule}；下次检查 {next_check_at}）"
            )
            recurring = item.get("recurring_task")
            if recurring:
                recurring_name = markdown_label(recurring.get("name") or item.get("recurring_task_id"))
                recurring_status = markdown_label(recurring.get("status") or "unknown")
                recurring_reason = markdown_label(recurring.get("reason") or "未记录判断")
                lines.append(f"  关联周期任务：{recurring_name}：{recurring_status}（{recurring_reason}）")
            if item.get("monitor_reasons"):
                reasons = "；".join(markdown_label(reason) for reason in item["monitor_reasons"])
                lines.append(f"  监控异常：{reasons}")
            lines.append(f"  条件满足后：{resume_action}")
            lines.append(f"  并行工作：{parallel_action}")
            lines.append(f"  用户操作：{markdown_label(item.get('user_action') or '未记录')}")

    lines.extend([
        "",
        "## 任务账本中的未完成任务",
        "",
    ])
    if not tasks:
        lines.append("- 任务账本当前为 0；账本为 0 不代表所有 Codex 任务都已完成。仍需结合 Git / PR 收尾状态与相关任务上下文判断。")
    else:
        for task in tasks:
            status = task.get("status", "")
            title = markdown_label(task.get("title", "未命名任务"))
            next_action = markdown_label(task.get("next_action") or "未记录下一步")
            lines.append(f"- **{status}**：{title}（{project_label(task)}）")
            lines.append(f"  下一步：{next_action}")
    closure_counts = repository_closure.get("counts", {})
    lines.extend(
        [
            "",
            "## Git / PR 收尾状态",
            "",
            "- 进行中 / 证据不足：{in_progress}；待集成：{awaiting_integration}；PR 待处理：{pr_pending}；历史遗留：{legacy}；已合并待清理：{merged_cleanup}。".format(
                in_progress=closure_counts.get("in_progress", 0),
                awaiting_integration=closure_counts.get("awaiting_integration", 0),
                pr_pending=closure_counts.get("pr_pending", 0),
                legacy=closure_counts.get("legacy", 0),
                merged_cleanup=closure_counts.get("merged_cleanup", 0),
            ),
        ]
    )
    closure_findings = repository_closure.get("findings", [])
    if not closure_findings:
        lines.append("- 当前扫描范围内未发现待收尾 Git / PR 项；这仍不是对所有历史对话完成状态的证明。")
    else:
        blockers = [finding for finding in closure_findings if finding.get("category") == "in_progress"]
        automatic_candidates = [finding for finding in closure_findings if finding.get("category") != "in_progress"]
        lines.append(
            f"- 自动收尾候选：{len(automatic_candidates)} 项；将由本次自动化按动作预算处理，完整事实见仓库报告。"
        )
        if blockers:
            lines.append(f"- 当前真正阻塞候选：{len(blockers)} 项。")
        for finding in blockers[:5]:
            repository = markdown_label(finding.get("repository", "未知仓库"))
            branch = markdown_label(finding.get("branch") or "(detached)")
            finding_id = markdown_label(finding.get("id", ""))
            reason = markdown_label(finding.get("reason", "待确认"))
            lines.append(f"- **真正阻塞候选** `{finding_id}`：{repository} / `{branch}`")
            lines.append(f"  判断：{reason}")
        if len(blockers) > 5:
            lines.append(f"- 另有 {len(blockers) - 5} 个阻塞候选，详见仓库收尾报告。")
    for warning in repository_closure.get("warnings", [])[:5]:
        lines.append(f"- 扫描警告：{markdown_label(warning)}")

    lines.extend(["", "## 历史成果索引", ""])
    history_path = work_ledger_root() / "index.md"
    if recent_work:
        lines.append(
            f"- 历史成果账本已有记录；日报不再重复滚动展示旧条目。完整历史见 {path_link(history_path, 'Codex 工作成果账本')}。"
        )
    else:
        lines.append(f"- 历史成果账本尚无可用记录；索引位置：{path_link(history_path, 'Codex 工作成果账本')}。")
    lines.extend(["", "## 前日产物和待确认内容", ""])
    if not actions:
        lines.append("- 当前没有待确认产物。")
    else:
        lines.append("可直接回复编号处理，例如：`删除 A02`、`暂放 A02`、`移到待办 A02`。我会按编号处理；这张卡片本身不会自动删除文件。")
        lines.append("")
        for action in actions:
            lines.append(f"### {action['id']} · {action['label']} · {markdown_label(action['title'])}")
            lines.append(f"- 内容：{markdown_label(action['summary'])}")
            lines.append(f"- 位置：{path_link(action['path'], action['title'])}")
            lines.append(f"- 选择原因：{markdown_label(action['selection_reason'])}")
            lines.append(f"- 建议：{markdown_label(action['suggested_action'])}")
            lines.append(f"- 操作：`删除 {action['id']}` / `暂放 {action['id']}` / `移到待办 {action['id']}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_daily_digest_date(path):
    try:
        return dt.date.fromisoformat(Path(path).stem)
    except ValueError:
        return None


def parse_weekly_digest_range(path):
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})", Path(path).stem)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1)), dt.date.fromisoformat(match.group(2))
    except ValueError:
        return None


def read_digest_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def write_digest_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(text), encoding="utf-8")


def save_daily_digest(summary):
    path = daily_digest_archive_path()
    write_digest_text(path, summary)
    return path


def rollup_completed_months(today=None):
    today = today or dt.date.today()
    current_month_start = today.replace(day=1)
    daily_by_month = {}
    weekly_by_month = {}

    for path in sorted(digest_dir("daily").glob("*.md")):
        day = parse_daily_digest_date(path)
        if not day or day >= current_month_start:
            continue
        daily_by_month.setdefault(day.strftime("%Y-%m"), []).append((day, path))

    for path in sorted(digest_dir("weekly").glob("*.md")):
        period = parse_weekly_digest_range(path)
        if not period:
            continue
        _start, end = period
        if end >= current_month_start:
            continue
        weekly_by_month.setdefault(end.strftime("%Y-%m"), []).append((period, path))

    written = []
    months = sorted(set(daily_by_month) | set(weekly_by_month))
    for year_month in months:
        monthly_path = monthly_digest_archive_path(year_month)
        lines = [
            f"# Codex 月摘要 {year_month}",
            "",
            "本文件由每日摘要和周摘要自动汇总生成。生成后，来源 daily/weekly 文件会从活跃归档中移除。",
            "",
        ]
        weekly_items = weekly_by_month.get(year_month, [])
        if weekly_items:
            lines.extend(["## 周摘要", ""])
            for (start, end), path in weekly_items:
                lines.extend([f"### {start.isoformat()} 至 {end.isoformat()}", "", read_digest_text(path).strip(), ""])
        daily_items = daily_by_month.get(year_month, [])
        if daily_items:
            lines.extend(["## 剩余日报", ""])
            for day, path in daily_items:
                lines.extend([f"### {day.isoformat()}", "", read_digest_text(path).strip(), ""])
        write_digest_text(monthly_path, "\n".join(lines).rstrip() + "\n")
        written.append(str(monthly_path))
        for _period, path in weekly_items:
            path.unlink(missing_ok=True)
        for _day, path in daily_items:
            path.unlink(missing_ok=True)
    return written


def rollup_completed_weeks(today=None):
    today = today or dt.date.today()
    groups = {}
    for path in sorted(digest_dir("daily").glob("*.md")):
        day = parse_daily_digest_date(path)
        if not day or day >= today:
            continue
        week_start = day - dt.timedelta(days=day.weekday())
        week_end = week_start + dt.timedelta(days=6)
        if week_end >= today:
            continue
        groups.setdefault((week_start, week_end), []).append((day, path))

    written = []
    for (_week_start, _week_end), items in sorted(groups.items()):
        items = sorted(items)
        start = items[0][0]
        end = items[-1][0]
        weekly_path = weekly_digest_archive_path(start, end)
        lines = [
            f"# Codex 周摘要 {start.isoformat()} 至 {end.isoformat()}",
            "",
            "本文件由每日摘要自动汇总生成。生成后，来源 daily 文件会从活跃归档中移除。",
            "",
        ]
        for day, path in items:
            lines.extend([f"## {day.isoformat()}", "", read_digest_text(path).strip(), ""])
        write_digest_text(weekly_path, "\n".join(lines).rstrip() + "\n")
        written.append(str(weekly_path))
        for _day, path in items:
            path.unlink(missing_ok=True)
    return written


def daily_digest(source, *, force=False):
    if not force and daily_summary_already_shown(source):
        response(
            "",
            suppress_output=True,
            skipped_reason="daily_summary_already_shown",
            daily_summary_date=local_today(),
        )
        return
    tasks = active_tasks()
    operation_events = previous_day_operation_events()
    previous_activity, activity_source = previous_day_activity_bundle(operation_events)
    daily_changes = previous_day_operation_changes(operation_events)
    recent_work = recent_completed_work()
    recurring_report = run_recurring_task_audit()
    follow_ups = enrich_follow_ups(active_follow_ups(), recurring_report)
    closure_report = repository_closure_report(source)
    new_artifacts = artifact_summary_entries()
    artifacts = upsert_pending_artifacts(new_artifacts)
    actions = artifact_actions(artifacts)
    deleted_daily_digests = cleanup_daily_digest_files()
    summary = daily_card_markdown(
        tasks,
        artifacts,
        recent_work,
        closure_report,
        previous_activity,
        recurring_report,
        daily_changes,
        activity_source,
        follow_ups,
    )
    saved_digest_path = save_daily_digest(summary)
    monthly_rollup_paths = rollup_completed_months()
    weekly_rollup_paths = rollup_completed_weeks()
    mark_daily_summary(source)
    response(
        summary,
        task_count=len(tasks),
        previous_day_activity_count=len(previous_activity),
        previous_day_activities=previous_activity,
        previous_day_activity_source=activity_source,
        previous_day_change_count=len(daily_changes),
        previous_day_changes=daily_changes,
        recent_completed_work_count=len(recent_work),
        recurring_task_count=recurring_report.get("task_count", len(recurring_report.get("tasks", []))),
        recurring_task_counts=recurring_report.get("counts", {}),
        recurring_tasks=recurring_report.get("tasks", []),
        recurring_task_warnings=recurring_report.get("warnings", []),
        follow_up_count=len(follow_ups),
        follow_up_attention_count=sum(
            1 for item in follow_ups if item.get("monitor_state") == "attention"
        ),
        follow_ups=follow_ups,
        repository_closure_count=closure_report.get("finding_count", 0),
        repository_closure_counts=closure_report.get("counts", {}),
        repository_closure_findings=closure_report.get("findings", []),
        repository_closure_report_path=str(repository_closure_report_path("md")),
        repository_closure_warnings=closure_report.get("warnings", []),
        artifact_summary_count=len(artifacts),
        artifact_actions=actions,
        new_artifact_candidate_count=len(new_artifacts),
        pending_artifacts_path=str(pending_artifacts_path()),
        pending_artifacts_markdown_path=str(pending_artifacts_markdown_path()),
        cleanup_deleted_daily_digest_count=deleted_daily_digests,
        digest_path=str(saved_digest_path),
        weekly_rollup_paths=weekly_rollup_paths,
        monthly_rollup_paths=monthly_rollup_paths,
        daily_summary_date=local_today(),
        artifact_summary_date=local_yesterday(),
    )


def event_name(hook_input):
    return (
        hook_input.get("hook_event_name")
        or hook_input.get("hookEventName")
        or hook_input.get("event")
        or hook_input.get("trigger")
        or ""
    )


def run(hook_input):
    name = event_name(hook_input).lower()
    if name == "stop":
        extracted = extract_tasks(hook_input.get("transcript_path", ""))
        added = add_extracted_tasks(extracted, hook_input)
        response(
            f"任务连续性：已记录 {len(added)} 个显式标记任务。",
            added_task_count=len(added),
        )
        return
    if name in {"sessionstart", "session_start", "dailydigest", "daily_digest"}:
        daily_digest(name, force=bool(hook_input.get("force")))
        return
    if name in {"precompact", "pre_compact"}:
        tasks = active_tasks()
        response(task_summary(tasks), task_count=len(tasks))
        return
    response("任务连续性：当前事件无需处理。", added_task_count=0)


def main():
    try:
        run(read_hook_input())
    except Exception as error:
        response(f"任务连续性：记录失败，但不阻塞主流程。{error}", added_task_count=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
