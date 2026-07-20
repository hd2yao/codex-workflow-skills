#!/usr/bin/env python3
"""Find repeated workflow patterns from lightweight Codex summaries."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|cookie)\s*[:=]\s*[^ \n\r\t`'\"\]]{8,}"
    ),
)


@dataclass(frozen=True)
class PatternRule:
    key: str
    title: str
    keywords: tuple[str, ...]
    suggested_shape: str
    reason: str
    anchors: tuple[str, ...] = ()


@dataclass
class Evidence:
    path: Path
    line_no: int
    snippet: str


@dataclass
class Candidate:
    rule: PatternRule
    hits: int = 0
    files: set[Path] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def score(self) -> int:
        return min(100, min(self.hits, 30) * 2 + len(self.sources) * 6)

    @property
    def priority(self) -> str:
        if self.score >= 60 and len(self.sources) >= 5:
            return "P0"
        if self.score >= 28 and len(self.sources) >= 2:
            return "P1"
        return "P2"


PATTERNS = (
    PatternRule(
        key="skill-governance",
        title="Skill/模板治理与归档",
        keywords=(
            "skill",
            "技能",
            "template",
            "模板",
            "安装",
            "归档",
            "删除",
            "合并",
            "agents/openai.yaml",
            "SKILL.md",
            "skill-governance-review",
        ),
        suggested_shape="Skill 治理评审 / 模板合并 / 归档候选",
        reason="反复出现 skill 创建、安装、合并、归档时，适合沉淀为治理流程或模板资产。",
        anchors=("skill", "技能", "template", "模板", "agents/openai.yaml", "SKILL.md", "skill-governance-review"),
    ),
    PatternRule(
        key="thread-continuity",
        title="线程接续与项目空间迁移",
        keywords=(
            "接续当前线程",
            "新开线程",
            "新开对话",
            "fork 当前线程",
            "项目空间",
            "thread",
            "codex-thread-bridge",
            "context card",
            "上下文摘要",
        ),
        suggested_shape="插件入口 / 线程工作流 / 自动化提示",
        reason="反复处理上下文迁移时，应优先复用线程插件，避免重新扫描项目或重复总结。",
        anchors=("线程", "thread", "codex-thread-bridge", "context card", "上下文摘要", "新开对话", "fork 当前线程"),
    ),
    PatternRule(
        key="research-roadmap",
        title="需求优先调研到落地路线图",
        keywords=(
            "全网",
            "参考项目",
            "开源项目",
            "论文",
            "竞品",
            "需求优先",
            "候选筛选",
            "requirement-first-research",
            "reference-project-study-roadmap",
        ),
        suggested_shape="调研 Skill / 路线图模板 / 候选筛选规则",
        reason="开放式搜索和参考项目对照容易重复，应保留轻量筛选和精选路线图链路。",
    ),
    PatternRule(
        key="project-audit",
        title="项目证据审计与阶段交接",
        keywords=(
            "项目状态",
            "真实进度",
            "验收前",
            "风险/缺口",
            "阶段交接",
            "验证证据",
            "证据审计",
            "project-status-auditor",
        ),
        suggested_shape="按需审计 Skill / 交接模板",
        reason="只有需要文件、提交、测试和报告证据时才值得审计；普通线程迁移不应触发。",
    ),
    PatternRule(
        key="github-bootstrap",
        title="GitHub 项目初始化",
        keywords=(
            "创建 GitHub",
            "初始化 GitHub",
            "GitHub 仓库",
            "首次提交",
            "git init",
            "git push",
            ".gitignore",
            "github-project-bootstrap",
        ),
        suggested_shape="动作型 Skill / 确定性脚本",
        reason="仓库创建和首次推送有固定安全步骤，适合脚本化而不是每次重新解释。",
    ),
    PatternRule(
        key="workspace-governance",
        title="Program 工作区整理与待确认产物",
        keywords=(
            "needs-review",
            "trash-candidates",
            "待确认",
            "散落",
            "产物",
            "归属",
            "program-workspace-governance",
            "pending-artifacts",
        ),
        suggested_shape="工作区治理 / 每日摘要 / 待确认池",
        reason="散落产物需要进入待确认池，但不应自动移动或删除受保护内容。",
        anchors=("needs-review", "trash-candidates", "待确认", "program-workspace-governance", "pending-artifacts"),
    ),
    PatternRule(
        key="obsidian-codex-memory",
        title="Codex 变更回流 Obsidian",
        keywords=(
            "Obsidian",
            "Codex 变更日志",
            "Codex Skills 搜索索引",
            "回流",
            "长期记忆",
            "工作成果账本",
        ),
        suggested_shape="Obsidian 索引 / 变更日志 / 资源页",
        reason="Codex 自身能力变化需要进长期索引，但不应写入完整 transcript 或敏感信息。",
        anchors=("obsidian", "Codex 变更日志", "Codex Skills 搜索索引", "长期记忆"),
    ),
)


KNOWN_SKILLS = {
    "skill-governance": ("skill-governance-review",),
    "thread-continuity": ("codex-thread-bridge", "codex-task-continuity"),
    "research-roadmap": (
        "requirement-first-research",
        "reference-project-study-roadmap",
    ),
    "project-audit": ("project-status-auditor",),
    "github-bootstrap": ("github-project-bootstrap",),
    "workspace-governance": ("program-workspace-governance",),
    "obsidian-codex-memory": ("obsidian-memory-workflow",),
}


def redact(text: str) -> str:
    value = text
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def clean_line(text: str, limit: int = 220) -> str:
    value = redact(re.sub(r"\s+", " ", text).strip())
    if len(value) > limit:
        return value[: limit - 1].rstrip() + "…"
    return value


def parse_date(value: str) -> dt.date | None:
    for pattern, fmt in (
        (r"(20\d{2}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(20\d{6})", "%Y%m%d"),
    ):
        match = re.search(pattern, value)
        if match:
            try:
                return dt.datetime.strptime(match.group(1), fmt).date()
            except ValueError:
                return None
    return None


def is_recent(path: Path, cutoff: dt.date) -> bool:
    date = parse_date(str(path))
    return date is None or date >= cutoff


def is_in_period(path: Path, start: dt.date, end: dt.date) -> bool:
    date = parse_date(str(path))
    return date is not None and start <= date <= end


def collect_files(
    args: argparse.Namespace,
    cutoff: dt.date,
    period: tuple[dt.date, dt.date] | None = None,
) -> list[Path]:
    task_ledger = Path(args.task_ledger_dir).expanduser()
    if period is not None:
        activity_root = task_ledger / "activity"
        activity_files = []
        if activity_root.exists():
            for item in sorted(activity_root.glob("*.json")):
                if item.is_file() and is_in_period(item, *period):
                    activity_files.append(item)
        if activity_files:
            return activity_files[-args.max_files :]

    roots: list[Path] = []
    roots.extend(
        [
            task_ledger / "digests" / "daily",
            task_ledger / "digests" / "weekly",
            task_ledger / "digests" / "monthly",
            Path(args.context_card_dir).expanduser(),
        ]
    )

    direct_files = [
        Path(args.work_ledger_dir).expanduser() / "index.md",
        task_ledger / "pending-artifacts.md",
    ]
    obsidian_dir = Path(args.obsidian_codex_dir).expanduser()
    if obsidian_dir.exists():
        direct_files.extend(
            [
                obsidian_dir / "Codex 变更日志.md",
                obsidian_dir / "Codex 工作成果账本.md",
            ]
        )

    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for item in sorted(root.glob("*.md")):
            selected = (
                is_in_period(item, *period) if period is not None else is_recent(item, cutoff)
            )
            if item.is_file() and selected:
                files.append(item)
    for item in direct_files:
        if period is None and item.exists() and item.is_file():
            files.append(item)

    seen: set[Path] = set()
    result: list[Path] = []
    for item in files:
        resolved = item.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result[-args.max_files :]


def read_lines(path: Path, max_chars: int) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return text[:max_chars].splitlines()


def source_id(path: Path) -> str:
    match = re.search(r"(019[a-f0-9]+(?:-[a-f0-9]+){2,4})(?:\.md)?$", path.name)
    if match:
        return f"thread:{match.group(1)}"
    return f"file:{path}"


def source_lines(path: Path, max_chars_per_file: int):
    if path.suffix == ".json" and path.parent.name == "activity":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        activities = data.get("activities", {})
        items = activities.values() if isinstance(activities, dict) else activities
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                continue
            source = item.get("thread_id") or item.get("project_path") or f"{path}:{index}"
            text = " ".join(
                str(item.get(key) or "")
                for key in ("project_name", "title", "status", "summary", "next_action")
            )
            yield f"thread:{source}", index, text[:max_chars_per_file]
        return
    source = source_id(path)
    for line_no, line in enumerate(read_lines(path, max_chars_per_file), start=1):
        yield source, line_no, line


def analyze(files: Iterable[Path], max_chars_per_file: int) -> dict[str, Candidate]:
    candidates = {rule.key: Candidate(rule=rule) for rule in PATTERNS}
    source_hits: dict[tuple[str, str], int] = {}
    for path in files:
        for source, line_no, line in source_lines(path, max_chars_per_file):
            lowered = line.casefold()
            for candidate in candidates.values():
                if candidate.rule.anchors and not any(
                    anchor.casefold() in lowered for anchor in candidate.rule.anchors
                ):
                    continue
                matched = [kw for kw in candidate.rule.keywords if kw.casefold() in lowered]
                if not matched:
                    continue
                hit_key = (candidate.rule.key, source)
                existing_hits = source_hits.get(hit_key, 0)
                if existing_hits >= 5:
                    continue
                added_hits = min(len(matched), 5 - existing_hits)
                source_hits[hit_key] = existing_hits + added_hits
                candidate.hits += added_hits
                candidate.files.add(path)
                candidate.sources.add(source)
                if len(candidate.evidence) < 5:
                    candidate.evidence.append(Evidence(path, line_no, clean_line(line)))
    return candidates


def find_existing_skills(args: argparse.Namespace) -> dict[str, list[str]]:
    root = Path(args.existing_skills_dir).expanduser()
    installed = {
        item.name
        for item in root.iterdir()
        if root.exists() and item.is_dir() and (item / "SKILL.md").exists()
    } if root.exists() else set()
    return {
        key: [slug for slug in slugs if slug in installed]
        for key, slugs in KNOWN_SKILLS.items()
    }


def period_key(period: tuple[dt.date, dt.date]) -> str:
    return f"{period[0].isoformat()}_to_{period[1].isoformat()}"


def update_candidate_state(
    candidates: dict[str, Candidate],
    output_dir: Path,
    period: tuple[dt.date, dt.date] | None,
    existing_skills: dict[str, list[str]],
) -> dict[str, object]:
    path = output_dir / "candidates.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    entries = state.setdefault("candidates", {})
    key = period_key(period) if period else None
    if key:
        for entry in entries.values():
            periods = entry.get("periods", [])
            if key in periods:
                entry["periods"] = [item for item in periods if item != key]
                entry["weeks_seen"] = len(entry["periods"])
    for candidate in candidates.values():
        if candidate.hits <= 0:
            continue
        entry = entries.setdefault(
            candidate.rule.key,
            {"periods": [], "weeks_seen": 0, "status": "observed"},
        )
        periods = entry.setdefault("periods", [])
        if key and key not in periods:
            periods.append(key)
        entry.update(
            {
                "title": candidate.rule.title,
                "latest_score": candidate.score,
                "latest_file_count": len(candidate.files),
                "latest_source_count": len(candidate.sources),
                "weeks_seen": len(periods),
                "existing_skills": existing_skills.get(candidate.rule.key, []),
                "recommended_action": (
                    "update_existing" if existing_skills.get(candidate.rule.key) else "monitor"
                ),
            }
        )
    state["updated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    output_dir.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return state


def markdown_link(path: Path) -> str:
    text = str(path)
    escaped = text.replace(")", "%29")
    return f"`{escaped}`"


def render_report(
    candidates: dict[str, Candidate],
    files: list[Path],
    args: argparse.Namespace,
    period: tuple[dt.date, dt.date] | None,
    existing_skills: dict[str, list[str]],
) -> str:
    today = dt.date.fromisoformat(args.today)
    rows = sorted(
        [item for item in candidates.values() if item.hits > 0],
        key=lambda item: (item.priority, -item.score, item.rule.title),
    )

    recommend = [item for item in rows if item.priority in {"P0", "P1"}]
    defer = [item for item in rows if item.priority == "P2"]

    lines = [
        "# Codex 重复流程候选复盘",
        "",
        f"- 生成日期：{today.isoformat()}",
        (
            f"- 时间范围：{period[0].isoformat()} 至 {period[1].isoformat()}"
            if period
            else f"- 时间范围：最近 {args.days} 天"
        ),
        f"- 读取文件数：{len(files)}",
        "- 原则：只读摘要和账本；不读取完整 transcript；不自动创建、不自动删除、不自动改全局规则。",
        "",
        "## 推荐沉淀候选",
        "",
    ]

    if recommend:
        lines.extend(
            [
                "| 优先级 | 候选 | 处理方向 | 分数 | 独立来源 | 理由 |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for item in recommend:
            matched_skills = existing_skills.get(item.rule.key, [])
            direction = (
                f"更新已有能力：`{', '.join(matched_skills)}`"
                if matched_skills
                else f"继续监控：{item.rule.suggested_shape}"
            )
            lines.append(
                f"| {item.priority} | {item.rule.title} | {direction} | "
                f"{item.score} | {len(item.sources)} | {item.rule.reason} |"
            )
    else:
        lines.append("- 本轮没有达到 P0/P1 阈值的重复流程候选。")

    lines.extend(["", "## 候选证据", ""])
    for item in recommend[:8]:
        lines.extend([f"### {item.priority} {item.rule.title}", ""])
        for evidence in item.evidence[:3]:
            lines.append(
                f"- {markdown_link(evidence.path)}:{evidence.line_no} - {evidence.snippet}"
            )
        lines.append("")

    lines.extend(["## 暂不处理", ""])
    if defer:
        lines.extend(
            [
                "| 候选 | 处理方向 | 分数 | 独立来源 | 本周结论 |",
                "|---|---|---:|---:|---|",
            ]
        )
        for item in defer[:8]:
            matched_skills = existing_skills.get(item.rule.key, [])
            direction = (
                f"更新已有能力：`{', '.join(matched_skills)}`"
                if matched_skills
                else "继续监控，不创建新能力"
            )
            lines.append(
                f"| {item.rule.title} | {direction} | {item.score} | {len(item.sources)} | "
                "尚未在多个独立任务中重复，不触发能力变更。 |"
            )
    else:
        lines.append("- 无。")

    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "1. 保留本周候选与独立任务证据，下一周继续比较。",
            "2. 只有跨独立任务重复且有回归场景的候选，才进入 `skill-governance-review`。",
            "3. 治理评审通过后先试运行；验证有效才更新 Skill、模板、自动化、Hook 或规则。",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: str, output_dir: Path, today: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{today}-workflow-patterns.md"
    path.write_text(report, encoding="utf-8")
    return path


def parse_args(argv: list[str]) -> argparse.Namespace:
    today = dt.date.today().isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--today", default=today)
    parser.add_argument("--previous-week", action="store_true")
    parser.add_argument("--task-ledger-dir", default="~/.codex/task-ledger")
    parser.add_argument("--context-card-dir", default="~/.codex/context-cards")
    parser.add_argument("--work-ledger-dir", default="~/.codex/work-ledger")
    parser.add_argument(
        "--obsidian-codex-dir",
        default="~/program/documents/obsidian_vault/03_Resources/Codex工作台",
    )
    parser.add_argument("--output-dir", default="~/.codex/workflow-pattern-reports")
    parser.add_argument("--existing-skills-dir", default="~/.codex/skills")
    parser.add_argument("--max-files", type=int, default=120)
    parser.add_argument("--max-chars-per-file", type=int, default=120_000)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    args.days = max(1, args.days)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    today = dt.date.fromisoformat(args.today)
    cutoff = today - dt.timedelta(days=args.days)
    period = None
    if args.previous_week:
        current_monday = today - dt.timedelta(days=today.weekday())
        period = (current_monday - dt.timedelta(days=7), current_monday - dt.timedelta(days=1))
    files = collect_files(args, cutoff, period)
    candidates = analyze(files, args.max_chars_per_file)
    existing_skills = find_existing_skills(args)
    output_dir = Path(args.output_dir).expanduser()
    report = render_report(candidates, files, args, period, existing_skills)
    path = write_report(report, output_dir, args.today)
    update_candidate_state(candidates, output_dir, period, existing_skills)

    if args.json:
        payload = {
            "report_path": str(path),
            "file_count": len(files),
            "candidates": [
                {
                    "key": item.rule.key,
                    "title": item.rule.title,
                    "priority": item.priority,
                    "score": item.score,
                    "hits": item.hits,
                    "file_count": len(item.files),
                    "source_count": len(item.sources),
                }
                for item in sorted(candidates.values(), key=lambda c: -c.score)
                if item.hits > 0
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.stdout:
        print(report)
    else:
        print(f"report_path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
