#!/usr/bin/env python3
"""只读扫描本地 Git worktree、未收尾分支与 GitHub PR。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


DEFAULT_ROOT = Path("/Users/dysania/program")
DEFAULT_OUTPUT_DIR = Path.home() / ".codex" / "task-ledger" / "repository-closure"
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    "vendor",
}
CATEGORY_LABELS = {
    "in_progress": "进行中 / 证据不足",
    "awaiting_integration": "待集成",
    "pr_pending": "PR 待处理",
    "legacy": "历史遗留",
    "merged_cleanup": "已合并待清理",
}


def _run(args, *, cwd=None, timeout=20, check=True):
    result = subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(message)
    return result


def _git(path, *args, check=True):
    return _run(["git", "-C", str(path), *args], check=check)


def _resolve_git_path(worktree, raw):
    path = Path(raw)
    if not path.is_absolute():
        path = Path(worktree) / path
    return path.resolve()


def _registered_worktrees(repo):
    result = _git(repo, "worktree", "list", "--porcelain", check=False)
    if result.returncode:
        return []
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.removeprefix("worktree ")).expanduser().resolve())
    return paths


def discover_git_worktrees(roots):
    """发现 roots 下 Git checkout，并补入其登记在外部的 worktree。"""
    discovered = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.exists():
            continue
        if (root / ".git").exists():
            discovered.add(root.resolve())
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
            if ".git" in filenames or (Path(current) / ".git").is_dir():
                discovered.add(Path(current).resolve())

    pending = list(discovered)
    while pending:
        repo = pending.pop()
        for worktree in _registered_worktrees(repo):
            if worktree.exists() and worktree not in discovered:
                discovered.add(worktree)
                pending.append(worktree)
    return sorted(discovered, key=lambda path: str(path).lower())


def _sanitize_remote_url(url):
    if not url:
        return None
    if "://" not in url:
        return url
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    if parts.port:
        hostname = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, hostname, parts.path, parts.query, parts.fragment))


def _github_slug(remote_url):
    if not remote_url:
        return None
    patterns = (
        r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$",
        r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, remote_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


def github_pull_requests(repo):
    remote = _git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    slug = _github_slug(remote)
    if not slug:
        return []
    fields = ",".join(
        [
            "number",
            "headRefName",
            "baseRefName",
            "isDraft",
            "mergeStateStatus",
            "reviewDecision",
            "statusCheckRollup",
            "url",
            "updatedAt",
        ]
    )
    result = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            slug,
            "--state",
            "open",
            "--author",
            "@me",
            "--limit",
            "100",
            "--json",
            fields,
        ],
        timeout=30,
    )
    return json.loads(result.stdout)


def cached_github_client(delegate=github_pull_requests):
    """同一 Git common dir 的多个 worktree 只读取一次 GitHub。"""
    cache = {}

    def fetch(repo):
        remote = _git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
        key = _github_slug(remote)
        if not key:
            common_raw = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
            key = str(_resolve_git_path(repo, common_raw))
        if key not in cache:
            try:
                cache[key] = (True, delegate(repo))
            except Exception as exc:
                cache[key] = (False, str(exc))
        succeeded, value = cache[key]
        if not succeeded:
            raise RuntimeError(value)
        return value

    return fetch


def _default_base_ref(worktree):
    symbolic = _git(
        worktree,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        check=False,
    ).stdout.strip()
    candidates = [symbolic, "origin/main", "main", "origin/master", "master"]
    for candidate in candidates:
        if not candidate:
            continue
        if _git(worktree, "rev-parse", "--verify", "--quiet", candidate, check=False).returncode == 0:
            return candidate
    return None


def _ahead_behind(worktree, base, branch="HEAD"):
    if not base:
        return 0, 0
    result = _git(
        worktree,
        "rev-list",
        "--left-right",
        "--count",
        f"{base}...{branch}",
        check=False,
    )
    if result.returncode:
        return 0, 0
    fields = result.stdout.split()
    if len(fields) != 2:
        return 0, 0
    return int(fields[1]), int(fields[0])


def _branch_rows(worktree, base_ref):
    result = _git(
        worktree,
        "for-each-ref",
        "--format=%(refname:short)|%(committerdate:iso8601-strict)",
        "refs/heads",
        check=False,
    )
    rows = []
    normalized_base = (base_ref or "").removeprefix("origin/")
    for line in result.stdout.splitlines():
        if not line:
            continue
        branch, _, committed_at = line.partition("|")
        ahead, behind = _ahead_behind(worktree, base_ref, branch)
        merged = branch == normalized_base
        if base_ref and branch != normalized_base:
            merged = (
                _git(
                    worktree,
                    "merge-base",
                    "--is-ancestor",
                    branch,
                    base_ref,
                    check=False,
                ).returncode
                == 0
            )
        rows.append(
            {
                "name": branch,
                "committed_at": committed_at or None,
                "ahead_count": ahead,
                "behind_count": behind,
                "merged": merged,
            }
        )
    return rows


def inspect_worktree(path, *, gh_client=None, today=None):
    """读取一个 worktree 的 Git/PR 元数据，不读取工作文件内容。"""
    worktree = Path(path).expanduser().resolve()
    top_level = Path(_git(worktree, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    common_dir = _resolve_git_path(
        worktree,
        _git(worktree, "rev-parse", "--git-common-dir").stdout.strip(),
    )
    branch = _git(worktree, "branch", "--show-current", check=False).stdout.strip() or None
    status_lines = _git(
        worktree,
        "status",
        "--porcelain=v1",
        "--untracked-files=normal",
        check=False,
    ).stdout.splitlines()
    untracked_count = sum(line.startswith("??") for line in status_lines)
    tracked_change_count = len(status_lines) - untracked_count
    warnings = []
    upstream = _git(
        worktree,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    ).stdout.strip() or None
    base_ref = _default_base_ref(worktree)
    if not base_ref:
        warnings.append(f"{worktree}: 无法确定默认分支基准，仅报告可直接确认的状态")
    comparison_ref = upstream or base_ref
    ahead_count, behind_count = _ahead_behind(worktree, comparison_ref)
    remote_url = _git(worktree, "remote", "get-url", "origin", check=False).stdout.strip()
    pull_requests = []
    if gh_client is not None:
        try:
            pull_requests = gh_client(worktree) or []
        except Exception as exc:  # 审计失败不得阻塞主流程
            warnings.append(f"{worktree}: GitHub PR 元数据读取失败：{exc}")

    return {
        "worktree": str(worktree),
        "top_level": str(top_level),
        "common_dir": str(common_dir),
        "branch": branch,
        "detached": branch is None,
        "dirty": bool(status_lines),
        "tracked_change_count": tracked_change_count,
        "untracked_count": untracked_count,
        "upstream": upstream,
        "base_ref": base_ref,
        "ahead_count": ahead_count,
        "behind_count": behind_count,
        "remote_url": _sanitize_remote_url(remote_url),
        "github_repo": _github_slug(remote_url),
        "local_branches": _branch_rows(worktree, base_ref),
        "pull_requests": pull_requests,
        "warnings": warnings,
        "inspected_on": (today or dt.date.today()).isoformat(),
    }


def _parse_date(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _stable_id(kind, common_dir, branch, worktree=None):
    raw = "|".join(str(item or "") for item in (kind, common_dir, branch, worktree))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10].upper()
    return f"RC-{digest}"


def _is_legacy(last_updated, today, recent_days):
    updated = _parse_date(last_updated)
    return bool(updated and (today - updated).days > recent_days)


def _finding_category(category, updated_at, today, recent_days):
    if category != "merged_cleanup" and _is_legacy(updated_at, today, recent_days):
        return "legacy", category
    return category, None


def classify_findings(worktrees, *, recent_days=30, today=None):
    """把 inspect_worktree 结果分类并去重。"""
    today = today or dt.date.today()
    inspected = [
        item if isinstance(item, dict) else inspect_worktree(item, today=today)
        for item in worktrees
    ]
    findings = {}
    warnings = []

    for repo in inspected:
        warnings.extend(repo.get("warnings", []))
        common_dir = repo["common_dir"]
        current_branch = repo.get("branch")
        prs_by_branch = {
            pr.get("headRefName"): pr
            for pr in repo.get("pull_requests", [])
            if pr.get("headRefName")
        }

        if repo.get("detached") and not repo.get("dirty"):
            finding_id = _stable_id("detached", common_dir, None, repo["worktree"])
            findings[finding_id] = {
                "id": finding_id,
                "category": "in_progress",
                "original_category": None,
                "repository": repo.get("github_repo") or Path(repo["top_level"]).name,
                "worktree": repo["worktree"],
                "branch": None,
                "detached": True,
                "tracked_change_count": 0,
                "untracked_count": 0,
                "ahead_count": repo.get("ahead_count", 0),
                "behind_count": repo.get("behind_count", 0),
                "pr": None,
                "reason": "worktree 处于 detached HEAD，无法证明任务已安全收尾",
                "updated_at": repo.get("inspected_on"),
            }

        if repo.get("dirty"):
            finding_id = _stable_id("dirty", common_dir, current_branch, repo["worktree"])
            findings[finding_id] = {
                "id": finding_id,
                "category": "in_progress",
                "original_category": None,
                "repository": repo.get("github_repo") or Path(repo["top_level"]).name,
                "worktree": repo["worktree"],
                "branch": current_branch,
                "detached": repo.get("detached", False),
                "tracked_change_count": repo.get("tracked_change_count", 0),
                "untracked_count": repo.get("untracked_count", 0),
                "ahead_count": repo.get("ahead_count", 0),
                "behind_count": repo.get("behind_count", 0),
                "pr": prs_by_branch.get(current_branch),
                "reason": "工作区存在尚未提交的改动，任务完成证据不足",
                "updated_at": repo.get("inspected_on"),
            }

        for branch_row in repo.get("local_branches", []):
            branch = branch_row["name"]
            if branch_row.get("merged"):
                if branch == current_branch and branch != (repo.get("base_ref") or "").removeprefix("origin/"):
                    category = "merged_cleanup"
                else:
                    continue
            elif branch_row.get("ahead_count", 0) <= 0:
                continue
            else:
                category = "pr_pending" if branch in prs_by_branch else "awaiting_integration"
            category, original_category = _finding_category(
                category,
                branch_row.get("committed_at"),
                today,
                recent_days,
            )
            finding_id = _stable_id("branch", common_dir, branch)
            candidate = {
                "id": finding_id,
                "category": category,
                "original_category": original_category,
                "repository": repo.get("github_repo") or Path(repo["top_level"]).name,
                "worktree": repo["worktree"],
                "branch": branch,
                "detached": False,
                "tracked_change_count": repo.get("tracked_change_count", 0)
                if branch == current_branch
                else 0,
                "untracked_count": repo.get("untracked_count", 0)
                if branch == current_branch
                else 0,
                "ahead_count": branch_row.get("ahead_count", 0),
                "behind_count": branch_row.get("behind_count", 0),
                "pr": prs_by_branch.get(branch),
                "reason": {
                    "awaiting_integration": "分支含有尚未进入默认分支的提交",
                    "pr_pending": "分支已有开放 PR，尚未完成合并",
                    "legacy": "分支或 PR 超过近期窗口，需人工确认是否仍有效",
                    "merged_cleanup": "分支已进入默认分支，但 worktree 尚未清理",
                }[category],
                "updated_at": branch_row.get("committed_at"),
            }
            existing = findings.get(finding_id)
            if existing is None or branch == current_branch:
                findings[finding_id] = candidate

        local_branch_names = {row["name"] for row in repo.get("local_branches", [])}
        for pr in repo.get("pull_requests", []):
            branch = pr.get("headRefName")
            if not branch or branch in local_branch_names:
                continue
            category, original_category = _finding_category(
                "pr_pending",
                pr.get("updatedAt"),
                today,
                recent_days,
            )
            finding_id = _stable_id("pr", common_dir, branch)
            findings[finding_id] = {
                "id": finding_id,
                "category": category,
                "original_category": original_category,
                "repository": repo.get("github_repo") or Path(repo["top_level"]).name,
                "worktree": repo["worktree"],
                "branch": branch,
                "detached": False,
                "tracked_change_count": 0,
                "untracked_count": 0,
                "ahead_count": 0,
                "behind_count": 0,
                "pr": pr,
                "reason": "GitHub 上仍有开放 PR，本地未发现同名分支",
                "updated_at": pr.get("updatedAt"),
            }

    ordered = sorted(
        findings.values(),
        key=lambda item: (
            list(CATEGORY_LABELS).index(item["category"]),
            item["repository"].lower(),
            item.get("branch") or "",
            item["id"],
        ),
    )
    counts = {category: 0 for category in CATEGORY_LABELS}
    for finding in ordered:
        counts[finding["category"]] += 1
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_on": today.isoformat(),
        "repository_count": len(inspected),
        "finding_count": len(ordered),
        "counts": counts,
        "findings": ordered,
        "warnings": sorted(set(warnings)),
    }


def render_markdown(report):
    counts = report["counts"]
    lines = [
        "# 仓库收尾审计",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 扫描 checkout：{report['repository_count']}",
        f"- 发现项：{report['finding_count']}",
        f"- 进行中 / 证据不足：{counts['in_progress']}",
        f"- 待集成：{counts['awaiting_integration']}",
        f"- PR 待处理：{counts['pr_pending']}",
        f"- 历史遗留：{counts['legacy']}",
        f"- 已合并待清理：{counts['merged_cleanup']}",
        "",
    ]
    if report["findings"]:
        lines.extend(
            [
                "## 明细",
                "",
                "| ID | 分类 | 仓库 | 分支 | 改动 | ahead/behind | 说明 |",
                "| --- | --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for item in report["findings"]:
            changes = item["tracked_change_count"] + item["untracked_count"]
            lines.append(
                "| {id} | {category} | {repo} | {branch} | {changes} | {ahead}/{behind} | {reason} |".format(
                    id=item["id"],
                    category=CATEGORY_LABELS[item["category"]],
                    repo=item["repository"],
                    branch=item.get("branch") or "(detached)",
                    changes=changes,
                    ahead=item["ahead_count"],
                    behind=item["behind_count"],
                    reason=item["reason"],
                )
            )
        lines.append("")
    else:
        lines.extend(["当前扫描范围内未发现待收尾 Git/PR 项。", ""])
    if report["warnings"]:
        lines.extend(["## 扫描警告", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
        lines.append("")
    return "\n".join(lines)


def _write_report(report, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    markdown_path = output_dir / "latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="要扫描的项目根目录；可重复。默认使用 CODEX_REPOSITORY_SCAN_ROOTS 或 /Users/dysania/program。",
    )
    parser.add_argument("--include-github", action="store_true", help="通过 gh 读取开放 PR 元数据。")
    parser.add_argument("--recent-days", type=int, default=30, help="超过该天数的发现归为历史遗留。")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-write", action="store_true", help="只输出，不更新 latest 报告。")
    args = parser.parse_args(argv)

    roots = args.roots
    if not roots:
        configured = os.environ.get("CODEX_REPOSITORY_SCAN_ROOTS")
        roots = configured.split(os.pathsep) if configured else [str(DEFAULT_ROOT)]
    discovered = discover_git_worktrees(roots)
    gh_client = cached_github_client() if args.include_github else None
    inspected = []
    warnings = []
    for worktree in discovered:
        try:
            inspected.append(inspect_worktree(worktree, gh_client=gh_client))
        except Exception as exc:  # 单仓库失败不阻塞整份日报
            warnings.append(f"{worktree}: Git 扫描失败：{exc}")
    report = classify_findings(inspected, recent_days=args.recent_days)
    report["warnings"] = sorted(set(report["warnings"] + warnings))
    if not args.no_write:
        _write_report(report, args.output_dir.expanduser())
    if args.format == "markdown":
        sys.stdout.write(render_markdown(report))
    else:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
