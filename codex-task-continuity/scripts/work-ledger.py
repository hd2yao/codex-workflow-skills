#!/usr/bin/env python3
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path


STATUSES = {"completed", "partial", "shipped", "superseded", "archived"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)AWS_SECRET_ACCESS_KEY\s*=\s*\S+"),
    re.compile(r"(?i)(cookie|set-cookie)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(sessionid|password|secret|token|api[_-]?key)\s*=\s*\S+"),
]
DEFAULT_OBSIDIAN_PATH = (
    "/Users/dysania/program/documents/obsidian_vault/"
    "03_Resources/Codex工作台/Codex 工作成果账本.md"
)


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


def work_dir():
    return Path(os.environ.get("CODEX_WORK_LEDGER_DIR", "~/.codex/work-ledger")).expanduser()


def obsidian_path():
    raw = os.environ.get("CODEX_WORK_LEDGER_OBSIDIAN_PATH", DEFAULT_OBSIDIAN_PATH)
    if raw in {"", "none", "None", "-"}:
        return None
    return Path(raw).expanduser()


def ensure_work_dir(path):
    path.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def locked_work_dir(path):
    ensure_work_dir(path)
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
    return path / "work.jsonl"


def markdown_path(path):
    return path / "index.md"


def load_index(path):
    target = index_path(path)
    if not target.exists():
        return {"version": 1, "works": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "works": {}}
    if not isinstance(data.get("works"), dict):
        data["works"] = {}
    data["version"] = 1
    return data


