#!/usr/bin/env python3
"""Build a concise semantic weekly review from structured Codex ledgers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
STATUS_LABELS = {
    "completed": "已完成",
    "delivered_pending_trial": "已交付待试用",
    "in_progress": "进行中",
    "research_pending_implementation": "调研完成待实施",
    "waiting_user": "等待你的决定",
    "blocked": "等待外部条件",
}
DELIVERED_STATUSES = {"completed", "delivered_pending_trial"}
CONTAINER_NAMES = {"program", "env", "tools", "sources", "documents", "AI"}
LEARNING_STATUS_LABELS = {
    "observed": "观察",
    "clustered": "已聚类",
    "monitoring": "监控",
    "trial": "试运行",
    "adopted": "已采用",
    "rejected": "已拒绝",
    "verified": "已验证",
}
SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|cookie)\s*[:=]\s*\S{8,}"),
)
WORKFLOW_GROUP_ALIASES = {
    "codex-task-continuity": "codex-task-continuity（Skill + 配套 Hook）",
    "task-continuity-hook": "codex-task-continuity（Skill + 配套 Hook）",
    "task-ledger": "codex-task-continuity（Skill + 配套 Hook）",
    "recurring-task-audit": "codex-task-continuity（Skill + 配套 Hook）",
    "repository-action-budget": "codex-task-continuity（Skill + 配套 Hook）",
    "repository-closure-audit": "codex-task-continuity（Skill + 配套 Hook）",
    "codex-thread-health-guard": "codex-thread-health-guard（Skill + SessionStart Hook）",
    "thread-health-guard-hook": "codex-thread-health-guard（Skill + SessionStart Hook）",
}
WORKFLOW_SEMANTIC_RULES = (
    (
        re.compile(r"(?i)(上下文压缩|context_compacted)"),
        "上下文压缩与任务恢复",
    ),
    (
        re.compile(
            r"(?i)(前一日工作采集|昨日活动|线程索引|操作日志|历史 work ledger|"
            r"历史成果索引|临时图片|临时产物|对话候选扫描|活动记录)"
        ),
        "日报事实采集、临时产物清理与历史去重",
    ),
    (
        re.compile(
            r"(?i)(仓库收尾|提交等价性|远端状态刷新|默认分支与上游|"
            r"仓库操作预算|仓库写操作|周期任务.*(?:审计|健康|证据)|"
            r"审计项目声明的周期任务|Git worktree|未收尾分支|GitHub PR)"
        ),
        "仓库收尾、周期任务审计与动态写预算",
    ),
    (
        re.compile(
            r"(?i)(等待条件|续作监控|自动恢复|安全并行|目标因.*外部条件|"
            r"外部条件等待)"
        ),
        "等待目标监控、自动续作与安全并行",
    ),
    (
        re.compile(r"(?i)(主动提醒 Hook|SessionStart|thread migration|线程迁移)"),
        "高风险任务迁移提醒",
    ),
)
WORKFLOW_SUMMARY_PRIORITY = {
    "日报事实采集、临时产物清理与历史去重": 0,
    "仓库收尾、周期任务审计与动态写预算": 1,
    "等待目标监控、自动续作与安全并行": 2,
    "上下文压缩与任务恢复": 3,
    "高风险任务迁移提醒": 4,
}
WORKFLOW_NOISE = re.compile(
    r"(?i)(DTSTART|RRULE|设置投递目标|(?:实现)?内容已调整|用途与可识别能力未变化|"
    r"未保留更新前语义快照|功能入口|任务台账管理|References|Integration Rules|"
    r"(?:thread|任务)[-_ ]?(?:id|目标))"
)


def previous_week(today: dt.date) -> tuple[dt.date, dt.date]:
    monday = today - dt.timedelta(days=today.weekday())
    end = monday - dt.timedelta(days=1)
    return end - dt.timedelta(days=6), end


def period_key(period: tuple[dt.date, dt.date]) -> str:
    return f"{period[0].isoformat()}_to_{period[1].isoformat()}"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def clean(value: object, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = re.sub(r"/(?:Users|var|tmp)/[^\s，。；：]+", "[内部路径]", text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def selected_date(path: Path, start: dt.date, end: dt.date) -> dt.date | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", path.name)
    if not match:
        return None
    try:
        day = dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return day if start <= day <= end else None


def project_group_key(item: dict) -> str:
    name = str(item.get("project_name") or "").strip()
    raw_path = str(item.get("project_path") or "").strip()
    if not raw_path:
        return f"name:{name}"
    if Path(raw_path).name in CONTAINER_NAMES:
        return f"container:{raw_path}|{name}"
    return f"path:{raw_path}"


def project_name_score(name: str, raw_path: str) -> tuple[int, int, int]:
    path_name = Path(raw_path).name.casefold() if raw_path else ""
    generic = name.casefold() == path_name or name in CONTAINER_NAMES
    contains_cjk = bool(re.search(r"[\u4e00-\u9fff]", name))
    return (0 if generic else 2, 1 if contains_cjk else 0, len(name))


def collect_projects(task_ledger: Path, period: tuple[dt.date, dt.date]) -> list[dict]:
    start, end = period
    grouped: dict[str, dict] = {}
    for path in sorted((task_ledger / "activity").glob("*.json")):
        day = selected_date(path, start, end)
        if day is None:
            continue
        data = read_json(path, {})
        activities = data.get("activities", {})
        items = activities.values() if isinstance(activities, dict) else activities
        for item in items or []:
            if not isinstance(item, dict) or not item.get("project_name"):
                continue
            raw_path = str(item.get("project_path") or "").strip()
            key = project_group_key(item)
            incoming_name = clean(item["project_name"], 120)
            project = grouped.setdefault(
                key,
                {
                    "project_name": incoming_name,
                    "project_name_score": project_name_score(incoming_name, raw_path),
                    "status": "in_progress",
                    "title": "",
                    "summaries": [],
                    "next_action": "",
                    "thread_ids": set(),
                    "last_date": "",
                },
            )
            incoming_score = project_name_score(incoming_name, raw_path)
            if incoming_score > project["project_name_score"]:
                project["project_name"] = incoming_name
                project["project_name_score"] = incoming_score
            summary = clean(item.get("summary"))
            if summary and summary not in project["summaries"]:
                project["summaries"].append(summary)
            thread_id = clean(item.get("thread_id"), 96)
            if thread_id:
                project["thread_ids"].add(thread_id)
            marker = f"{day.isoformat()}|{clean(item.get('updated_at'), 64)}"
            if marker >= project["last_date"]:
                project.update(
                    {
                        "status": clean(item.get("status") or "in_progress", 64),
                        "title": clean(item.get("title"), 160),
                        "next_action": clean(item.get("next_action")),
                        "last_date": marker,
                    }
                )
    projects = []
    for project in grouped.values():
        project["summaries"] = project["summaries"][-4:]
        project["thread_count"] = len(project.pop("thread_ids"))
        project.pop("project_name_score", None)
        project.pop("last_date", None)
        projects.append(project)
    return sorted(
        projects,
        key=lambda item: (
            item["status"] in DELIVERED_STATUSES,
            item["project_name"].casefold(),
        ),
    )


def extract_section(text: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)", text
    )
    return match.group(1).strip() if match else ""


def collect_recurring(task_ledger: Path, period: tuple[dt.date, dt.date]) -> list[dict]:
    archive = task_ledger / "digests" / "weekly" / f"{period_key(period)}.md"
    try:
        text = archive.read_text(encoding="utf-8")
    except OSError:
        return []
    entries: dict[str, dict] = {}
    for section in re.findall(
        r"(?ms)^## 周期任务运行状态\s*$\n(.*?)(?=^## |\Z)", text
    ):
        current = None
        for line in section.splitlines():
            header = re.match(r"^- \*\*(.+?)\*\*：(.+)$", line.strip())
            if header:
                name = clean(header.group(2), 180)
                current = {"name": name, "status": clean(header.group(1), 40), "details": []}
                entries[name] = current
                continue
            detail = re.match(r"^\s{2,}([^：]+)：(.+)$", line)
            if current and detail and detail.group(1).strip() in {"判断", "运行信息", "下次计划"}:
                current["details"].append(
                    f"{clean(detail.group(1), 40)}：{clean(detail.group(2), 220)}"
                )
    return list(entries.values())


def event_date(value: str) -> dt.date | None:
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(LOCAL_TZ).date()


def workflow_group(actor: str, category: str) -> str:
    if actor in WORKFLOW_GROUP_ALIASES:
        return WORKFLOW_GROUP_ALIASES[actor]
    if actor == "codex" and category == "automation":
        return "Codex 每日摘要 Automation"
    suffix = {"skill": "Skill", "hook": "Hook", "automation": "Automation"}.get(category)
    if suffix and not actor.endswith(f" {suffix}"):
        return f"{actor} {suffix}"
    return actor


def workflow_summary_tags(actor: str, summary: object) -> list[str]:
    value = clean(summary, 1200)
    prefix = f"{actor}："
    if value.startswith(prefix):
        value = value[len(prefix) :]

    tags = [label for pattern, label in WORKFLOW_SEMANTIC_RULES if pattern.search(value)]
    if tags:
        return list(dict.fromkeys(tags))

    fallback = []
    for part in re.split(r"[；。]", value):
        part = part.strip("。； ")
        if not part or WORKFLOW_NOISE.search(part) or len(part) > 64:
            continue
        if re.search(r"(?:^|[^0-9a-f])[0-9a-f]{16,}(?:$|[^0-9a-f])", part, re.I):
            continue
        fallback.append(part)
    return list(dict.fromkeys(fallback))[:2]


def collect_workflow_changes(path: Path, period: tuple[dt.date, dt.date]) -> list[dict]:
    start, end = period
    selected: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        day = event_date(event.get("occurred_at", ""))
        if day is None or not start <= day <= end:
            continue
        if event.get("scope") != "global_workflow":
            continue
        actor = clean((event.get("actor") or {}).get("label"), 120)
        category = clean(event.get("category"), 40)
        if category not in {"skill", "hook", "automation"} and actor != "Codex 全局规则":
            continue
        action = clean(event.get("action"), 80)
        key = workflow_group(actor or clean(event.get("title"), 120), category)
        item = selected.setdefault(
            key,
            {
                "actor": key,
                "actions": set(),
                "categories": set(),
                "summaries": [],
                "date": day.isoformat(),
            },
        )
        item["actions"].add(action)
        item["categories"].add(category)
        for summary in workflow_summary_tags(actor, event.get("summary")):
            if summary not in item["summaries"]:
                item["summaries"].append(summary)
        item["date"] = max(item["date"], day.isoformat())
    result = []
    for item in selected.values():
        item["actions"] = sorted(item["actions"])
        if (
            item["categories"] == {"automation"}
            and any(action.endswith("_added") for action in item["actions"])
            and any(action.endswith("_deleted") for action in item["actions"])
        ):
            continue
        item["summaries"] = sorted(
            item["summaries"],
            key=lambda value: (WORKFLOW_SUMMARY_PRIORITY.get(value, 99), value),
        )[:4]
        item.pop("categories", None)
        result.append(item)
    return sorted(result, key=lambda item: (item["date"], item["actor"]))


def collect_learning(root: Path, period: tuple[dt.date, dt.date]) -> list[dict]:
    start, end = period
    key = period_key(period)
    observations = read_json(root / "observations.json", {}).get("observations", {})
    weekly_threads: dict[str, set[str]] = {}
    weekly_counts: dict[str, int] = {}
    for item in observations.values():
        try:
            day = dt.date.fromisoformat(item.get("date", ""))
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        for category in item.get("categories") or ["explicit_correction"]:
            weekly_threads.setdefault(category, set()).add(clean(item.get("thread_id"), 96))
            weekly_counts[category] = weekly_counts.get(category, 0) + 1
    state = read_json(root / "candidates.json", {}).get("candidates", {})
    result = []
    for category in sorted(set(weekly_threads) | set(state)):
        candidate = state.get(category, {})
        if category not in weekly_threads and key not in candidate.get("periods", []):
            continue
        threads = {item for item in weekly_threads.get(category, set()) if item}
        result.append(
            {
                "key": category,
                "title": clean(candidate.get("title") or category, 160),
                "root_cause": clean(candidate.get("root_cause") or "本周只记录现象，根因待跨任务复发后复核。"),
                "status": clean(candidate.get("status") or "observed", 40),
                "weekly_thread_count": len(threads),
                "observation_count": weekly_counts.get(category, 0),
                "next_action": clean(candidate.get("next_action") or "继续观察是否在独立任务中复发。"),
                "next_check_at": clean(candidate.get("next_check_at"), 40),
            }
        )
    return result


def collect_patterns(root: Path, period: tuple[dt.date, dt.date]) -> list[dict]:
    key = period_key(period)
    candidates = read_json(root / "candidates.json", {}).get("candidates", {})
    result = []
    for candidate_key, item in candidates.items():
        if key not in item.get("periods", []):
            continue
        result.append(
            {
                "key": candidate_key,
                "title": clean(item.get("title") or candidate_key, 160),
                "status": clean(item.get("status") or "observed", 40),
                "weeks_seen": int(item.get("weeks_seen") or 0),
                "existing_skills": [clean(value, 100) for value in item.get("existing_skills", [])],
                "recommended_action": clean(item.get("recommended_action") or "monitor", 60),
            }
        )
    return sorted(result, key=lambda item: item["title"])


def render_project(project: dict) -> list[str]:
    label = STATUS_LABELS.get(project["status"], project["status"])
    title = f" · {project['title']}" if project.get("title") else ""
    lines = [f"- **{label} · {project['project_name']}**{title}"]
    if project["summaries"]:
        summaries = [value.rstrip("。； ") for value in project["summaries"]]
        lines.append("  本周：" + "；".join(summaries) + "。")
    if project.get("next_action"):
        lines.append("  后续：" + project["next_action"])
    return lines


def render(payload: dict) -> str:
    period = payload["period"]
    projects = payload["projects"]
    delivered = [item for item in projects if item["status"] in DELIVERED_STATUSES]
    continuing = [item for item in projects if item["status"] not in DELIVERED_STATUSES]
    lines = [
        f"# Codex 每周工作总结 · {period['start']} 至 {period['end']}",
        "",
        f"本周覆盖 {len(projects)} 个项目、{sum(item['thread_count'] for item in projects)} 个独立任务。以下是可直接决策的语义总结，原始日报仅作为内部证据。",
        "",
        "## 本周完成与可试用",
        "",
    ]
    if delivered:
        for project in delivered:
            lines.extend(render_project(project))
    else:
        lines.append("- 本周没有记录到已完成或待试用项目。")
    lines.extend(["", "## 继续推进", ""])
    if continuing:
        for project in continuing:
            lines.extend(render_project(project))
    else:
        lines.append("- 本周没有需要续作的项目。")

    lines.extend(["", "## 周期任务", ""])
    if payload["recurring_tasks"]:
        for item in payload["recurring_tasks"]:
            details = "；".join(item["details"])
            lines.append(f"- **{item['status']} · {item['name']}**：{details}")
    else:
        lines.append("- 本周没有可核实的周期任务记录。")

    lines.extend(["", "## Codex 工作流变更", ""])
    if payload["workflow_changes"]:
        for item in payload["workflow_changes"]:
            action_labels = []
            for action in item["actions"]:
                if action.endswith("_added"):
                    action_labels.append("新增")
                elif action.endswith("_deleted"):
                    action_labels.append("删除")
                elif action.endswith("_updated"):
                    action_labels.append("更新")
            action_text = "/".join(dict.fromkeys(action_labels)) or "变更"
            if item["summaries"]:
                summary = "；".join(item["summaries"])
            elif action_labels == ["删除"]:
                summary = "该能力已从全局工作流移除"
            elif action_labels == ["新增"]:
                summary = "该能力已加入全局工作流"
            else:
                summary = "职责已更新"
            lines.append(
                f"- **{item['actor']} · {action_text}**："
                f"{summary}"
            )
    else:
        lines.append("- 本周没有记录到全局 Skill、Hook、Automation 或配置变更。")

    lines.extend(["", "## 跨任务问题与根因", ""])
    if payload["learning_candidates"]:
        for item in payload["learning_candidates"]:
            scope = (
                f"本周涉及 {item['weekly_thread_count']} 个独立任务"
                if item["weekly_thread_count"]
                else "本周沿用既有监控状态"
            )
            lines.append(
                f"- **{item['title']} · {LEARNING_STATUS_LABELS.get(item['status'], item['status'])}**：{scope}。根因：{item['root_cause']} "
                f"下一步：{item['next_action']}"
            )
    else:
        lines.append("- 本周没有跨任务重复的纠偏问题；单任务问题只保留观察，不触发规则变更。")

    lines.extend(["", "## Harness 成长跟踪", ""])
    if payload["workflow_candidates"]:
        for item in payload["workflow_candidates"]:
            if item["existing_skills"]:
                direction = f"已有承载 `{'`, `'.join(item['existing_skills'])}`；当前只观察，未触发更新"
            else:
                direction = "继续监控，不创建新能力"
            occurrence = "本周首次出现" if item["weeks_seen"] <= 1 else f"连续出现 {item['weeks_seen']} 周"
            lines.append(
                f"- **{item['title']} · {LEARNING_STATUS_LABELS.get(item['status'], item['status'])}**：{occurrence}；{direction}。"
            )
    else:
        lines.append("- 本周没有进入持续跟踪的可复用流程候选。")

    user_items = [item for item in projects if item["status"] == "waiting_user"]
    lines.extend(["", "## 需要你处理", ""])
    if user_items:
        for item in user_items:
            lines.append(f"- **{item['project_name']}**：{item['next_action']}")
    else:
        lines.append("- 无。其余续作、监控和候选跟踪由自动化继续处理。")
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict, report: str, output_dir: Path, key: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{key}.md"
    json_path = output_dir / f"{key}.json"
    md_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=dt.date.today().isoformat())
    parser.add_argument("--previous-week", action="store_true")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--task-ledger-dir", default="~/.codex/task-ledger")
    parser.add_argument("--operation-ledger", default="~/.codex/operation-ledger/events.jsonl")
    parser.add_argument("--error-learning-dir", default="~/.codex/error-learning")
    parser.add_argument("--workflow-pattern-dir", default="~/.codex/workflow-pattern-reports")
    parser.add_argument("--output-dir", default="~/.codex/task-ledger/digests/reviews/weekly")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    today = dt.date.fromisoformat(args.today)
    if args.previous_week:
        period = previous_week(today)
    elif args.start and args.end:
        period = (dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end))
    else:
        raise SystemExit("use --previous-week or both --start and --end")
    task_ledger = Path(args.task_ledger_dir).expanduser()
    payload = {
        "version": 1,
        "period": {"start": period[0].isoformat(), "end": period[1].isoformat()},
        "projects": collect_projects(task_ledger, period),
        "recurring_tasks": collect_recurring(task_ledger, period),
        "workflow_changes": collect_workflow_changes(Path(args.operation_ledger).expanduser(), period),
        "learning_candidates": collect_learning(Path(args.error_learning_dir).expanduser(), period),
        "workflow_candidates": collect_patterns(Path(args.workflow_pattern_dir).expanduser(), period),
    }
    report = render(payload)
    md_path, json_path = write_outputs(
        payload, report, Path(args.output_dir).expanduser(), period_key(period)
    )
    if args.json:
        print(json.dumps({"report_path": str(md_path), "json_path": str(json_path), **payload}, ensure_ascii=False))
    elif args.stdout:
        print(report, end="")
    else:
        print(f"report_path={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
