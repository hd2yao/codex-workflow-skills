#!/usr/bin/env python3
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path


STATUSES = {
    "idea",
    "todo",
    "in_progress",
    "waiting_user",
    "blocked",
    "needs_review",
    "cleanup_candidate",
    "done",
    "dropped",
    "archived",
}

ACTIVE_STATUSES = {
    "idea",
    "todo",
    "in_progress",
    "waiting_user",
    "blocked",
    "needs_review",
    "cleanup_candidate",
}

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)AWS_SECRET_ACCESS_KEY\s*=\s*\S+"),
    re.compile(r"(?i)(cookie|set-cookie)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(sessionid|password|secret|token|api[_-]?key)\s*=\s*\S+"),
]


def redact_text(value):
    if value is None:
        return ""
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def redact_value(value):
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today():
    return dt.date.today().isoformat()


def ledger_dir():
    return Path(os.environ.get("CODEX_TASK_LEDGER_DIR", "~/.codex/task-ledger")).expanduser()


def ensure_ledger_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "daily").mkdir(exist_ok=True)


@contextlib.contextmanager
def locked_ledger(path):
    ensure_ledger_dir(path)
    lock_path = path / ".lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def index_path(path):
    return path / "index.json"


def events_path(path):
    return path / "tasks.jsonl"


