#!/usr/bin/env python3
"""Score Codex thread health and prepare a clean continuation pack."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CODEX_HOME = Path("~/.codex").expanduser()
DEFAULT_BRIDGE_DIR = Path(
    os.environ.get(
        "CODEX_THREAD_BRIDGE_DIR",
        "/Users/dysania/program/tools/agent-tools/codex-thread-bridge",
    )
)
EXTREME_TOKEN_THRESHOLD = 1_000_000
EXTREME_CARD_THRESHOLD = 4

POLLUTION_PATTERNS = (
    re.compile(r"不是这个|不对|搞错|错了|理解错|跑偏|偏了|重来|重新来"),
    re.compile(r"先别管前面|忘掉前面|不要按前面|前面.*不算|上下文.*乱|上下文.*污染|串了"),
)

STRUGGLE_PATTERNS = (
    re.compile(r"失败|报错|错误|验证失败|没通过|还是不行|反复|阻塞|超时"),
    re.compile(r"\b(error|failed|failure|traceback|exception|timeout|blocked)\b", re.I),
)

PHASE_TRANSITION_PATTERNS = (
    re.compile(r"(阶段|里程碑|milestone|M\d+).{0,24}(完成|结束|done|closed)", re.I),
    re.compile(r"(完成|测试通过|验证通过).{0,24}(commit|提交)", re.I),
    re.compile(r"(commit|提交|handoff|HANDOFF|交接).{0,32}(下一阶段|新阶段|M\d+|接下来)", re.I),
    re.compile(r"(进入|开始|继续).{0,12}(M\d+|下一阶段|新阶段|整体审查|review|重构|UI|Console)", re.I),
)

MIGRATION_BLOCKER_PATTERNS = (
    re.compile(r"(命令|测试|构建|安装).{0,16}(还在跑|正在跑|运行中|未结束|等待|pending)", re.I),
    re.compile(r"(刚定位|已定位).{0,24}(根因|原因).{0,24}(准备|下一步).{0,12}(改|修)", re.I),
    re.compile(r"(还没|尚未|未).{0,12}(验证|测试|跑完|闭环|提交|commit)", re.I),
    re.compile(r"(不要|别|先别).{0,12}(开新线程|新开线程|迁移|接续)", re.I),
)

META_GUIDANCE_PATTERNS = (
    re.compile(r"官方|社区|Reddit|GitHub issue|文档|资料|评审|对比|优化|建议"),
    re.compile(r"什么时候(应该|不该)|哪些节点|实践建议|最终判断|比如|例如|这几种情况"),
    re.compile(r"判断标准|触发条件|规则|信号|设计成|可以让旧线程|新线程第一句话"),
)

NON_BLOCKING_STATUS_PATTERNS = (
    re.compile(r"不会在未提交|接下来我会提交|已经提交|提交完成|源码修正已经提交|验证通过"),
    re.compile(r"不属于这个 git 仓库|不包含在这个提交|已完成提交"),
)

ABS_PATH_RE = re.compile(r"/(?:Users|home|tmp|var|opt|Volumes)/[^\s`'\"，。；；、)>\]]+")

HANDOFF_FIRST_FILES = (
    "docs/HANDOFF.md",
    "README.md",
    "当前 git status/diff",
    "项目测试脚本和最近测试结果",
    "最近 commit 记录",
)

NEW_THREAD_PROMPT_SUFFIX = (
    "请先阅读 docs/HANDOFF.md、README.md、当前 git status/diff、项目测试脚本和最近 commit 记录。"
    "你是在干净新线程中接手上一个 Codex 线程继续推进；不要重新设计已完成阶段。"
    "先确认你理解的当前目标、已有进展、风险和下一步，然后继续执行。"
    "不要假设完整旧线程都在上下文里；需要细节时读取 pack 中列出的 rollout 或 context card。"
)


@dataclass(frozen=True)
class ThreadSnapshot:
    thread_id: str
    title: str
    cwd: str
    workspace_hint: str
    tokens_used: int
    context_card_count: int
    rollout_path: str
    messages: list[tuple[str, str]]


def clean_inline(value: str, limit: int = 160) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        return value[: limit - 1].rstrip() + "..."
    return value


def title_for_continuation(title: str, thread_id: str) -> str:
    source = clean_inline(title or "未命名线程", 54)
    short_id = (thread_id or "unknown")[:8]
    return f"接续: {source} [from {short_id}]"


def count_matches(patterns: tuple[re.Pattern[str], ...], messages: list[tuple[str, str]]) -> int:
    count = 0
    for _role, text in messages:
        if any(pattern.search(text) for pattern in patterns):
            count += 1
    return count


def signal_messages(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        (role, text)
        for role, text in messages
        if not any(pattern.search(text) for pattern in META_GUIDANCE_PATTERNS)
    ]


def is_non_blocking_status(text: str) -> bool:
    return any(pattern.search(text) for pattern in NON_BLOCKING_STATUS_PATTERNS)


def project_roots_from_texts(snapshot: ThreadSnapshot) -> set[str]:
    roots: set[str] = set()
    texts = [snapshot.cwd, snapshot.workspace_hint]
    texts.extend(text for _role, text in snapshot.messages)
    for text in texts:
        for match in ABS_PATH_RE.finditer(text or ""):
            path = Path(match.group(0))
            parts = path.parts
            if len(parts) >= 5 and parts[1] == "Users":
                roots.add(str(Path(*parts[:5])))
            elif len(parts) >= 4:
                roots.add(str(Path(*parts[:4])))
    return roots


def score_snapshot(snapshot: ThreadSnapshot) -> dict[str, Any]:
    context_score = 0
    pollution_score = 0
    struggle_score = 0
    phase_transition_score = 0
    evidence: list[str] = []
    messages_for_signals = signal_messages(snapshot.messages)

    if snapshot.tokens_used >= 180_000:
        context_score += 4
        evidence.append(f"tokens_used 极高: {snapshot.tokens_used}")
    elif snapshot.tokens_used >= 120_000:
        context_score += 3
        evidence.append(f"tokens_used 较高: {snapshot.tokens_used}")
    elif snapshot.tokens_used >= 80_000:
        context_score += 1
        evidence.append(f"tokens_used 已偏高: {snapshot.tokens_used}")

    if snapshot.context_card_count >= 4:
        context_score += 4
        evidence.append(f"context card 已有 {snapshot.context_card_count} 张")
    elif snapshot.context_card_count >= 2:
        context_score += 2
        evidence.append(f"context card 已有 {snapshot.context_card_count} 张")
    elif snapshot.context_card_count == 1:
        context_score += 1
        evidence.append("已有 1 张 context card")

    user_messages = [(role, text) for role, text in messages_for_signals if role == "用户"]
    pollution_count = count_matches(POLLUTION_PATTERNS, user_messages)
    if pollution_count >= 2:
        pollution_score += 4
        evidence.append(f"最近用户纠错/重置范围 {pollution_count} 次")
    elif pollution_count == 1:
        pollution_score += 2
        evidence.append("最近出现用户纠错或范围重置")

    roots = project_roots_from_texts(snapshot)
    if len(roots) >= 3:
        pollution_score += 2
        evidence.append(f"最近上下文混入多个项目路径: {', '.join(sorted(roots)[:3])}")

    struggle_count = count_matches(STRUGGLE_PATTERNS, messages_for_signals)
    if struggle_count >= 4:
        struggle_score += 4
        evidence.append(f"最近失败/报错/阻塞信号 {struggle_count} 次")
    elif struggle_count >= 2:
        struggle_score += 2
        evidence.append(f"最近失败/报错/阻塞信号 {struggle_count} 次")
    elif struggle_count == 1:
        struggle_score += 1
        evidence.append("最近出现失败、报错或阻塞信号")

    phase_count = count_matches(PHASE_TRANSITION_PATTERNS, messages_for_signals)
    if phase_count >= 2:
        phase_transition_score += 5
        evidence.append(f"最近出现阶段完成/新阶段交接信号 {phase_count} 次")
    elif phase_count == 1:
        phase_transition_score += 4
        evidence.append("最近出现阶段完成或新阶段交接信号")

    migration_blockers = [
        clean_inline(text, 220)
        for _role, text in messages_for_signals
        if any(pattern.search(text) for pattern in MIGRATION_BLOCKER_PATTERNS)
        and not is_non_blocking_status(text)
    ]

    total = context_score + pollution_score + struggle_score + phase_transition_score
    has_context_pressure = context_score >= 3
    has_contamination_or_struggle = pollution_score + struggle_score >= 3
    has_phase_transition = phase_transition_score >= 4
    has_extreme_context = (
        snapshot.tokens_used >= EXTREME_TOKEN_THRESHOLD
        or snapshot.context_card_count >= EXTREME_CARD_THRESHOLD
    )
    if has_extreme_context:
        evidence.append("极端长上下文达到自动接续阈值")

    would_create_new_thread = (
        (has_context_pressure and has_contamination_or_struggle and total >= 6)
        or has_phase_transition
        or has_extreme_context
    )

    if migration_blockers and would_create_new_thread:
        risk_level = "medium"
        recommended_action = "finish_current_closure_before_migration"
    elif would_create_new_thread:
        risk_level = "high"
        recommended_action = "create_clean_continuation_thread"
    elif total >= 3 or context_score >= 2 or pollution_score + struggle_score >= 2:
        risk_level = "medium"
        recommended_action = "continue_current_thread"
    else:
        risk_level = "low"
        recommended_action = "continue_current_thread"

    return {
        "risk_level": risk_level,
        "score": total,
        "scores": {
            "context": context_score,
            "pollution": pollution_score,
            "struggle": struggle_score,
            "phase_transition": phase_transition_score,
        },
        "should_create_new_thread": risk_level == "high" and not migration_blockers,
        "recommended_action": recommended_action,
        "migration_kind": "clean_continuation" if risk_level == "high" else "",
        "migration_blockers": migration_blockers,
        "evidence": evidence,
        "handoff_first_files": list(HANDOFF_FIRST_FILES),
        "new_thread_prompt_suffix": NEW_THREAD_PROMPT_SUFFIX,
        "suggested_title": title_for_continuation(snapshot.title, snapshot.thread_id),
    }


def load_bridge_module() -> Any:
    sys.path.insert(0, str(DEFAULT_BRIDGE_DIR))
    import thread_bridge  # type: ignore[import-not-found]

    return thread_bridge


def load_snapshot(codex_home: Path, thread_id: str, max_events: int) -> ThreadSnapshot:
    bridge = load_bridge_module()
    if thread_id:
        record = bridge.get_thread(codex_home, thread_id)
    else:
        records = bridge.list_threads(codex_home, limit=1)
        if not records:
            raise RuntimeError("未找到 Codex 线程记录")
        record = records[0]

    messages = bridge.recent_rollout_messages(record.rollout_path, max_events=max_events)
    return ThreadSnapshot(
        thread_id=record.id,
        title=record.title,
        cwd=record.cwd,
        workspace_hint=record.workspace_hint,
        tokens_used=record.tokens_used,
        context_card_count=len(record.context_card_paths),
        rollout_path=str(record.rollout_path),
        messages=messages,
    )


def write_pack(codex_home: Path, thread_id: str, output: str, max_events: int) -> str:
    bridge = load_bridge_module()
    pack = bridge.build_context_pack(codex_home, thread_id, max_events=max_events)
    path = Path(output).expanduser()
    if str(path) == "-":
        fd, name = tempfile.mkstemp(prefix="codex-continuation-", suffix=".md")
        os.close(fd)
        path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pack, encoding="utf-8")
    return str(path)


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    codex_home = Path(args.codex_home).expanduser()
    snapshot = load_snapshot(codex_home, args.thread_id, args.max_events)
    result = score_snapshot(snapshot)
    result.update(
        {
            "thread_id": snapshot.thread_id,
            "title": snapshot.title,
            "cwd": snapshot.cwd,
            "workspace_hint": snapshot.workspace_hint,
            "tokens_used": snapshot.tokens_used,
            "context_card_count": snapshot.context_card_count,
            "rollout_path": snapshot.rollout_path,
        }
    )
    if args.pack_output:
        result["continuation_pack_path"] = write_pack(
            codex_home,
            snapshot.thread_id,
            args.pack_output,
            args.max_events,
        )
    return result


def scan_recent(codex_home: Path, limit: int, max_events: int) -> dict[str, Any]:
    bridge = load_bridge_module()
    threads = []
    for record in bridge.list_threads(codex_home, limit=limit):
        messages = bridge.recent_rollout_messages(record.rollout_path, max_events=max_events)
        snapshot = ThreadSnapshot(
            thread_id=record.id,
            title=record.title,
            cwd=record.cwd,
            workspace_hint=record.workspace_hint,
            tokens_used=record.tokens_used,
            context_card_count=len(record.context_card_paths),
            rollout_path=str(record.rollout_path),
            messages=messages,
        )
        score = score_snapshot(snapshot)
        threads.append(
            {
                "thread_id": record.id,
                "title": record.title,
                "cwd": record.cwd,
                "tokens_used": record.tokens_used,
                "context_card_count": len(record.context_card_paths),
                "risk_level": score["risk_level"],
                "recommended_action": score["recommended_action"],
                "should_create_new_thread": score["should_create_new_thread"],
                "scores": score["scores"],
                "evidence": score["evidence"],
                "migration_blockers": score["migration_blockers"],
                "suggested_title": score["suggested_title"],
            }
        )
    high_count = sum(1 for item in threads if item["risk_level"] == "high")
    return {"scan_limit": limit, "high_count": high_count, "threads": threads}


def format_markdown(result: dict[str, Any]) -> str:
    if "threads" in result:
        lines = [
            "# Codex 线程健康批量扫描",
            "",
            f"- 扫描数量: `{result.get('scan_limit', len(result['threads']))}`",
            f"- 高风险数量: `{result.get('high_count', 0)}`",
            "",
        ]
        for item in result["threads"]:
            evidence = "；".join(item.get("evidence") or ["无明显证据"])
            lines.append(
                f"- `{item['thread_id'][:8]}` {clean_inline(item['title'], 48)}: "
                f"{item['risk_level']} / {item['recommended_action']} / "
                f"tokens={item['tokens_used']} cards={item['context_card_count']} / {evidence}"
            )
        return "\n".join(lines)

    lines = [
        "# Codex 线程健康检查",
        "",
        f"- 风险等级: `{result['risk_level']}`",
        f"- 建议动作: `{result['recommended_action']}`",
        f"- 分数: `{result['score']}`",
        f"- 来源线程: `{result['thread_id']}`",
        f"- 建议新标题: `{result['suggested_title']}`",
        "",
        "## 证据",
        "",
    ]
    evidence = result.get("evidence") or []
    lines.extend(f"- {item}" for item in evidence)
    if not evidence:
        lines.append("- 未发现高风险证据。")
    blockers = result.get("migration_blockers") or []
    if blockers:
        lines.extend(["", "## 暂缓迁移原因", ""])
        lines.extend(f"- {item}" for item in blockers)
    first_files = result.get("handoff_first_files") or []
    if first_files and result.get("should_create_new_thread"):
        lines.extend(["", "## 新线程优先读取", ""])
        lines.extend(f"- {item}" for item in first_files)
    if result.get("continuation_pack_path"):
        lines.extend(["", f"- Continuation pack: `{result['continuation_pack_path']}`"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score Codex thread health.")
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--max-events", type=int, default=24)
    parser.add_argument("--pack-output", default="")
    parser.add_argument("--scan-recent", type=int, default=0)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.scan_recent:
            result = scan_recent(Path(args.codex_home).expanduser(), args.scan_recent, args.max_events)
        else:
            result = build_result(args)
    except Exception as exc:
        result = {
            "risk_level": "unknown",
            "score": 0,
            "scores": {"context": 0, "pollution": 0, "struggle": 0, "phase_transition": 0},
            "should_create_new_thread": False,
            "recommended_action": "health_check_failed",
            "migration_kind": "",
            "migration_blockers": [],
            "evidence": [clean_inline(str(exc), 500)],
        }
    if args.format == "markdown":
        print(format_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
