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
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def score(self) -> int:
        return min(100, min(self.hits, 30) * 2 + len(self.files) * 4)

    @property
    def priority(self) -> str:
        if self.score >= 60 and len(self.files) >= 5:
            return "P0"
        if self.score >= 28 and len(self.files) >= 2:
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
    ),
)


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


def collect_files(args: argparse.Namespace, cutoff: dt.date) -> list[Path]:
    roots: list[Path] = []
    task_ledger = Path(args.task_ledger_dir).expanduser()
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
            if item.is_file() and is_recent(item, cutoff):
                files.append(item)
    for item in direct_files:
        if item.exists() and item.is_file():
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


def analyze(files: Iterable[Path], max_chars_per_file: int) -> dict[str, Candidate]:
    candidates = {rule.key: Candidate(rule=rule) for rule in PATTERNS}
    for path in files:
        file_hits: dict[str, int] = {rule.key: 0 for rule in PATTERNS}
        for line_no, line in enumerate(read_lines(path, max_chars_per_file), start=1):
            lowered = line.casefold()
            for candidate in candidates.values():
                matched = [kw for kw in candidate.rule.keywords if kw.casefold() in lowered]
                if not matched:
                    continue
                if file_hits[candidate.rule.key] >= 5:
                    continue
                added_hits = min(len(matched), 5 - file_hits[candidate.rule.key])
                file_hits[candidate.rule.key] += added_hits
                candidate.hits += added_hits
                candidate.files.add(path)
                if len(candidate.evidence) < 5:
                    candidate.evidence.append(Evidence(path, line_no, clean_line(line)))
    return candidates


def markdown_link(path: Path) -> str:
    text = str(path)
    escaped = text.replace(")", "%29")
    return f"`{escaped}`"


def render_report(candidates: dict[str, Candidate], files: list[Path], args: argparse.Namespace) -> str:
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
        f"- 时间范围：最近 {args.days} 天",
        f"- 读取文件数：{len(files)}",
        "- 原则：只读摘要和账本；不读取完整 transcript；不自动创建、不自动删除、不自动改全局规则。",
        "",
        "## 推荐沉淀候选",
        "",
    ]

    if recommend:
        lines.extend(
            [
                "| 优先级 | 候选 | 建议形态 | 分数 | 证据文件 | 理由 |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for item in recommend:
            lines.append(
                f"| {item.priority} | {item.rule.title} | {item.rule.suggested_shape} | "
                f"{item.score} | {len(item.files)} | {item.rule.reason} |"
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
        lines.extend(["| 候选 | 分数 | 证据文件 | 暂不处理原因 |", "|---|---:|---:|---|"])
        for item in defer[:8]:
            lines.append(
                f"| {item.rule.title} | {item.score} | {len(item.files)} | 证据不足或频率偏低，继续观察。 |"
            )
    else:
        lines.append("- 无。")

    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "1. 人工确认 P0/P1 候选是否值得处理。",
            "2. 对确认项使用 `skill-governance-review` 判断应进入 Skill、模板、自动化、Hook、AGENTS 规则、Obsidian 索引，还是归档。",
            "3. 只对已确认候选执行创建、合并或归档动作。",
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
    parser.add_argument("--task-ledger-dir", default="~/.codex/task-ledger")
    parser.add_argument("--context-card-dir", default="~/.codex/context-cards")
    parser.add_argument("--work-ledger-dir", default="~/.codex/work-ledger")
    parser.add_argument(
        "--obsidian-codex-dir",
        default="~/program/documents/obsidian_vault/03_Resources/Codex工作台",
    )
    parser.add_argument("--output-dir", default="~/.codex/workflow-pattern-reports")
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
    files = collect_files(args, cutoff)
    candidates = analyze(files, args.max_chars_per_file)
    report = render_report(candidates, files, args)
    path = write_report(report, Path(args.output_dir).expanduser(), args.today)

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
