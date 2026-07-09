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

POLLUTION_PATTERNS = (
    re.compile(r"不是这个|不对|搞错|错了|理解错|跑偏|偏了|重来|重新来"),
    re.compile(r"先别管前面|忘掉前面|不要按前面|前面.*不算|上下文.*乱|上下文.*污染|串了"),
)

STRUGGLE_PATTERNS = (
    re.compile(r"失败|报错|错误|验证失败|没通过|还是不行|反复|阻塞|超时"),
    re.compile(r"\b(error|failed|failure|traceback|exception|timeout|blocked)\b", re.I),
)

ABS_PATH_RE = re.compile(r"/(?:Users|home|tmp|var|opt|Volumes)/[^\s`'\"，。；；、)>\]]+")


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
    evidence: list[str] = []

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

    user_messages = [(role, text) for role, text in snapshot.messages if role == "用户"]
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

    struggle_count = count_matches(STRUGGLE_PATTERNS, snapshot.messages)
    if struggle_count >= 4:
        struggle_score += 4
        evidence.append(f"最近失败/报错/阻塞信号 {struggle_count} 次")
    elif struggle_count >= 2:
        struggle_score += 2
        evidence.append(f"最近失败/报错/阻塞信号 {struggle_count} 次")
    elif struggle_count == 1:
        struggle_score += 1
        evidence.append("最近出现失败、报错或阻塞信号")

    total = context_score + pollution_score + struggle_score
    has_context_pressure = context_score >= 3
    has_contamination_or_struggle = pollution_score + struggle_score >= 3

    if has_context_pressure and has_contamination_or_struggle and total >= 6:
        risk_level = "high"
        recommended_action = "create_new_thread"
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
        },
        "should_create_new_thread": risk_level == "high",
        "recommended_action": recommended_action,
        "evidence": evidence,
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


def format_markdown(result: dict[str, Any]) -> str:
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
    if result.get("continuation_pack_path"):
        lines.extend(["", f"- Continuation pack: `{result['continuation_pack_path']}`"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score Codex thread health.")
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--max-events", type=int, default=24)
    parser.add_argument("--pack-output", default="")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_result(args)
    except Exception as exc:
        result = {
            "risk_level": "unknown",
            "score": 0,
            "scores": {"context": 0, "pollution": 0, "struggle": 0},
            "should_create_new_thread": False,
            "recommended_action": "health_check_failed",
            "evidence": [clean_inline(str(exc), 500)],
        }
    if args.format == "markdown":
        print(format_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
