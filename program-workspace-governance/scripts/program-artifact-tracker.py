#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


ABS_PATH_PATTERN = re.compile(r"(?P<path>/(?:Users|tmp|var|private|Volumes)/[^\s`'\"，。；;:]+)")
REL_PATH_PATTERN = re.compile(r"(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)")
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


def today():
    return dt.date.today().isoformat()


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def governance_dir():
    return Path(os.environ.get("CODEX_PROGRAM_GOVERNANCE_DIR", "~/.codex/program-governance")).expanduser()


def read_hook_input():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def response(message, **extra):
    payload = {"continue": True, "systemMessage": redact_text(message)}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def load_transcript(path):
    if not path:
        return []
    transcript = Path(path).expanduser()
    if not transcript.exists():
        return []
    records = []
    with transcript.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[-160:]


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


def normalize_candidate(raw_path, cwd):
    text = redact_text(raw_path).rstrip(").,，。]")
    path = Path(text)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    return str(path)


def extract_candidate_paths(records, cwd):
    candidates = []
    seen = set()
    for record in records:
        for text in text_from_record(record):
            cleaned = redact_text(text)
            for pattern in (ABS_PATH_PATTERN, REL_PATH_PATTERN):
                for match in pattern.finditer(cleaned):
                    if pattern is REL_PATH_PATTERN and match.start() > 0 and cleaned[match.start() - 1] == "/":
                        continue
                    candidate = normalize_candidate(match.group("path"), cwd)
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    candidates.append(
                        {
                            "path": candidate,
                            "exists": Path(candidate).exists(),
                            "suggested_action": "curator_plan",
                        }
                    )
    return candidates


def manifest_paths(base_dir, session_id):
    date_dir = base_dir / "artifacts" / today()
    date_dir.mkdir(parents=True, exist_ok=True)
    safe_session = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id or "unknown-session").strip("-")
    return date_dir / f"{safe_session}.json", date_dir / f"{safe_session}.md"


def render_markdown(manifest):
    lines = [
        f"# Program 产物记录 {manifest['date']}",
        "",
        f"- session：`{manifest['session_id']}`",
        f"- cwd：`{manifest['cwd']}`",
        f"- 候选数：{manifest['candidate_count']}",
        "",
        "## 候选产物",
    ]
    if not manifest["candidates"]:
        lines.append("- 暂无")
    else:
        for item in manifest["candidates"]:
            exists = "exists" if item["exists"] else "missing"
            lines.append(f"- `{item['path']}` ({exists})")
    return "\n".join(lines) + "\n"


def write_manifest(hook_input):
    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")
    records = load_transcript(hook_input.get("transcript_path", ""))
    candidates = extract_candidate_paths(records, cwd)
    manifest = {
        "version": 1,
        "date": today(),
        "generated_at": now_iso(),
        "session_id": redact_text(session_id),
        "cwd": redact_text(cwd),
        "transcript_path": redact_text(hook_input.get("transcript_path", "")),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    json_path, markdown_path = manifest_paths(governance_dir(), session_id)
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(manifest), encoding="utf-8")
    return json_path, markdown_path, manifest


def run(hook_input):
    json_path, markdown_path, manifest = write_manifest(hook_input)
    response(
        f"Program 产物记录：已记录 {manifest['candidate_count']} 个候选产物。",
        manifest_path=str(json_path),
        markdown_path=str(markdown_path),
        candidate_count=manifest["candidate_count"],
    )


def main():
    try:
        run(read_hook_input())
    except Exception as error:
        response(f"Program 产物记录失败，但不阻塞主流程。{error}", candidate_count=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
