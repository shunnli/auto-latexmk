# auto-latexmk

📄 Compile and clean LaTeX projects with three terminal commands.

| Command | Operation |
| --- | --- |
| `auto-latexmk [PATH]` | Compile |
| `auto-latexmk-clean [PATH]` | Clean auxiliary files, keeping PDFs |
| `auto-latexmk-rebuild [PATH]` | Clean, then compile |

`PATH` is a main `.tex` file or a directory to scan recursively. It defaults to the current directory.

## 🚀 Quick start

Requires **Python 3.11+**, **latexmk**, and the LaTeX engines you use on `PATH`.

```bash
auto-latexmk                            # Compile the current directory
auto-latexmk main.tex -pdf              # Compile with pdfLaTeX
auto-latexmk notes -j 2 -x '*-draft.tex' # Compile a folder, excluding drafts
auto-latexmk-clean notes                # Clean auxiliary files
auto-latexmk-rebuild main.tex           # Clean and compile again
```

## 🎛️ Options

| Option | Description |
| --- | --- |
| `-x PATTERN`, `--exclude PATTERN` | Exclude a file/directory basename; repeatable |
| `--no-gitignore` | Ignore `.gitignore` rules during scanning |
| `--no-color` | Disable terminal colors |
| `--verbose` | Show full output, grouped by document after it finishes |
| `-h`, `--help` | Show command help |
| `--version` | Show version |

**Compilation and rebuilding** also accept:

| Option | Description |
| --- | --- |
| `--engine ENGINE` | `auto` (default), `xelatex`, `pdflatex`, or `lualatex` |
| `-pdfxe` / `-pdf` / `-pdflua` | Select XeLaTeX / pdfLaTeX / LuaLaTeX |
| `-j N`, `--jobs N` | Parallel documents; default: `min(4, CPU count)` |
| `--no-engine-cache` | Disable reading and updating engine preferences |
| `--force` | Bypass Git-based skipping during directory scanning |

Choose one engine option. Cleanup runs sequentially.

## ⚙️ Defaults

- **Discovery:** find main files containing an uncommented `\documentclass`, respect nested `.gitignore`, and skip hidden directories. Explicit file paths bypass scan filters.
- **Git-aware compilation:** for PDFs already tracked by Git, directory scans check the PDF, sources, and dependencies (including images). Skip only when everything is clean and the PDF's last-change commit covers the dependency changes, avoiding unnecessary PDF diffs. Otherwise, or if uncertain, run latexmk normally. `--force` bypasses these checks.
- **Files:** put auxiliary files in `.aux/` and PDFs beside the source. Cleanup uses `latexmk -c`; rebuilding skips compilation if cleanup fails.
- **Engine:** explicit option → first-line `% !TEX` directive → last successful engine → XeLaTeX. Preferences are stored in `~/.cache/auto-latexmk/compiler-preferences.json`.
- **Execution:** show progress and a final summary. A failed document does not stop others. There is no time limit; **Ctrl+C** stops active processes and preserves captured output.

Explicit `.tex` paths, explicit engine options, and `auto-latexmk-rebuild` also bypass Git skipping.

## 📊 Output and timing

Normal mode shows a progress bar and summary:

```text
Compile  ████████████████  2/2  00:04
Processed 2 document(s) in 4.15s: 2 succeeded, 0 failed, 0 cancelled, 7 skipped
```

Times show elapsed execution time, excluding directory scanning and Git checks. Skipped documents are excluded from the task count; `--verbose` lists their paths and reasons.

With `--verbose` or redirected output, each completed document gets a line with its own duration (excluding queue time). Parallel durations overlap, so they do not add up to the summary time.

## 🔎 Troubleshooting

Failures show the document, engine, failed step, error excerpt, and log paths:

```text
FAILED  /project/main.tex
  Engine: pdflatex
  compile: compile failed with exit code 12
    ./sections/intro.tex:18: Undefined control sequence.
  TeX log: /project/.aux/main.log
  Full output: /project/.aux/main.auto-latexmk.log
```

Full output and command details are saved to **`.aux/<name>.auto-latexmk.log`** after each document finishes, including when interrupted. Each run replaces that document's previous capture; rebuilds include both steps. Error excerpts use the current run, and unchanged TeX logs are not linked.

To display full output in the terminal:

```bash
auto-latexmk main.tex --verbose
```

Exit codes: `0` success · `1` failure · `2` invalid arguments · `130` interrupted.

## 🛠️ Development

From this checkout, prefix any of the three commands with `uv run`:

```bash
uv sync
uv run auto-latexmk /path/to/project
uv run python -m unittest discover -s tests -v
```

For direct use outside the checkout, install with `uv tool install -e .`.

Checks: `uvx ruff check src tests`, `uv lock --check`, and `uv build`.
Type checking: `uvx pyright --pythonpath .venv/Scripts/python.exe src tests` (use `.venv/bin/python` on Linux/macOS).

Tests cover commands, discovery, caching, diagnostics, and interruption. TeX Live tests exercise real compilation and cleanup, and skip when required tools are unavailable.