def write_json_atomic(path, data):
    ensure_work_dir(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(redact_value(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_event(path, event_type, work):
    ensure_work_dir(path)
    event = redact_value({"event": event_type, "at": utc_now(), "work": work})
    with events_path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def slugify(value):
    text = redact_text(value).strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-_")
    return text[:48] or "work"


def make_work_id(title):
    return f"work_{today().replace('-', '')}_{slugify(title)}_{uuid.uuid4().hex[:8]}"


def csv_values(raw):
    if not raw:
        return []
    return [redact_text(item.strip()) for item in raw.split(",") if item.strip()]


def list_values(values):
    return [redact_text(item) for item in (values or []) if str(item).strip()]


def normalize_work(work):
    work = redact_value(work)
    status = work.get("status") or "completed"
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    work["status"] = status
    work.setdefault("summary", "")
    work.setdefault("capabilities", [])
    work.setdefault("usage", "")
    work.setdefault("verification", "")
    work.setdefault("limitations", [])
    work.setdefault("follow_ups", [])
    work.setdefault("tags", [])
    if not isinstance(work.get("project"), dict):
        work["project"] = {}
    if not isinstance(work.get("source"), dict):
        work["source"] = {}
    if not isinstance(work.get("files"), list):
        work["files"] = []
    if not isinstance(work.get("commits"), list):
        work["commits"] = []
    return work


def sorted_works(works):
    return sorted(works, key=lambda item: (item.get("updated_at") or "", item.get("title") or ""), reverse=True)


def render_list(label, items):
    if not items:
        return [f"- {label}：无"]
    lines = [f"- {label}："]
    lines.extend(f"  - {item}" for item in items)
    return lines


def render_work_markdown(work):
    project = work.get("project", {})
    lines = [
        f"## {work.get('title')}",
        "",
        f"- 状态：`{work.get('status')}`",
        f"- 更新时间：{work.get('updated_at', '')}",
        f"- 项目：{project.get('name') or '未记录'}",
    ]
    if project.get("path"):
        lines.append(f"- 项目路径：`{project.get('path')}`")
    if work.get("summary"):
        lines.append(f"- 做了什么：{work.get('summary')}")
    lines.extend(render_list("当前能力", work.get("capabilities", [])))
    if work.get("usage"):
        lines.append(f"- 如何使用：{work.get('usage')}")
    if work.get("verification"):
        lines.append(f"- 验证：{work.get('verification')}")
    lines.extend(render_list("已知限制", work.get("limitations", [])))
    lines.extend(render_list("后续可能优化", work.get("follow_ups", [])))
    if work.get("commits"):
        lines.extend(render_list("相关 commit", work.get("commits", [])))
    if work.get("files"):
        lines.extend(render_list("相关文件", work.get("files", [])))
    lines.append("")
    return lines


def render_index(data):
    works = sorted_works(list(data.get("works", {}).values()))
    lines = [
        "---",
        "type: codex-work-ledger",
        "status: active",
        f"updated: {today()}",
        "tags: [codex, work-ledger, self-improvement]",
        "---",
        "",
        "# Codex 工作成果账本",
        "",
        "记录已完成或阶段性完成的 Codex 工作成果。未完成事项仍在 task ledger，待确认文件仍在 pending-artifacts。",
        "",
        "## 总览",
        "",
        f"- 已记录工作：{len(works)}",
        "",
    ]
    if not works:
        lines.append("- 暂无记录。")
        lines.append("")
    for work in works:
        lines.extend(render_work_markdown(work))
    return "\n".join(lines).rstrip() + "\n"


def write_indexes(path, data):
    ensure_work_dir(path)
    write_json_atomic(index_path(path), data)
    markdown = redact_text(render_index(data))
    markdown_path(path).write_text(markdown, encoding="utf-8")
    mirror = obsidian_path()
    if mirror:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(markdown, encoding="utf-8")


def add_work(args):
    path = work_dir()
    now = utc_now()
    work = normalize_work(
        {
            "id": make_work_id(args.title),
            "title": redact_text(args.title),
            "status": args.status,
            "summary": redact_text(args.summary),
            "capabilities": list_values(args.capability),
            "usage": redact_text(args.usage),
            "verification": redact_text(args.verification),
            "limitations": list_values(args.limitation),
            "follow_ups": list_values(args.follow_up),
            "project": {
                "name": redact_text(args.project_name),
                "path": redact_text(args.project_path),
            },
            "source": {
                "session_id": redact_text(args.session_id),
                "thread_id": redact_text(args.thread_id),
            },
            "files": list_values(args.file),
            "commits": list_values(args.commit),
            "tags": csv_values(args.tag),
            "created_at": now,
            "updated_at": now,
        }
    )
    with locked_work_dir(path):
        data = load_index(path)
        data.setdefault("works", {})[work["id"]] = work
        write_indexes(path, data)
        append_event(path, "add", work)
    return {"work": work, "index_path": str(index_path(path)), "markdown_path": str(markdown_path(path))}


def list_works(args):
    path = work_dir()
    ensure_work_dir(path)
    data = load_index(path)
    works = list(data.get("works", {}).values())
    if args.status:
        statuses = {item.strip() for item in args.status.split(",") if item.strip()}
        works = [work for work in works if work.get("status") in statuses]
    return {"works": sorted_works(works)[: args.limit]}


def sync_indexes(args):
    path = work_dir()
    ensure_work_dir(path)
    data = load_index(path)
    write_indexes(path, data)
    return {
        "index_path": str(index_path(path)),
        "markdown_path": str(markdown_path(path)),
        "obsidian_path": str(obsidian_path() or ""),
        "work_count": len(data.get("works", {})),
    }


def print_result(result, output_format):
    result = redact_value(result)
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "work" in result:
        work = result["work"]
        print(f"{work['id']} {work['status']} {work['title']}")
        return
    if "works" in result:
        for work in result["works"]:
            print(f"{work['id']} {work.get('status')} {work.get('title')}")
        return
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Codex completed work ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add")
    add.add_argument("--title", required=True)
    add.add_argument("--status", choices=sorted(STATUSES), default="completed")
    add.add_argument("--summary", default="")
    add.add_argument("--capability", action="append", default=[])
    add.add_argument("--usage", default="")
    add.add_argument("--verification", default="")
    add.add_argument("--limitation", action="append", default=[])
    add.add_argument("--follow-up", action="append", default=[])
    add.add_argument("--project-name", default="")
    add.add_argument("--project-path", default="")
    add.add_argument("--session-id", default="")
    add.add_argument("--thread-id", default="")
    add.add_argument("--commit", action="append", default=[])
    add.add_argument("--file", action="append", default=[])
    add.add_argument("--tag", default="")
    add.add_argument("--format", choices=["text", "json"], default="text")
    add.set_defaults(func=add_work)

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--status", default="")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument("--format", choices=["text", "json"], default="text")
    list_cmd.set_defaults(func=list_works)

    sync = subparsers.add_parser("sync-obsidian")
    sync.add_argument("--format", choices=["text", "json"], default="text")
    sync.set_defaults(func=sync_indexes)

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
