#!/usr/bin/env python3
"""Silently record explicit user corrections from new transcript records."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path


CORRECTION_SIGNALS = (
    "你理解错",
    "不是我说",
    "不是这个",
    "方向不对",
    "你发散",
    "你还是没有",
    "怎么还",
    "为什么没有",
    "反复",
    "搞了几天",
    "一直修改",
    "没能达成",
    "我怎么没看到",
    "我很生气",
    "不合理",
    "没有做到",
)
RETROSPECTIVE_SIGNALS = ("还是", "怎么", "为什么", "之前", "本来", "反而", "明明", "却", "已经", "几次", "一直")
NEGATIVE_SIGNALS = ("应该", "不能", "没有", "没", "不对", "错误", "遗漏", "漏掉", "偏离")
CATEGORY_SIGNALS = {
    "user_visibility_gap": ("没看到", "没有显示", "没有展示", "没有投递", "内部文档", "只在文档", "用户可见"),
    "incomplete_feedback_loop": ("没有继续", "没有跟踪", "没有监控", "没有闭环", "后续有没有", "一直记录", "持续"),
    "repeated_rework": ("反复", "还是没有", "搞了几天", "一直修改", "几次", "没能达成"),
    "requirement_misread": ("理解错", "不是我说", "不是这个", "方向不对", "我说的是"),
    "validation_mismatch": ("你说完成", "没有验证", "没有运行", "实际没有", "并没有完成"),
    "scope_drift": ("发散", "不是这个项目", "范围偏", "方向偏"),
}


def skill_dir() -> Path:
    return Path(
        os.environ.get(
            "CODEX_ERROR_LEARNING_SKILL_DIR",
            "~/.codex/skills/codex-error-learning-loop",
        )
    ).expanduser()


def load_ledger_module():
    path = skill_dir() / "scripts" / "error-learning-ledger.py"
    spec = importlib.util.spec_from_file_location("error_learning_ledger", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load error learning ledger")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(filter(None, (text_from_content(item) for item in content)))
    if isinstance(content, dict):
        for key in ("text", "message", "content", "input"):
            if key in content:
                value = text_from_content(content[key])
                if value:
                    return value
    return ""


def user_message(record):
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if record.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
        return text_from_content(payload.get("content"))
    if payload.get("type") == "user_message":
        return text_from_content(payload.get("message")) or text_from_content(payload.get("text_elements"))
    return ""


def clean(value: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def is_boilerplate(text: str) -> bool:
    lowered = text.lstrip().lower()
    return lowered.startswith(("# agents.md", "<environment_context>", "<skills_instructions>", "<permissions instructions>"))


def is_correction(text: str) -> bool:
    normalized = clean(text, 2000)
    if is_boilerplate(normalized):
        return False
    if any(signal in normalized for signal in CORRECTION_SIGNALS):
        return True
    return (
        "你" in normalized
        and any(signal in normalized for signal in RETROSPECTIVE_SIGNALS)
        and any(signal in normalized for signal in NEGATIVE_SIGNALS)
    )


def categories(text: str) -> list[str]:
    matched = [key for key, signals in CATEGORY_SIGNALS.items() if any(signal in text for signal in signals)]
    return matched or ["explicit_correction"]


def expected_from(text: str) -> str:
    matches = re.findall(r"(?:应该|希望|不能|需要|要)([^。！？]{4,180})", text)
    return clean("；".join(matches[:2]) if matches else text)


def state_path(thread_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", thread_id or "unknown")
    return Path(os.environ.get("CODEX_ERROR_LEARNING_DIR", "~/.codex/error-learning")).expanduser() / "hook-state" / f"{safe}.json"


def load_offset(path: Path) -> int:
    try:
        return max(0, int(json.loads(path.read_text(encoding="utf-8")).get("offset", 0)))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def save_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"offset": offset}, sort_keys=True) + "\n", encoding="utf-8")


def run(payload: dict) -> None:
    transcript = Path(payload.get("transcript_path") or "").expanduser()
    if not transcript.is_file():
        return
    thread_id = str(payload.get("session_id") or payload.get("thread_id") or "unknown")
    cursor_path = state_path(thread_id)
    offset = load_offset(cursor_path)
    size = transcript.stat().st_size
    if offset > size:
        offset = 0
    ledger = load_ledger_module()
    with transcript.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        lines = handle.readlines()
        next_offset = handle.tell()
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = clean(user_message(record), 1000)
        if not text or not is_correction(text):
            continue
        args = type(
            "Args",
            (),
            {
                "thread_id": thread_id,
                "thread_title": payload.get("thread_title") or "",
                "occurred_at": record.get("timestamp") or ledger.utc_now(),
                "project_name": Path(payload.get("cwd") or "").name,
                "project_path": payload.get("cwd") or "",
                "summary": clean(text),
                "expected": expected_from(text),
                "category": categories(text),
                "source": "explicit_user_correction",
            },
        )()
        ledger.record_observation(args)
    save_offset(cursor_path, next_offset)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            run(payload)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
