#!/usr/bin/env python3
"""SessionStart hook that nudges Codex to run thread migration when risk is high."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


GUARD_SCRIPT = Path(
    os.environ.get(
        "CODEX_THREAD_HEALTH_GUARD_SCRIPT",
        "/Users/dysania/.codex/skills/codex-thread-health-guard/scripts/thread-health-guard.py",
    )
)


def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_guard_module() -> Any:
    spec = importlib.util.spec_from_file_location("thread_health_guard", GUARD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载线程健康守卫: {GUARD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["thread_health_guard"] = module
    spec.loader.exec_module(module)
    return module


def argv_from_hook_input(hook_input: dict[str, Any]) -> list[str]:
    argv = ["--format", "json"]
    thread_id = str(
        hook_input.get("session_id")
        or hook_input.get("thread_id")
        or hook_input.get("conversation_id")
        or ""
    )
    if thread_id:
        argv.extend(["--thread-id", thread_id])
    return argv


def success_payload(message: str, *, suppress: bool = False) -> dict[str, Any]:
    return {"continue": True, "suppressOutput": suppress, "systemMessage": message}


def error_payload(message: str) -> dict[str, Any]:
    return {
        "continue": True,
        "suppressOutput": True,
        "systemMessage": f"线程健康守卫检查失败: {message}",
    }


def build_message(result: dict[str, Any]) -> str:
    evidence = result.get("evidence") or []
    evidence_text = "\n".join(f"- {item}" for item in evidence[:5])
    if not evidence_text:
        evidence_text = "- 未记录证据"
    return "\n".join(
        [
            "线程健康守卫判定当前线程为高风险，继续执行前必须先处理迁移判断。",
            "",
            f"- 来源线程: `{result.get('thread_id', 'unknown')}`",
            f"- 当前标题: {result.get('title', 'unknown')}",
            f"- 建议新标题: `{result.get('suggested_title', 'unknown')}`",
            f"- 建议动作: `{result.get('recommended_action', 'unknown')}`",
            "",
            "证据:",
            evidence_text,
            "",
            "执行要求:",
            "- 如果当前没有正在运行的命令、未闭环验证或关键编辑，请用 `create_thread` 创建干净新线程继续。",
            "- 新线程 prompt 使用 continuation pack，并要求先读 `docs/HANDOFF.md`、`README.md`、当前 git status/diff、测试脚本和最近 commit。",
            "- 如果存在当前必须先收敛的工作，先完成收敛，再重新运行线程健康守卫。",
        ]
    )


def main() -> int:
    try:
        hook_input = read_hook_input()
        guard = load_guard_module()
        args = guard.build_parser().parse_args(argv_from_hook_input(hook_input))
        result = guard.build_result(args)
        if result.get("risk_level") != "high" or not result.get("should_create_new_thread"):
            print(json.dumps(success_payload("", suppress=True), ensure_ascii=False))
            return 0
        print(json.dumps(success_payload(build_message(result)), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(error_payload(str(exc)), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
