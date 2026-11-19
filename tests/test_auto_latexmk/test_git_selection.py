import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from auto_latexmk.cli import main, parse_args
from auto_latexmk.models import TaskType
from auto_latexmk.planning import create_task_plan


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Keep fixture repositories independent of user Git configuration.
        self.environment = patch.dict(os.environ, {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Tests")
        self.write("figures/tikz/main.tex", "\\documentclass{standalone}\n\\input{parts/first}\n")
        self.write("figures/tikz/parts/first.tex", "\\include{parts/second}\n")
        self.write("figures/tikz/parts/second.tex", "original\n")
        self.write("figures/tikz/main.pdf", "original PDF\n")
        self.commit()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True,
            capture_output=True,
        ).stdout

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "Fixture")

    def plan(self, path=None, *, task_type=TaskType.COMPILE,
             requested_engine="auto", use_gitignore=True, force=False):
        return create_task_plan(
            str(path or self.root), task_type=task_type,
            requested_engine=requested_engine, use_gitignore=use_gitignore,
            force=force, exclude_patterns=[], pref_cache=None,
        )

    def test_clean_tracked_pdf_and_recursive_dependencies_are_skipped(self):
        plan = self.plan()
        self.assertEqual(plan.tasks, ())
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("unchanged in Git", plan.skipped[0].reason)
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_worktree_and_staged_changes_trigger_compilation(self):
        for name in ("main.pdf", "main.tex", "parts/first.tex", "parts/second.tex"):
            for staged in (False, True):
                with self.subTest(name=name, staged=staged):
                    relative = "figures/tikz/" + name
                    path = self.root / relative
                    original = path.read_text(encoding="utf-8")
                    self.write(relative, original + "changed\n")
                    if staged:
                        self.git("add", relative)
                    self.assertEqual(len(self.plan().tasks), 1)
                    self.write(relative, original)
                    self.git("add", relative)

    def test_staged_change_with_worktree_restored_is_still_changed(self):
        relative = "figures/tikz/parts/second.tex"
        self.write(relative, "staged change\n")
        self.git("add", relative)
        self.write(relative, "original\n")
        self.assertEqual(len(self.plan().tasks), 1)

    def test_missing_pdf_compiles(self):
        (self.root / "figures/tikz/main.pdf").unlink()
        self.assertEqual(len(self.plan().tasks), 1)

    def test_untracked_or_ignored_pdf_compiles(self):
        self.git("rm", "--cached", "figures/tikz/main.pdf")
        with patch("auto_latexmk.git_selection.GitSelection._snapshot") as snapshot:
            self.assertEqual(len(self.plan().tasks), 1)
            self.write(".gitignore", "*.pdf\n")
            self.assertEqual(len(self.plan().tasks), 1)
        snapshot.assert_not_called()

    def test_tracked_pdf_remains_protected_even_with_ignore_pattern(self):
        self.write(".gitignore", "*.pdf\n")
        self.assertEqual(len(self.plan().skipped), 1)

    def test_untracked_or_missing_dependency_compiles(self):
        relative = "figures/tikz/parts/second.tex"
        self.git("rm", "--cached", relative)
        self.assertEqual(len(self.plan().tasks), 1)
        (self.root / relative).unlink()
        self.assertEqual(len(self.plan().tasks), 1)

    def test_unrelated_change_does_not_trigger_compilation(self):
        self.write("unrelated.tex", "fragment\n")
        self.assertEqual(len(self.plan().skipped), 1)

    def test_force_explicit_file_engine_clean_and_rebuild_bypass_check(self):
        cases = [
            (self.root, {"force": True}),
            (self.root / "figures/tikz/main.tex", {}),
            (self.root, {"requested_engine": "pdflatex"}),
            (self.root, {"task_type": TaskType.CLEAN}),
            (self.root, {"task_type": TaskType.REBUILD}),
        ]
        for path, options in cases:
            with self.subTest(options=options, path=path):
                plan = self.plan(path, **options)
                self.assertEqual(len(plan.tasks), 1)
                self.assertEqual(plan.skipped, ())

    def test_no_gitignore_does_not_disable_git_selection(self):
        self.assertEqual(len(self.plan(use_gitignore=False).skipped), 1)

    def test_unresolved_or_dynamic_dependencies_compile(self):
        for dependency in (
            "\\input{missing}", "\\input{\\partname}",
            "\\import{parts/}{first}", "\\input{../outside}",
        ):
            with self.subTest(dependency=dependency):
                self.write("figures/tikz/main.tex", "\\documentclass{article}\n" + dependency)
                self.commit()
                self.assertEqual(len(self.plan().tasks), 1)

    def test_comments_unbraced_input_unicode_spaces_and_cycles(self):
        self.write("figures/tikz/main.tex", (
            "\\documentclass{article}\n% \\input{missing}\n"
            "\\input parts/first\n\\input{含 空格}\n"
        ))
        self.write("figures/tikz/含 空格.tex", "\\input{parts/../main}\n")
        self.write("figures/tikz/main.pdf", "updated PDF\n")
        self.commit()
        self.assertEqual(len(self.plan().skipped), 1)
        self.write("figures/tikz/含 空格.tex", "changed\n")
        self.assertEqual(len(self.plan().tasks), 1)

    def test_local_styles_graphics_and_bibliography_changes_compile(self):
        self.write("figures/tikz/main.tex", (
            "\\documentclass{article}\n\\usepackage{local}\n"
            "\\includegraphics{plot}\n\\bibliography{refs}\n"
        ))
        for name in ("local.sty", "plot.pdf", "refs.bib"):
            self.write("figures/tikz/" + name, "original\n")
        self.write("figures/tikz/main.pdf", "updated PDF\n")
        self.commit()
        self.assertEqual(len(self.plan().skipped), 1)
        for name in ("local.sty", "plot.pdf", "refs.bib"):
            with self.subTest(name=name):
                self.write("figures/tikz/" + name, "changed\n")
                self.assertEqual(len(self.plan().tasks), 1)
                self.write("figures/tikz/" + name, "original\n")

    def test_git_failure_and_non_repository_compile(self):
        with patch("auto_latexmk.git_selection._git", side_effect=FileNotFoundError):
            self.assertEqual(len(self.plan().tasks), 1)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "main.tex").write_text("\\documentclass{article}")
            Path(directory, "main.pdf").write_text("PDF")
            self.assertEqual(len(self.plan(directory).tasks), 1)

    def test_committed_source_changes_compile_until_pdf_is_updated(self):
        for name in ("main.tex", "parts/first.tex", "parts/second.tex"):
            with self.subTest(name=name):
                relative = "figures/tikz/" + name
                path = self.root / relative
                self.write(relative, path.read_text(encoding="utf-8") + "changed\n")
                self.commit()
                self.assertEqual(self.git("status", "--porcelain"), b"")
                self.assertEqual(len(self.plan().tasks), 1)
                self.assertEqual(len(self.plan(force=True).tasks), 1)
                self.write("figures/tikz/main.pdf", "updated for " + name)
                self.commit()
                self.assertEqual(len(self.plan().skipped), 1)

    def test_committed_image_change_compiles(self):
        self.write("figures/tikz/main.tex", (
            "\\documentclass{article}\n\\includegraphics{plot}\n"
        ))
        self.write("figures/tikz/plot.pdf", "original image\n")
        self.write("figures/tikz/main.pdf", "updated PDF\n")
        self.commit()
        self.assertEqual(len(self.plan().skipped), 1)
        self.write("figures/tikz/plot.pdf", "changed image\n")
        self.commit()
        self.assertEqual(len(self.plan().tasks), 1)

    def test_unrelated_commit_does_not_trigger_compilation(self):
        self.write("unrelated.txt", "unrelated\n")
        self.commit()
        self.assertEqual(len(self.plan().skipped), 1)

    def test_commit_order_does_not_depend_on_timestamps(self):
        self.write("figures/tikz/parts/second.tex", "changed\n")
        with patch.dict(os.environ, {
            "GIT_AUTHOR_DATE": "2001-01-01T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2001-01-01T00:00:00+0000",
        }):
            self.commit()
        self.assertEqual(len(self.plan().tasks), 1)
        self.write("figures/tikz/main.pdf", "updated PDF\n")
        with patch.dict(os.environ, {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
        }):
            self.commit()
        self.assertEqual(len(self.plan().skipped), 1)

    def test_unrelated_branch_changes_are_not_ordered_by_merge(self):
        branch = self.git("branch", "--show-current").decode().strip()
        self.git("checkout", "-b", "source-change")
        self.write("figures/tikz/parts/second.tex", "changed on source branch\n")
        self.commit()
        self.git("checkout", branch)
        self.write("figures/tikz/main.pdf", "updated on PDF branch\n")
        self.commit()
        self.git("merge", "--no-edit", "source-change")
        self.assertEqual(len(self.plan().tasks), 1)

    def test_incomplete_history_compiles(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "shallow"
            self.git("clone", "--depth=1", self.root.as_uri(), str(destination))
            self.assertEqual(len(self.plan(destination).tasks), 1)

    def test_history_query_failure_compiles(self):
        with patch("auto_latexmk.git_selection.GitSelection._last_commit", return_value=""):
            self.assertEqual(len(self.plan().tasks), 1)
        with patch("auto_latexmk.git_selection.GitSelection._last_commit", side_effect=subprocess.TimeoutExpired("git", 10)):
            self.assertEqual(len(self.plan().tasks), 1)

    def test_deleted_local_package_is_not_treated_as_system_package(self):
        self.write("figures/tikz/main.tex", "\\documentclass{article}\n\\usepackage{local}\n")
        self.write("figures/tikz/local.sty", "local style\n")
        self.commit()
        (self.root / "figures/tikz/local.sty").unlink()
        self.assertEqual(len(self.plan().tasks), 1)
        self.git("add", "-u")
        self.assertEqual(len(self.plan().tasks), 1)

    def test_cli_reports_skips_without_running_latexmk(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                output = StringIO()
                args = [str(self.root), "--no-engine-cache", "--no-color"]
                if verbose:
                    args.append("--verbose")
                with redirect_stderr(output), patch("auto_latexmk.cli.run_tasks", return_value=[]) as run:
                    result = main(args)
                self.assertEqual(result, 0)
                self.assertEqual(run.call_args.args[0], ())
                self.assertEqual("SKIPPED" in output.getvalue(), verbose)
                self.assertIn("0 cancelled, 1 skipped", output.getvalue())
                self.assertNotIn("No LaTeX main documents", output.getvalue())
                if not verbose:
                    self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_force_option_reaches_planner(self):
        self.assertTrue(parse_args(["--force"]).force)
        with (
            patch("auto_latexmk.cli.create_task_plan", wraps=create_task_plan) as planner,
            patch("auto_latexmk.cli.run_tasks", return_value=[]),
            patch("auto_latexmk.planning.GitSelection") as selection,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(main([str(self.root), "--force", "--no-engine-cache"]), 0)
        self.assertTrue(planner.call_args.kwargs["force"])
        selection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
