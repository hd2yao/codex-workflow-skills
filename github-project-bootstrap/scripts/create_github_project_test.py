import io
import tempfile
import unittest
from pathlib import Path

import create_github_project as subject


class CreateGitHubProjectTest(unittest.TestCase):
    def test_slugify_repo_name_uses_kebab_case(self):
        self.assertEqual(
            subject.slugify_repo_name("AI Contract Review Tool"),
            "ai-contract-review-tool",
        )
        self.assertEqual(
            subject.slugify_repo_name("  GitHub Repo_Bootstrap!! "),
            "github-repo-bootstrap",
        )

        with self.assertRaisesRegex(ValueError, "empty repository name"):
            subject.slugify_repo_name("!!!")

    def test_build_plan_targets_owner_repo_and_project_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = subject.build_plan(
                repo_name="invoice-tracker",
                description="Track invoice status and payment reminders",
                parent_dir=Path(tmp),
                visibility="private",
                owner="alice",
                create_readme=True,
                use_existing_dir=False,
                commit_existing_files=False,
                allow_large_files=False,
                max_file_mb=20,
            )

            self.assertEqual(plan.repo_name, "invoice-tracker")
            self.assertEqual(plan.full_repo_name, "alice/invoice-tracker")
            self.assertEqual(plan.project_dir, Path(tmp).resolve() / "invoice-tracker")
            self.assertEqual(plan.readme_title, "invoice-tracker")
            self.assertFalse(plan.commit_existing_files)
            self.assertEqual(plan.max_file_mb, 20)

    def test_dry_run_prints_commands_without_creating_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            rc = subject.main(
                [
                    "--description",
                    "Track invoice status and payment reminders",
                    "--repo-name",
                    "invoice-tracker",
                    "--owner",
                    "alice",
                    "--parent-dir",
                    tmp,
                    "--dry-run",
                ],
                stdout=stdout,
            )

            self.assertEqual(rc, 0)
            self.assertFalse((Path(tmp) / "invoice-tracker").exists())
            output = stdout.getvalue()
            self.assertIn("DRY RUN", output)
            self.assertIn("gh repo create alice/invoice-tracker --private", output)
            self.assertIn("git push -u origin main", output)
            self.assertIn(str(Path(tmp).resolve() / "invoice-tracker"), output)

    def test_existing_directory_requires_explicit_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "invoice-tracker").mkdir()

            with self.assertRaisesRegex(FileExistsError, "--use-existing-dir"):
                subject.build_plan(
                    repo_name="invoice-tracker",
                    description="Track invoice status and payment reminders",
                    parent_dir=Path(tmp),
                    visibility="private",
                    owner=None,
                    create_readme=True,
                    use_existing_dir=False,
                    commit_existing_files=False,
                    allow_large_files=False,
                    max_file_mb=20,
                )

    def test_repo_lookup_uses_authenticated_owner_when_owner_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = subject.build_plan(
                repo_name="invoice-tracker",
                description="Track invoice status and payment reminders",
                parent_dir=Path(tmp),
                visibility="private",
                owner=None,
                create_readme=True,
                use_existing_dir=False,
                commit_existing_files=False,
                allow_large_files=False,
                max_file_mb=20,
            )

            self.assertEqual(
                subject.repo_lookup_name(plan, authenticated_owner="alice"),
                "alice/invoice-tracker",
            )

    def test_existing_project_full_commit_mode_requires_explicit_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "invoice-tracker").mkdir()

            plan = subject.build_plan(
                repo_name="invoice-tracker",
                description="Track invoice status and payment reminders",
                parent_dir=Path(tmp),
                visibility="private",
                owner=None,
                create_readme=True,
                use_existing_dir=True,
                commit_existing_files=True,
                allow_large_files=False,
                max_file_mb=20,
            )

            self.assertTrue(plan.use_existing_dir)
            self.assertTrue(plan.commit_existing_files)

    def test_ensure_default_gitignore_preserves_existing_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            gitignore = project_dir / ".gitignore"
            gitignore.write_text("custom-output/\n", encoding="utf-8")

            changed = subject.ensure_default_gitignore(project_dir)

            self.assertTrue(changed)
            content = gitignore.read_text(encoding="utf-8")
            self.assertIn("custom-output/", content)
            self.assertIn(".env", content)
            self.assertIn("*.pem", content)
            self.assertIn("*.wav", content)

    def test_dry_run_existing_project_full_commit_prints_safety_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "invoice-tracker").mkdir()
            stdout = io.StringIO()

            rc = subject.main(
                [
                    "--description",
                    "Track invoice status and payment reminders",
                    "--repo-name",
                    "invoice-tracker",
                    "--parent-dir",
                    tmp,
                    "--use-existing-dir",
                    "--commit-existing-files",
                    "--dry-run",
                ],
                stdout=stdout,
            )

            self.assertEqual(rc, 0)
            output = stdout.getvalue()
            self.assertIn("ensure default .gitignore safety rules", output)
            self.assertIn("git add -A", output)
            self.assertIn("check staged files <= 20 MB", output)


if __name__ == "__main__":
    unittest.main()
