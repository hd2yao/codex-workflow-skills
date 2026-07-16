import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "repository-closure-audit.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("repository_closure_audit", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Codex Test")
    git(path, "config", "user.email", "codex-test@example.invalid")
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-m", "initial")


class RepositoryClosureAuditTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_discovers_repo_and_registered_external_worktree(self):
        repo = self.root / "projects" / "demo"
        external = self.root / "outside" / "demo-feature"
        init_repo(repo)
        git(repo, "branch", "feature/test")
        git(repo, "worktree", "add", str(external), "feature/test")

        discovered = self.module.discover_git_worktrees([self.root / "projects"])

        self.assertEqual({repo.resolve(), external.resolve()}, set(discovered))

    def test_classifies_dirty_worktree_and_never_exposes_file_contents(self):
        repo = self.root / "dirty"
        init_repo(repo)
        secret_canary = "CANARY_SECRET_VALUE"
        (repo / "tracked.txt").write_text(f"changed {secret_canary}\n", encoding="utf-8")
        (repo / ".env").write_text(f"TOKEN={secret_canary}\n", encoding="utf-8")

        inspected = self.module.inspect_worktree(repo, today=date(2026, 7, 14))
        report = self.module.classify_findings([inspected], today=date(2026, 7, 14))
        encoded = json.dumps(report, ensure_ascii=False)

        self.assertEqual(1, report["counts"]["in_progress"])
        self.assertEqual(1, report["findings"][0]["tracked_change_count"])
        self.assertEqual(1, report["findings"][0]["untracked_count"])
        self.assertNotIn(secret_canary, encoded)
        self.assertNotIn("TOKEN=", encoded)

    def test_dirty_finding_explains_stage_and_recent_disposition_without_evidence_boilerplate(self):
        repo = self.root / "dirty-stage"
        init_repo(repo)
        (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")

        inspected = self.module.inspect_worktree(repo, today=date.today())
        report = self.module.classify_findings([inspected], recent_days=15, today=date.today())
        finding = report["findings"][0]

        self.assertEqual("uncommitted_changes", finding["workflow_stage"])
        self.assertEqual("active_deferred", finding["disposition"])
        self.assertIn("1 个已跟踪改动", finding["reason"])
        self.assertIn("当前分支 main", finding["reason"])
        self.assertNotIn("证据不足", finding["reason"])

    def test_dirty_finding_older_than_15_days_is_prioritized_for_auto_finish(self):
        repo = self.root / "stale-dirty"
        init_repo(repo)
        (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        inspected = self.module.inspect_worktree(repo, today=date.today())
        inspected["head_committed_at"] = "2026-06-01T10:00:00+08:00"
        inspected["working_tree_updated_at"] = "2026-06-01T11:00:00+08:00"

        report = self.module.classify_findings(
            [inspected],
            recent_days=15,
            today=date(2026, 7, 16),
        )
        finding = report["findings"][0]

        self.assertEqual(45, finding["age_days"])
        self.assertTrue(finding["stale"])
        self.assertEqual("auto_finish", finding["disposition"])
        self.assertIn("超过 15 天", finding["next_action"])

    def test_ignore_rules_skip_foreign_repository_by_path(self):
        repo = self.root / "backend-cms-api"
        init_repo(repo)
        ignore_path = self.root / "ignore.json"
        ignore_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "repositories": [
                        {"path": str(repo), "reason": "非本人项目，不参与自动收尾"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        rules = self.module.load_ignore_rules(ignore_path)
        ignored = self.module.ignored_worktree(repo, rules)

        self.assertTrue(ignored)
        self.assertEqual("非本人项目，不参与自动收尾", ignored["reason"])

    def test_clean_unmerged_branch_without_pr_is_awaiting_integration(self):
        repo = self.root / "ahead"
        init_repo(repo)
        git(repo, "switch", "-c", "feature/ready")
        (repo / "tracked.txt").write_text("ready\n", encoding="utf-8")
        git(repo, "commit", "-am", "ready")

        inspected = self.module.inspect_worktree(repo, today=date(2026, 7, 14))
        report = self.module.classify_findings([inspected], today=date(2026, 7, 14))

        finding = report["findings"][0]
        self.assertEqual("awaiting_integration", finding["category"])
        self.assertEqual("feature/ready", finding["branch"])
        self.assertEqual(1, finding["ahead_count"])
        self.assertRegex(finding["id"], r"^RC-[0-9A-F]{10}$")
        self.assertEqual(
            finding["id"],
            self.module.classify_findings(
                [self.module.inspect_worktree(repo, today=date(2026, 7, 14))],
                today=date(2026, 7, 14),
            )["findings"][0]["id"],
        )

    def test_inspection_separates_default_and_upstream_comparisons(self):
        origin = self.root / "origin.git"
        git(self.root, "init", "--bare", str(origin))
        repo = self.root / "comparison"
        init_repo(repo)
        git(repo, "remote", "add", "origin", str(origin))
        git(repo, "push", "-u", "origin", "main")
        git(repo, "remote", "set-head", "origin", "main")
        git(repo, "switch", "-c", "feature/compare")
        (repo / "tracked.txt").write_text("feature one\n", encoding="utf-8")
        git(repo, "commit", "-am", "feature one")
        git(repo, "push", "-u", "origin", "feature/compare")
        (repo / "tracked.txt").write_text("feature two\n", encoding="utf-8")
        git(repo, "commit", "-am", "feature two")

        inspected = self.module.inspect_worktree(repo, today=date(2026, 7, 14))

        self.assertEqual(2, inspected["default_ahead_count"])
        self.assertEqual(0, inspected["default_behind_count"])
        self.assertEqual(1, inspected["upstream_ahead_count"])
        self.assertEqual(0, inspected["upstream_behind_count"])
        self.assertEqual("origin/main", inspected["default_comparison_ref"])
        self.assertEqual("origin/feature/compare", inspected["upstream_comparison_ref"])

    def test_clean_detached_worktree_already_in_default_is_cleanup(self):
        repo = self.root / "detached"
        init_repo(repo)
        git(repo, "switch", "--detach")

        inspected = self.module.inspect_worktree(repo, today=date(2026, 7, 14))
        report = self.module.classify_findings([inspected], today=date(2026, 7, 14))

        self.assertEqual(1, report["counts"]["merged_cleanup"])
        self.assertTrue(report["findings"][0]["detached"])
        self.assertIn("可清理", report["findings"][0]["reason"])

    def test_unknown_default_branch_produces_warning(self):
        repo = self.root / "unknown-default"
        repo.mkdir()
        git(repo, "init", "-b", "trunk")
        git(repo, "config", "user.name", "Codex Test")
        git(repo, "config", "user.email", "codex-test@example.invalid")
        repo.joinpath("tracked.txt").write_text("initial\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-m", "initial")

        inspected = self.module.inspect_worktree(repo, today=date(2026, 7, 14))

        self.assertTrue(any("默认分支" in warning for warning in inspected["warnings"]))

    def test_matching_open_pr_changes_category_to_pr_pending(self):
        repo = self.root / "pr"
        init_repo(repo)
        git(repo, "switch", "-c", "feature/pr")
        (repo / "tracked.txt").write_text("pr\n", encoding="utf-8")
        git(repo, "commit", "-am", "pr")

        def fake_gh(_repo):
            return [
                {
                    "number": 12,
                    "headRefName": "feature/pr",
                    "isDraft": False,
                    "mergeStateStatus": "CLEAN",
                    "reviewDecision": "APPROVED",
                    "url": "https://example.invalid/pull/12",
                    "updatedAt": "2026-07-14T00:00:00Z",
                }
            ]

        inspected = self.module.inspect_worktree(
            repo,
            gh_client=fake_gh,
            today=date(2026, 7, 14),
        )
        report = self.module.classify_findings([inspected], today=date(2026, 7, 14))

        finding = report["findings"][0]
        self.assertEqual("pr_pending", finding["category"])
        self.assertEqual(12, finding["pr"]["number"])

    def test_github_failure_becomes_warning_and_does_not_abort(self):
        repo = self.root / "warning"
        init_repo(repo)

        def failing_gh(_repo):
            raise RuntimeError("gh unavailable")

        inspected = self.module.inspect_worktree(
            repo,
            gh_client=failing_gh,
            today=date(2026, 7, 14),
        )

        self.assertEqual([], inspected["pull_requests"])
        self.assertIn("gh unavailable", inspected["warnings"][0])

    def test_github_query_only_reads_current_users_pull_requests(self):
        repo = self.root / "github-author"
        init_repo(repo)
        captured = {}

        def fake_run(args, **_kwargs):
            captured["args"] = args
            return SimpleNamespace(stdout="[]")

        with mock.patch.object(
            self.module,
            "_git",
            return_value=SimpleNamespace(stdout="git@github.com:example/demo.git"),
        ), mock.patch.object(self.module, "_run", side_effect=fake_run):
            self.module.github_pull_requests(repo)

        self.assertIn("--author", captured["args"])
        self.assertEqual("@me", captured["args"][captured["args"].index("--author") + 1])

    def test_github_client_is_cached_across_worktrees_of_same_repository(self):
        repo = self.root / "cached"
        external = self.root / "cached-feature"
        init_repo(repo)
        git(repo, "branch", "feature/cache")
        git(repo, "worktree", "add", str(external), "feature/cache")
        calls = []

        def delegate(path):
            calls.append(Path(path))
            return [{"number": 1}]

        cached = self.module.cached_github_client(delegate)

        self.assertEqual([{"number": 1}], cached(repo))
        self.assertEqual([{"number": 1}], cached(external))
        self.assertEqual(1, len(calls))

    def test_markdown_lists_counts_and_report_timestamp(self):
        repo = self.root / "markdown"
        init_repo(repo)
        (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        report = self.module.classify_findings(
            [self.module.inspect_worktree(repo, today=date(2026, 7, 14))],
            today=date(2026, 7, 14),
        )

        rendered = self.module.render_markdown(report)

        self.assertIn("仓库收尾审计", rendered)
        self.assertIn("有未提交改动：1", rendered)
        self.assertNotIn("证据不足", rendered)
        self.assertIn("2026-07-14", rendered)


if __name__ == "__main__":
    unittest.main()
