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
DEFAULT_IGNORE_PATH = DEFAULT_OUTPUT_DIR / "ignore.json"
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
    "in_progress": "有未提交改动",
    "awaiting_integration": "待集成",
    "pr_pending": "PR 待处理",
    "legacy": "历史遗留",
    "merged_cleanup": "已合并待清理",
}


def load_ignore_rules(path=DEFAULT_IGNORE_PATH):
    """读取持久忽略规则；文件缺失或格式损坏时按空规则处理。"""
    target = Path(path).expanduser()
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    repositories = data.get("repositories", []) if isinstance(data, dict) else []
    return [item for item in repositories if isinstance(item, dict) and item.get("path")]


def ignored_worktree(path, rules):
    """返回匹配的忽略规则；默认只匹配仓库根路径。"""
    try:
        candidate = Path(path).expanduser().resolve()
    except OSError:
        candidate = Path(path).expanduser()
    for rule in rules:
        try:
            ignored = Path(rule["path"]).expanduser().resolve()
        except OSError:
            ignored = Path(rule["path"]).expanduser()
        if candidate == ignored:
            return rule
        if rule.get("include_worktrees"):
            try:
                candidate.relative_to(ignored)
                return rule
            except ValueError:
                pass
    return None


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


def _tree_equivalent(worktree, base, branch):
    if not base:
        return False
    return _git(worktree, "diff", "--quiet", base, branch, check=False).returncode == 0


def _patch_equivalent(worktree, base, branch):
    if not base:
        return False
    result = _git(worktree, "cherry", base, branch, check=False)
    if result.returncode:
        return False
    return not any(line.startswith("+") for line in result.stdout.splitlines())


def _branch_rows(worktree, base_ref):
    result = _git(
        worktree,
        "for-each-ref",
        "--format=%(refname:short)|%(committerdate:iso8601-strict)|%(upstream:short)",
        "refs/heads",
        check=False,
    )
    rows = []
    normalized_base = (base_ref or "").removeprefix("origin/")
    for line in result.stdout.splitlines():
        if not line:
            continue
        branch, committed_at, upstream = (line.split("|", 2) + ["", ""])[:3]
        ahead, behind = _ahead_behind(worktree, base_ref, branch)
        upstream_ahead, upstream_behind = _ahead_behind(worktree, upstream, branch)
        merged = branch == normalized_base
        tree_equivalent = False
        patch_equivalent = False
        if base_ref and branch != normalized_base:
            ancestor_merged = (
                _git(worktree, "merge-base", "--is-ancestor", branch, base_ref, check=False).returncode
                == 0
            )
            tree_equivalent = _tree_equivalent(worktree, base_ref, branch)
            patch_equivalent = _patch_equivalent(worktree, base_ref, branch)
            merged = ancestor_merged or tree_equivalent or patch_equivalent
        rows.append(
            {
                "name": branch,
                "committed_at": committed_at or None,
                "ahead_count": ahead,
                "behind_count": behind,
                "default_ahead_count": ahead,
                "default_behind_count": behind,
                "upstream": upstream or None,
                "upstream_ahead_count": upstream_ahead,
                "upstream_behind_count": upstream_behind,
                "remote_present": bool(upstream),
                "merged": merged,
                "tree_equivalent": tree_equivalent,
                "patch_equivalent": patch_equivalent,
            }
        )
    return rows


def _working_tree_updated_at(worktree, status_lines):
    paths = []
    for line in status_lines:
        raw = line[3:].strip() if len(line) > 3 else ""
        if " -> " in raw:
            raw = raw.rsplit(" -> ", 1)[-1]
        raw = raw.strip('"')
        if raw:
            paths.append(Path(worktree) / raw)
    timestamps = []
    for path in paths:
        try:
            timestamps.append(path.stat().st_mtime)
        except OSError:
            continue
    if not timestamps:
        return None
    return dt.datetime.fromtimestamp(max(timestamps)).astimezone().isoformat(timespec="seconds")


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
    default_ahead_count, default_behind_count = _ahead_behind(worktree, base_ref)
    upstream_ahead_count, upstream_behind_count = _ahead_behind(worktree, upstream)
    head_ancestor_merged = bool(
        base_ref
        and _git(worktree, "merge-base", "--is-ancestor", "HEAD", base_ref, check=False).returncode == 0
    )
    head_tree_equivalent = _tree_equivalent(worktree, base_ref, "HEAD")
    head_patch_equivalent = _patch_equivalent(worktree, base_ref, "HEAD")
    remote_url = _git(worktree, "remote", "get-url", "origin", check=False).stdout.strip()
    pull_requests = []
    if gh_client is not None:
        try:
            pull_requests = gh_client(worktree) or []
        except Exception as exc:  # 审计失败不得阻塞主流程
            warnings.append(f"{worktree}: GitHub PR 元数据读取失败：{exc}")

    head_committed_at = _git(
        worktree,
        "log",
        "-1",
        "--format=%cI",
        check=False,
    ).stdout.strip() or None

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
        "default_comparison_ref": base_ref,
        "default_ahead_count": default_ahead_count,
        "default_behind_count": default_behind_count,
        "upstream_comparison_ref": upstream,
        "upstream_ahead_count": upstream_ahead_count,
        "upstream_behind_count": upstream_behind_count,
        "ahead_count": default_ahead_count,
        "behind_count": default_behind_count,
        "head_merged": head_ancestor_merged or head_tree_equivalent or head_patch_equivalent,
        "head_tree_equivalent": head_tree_equivalent,
        "head_patch_equivalent": head_patch_equivalent,
        "remote_url": _sanitize_remote_url(remote_url),
        "github_repo": _github_slug(remote_url),
        "local_branches": _branch_rows(worktree, base_ref),
        "pull_requests": pull_requests,
        "warnings": warnings,
        "inspected_on": (today or dt.date.today()).isoformat(),
        "head_committed_at": head_committed_at,
        "working_tree_updated_at": _working_tree_updated_at(worktree, status_lines),
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


