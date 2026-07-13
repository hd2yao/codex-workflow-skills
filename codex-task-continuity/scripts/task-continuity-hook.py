#!/usr/bin/env python3
import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import datetime as dt
from pathlib import Path


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
    return is_git_tracked_file(item) or is_git_managed_subtree(item)


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
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        if item.resolve().is_relative_to(temp_root):
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


def daily_card_markdown(tasks, artifacts, recent_work=None):
    recent_work = recent_work or []
    actions = artifact_actions(artifacts)
    lines = [
        "## Codex 每日任务摘要",
        "",
        f"**日期**：{local_today()}  ",
        f"**未完成任务**：{len(tasks)}  ",
        f"**产物待确认**：{len(actions)}",
        "",
        "## 未完成任务",
        "",
    ]
    if not tasks:
        lines.append("- 当前没有记录到未完成任务。")
    else:
        for task in tasks:
            status = task.get("status", "")
            title = markdown_label(task.get("title", "未命名任务"))
            next_action = markdown_label(task.get("next_action") or "未记录下一步")
            lines.append(f"- **{status}**：{title}（{project_label(task)}）")
            lines.append(f"  下一步：{next_action}")
    lines.extend(["", "## 最近完成", ""])
    if not recent_work:
        lines.append("- 当前没有记录到最近完成工作。")
    else:
        for work in recent_work:
            title = markdown_label(work.get("title", "未命名工作"))
            status = markdown_label(work.get("status", "completed"))
            summary = markdown_label(work.get("summary") or "未记录概要")
            usage = markdown_label(work.get("usage") or "未记录使用方式")
            lines.append(f"- **{status}**：{title}")
            lines.append(f"  做了什么：{summary}")
            lines.append(f"  如何使用：{usage}")
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


def daily_digest(source):
    if daily_summary_already_shown(source):
        response(
            "",
            suppress_output=True,
            skipped_reason="daily_summary_already_shown",
            daily_summary_date=local_today(),
        )
        return
    tasks = active_tasks()
    recent_work = recent_completed_work()
    new_artifacts = artifact_summary_entries()
    artifacts = upsert_pending_artifacts(new_artifacts)
    actions = artifact_actions(artifacts)
    deleted_daily_digests = cleanup_daily_digest_files()
    summary = daily_card_markdown(tasks, artifacts, recent_work)
    saved_digest_path = save_daily_digest(summary)
    monthly_rollup_paths = rollup_completed_months()
    weekly_rollup_paths = rollup_completed_weeks()
    mark_daily_summary(source)
    response(
        summary,
        task_count=len(tasks),
        recent_completed_work_count=len(recent_work),
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
        daily_digest(name)
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
