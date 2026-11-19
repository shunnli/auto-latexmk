"""Read-only Git checks for keeping committed PDF artifacts unchanged."""

import os
import subprocess
from pathlib import Path

from auto_latexmk.tex_dependencies import tex_dependencies


def _git(directory: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-optional-locks", "--literal-pathspecs", "-C", str(directory), *args],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout


def _paths(output: bytes) -> set[str]:
    return {os.fsdecode(path) for path in output.split(b"\0") if path}


class GitSelection:
    def __init__(self):
        self._roots: dict[Path, Path | None] = {}
        self._snapshots: dict[Path, tuple[set[str], set[str]] | None] = {}
        self._commits: dict[tuple[Path, str], str] = {}
        self._ancestry: dict[tuple[Path, str, str], bool] = {}

    def _snapshot(self, directory: Path):
        if directory not in self._roots:
            try:
                self._roots[directory] = Path(
                    os.fsdecode(_git(directory, "rev-parse", "--show-toplevel")).rstrip("\r\n")
                )
            except (OSError, subprocess.SubprocessError):
                self._roots[directory] = None
        root = self._roots[directory]
        if root is None:
            return None
        if root not in self._snapshots:
            try:
                if _git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
                    self._snapshots[root] = None
                    return None
                tracked = _paths(_git(root, "ls-files", "-z"))
                changed = set()
                for flags in ((), ("--cached",)):
                    changed.update(_paths(_git(
                        root, "diff", *flags, "--name-only", "-z", "--no-renames",
                        "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
                    )))
                self._snapshots[root] = (tracked, changed)
            except (OSError, subprocess.SubprocessError):
                self._snapshots[root] = None
        snapshot = self._snapshots[root]
        return (root, *snapshot) if snapshot is not None else None

    def _last_commit(self, root: Path, path: Path) -> str:
        relative = path.resolve().relative_to(root).as_posix()
        key = (root, relative)
        if key not in self._commits:
            self._commits[key] = _git(
                root, "log", "-1", "--format=%H", "HEAD", "--", relative,
            ).decode("ascii").strip()
        return self._commits[key]

    def _pdf_covers_dependencies(self, root: Path, pdf: Path, dependencies: set[Path]) -> bool:
        try:
            pdf_commit = self._last_commit(root, pdf)
            if not pdf_commit:
                return False
            for path in dependencies:
                commit = self._last_commit(root, path)
                if not commit:
                    return False
                if commit == pdf_commit:
                    continue
                key = (root, commit, pdf_commit)
                if key not in self._ancestry:
                    try:
                        _git(root, "merge-base", "--is-ancestor", commit, pdf_commit)
                        self._ancestry[key] = True
                    except subprocess.CalledProcessError:
                        self._ancestry[key] = False
                if not self._ancestry[key]:
                    return False
            return True
        except (OSError, ValueError, subprocess.SubprocessError):
            return False

    def skip_reason(self, tex_file: str) -> str | None:
        source = Path(tex_file)
        pdf = source.with_suffix(".pdf")
        if not pdf.is_file() or pdf.is_symlink():
            return None
        # Only tracked output artifacts are candidates for Git-based skipping.
        # Leave all other documents to latexmk without inspecting dependencies/history.
        try:
            _git(source.parent, "ls-files", "--error-unmatch", "--", pdf.name)
        except (OSError, subprocess.SubprocessError):
            return None
        snapshot = self._snapshot(source.parent)
        if snapshot is None:
            return None
        root, tracked, changed = snapshot
        try:
            root = root.resolve()
        except OSError:
            return None

        def clean(path: Path) -> bool:
            try:
                relative = path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                return False
            return relative in tracked and relative not in changed

        # Changes or uncertainty always leave the document selected for compilation.
        if not clean(pdf):
            return None
        dependencies = tex_dependencies(
            tex_file, known_files={root / path for path in tracked | changed},
        )
        if dependencies is None or not all(clean(path) for path in dependencies):
            return None
        if not self._pdf_covers_dependencies(root, pdf, dependencies):
            return None
        return "PDF and dependencies are unchanged in Git; PDF commit covers dependency commits"
