#!/usr/bin/env python3
"""Persist lightweight correction observations and weekly learning candidates."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


DEFAULT_ROOT = Path.home() / ".codex" / "error-learning"
CANDIDATE_STATUSES = {
    "observed",
    "clustered",
    "monitoring",
    "trial",
    "adopted",
    "rejected",
    "verified",
}
TERMINAL_STATUSES = {"rejected", "verified"}
SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|cookie)\s*[:=]\s*\S{8,}"),
)
CATEGORY_DETAILS = {
    "user_visibility_gap": (
        "内部产物缺少用户可见交付",
        "完成标准停留在内部产物生成，没有验证投递、消费和反馈状态。",
    ),
    "incomplete_feedback_loop": (
        "后续跟踪与闭环缺失",
        "系统记录了候选或阶段结果，但没有持续状态、恢复动作和完成验证。",
    ),
    "repeated_rework": (
        "同一目标反复返工",
        "前置需求、验收标准或数据源没有锁定，局部修补持续替代端到端收敛。",
    ),
    "requirement_misread": (
        "需求或示例被误读",
        "实现把用户举例或局部表达当成完整目标，没有先还原真实结果和边界。",
    ),
    "validation_mismatch": (
        "验证结论与真实结果不一致",
        "完成声明没有绑定能证明用户目标的最新端到端证据。",
    ),
    "scope_drift": (
        "范围或项目方向偏离",
        "执行阶段缺少项目、范围或意图锁，旧上下文推动了无关工作。",
    ),
    "explicit_correction": (
        "明确纠正待进一步分类",
        "用户明确纠正了结果或方向，但当前证据不足以稳定归入更具体根因。",
    ),
}


def root_dir() -> Path:
    return Path(os.environ.get("CODEX_ERROR_LEARNING_DIR", DEFAULT_ROOT)).expanduser()


def observations_path() -> Path:
    return root_dir() / "observations.json"


def candidates_path() -> Path:
    return root_dir() / "candidates.json"


def redact(value: str) -> str:
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(value: str, limit: int = 320) -> str:
    text = redact(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def load_json(path: Path, key: str) -> dict:
    if not path.exists():
        return {"version": 1, key: {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, key: {}}
    if not isinstance(data.get(key), dict):
        data[key] = {}
    data["version"] = 1
    return data


@contextlib.contextmanager
def locked_root():
    root = root_dir()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def parse_moment(value: str) -> dt.datetime:
    normalized = value.replace("Z", "+00:00")
    moment = dt.datetime.fromisoformat(normalized)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def observation_id(thread_id: str, occurred_at: str, summary: str) -> str:
    normalized = "|".join((thread_id.strip(), occurred_at.strip(), compact(summary).casefold()))
    return "obs_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def record_observation(args) -> dict:
    occurred = parse_moment(args.occurred_at).isoformat(timespec="seconds")
    summary = compact(args.summary)
    item_id = observation_id(args.thread_id, occurred, summary)
    now = utc_now()
    with locked_root():
        data = load_json(observations_path(), "observations")
        existing = data["observations"].get(item_id, {})
        item = {
            "id": item_id,
            "thread_id": compact(args.thread_id, 96),
            "thread_title": compact(args.thread_title or "", 180),
            "project_name": compact(args.project_name or "", 160),
            "project_path": compact(args.project_path or "", 320),
            "occurred_at": occurred,
            "date": parse_moment(occurred).astimezone().date().isoformat(),
            "summary": summary,
            "expected": compact(args.expected or "", 320),
            "categories": sorted(set(args.category or ["explicit_correction"])),
            "status": "observed",
            "source": compact(args.source or "explicit_user_correction", 80),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        data["observations"][item_id] = item
        atomic_write(observations_path(), data)
    return {"observation": item}


def list_observations(args) -> dict:
    data = load_json(observations_path(), "observations")
    start = dt.date.fromisoformat(args.from_date) if args.from_date else None
    end = dt.date.fromisoformat(args.to_date) if args.to_date else None
    items = []
    for item in data["observations"].values():
        try:
            day = dt.date.fromisoformat(item["date"])
        except (KeyError, ValueError):
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        items.append(item)
    items.sort(key=lambda item: (item.get("occurred_at", ""), item.get("id", "")))
    return {"observations": items}


def previous_week(today: dt.date) -> tuple[dt.date, dt.date]:
    current_start = today - dt.timedelta(days=today.weekday())
    end = current_start - dt.timedelta(days=1)
    return end - dt.timedelta(days=6), end


def candidate_from_group(key: str, observations: list[dict], period: tuple[dt.date, dt.date], existing: dict) -> dict:
    start, end = period
    period_key = f"{start.isoformat()}_to_{end.isoformat()}"
    title, root_cause = CATEGORY_DETAILS.get(key, CATEGORY_DETAILS["explicit_correction"])
    weekly_threads = sorted({item["thread_id"] for item in observations if item.get("thread_id")})
    all_threads = sorted(set(existing.get("thread_ids", [])) | set(weekly_threads))
    periods = list(existing.get("periods", []))
    if period_key not in periods:
        periods.append(period_key)
    status = existing.get("status", "observed")
    if status not in TERMINAL_STATUSES and len(weekly_threads) >= 2 and status == "observed":
        status = "monitoring"
    now = utc_now()
    return {
        "key": key,
        "title": existing.get("title") or title,
        "root_cause": existing.get("root_cause") or root_cause,
        "status": status,
        "first_seen_at": existing.get("first_seen_at") or observations[0]["occurred_at"],
        "last_seen_at": observations[-1]["occurred_at"],
        "thread_ids": all_threads,
        "independent_thread_count": len(weekly_threads),
        "total_independent_thread_count": len(all_threads),
        "observation_count": len(observations),
        "periods": periods,
        "weeks_seen": len(periods),
        "existing_capabilities": existing.get("existing_capabilities", []),
        "next_action": existing.get("next_action") or "继续观察独立线程是否复发；达到门槛后补回归场景并进入治理评审。",
        "next_check_at": existing.get("next_check_at") or (end + dt.timedelta(days=8)).isoformat(),
        "regression_scenario": existing.get("regression_scenario", ""),
        "governance_approved": bool(existing.get("governance_approved")),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }


def synthesize_week(args) -> dict:
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    period = previous_week(today)
    start, end = period
    observations = list_observations(
        argparse.Namespace(from_date=start.isoformat(), to_date=end.isoformat())
    )["observations"]
    grouped: dict[str, list[dict]] = {}
    for item in observations:
        for category in item.get("categories") or ["explicit_correction"]:
            grouped.setdefault(category, []).append(item)
    with locked_root():
        state = load_json(candidates_path(), "candidates")
        weekly = []
        for key, items in sorted(grouped.items()):
            items.sort(key=lambda item: item.get("occurred_at", ""))
            candidate = candidate_from_group(key, items, period, state["candidates"].get(key, {}))
            state["candidates"][key] = candidate
            weekly.append(candidate)
        atomic_write(candidates_path(), state)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "observation_count": len(observations),
        "candidates": weekly,
    }


def update_candidate(args) -> dict:
    if args.status not in CANDIDATE_STATUSES:
        raise ValueError(f"unknown candidate status: {args.status}")
    with locked_root():
        state = load_json(candidates_path(), "candidates")
        if args.key not in state["candidates"]:
            raise ValueError(f"candidate not found: {args.key}")
        item = state["candidates"][args.key]
        regression = args.regression_scenario or item.get("regression_scenario", "")
        governance = bool(args.governance_approved or item.get("governance_approved"))
        if args.status == "trial":
            if item.get("total_independent_thread_count", 0) < 2:
                raise ValueError("trial requires at least two independent threads")
            if not regression:
                raise ValueError("trial requires a regression scenario")
            if not governance:
                raise ValueError("trial requires governance approval")
        item.update(
            {
                "status": args.status,
                "title": compact(args.title) if args.title else item.get("title", ""),
                "root_cause": compact(args.root_cause) if args.root_cause else item.get("root_cause", ""),
                "existing_capabilities": sorted(
                    set(item.get("existing_capabilities", []))
                    | {compact(value, 120) for value in (args.existing_capability or []) if value}
                ),
                "regression_scenario": compact(regression),
                "governance_approved": governance,
                "next_action": compact(args.next_action) if args.next_action else item.get("next_action", ""),
                "next_check_at": args.next_check_at or item.get("next_check_at", ""),
                "updated_at": utc_now(),
            }
        )
        state["candidates"][args.key] = item
        atomic_write(candidates_path(), state)
    return {"candidate": item}


def list_candidates(_args) -> dict:
    state = load_json(candidates_path(), "candidates")
    items = sorted(state["candidates"].values(), key=lambda item: (item.get("status", ""), item.get("key", "")))
    return {"candidates": items}


def add_format(parser):
    parser.add_argument("--format", choices=("json", "text"), default="text")


def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record-observation")
    record.add_argument("--thread-id", required=True)
    record.add_argument("--thread-title")
    record.add_argument("--occurred-at", required=True)
    record.add_argument("--project-name")
    record.add_argument("--project-path")
    record.add_argument("--summary", required=True)
    record.add_argument("--expected")
    record.add_argument("--category", action="append")
    record.add_argument("--source")
    add_format(record)
    record.set_defaults(func=record_observation)

    listed = sub.add_parser("list-observations")
    listed.add_argument("--from-date")
    listed.add_argument("--to-date")
    add_format(listed)
    listed.set_defaults(func=list_observations)

    weekly = sub.add_parser("synthesize-week")
    weekly.add_argument("--today")
    add_format(weekly)
    weekly.set_defaults(func=synthesize_week)

    update = sub.add_parser("update-candidate")
    update.add_argument("--key", required=True)
    update.add_argument("--status", required=True)
    update.add_argument("--title")
    update.add_argument("--root-cause")
    update.add_argument("--existing-capability", action="append")
    update.add_argument("--regression-scenario")
    update.add_argument("--governance-approved", action="store_true")
    update.add_argument("--next-action")
    update.add_argument("--next-check-at")
    add_format(update)
    update.set_defaults(func=update_candidate)

    candidates = sub.add_parser("list-candidates")
    add_format(candidates)
    candidates.set_defaults(func=list_candidates)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
