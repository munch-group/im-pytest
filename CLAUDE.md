# CLAUDE.md — im-pytest

Guidance for working in this repository.

## What this is

A **thin runner over pytest** for the *Instructing Machines* course. It lets one
set of per-project pytest files be used three escalating ways (see `README.md`):
a friendly hidden runner (`check()` / `%%test`), the raw `pytest` CLI, and
student-authored tests. Design rationale and the course context live in
`../instructing-machines/docs/planning/course-plan.md`.

Key design principle: **pytest does the real work.** Its assert-rewriting already
produces readable failures, so this package stays small — it only imports the
student's solution, degrades gracefully when a function is missing, renders
friendly output, and (for mode 2) provides the fixture/marker/banner. It replaced
a ~400-line per-file `unittest` harness from the old course.

## Package layout (`src/im_pytest/`)

- `report.py` — `Report` / `Outcome` data model + text and HTML rendering. Every
  mode renders *this* object, so friendly output lives in one place.
- `plugin.py` — the `pytest11` plugin (registered via entry point, so raw pytest
  in mode 2 works with no boilerplate in the test file): the `sol` fixture
  (imports the student's `<project>.py` **by explicit file path**, fresh each run,
  stdout suppressed), the `requires` marker + skip logic, and the terminal
  "not defined" banner. `_INJECTED` lets `%%test` supply a cell-as-module.
- `runner.py` — `run()` / `run_injected()`: invoke `pytest.main` in-process,
  collect a `Report`, suppress pytest's own terminal output for mode 1.
- `widget.py` — `TestResultWidget` (an `anywidget` styled like script-widget's
  `%%exercise` output), plus `check()` and the `%%test` cell magic. Auto-registers
  the magic on import. The widget shows a **Checks** card (✓/✗ per function) and,
  only when the student's code printed or raised a non-assertion error, a separate
  **Terminal output** card with their prints and a colored, student-focused
  traceback — mirroring the `%%exercise` widget.
- `cli.py` — the `pytest-check` console entry point.
- `resources.py` — locate `test_<project>.py` (working folder or `IM_PROJECT_TESTS`).

## Conventions & gotchas

- Import the student module **by file path** (`spec_from_file_location`), never a
  bare `import_module`, so a stale copy on `sys.path` from a previous run can't win.
- Import the student module **once**: the mode-1 runner imports it (capturing its
  prints) and stashes it in `plugin._INJECTED` so the `sol` fixture reuses it
  rather than re-executing the file (no double prints/side effects).
- **Assertion failures vs code errors** are separated in `_Capture`
  (`pytest_exception_interact`): an `AssertionError` about a return value is a
  `FAIL` check; any other exception is an `ERROR` check whose colored,
  student-sliced traceback (via `runner.format_traceback`, `IPython`'s
  `FormattedTB`) and captured prints go to the widget's terminal-output card.
- The plugin is inert for non-project tests: it only touches items carrying the
  `requires` marker and only prints the banner when something is undefined — so it
  is safe to have globally installed.
- Test the runner in a **fresh subprocess** (see `test/test_runner.py`), never by
  nesting `pytest.main` inside an outer pytest run.
- Grade/auto-marking mode is deferred.

## Course integration status

The translation project is ported and lives as a fixture in `test/fixtures/`.
Porting the remaining projects (orf, codonbias, seqdist, hiv, folding, alignment,
assembly), fixing their known test-suite bugs, and placing them in the course repo
is a later milestone tracked in the course plan.
