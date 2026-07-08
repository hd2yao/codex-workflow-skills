#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CONTROL_DIRS = {"_inbox", "_experiments", "_external", "_archive"}
DOC_SUFFIXES = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".csv", ".json"}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db"}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", ".npmrc", ".netrc"}
TRASH_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
EXPERIMENT_PREFIXES = ("tmp", "temp", "experiment", "scratch", "probe", "test")
EXTERNAL_HINTS = ("opensource", "open-source", "reference", "vendor", "upstream")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)AWS_SECRET_ACCESS_KEY\s*=\s*\S+"),
    re.compile(r"(?i)(cookie|set-cookie)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(sessionid|password|secret|token|api[_-]?key)\s*=\s*\S+"),
]


def redact_text(value):
    text = "" if value is None else str(value)
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


def today():
    return dt.date.today().isoformat()


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_sensitive_path(path):
    name = path.name
    lowered = name.lower()
    if lowered in SENSITIVE_NAMES:
        return True
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return any(part.lower() in SENSITIVE_NAMES for part in path.parts)


def is_git_repo_root(path):
    return path.is_dir() and (path / ".git").exists()


def find_git_root(path):
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def is_tracked_by_git(path):
    repo = find_git_root(path)
    if not repo:
        return False
    try:
        relative = path.relative_to(repo)
    except ValueError:
        return False
    if path.is_dir():
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", str(relative)],
            text=True,
            capture_output=True,
            check=False,
        )
        return bool(result.stdout.strip())
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", str(relative)],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def controlled_dirs(root, plan_date):
    return {
        "needs_review": root / "_inbox" / "needs-review",
        "experiment": root / "_experiments",
        "external": root / "_external",
        "trash_candidate": root / "_archive" / "trash-candidates" / plan_date,
    }


def destination_for(root, path, category, plan_date):
    dirs = controlled_dirs(root, plan_date)
    return dirs[category] / path.name


def operation(source, root, action, category, reason, plan_date, risk="low"):
    destination = ""
    if action == "move":
        destination = str(destination_for(root, source, category, plan_date))
    return redact_value(
        {
            "source": str(source),
            "destination": destination,
            "action": action,
            "category": category,
            "risk": risk,
            "reason": reason,
        }
    )


def classify_path(path, root, plan_date, from_documents_codex=False):
    name = path.name
    lowered = name.lower()
    if is_sensitive_path(path):
        return operation(path, root, "skip", "protected", "protected_sensitive_path", plan_date, "high")
    if is_git_repo_root(path):
        return operation(path, root, "skip", "protected", "protected_git_repo_root", plan_date, "high")
    if is_tracked_by_git(path):
        return operation(path, root, "skip", "protected", "protected_tracked_file", plan_date, "high")
    if path.is_dir() and name in CONTROL_DIRS:
        return operation(path, root, "skip", "protected", "controlled_directory", plan_date, "low")
    if name in TRASH_NAMES:
        return operation(path, root, "move", "trash_candidate", "cache_or_build_artifact", plan_date)
    if from_documents_codex:
        return operation(path, root, "move", "needs_review", "documents_codex_artifact", plan_date)
    if path.is_dir() and lowered.startswith(EXPERIMENT_PREFIXES):
        return operation(path, root, "move", "experiment", "top_level_experiment", plan_date)
    if path.is_dir() and any(hint in lowered for hint in EXTERNAL_HINTS):
        return operation(path, root, "move", "external", "external_reference_candidate", plan_date)
    if path.is_file() and path.suffix.lower() in DOC_SUFFIXES:
        return operation(path, root, "move", "needs_review", "loose_document", plan_date)
    return operation(path, root, "skip", "unclassified", "no_safe_default_route", plan_date, "medium")


