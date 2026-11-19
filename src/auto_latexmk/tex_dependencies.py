"""Conservative discovery of literal TeX dependencies; no TeX execution."""

import re
from pathlib import Path


def strip_latex_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


_COMMAND = re.compile(
    r"\\(input|include|includegraphics|bibliography|addbibresource|"
    r"documentclass|usepackage|RequirePackage|LoadClass)\b"
)
_ARGUMENT = re.compile(r"\s*(?:\[[^\]]*\]\s*)?\{([^{}]*)\}")
_UNBRACED = re.compile(r"\s+([^\s{}%]+)")
_UNSUPPORTED = re.compile(
    r"\\(?:import|subimport|subfile|subfileinclude|inputfrom|subinputfrom|includefrom|subincludefrom|"
    r"InputIfFileExists|IfFileExists|includeonly|graphicspath|DeclareGraphicsExtensions|"
    r"VerbatimInput|lstinputlisting|pgfplotstableread|catcode|csname)\b|"
    r"\\(?:def|let)\s*\\input@path"
)


def tex_dependencies(tex_file: str, *, known_files: set[Path]) -> set[Path] | None:
    """Return literal inputs, or None when dependency resolution is uncertain.

    Like ordinary TeX input, relative names resolve from the main file's cwd,
    not from the directory containing each included fragment.
    """
    main = Path(tex_file)
    root = main.parent
    dependencies: set[Path] = set()

    def visit(source: Path) -> bool:
        if not source.is_file() or source.is_symlink():
            return False
        source = source.resolve()
        if source in dependencies:
            return True
        dependencies.add(source)
        try:
            content = "\n".join(
                strip_latex_comment(line)
                for line in source.read_text(encoding="utf-8").splitlines()
            )
        except (OSError, UnicodeError):
            return False
        if _UNSUPPORTED.search(content):
            return False
        for match in _COMMAND.finditer(content):
            command = match[1]
            offset = match.end()
            if command == "includegraphics" and content[offset:offset + 1] == "*":
                offset += 1
            argument = _ARGUMENT.match(content, offset)
            if argument is None and command == "input":
                argument = _UNBRACED.match(content, offset)
            if argument is None:
                return False
            names = argument[1].strip()
            if not names or any(char in names for char in "\\#{}$~^"):
                return False
            for name in names.split(","):
                candidate = root / name.strip()
                if command in {"documentclass", "LoadClass", "usepackage", "RequirePackage"}:
                    suffix = ".cls" if command in {"documentclass", "LoadClass"} else ".sty"
                    candidate = candidate.with_suffix(suffix)
                    # Standard TeX-distribution classes/packages are not project inputs.
                    if not candidate.exists():
                        if candidate.resolve() in known_files or "/" in name or "\\" in name:
                            return False
                        continue
                elif command == "includegraphics":
                    if not candidate.suffix:
                        matches = [
                            candidate.with_suffix(suffix)
                            for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".eps")
                            if candidate.with_suffix(suffix).is_file()
                        ]
                        if len(matches) != 1:
                            return False
                        candidate = matches[0]
                elif not candidate.suffix:
                    suffix = ".bib" if command in {"bibliography", "addbibresource"} else ".tex"
                    candidate = candidate.with_suffix(suffix)
                if command in {"includegraphics", "bibliography", "addbibresource"}:
                    if not candidate.is_file() or candidate.is_symlink():
                        return False
                    dependencies.add(candidate)
                elif not visit(candidate):
                    return False
        return True

    try:
        return dependencies if visit(main) else None
    except (OSError, ValueError, RecursionError):
        return None