def load_index(path):
    path = index_path(path)
    if not path.exists():
        return {"version": 1, "tasks": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if "tasks" not in data or not isinstance(data["tasks"], dict):
        return {"version": 1, "tasks": {}}
    return data


def save_index(path, data):
    ensure_ledger_dir(path)
    fd, temp_name = tempfile.mkstemp(prefix="index.", suffix=".json", dir=str(path))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(redact_value(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(index_path(path))
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_event(path, event_type, task):
    ensure_ledger_dir(path)
    event = redact_value({"event": event_type, "at": utc_now(), "task": task})
    with events_path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def slugify(value):
    text = redact_text(value).strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-_")
    return text[:48] or "task"


def make_task_id(title):
    return f"task_{today().replace('-', '')}_{slugify(title)}_{uuid.uuid4().hex[:8]}"


def stable_import_id(status, artifact_path):
    digest = hashlib.sha1(f"{status}:{artifact_path}".encode("utf-8")).hexdigest()[:10]
    return f"task_{today().replace('-', '')}_{status}_{digest}"


def parse_tags(raw):
    if not raw:
        return []
    return [redact_text(item.strip()) for item in raw.split(",") if item.strip()]


def normalize_task(task):
    task = redact_value(task)
    status = task.get("status") or "todo"
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    task["status"] = status
    if not isinstance(task.get("source"), dict):
        task["source"] = {}
    if not isinstance(task.get("project"), dict):
        task["project"] = {}
    if not isinstance(task.get("artifacts"), list):
        task["artifacts"] = []
    if not isinstance(task.get("tags"), list):
        task["tags"] = []
    task.setdefault("next_action", "")
    task.setdefault("blocker", "")
    task.setdefault("remind_on", "")
    return task


def upsert_task(path, task, event_type):
    task = normalize_task(task)
    with locked_ledger(path):
        data = load_index(path)
        data["tasks"][task["id"]] = task
        save_index(path, data)
        append_event(path, event_type, task)
    return task


def add_task(args):
    now = utc_now()
    task = {
        "id": make_task_id(args.title),
        "title": redact_text(args.title),
        "status": args.status,
        "source": {
            "session_id": redact_text(args.session_id),
            "thread_id": redact_text(args.thread_id),
            "transcript_path": redact_text(args.transcript_path),
            "created_at": now,
        },
        "project": {
            "name": redact_text(args.project_name),
            "path": redact_text(args.project_path),
            "obsidian_page": redact_text(args.obsidian_page),
        },
        "artifacts": [],
        "next_action": redact_text(args.next_action),
        "blocker": redact_text(args.blocker),
        "remind_on": redact_text(args.remind_on),
        "updated_at": now,
        "created_at": now,
        "tags": parse_tags(args.tags),
    }
    return {"task": upsert_task(ledger_dir(), task, "add")}


def sorted_tasks(tasks):
    return sorted(
        tasks,
        key=lambda item: (
            item.get("remind_on") or "9999-99-99",
            item.get("updated_at") or "",
            item.get("title") or "",
        ),
    )


def list_tasks(args):
    path = ledger_dir()
    ensure_ledger_dir(path)
    data = load_index(path)
    tasks = list(data.get("tasks", {}).values())
    if args.status:
        statuses = {item.strip() for item in args.status.split(",") if item.strip()}
        tasks = [task for task in tasks if task.get("status") in statuses]
    if args.project:
        project = args.project
        tasks = [
            task
            for task in tasks
            if project in (task.get("project", {}).get("name") or "")
            or project in (task.get("project", {}).get("path") or "")
        ]
    return {"tasks": sorted_tasks(tasks)}


def update_task(args):
    path = ledger_dir()
    with locked_ledger(path):
        data = load_index(path)
        task = data.get("tasks", {}).get(args.task_id)
        if not task:
            raise KeyError(f"task not found: {args.task_id}")
        if args.status:
            task["status"] = args.status
        for field in ("next_action", "blocker", "remind_on"):
            value = getattr(args, field)
            if value is not None:
                task[field] = redact_text(value)
        if args.tags is not None:
            task["tags"] = parse_tags(args.tags)
        task["updated_at"] = utc_now()
        task = normalize_task(task)
        data["tasks"][task["id"]] = task
        save_index(path, data)
        append_event(path, "update", task)
    return {"task": task}


def candidate_entries(root):
    if not root:
        return []
    root_path = Path(root).expanduser()
    if not root_path.exists():
        return []
    entries = []
    for child in sorted(root_path.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
            entries.extend(item for item in sorted(child.iterdir()) if not item.name.startswith("."))
        else:
            entries.append(child)
    return entries


def existing_artifact_paths(tasks, status):
    paths = set()
    for task in tasks.values():
        if task.get("status") != status:
            continue
        for artifact in task.get("artifacts", []):
            if isinstance(artifact, dict) and artifact.get("path"):
                paths.add(artifact["path"])
    return paths


def task_from_artifact(path, status):
    artifact_path = redact_text(str(path))
    if status == "needs_review":
        title = f"处理待确认产物：{Path(artifact_path).name}"
        next_action = "判断保留、归档、转项目或丢弃"
    else:
        title = f"确认隔离区候选：{Path(artifact_path).name}"
        next_action = "判断永久删除或恢复"
    now = utc_now()
    return {
        "id": stable_import_id(status, artifact_path),
        "title": title,
        "status": status,
        "source": {
            "session_id": "",
            "thread_id": "",
            "transcript_path": "",
            "created_at": now,
        },
        "project": {"name": "Program", "path": "/Users/dysania/program", "obsidian_page": ""},
        "artifacts": [{"path": artifact_path, "kind": status}],
        "next_action": next_action,
        "blocker": "",
        "remind_on": "",
        "updated_at": now,
        "created_at": now,
        "tags": ["program-governance", status],
    }


def import_curator(args):
    path = ledger_dir()
    imported = []
    with locked_ledger(path):
        data = load_index(path)
        tasks = data.setdefault("tasks", {})
        existing_review = existing_artifact_paths(tasks, "needs_review")
        existing_cleanup = existing_artifact_paths(tasks, "cleanup_candidate")
        specs = [
            ("needs_review", candidate_entries(args.needs_review_dir), existing_review),
            ("cleanup_candidate", candidate_entries(args.trash_candidates_dir), existing_cleanup),
        ]
        for status, entries, existing in specs:
            for entry in entries:
                artifact_path = redact_text(str(entry))
                if artifact_path in existing:
                    continue
                task = normalize_task(task_from_artifact(entry, status))
                tasks[task["id"]] = task
                imported.append(task)
                append_event(path, "import-curator", task)
        save_index(path, data)
    return {"tasks": sorted_tasks(imported)}


def load_manifest(path):
    manifest_path = Path(path).expanduser()
    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def manifest_items(manifest):
    if isinstance(manifest, list):
        return manifest
    for key in ("tasks", "items", "artifacts", "records"):
        value = manifest.get(key) if isinstance(manifest, dict) else None
        if isinstance(value, list):
            return value
    return []


def import_artifacts(args):
    manifest = load_manifest(args.manifest)
    imported = []
    for item in manifest_items(manifest):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or item.get("path") or "导入产物处理"
        now = utc_now()
        task = {
            "id": make_task_id(title),
            "title": redact_text(title),
            "status": item.get("status") or args.default_status,
            "source": {
                "session_id": redact_text(item.get("session_id", "")),
                "thread_id": redact_text(item.get("thread_id", "")),
                "transcript_path": redact_text(item.get("transcript_path", "")),
                "created_at": now,
            },
            "project": {
                "name": redact_text(item.get("project_name", "")),
                "path": redact_text(item.get("project_path", "")),
                "obsidian_page": redact_text(item.get("obsidian_page", "")),
            },
            "artifacts": redact_value(item.get("artifacts", [])),
            "next_action": redact_text(item.get("next_action", "")),
            "blocker": redact_text(item.get("blocker", "")),
            "remind_on": redact_text(item.get("remind_on", "")),
            "updated_at": now,
            "created_at": now,
            "tags": parse_tags(item.get("tags", "")) if isinstance(item.get("tags"), str) else redact_value(item.get("tags", [])),
        }
        imported.append(upsert_task(ledger_dir(), task, "import-artifacts"))
    return {"tasks": sorted_tasks(imported)}


def render_task_line(task):
    project = task.get("project", {}).get("name") or task.get("project", {}).get("path") or "无项目"
    next_action = task.get("next_action") or "未记录下一步"
    return f"- [{task.get('status')}] {task.get('title')}（{project}）：{next_action}"


def render_section(title, tasks):
    lines = [f"## {title}"]
    if not tasks:
        lines.append("- 暂无")
    else:
        lines.extend(render_task_line(task) for task in tasks)
    return "\n".join(lines)


def digest(args):
    path = ledger_dir()
    ensure_ledger_dir(path)
    data = load_index(path)
    tasks = [task for task in data.get("tasks", {}).values() if task.get("status") in ACTIVE_STATUSES]
    groups = {
        "待继续": [task for task in tasks if task.get("status") in {"idea", "todo", "in_progress"}],
        "等待确认": [task for task in tasks if task.get("status") == "waiting_user"],
        "阻塞": [task for task in tasks if task.get("status") == "blocked"],
        "需要处理": [task for task in tasks if task.get("status") in {"needs_review", "cleanup_candidate"}],
    }
    digest_date = args.date or today()
    lines = [f"# Codex 任务摘要 {digest_date}", ""]
    for title, section_tasks in groups.items():
        lines.append(render_section(title, sorted_tasks(section_tasks)))
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    daily_path = path / "daily" / f"{digest_date}.md"
    daily_path.write_text(redact_text(text), encoding="utf-8")
    return {"digest_path": str(daily_path), "task_count": len(tasks)}


def print_result(result, output_format):
    result = redact_value(result)
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "task" in result:
        task = result["task"]
        print(f"{task['id']} {task['status']} {task['title']}")
        return
    if "tasks" in result:
        for task in result["tasks"]:
            print(f"{task['id']} {task['status']} {task['title']}")
        return
    if "digest_path" in result:
        print(result["digest_path"])
        return
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Codex task continuity ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add")
    add.add_argument("--title", required=True)
    add.add_argument("--status", choices=sorted(STATUSES), default="todo")
    add.add_argument("--next-action", default="")
    add.add_argument("--blocker", default="")
    add.add_argument("--remind-on", default="")
    add.add_argument("--project-name", default="")
    add.add_argument("--project-path", default="")
    add.add_argument("--obsidian-page", default="")
    add.add_argument("--session-id", default="")
    add.add_argument("--thread-id", default="")
    add.add_argument("--transcript-path", default="")
    add.add_argument("--tags", default="")
    add.add_argument("--format", choices=["text", "json"], default="text")
    add.set_defaults(func=add_task)

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--status", default="")
    list_cmd.add_argument("--project", default="")
    list_cmd.add_argument("--format", choices=["text", "json"], default="text")
    list_cmd.set_defaults(func=list_tasks)

    update = subparsers.add_parser("update")
    update.add_argument("task_id")
    update.add_argument("--status", choices=sorted(STATUSES))
    update.add_argument("--next-action")
    update.add_argument("--blocker")
    update.add_argument("--remind-on")
    update.add_argument("--tags")
    update.add_argument("--format", choices=["text", "json"], default="text")
    update.set_defaults(func=update_task)

    digest_cmd = subparsers.add_parser("digest")
    digest_cmd.add_argument("--date", default="")
    digest_cmd.add_argument("--format", choices=["text", "json"], default="text")
    digest_cmd.set_defaults(func=digest)

    import_curator_cmd = subparsers.add_parser("import-curator")
    import_curator_cmd.add_argument("--needs-review-dir", default="")
    import_curator_cmd.add_argument("--trash-candidates-dir", default="")
    import_curator_cmd.add_argument("--format", choices=["text", "json"], default="text")
    import_curator_cmd.set_defaults(func=import_curator)

    import_artifacts_cmd = subparsers.add_parser("import-artifacts")
    import_artifacts_cmd.add_argument("--manifest", required=True)
    import_artifacts_cmd.add_argument("--default-status", choices=sorted(STATUSES), default="todo")
    import_artifacts_cmd.add_argument("--format", choices=["text", "json"], default="text")
    import_artifacts_cmd.set_defaults(func=import_artifacts)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except Exception as error:
        print(json.dumps({"error": redact_text(str(error))}, ensure_ascii=False), file=sys.stderr)
        return 1
    print_result(result, args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