def scan_candidates(root, documents_codex, plan_date):
    candidates = []
    if root.exists():
        for child in sorted(root.iterdir()):
            candidates.append(classify_path(child, root, plan_date))
    if documents_codex and documents_codex.exists():
        for child in sorted(documents_codex.iterdir()):
            candidates.append(classify_path(child, root, plan_date, from_documents_codex=True))
    return candidates


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(redact_value(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def markdown_plan(plan):
    lines = [
        f"# Program 整理计划 {plan['date']}",
        "",
        f"- 根目录：`{plan['root']}`",
        f"- 候选项：{len(plan['operations'])}",
        "",
        "## 操作清单",
    ]
    for item in plan["operations"]:
        destination = f" -> `{item['destination']}`" if item.get("destination") else ""
        lines.append(
            f"- `{item['action']}` `{item['source']}`{destination} "
            f"({item['category']}, {item['reason']})"
        )
    return "\n".join(lines) + "\n"


def command_scan(args):
    root = Path(args.root).expanduser().resolve()
    docs = Path(args.documents_codex).expanduser().resolve() if args.documents_codex else None
    candidates = scan_candidates(root, docs, args.date or today())
    return {"root": str(root), "candidate_count": len(candidates), "candidates": candidates}


def build_plan(args):
    root = Path(args.root).expanduser().resolve()
    docs = Path(args.documents_codex).expanduser().resolve() if args.documents_codex else None
    plan_date = args.date or today()
    operations = scan_candidates(root, docs, plan_date)
    return {
        "version": 1,
        "generated_at": now_iso(),
        "date": plan_date,
        "root": str(root),
        "documents_codex": str(docs) if docs else "",
        "operations": operations,
    }


def command_plan(args):
    plan = build_plan(args)
    output_dir = Path(args.output_dir).expanduser().resolve()
    plan_path = output_dir / f"program-curator-plan-{plan['date']}.json"
    markdown_path = output_dir / f"program-curator-plan-{plan['date']}.md"
    write_json_atomic(plan_path, plan)
    markdown_path.write_text(markdown_plan(plan), encoding="utf-8")
    return {
        "plan_path": str(plan_path),
        "markdown_path": str(markdown_path),
        "operation_count": len(plan["operations"]),
    }


def load_plan(path):
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def is_under(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def allowed_destination(root, destination):
    controlled = [
        root / "_inbox",
        root / "_experiments",
        root / "_external",
        root / "_archive" / "trash-candidates",
    ]
    return any(is_under(destination.parent, item) or destination.parent.resolve() == item.resolve() for item in controlled)


def unique_destination(destination):
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    for index in range(1, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"unable to find unique destination for {destination}")


def move_log_path(root, plan_date):
    return root / "_archive" / "move-log" / f"{plan_date}.jsonl"


def append_move_log(root, plan_date, event):
    path = move_log_path(root, plan_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_value(event), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def ensure_control_dirs(root, plan_date):
    for path in controlled_dirs(root, plan_date).values():
        path.mkdir(parents=True, exist_ok=True)
    (root / "_archive" / "move-log").mkdir(parents=True, exist_ok=True)


def skip_result(item, reason):
    skipped = dict(item)
    skipped["reason"] = reason
    return skipped


def apply_plan(args):
    plan = load_plan(args.plan)
    root = Path(plan["root"]).expanduser().resolve()
    plan_date = plan.get("date") or today()
    ensure_control_dirs(root, plan_date)
    moved = []
    skipped = []
    for item in plan.get("operations", []):
        source = Path(item.get("source", "")).expanduser()
        destination = Path(item.get("destination", "")).expanduser() if item.get("destination") else None
        if item.get("action") != "move":
            skipped.append(skip_result(item, item.get("reason") or "not_move_action"))
            continue
        if not source.exists():
            skipped.append(skip_result(item, "source_missing"))
            continue
        if is_sensitive_path(source):
            skipped.append(skip_result(item, "protected_sensitive_path"))
            continue
        if is_git_repo_root(source):
            skipped.append(skip_result(item, "protected_git_repo_root"))
            continue
        if is_tracked_by_git(source):
            skipped.append(skip_result(item, "protected_tracked_file"))
            continue
        if not destination or not allowed_destination(root, destination):
            skipped.append(skip_result(item, "destination_not_preauthorized"))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        final_destination = unique_destination(destination)
        event = {
            "at": now_iso(),
            "source": str(source),
            "destination": str(final_destination),
            "category": item.get("category", ""),
            "reason": item.get("reason", ""),
            "dry_run": args.dry_run,
        }
        if not args.dry_run:
            shutil.move(str(source), str(final_destination))
            append_move_log(root, plan_date, event)
        moved.append(event)
    log_path = move_log_path(root, plan_date)
    return {
        "moved_count": len(moved),
        "skipped_count": len(skipped),
        "moved": moved,
        "skipped": skipped,
        "move_log_path": str(log_path),
    }


def command_report(args):
    scan = command_scan(args)
    counts = {}
    for item in scan["candidates"]:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return {"root": scan["root"], "candidate_count": scan["candidate_count"], "counts": counts}


def print_result(result, output_format):
    result = redact_value(result)
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "plan_path" in result:
        print(result["plan_path"])
        return
    if "moved_count" in result:
        print(f"moved={result['moved_count']} skipped={result['skipped_count']}")
        return
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Program workspace curator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--root", required=True)
    scan.add_argument("--documents-codex", default="")
    scan.add_argument("--date", default="")
    scan.add_argument("--format", choices=["text", "json"], default="text")
    scan.set_defaults(func=command_scan)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--root", required=True)
    plan.add_argument("--documents-codex", default="")
    plan.add_argument("--output-dir", required=True)
    plan.add_argument("--date", default="")
    plan.add_argument("--format", choices=["text", "json"], default="text")
    plan.set_defaults(func=command_plan)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--format", choices=["text", "json"], default="text")
    apply.set_defaults(func=apply_plan)

    report = subparsers.add_parser("report")
    report.add_argument("--root", required=True)
    report.add_argument("--documents-codex", default="")
    report.add_argument("--date", default="")
    report.add_argument("--format", choices=["text", "json"], default="text")
    report.set_defaults(func=command_report)

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