def _age_days(value, today):
    updated = _parse_date(value)
    if updated is None:
        return None
    return max(0, (today - updated).days)


def _decision_metadata(finding, today, recent_days):
    last_activity_at = (
        finding.get("last_activity_at")
        or finding.get("working_tree_updated_at")
        or finding.get("updated_at")
    )
    age_days = _age_days(last_activity_at, today)
    stale = age_days is not None and age_days > recent_days
    category = finding.get("category")
    stage = finding.get("workflow_stage")
    if not stage:
        stage = {
            "in_progress": "uncommitted_changes",
            "awaiting_integration": "committed_not_merged",
            "pr_pending": "pr_not_merged",
            "legacy": "stale_branch",
            "merged_cleanup": "merged_cleanup",
        }.get(category, "repository_review")
    if category == "merged_cleanup":
        disposition = "auto_cleanup"
        next_action = "分支已进入默认分支，按仓库级动作预算清理 worktree 和旧分支。"
    elif stale or category == "legacy":
        disposition = "auto_finish"
        next_action = (
            f"最近活动已超过 {recent_days} 天，优先交给对应任务完成测试、推送、合并和清理；"
            "遇到冲突或测试失败时记录准确失败步骤。"
        )
    else:
        disposition = "active_deferred"
        next_action = "近期仍有活动，保留当前分支；对应任务完成后自动推送、合并并清理。"
    finding.update(
        {
            "workflow_stage": stage,
            "last_activity_at": last_activity_at,
            "age_days": age_days,
            "stale": stale,
            "disposition": disposition,
            "next_action": finding.get("next_action") or next_action,
        }
    )
    return finding


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
            if repo.get("head_merged"):
                detached_category = "merged_cleanup"
                detached_reason = "detached HEAD 已包含于默认分支，可清理该 worktree"
            elif repo.get("default_ahead_count", 0) > 0:
                detached_category = "awaiting_integration"
                detached_reason = "detached HEAD 含默认分支尚未包含的提交，应先创建救援分支并推送"
            else:
                detached_category = "in_progress"
                detached_reason = "worktree 处于 detached HEAD，且无法证明已安全收尾"
            findings[finding_id] = {
                "id": finding_id,
                "category": detached_category,
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
                "reason": detached_reason,
                "suggested_action": "cleanup_worktree" if detached_category == "merged_cleanup" else "create_rescue_branch_and_push",
                "updated_at": repo.get("inspected_on"),
            }

        if repo.get("dirty"):
            finding_id = _stable_id("dirty", common_dir, current_branch, repo["worktree"])
            tracked = repo.get("tracked_change_count", 0)
            untracked = repo.get("untracked_count", 0)
            branch_label = current_branch or "detached HEAD"
            change_parts = []
            if tracked:
                change_parts.append(f"{tracked} 个已跟踪改动")
            if untracked:
                change_parts.append(f"{untracked} 个未跟踪文件")
            findings[finding_id] = {
                "id": finding_id,
                "category": "in_progress",
                "original_category": None,
                "repository": repo.get("github_repo") or Path(repo["top_level"]).name,
                "worktree": repo["worktree"],
                "branch": current_branch,
                "detached": repo.get("detached", False),
                "tracked_change_count": tracked,
                "untracked_count": untracked,
                "ahead_count": repo.get("ahead_count", 0),
                "behind_count": repo.get("behind_count", 0),
                "default_comparison_ref": repo.get("default_comparison_ref"),
                "default_ahead_count": repo.get("default_ahead_count", 0),
                "default_behind_count": repo.get("default_behind_count", 0),
                "upstream_comparison_ref": repo.get("upstream_comparison_ref"),
                "upstream_ahead_count": repo.get("upstream_ahead_count", 0),
                "upstream_behind_count": repo.get("upstream_behind_count", 0),
                "pr": prs_by_branch.get(current_branch),
                "reason": f"当前分支 {branch_label} 有 {'、'.join(change_parts) or '未提交改动'}，尚未进入提交与合并阶段。",
                "suggested_action": "resolve_dirty_worktree",
                "workflow_stage": "uncommitted_changes",
                "working_tree_updated_at": repo.get("working_tree_updated_at"),
                "last_activity_at": repo.get("working_tree_updated_at") or repo.get("head_committed_at"),
                "updated_at": repo.get("working_tree_updated_at") or repo.get("head_committed_at"),
            }

        for branch_row in repo.get("local_branches", []):
            branch = branch_row["name"]
            if branch_row.get("merged"):
                if branch == (repo.get("base_ref") or "").removeprefix("origin/"):
                    continue
                if branch == current_branch and repo.get("dirty"):
                    continue
                category = "merged_cleanup"
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
                "default_comparison_ref": repo.get("default_comparison_ref"),
                "default_ahead_count": branch_row.get("default_ahead_count", 0),
                "default_behind_count": branch_row.get("default_behind_count", 0),
                "upstream_comparison_ref": branch_row.get("upstream"),
                "upstream_ahead_count": branch_row.get("upstream_ahead_count", 0),
                "upstream_behind_count": branch_row.get("upstream_behind_count", 0),
                "remote_present": branch_row.get("remote_present", False),
                "tree_equivalent": branch_row.get("tree_equivalent", False),
                "patch_equivalent": branch_row.get("patch_equivalent", False),
                "pr": prs_by_branch.get(branch),
                "reason": {
                    "awaiting_integration": "分支含有尚未进入默认分支的提交",
                    "pr_pending": "分支已有开放 PR，尚未完成合并",
                    "legacy": f"分支最近活动超过 {recent_days} 天，且仍有提交未进入默认分支",
                    "merged_cleanup": "分支已进入默认分支，但 worktree 尚未清理",
                }[category],
                "suggested_action": {
                    "awaiting_integration": "push_or_open_pr",
                    "pr_pending": "finish_pr",
                    "legacy": "preserve_remote_then_review",
                    "merged_cleanup": "cleanup_worktree_and_branches",
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
        (_decision_metadata(item, today, recent_days) for item in findings.values()),
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
        "schema_version": 2,
        "generated_at": dt.datetime.now().astimezone().replace(
            year=today.year,
            month=today.month,
            day=today.day,
        ).isoformat(timespec="seconds"),
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
        f"- 有未提交改动：{counts['in_progress']}",
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
                "| ID | 分类 | 仓库 | 分支 | 改动 | 默认分支 ahead/behind | upstream ahead/behind | 说明 |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for item in report["findings"]:
            changes = item["tracked_change_count"] + item["untracked_count"]
            lines.append(
                "| {id} | {category} | {repo} | {branch} | {changes} | {ahead}/{behind} | {upstream_ahead}/{upstream_behind} | {reason} |".format(
                    id=item["id"],
                    category=CATEGORY_LABELS[item["category"]],
                    repo=item["repository"],
                    branch=item.get("branch") or "(detached)",
                    changes=changes,
                    ahead=item["ahead_count"],
                    behind=item["behind_count"],
                    upstream_ahead=item.get("upstream_ahead_count", 0),
                    upstream_behind=item.get("upstream_behind_count", 0),
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
    parser.add_argument("--refresh-remotes", action="store_true", help="扫描前对 origin 执行 fetch --prune。")
    parser.add_argument("--recent-days", type=int, default=15, help="超过该天数的发现优先自动收尾。")
    parser.add_argument(
        "--ignore-file",
        type=Path,
        default=None,
        help="持久忽略的仓库列表。",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-write", action="store_true", help="只输出，不更新 latest 报告。")
    args = parser.parse_args(argv)

    roots = args.roots
    if not roots:
        configured = os.environ.get("CODEX_REPOSITORY_SCAN_ROOTS")
        roots = configured.split(os.pathsep) if configured else [str(DEFAULT_ROOT)]
    discovered = discover_git_worktrees(roots)
    ignore_rules = load_ignore_rules(args.ignore_file or args.output_dir / "ignore.json")
    gh_client = cached_github_client() if args.include_github else None
    inspected = []
    warnings = []
    refreshed_common_dirs = set()
    for worktree in discovered:
        if ignored_worktree(worktree, ignore_rules):
            continue
        try:
            common_dir = _resolve_git_path(
                worktree,
                _git(worktree, "rev-parse", "--git-common-dir").stdout.strip(),
            )
            if args.refresh_remotes and common_dir not in refreshed_common_dirs:
                refreshed_common_dirs.add(common_dir)
                refresh = _git(worktree, "fetch", "--prune", "origin", check=False)
                if refresh.returncode:
                    detail = refresh.stderr.strip() or refresh.stdout.strip() or "fetch --prune 失败"
                    warnings.append(f"{worktree}: 远端刷新失败：{detail}")
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
