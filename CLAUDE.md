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
  in mode 2 works with no boilerplate in the test file): the `module` fixture
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
- `cli.py` — the `pytest-check` console entry point, including `--solution` and
  the `--sweep <dir>` pre-term check over every project.
- `resources.py` — locate `test_<project>.py` (working folder or `IM_PROJECT_TESTS`).

## Conventions & gotchas

- Import the student module **by file path** (`spec_from_file_location`), never a
  bare `import_module`, so a stale copy on `sys.path` from a previous run can't win.
- Import the student module **once**: the mode-1 runner imports it (capturing its
  prints) and stashes it in `plugin._INJECTED` so the `module` fixture reuses it
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
- **Solution mode** (`--solution`, `IM_SOLUTION_SUFFIX`, `run(solution=True)`) is
  one suffix on the filename `plugin.import_student` opens: `<project>_solution.py`
  instead of `<project>.py`, under the same module name. It must never fall back
  to `<project>.py` when the solution is missing — testing the stub by accident
  reports skips, and a run of skips reads as green. In solution mode a missing
  `requires` name fails rather than skips, for the same reason.
- **Never let pytest collect above the project folder.** `runner._run_pytest`
  pins `--rootdir`/`--confcutdir` to the test file's own directory, and the plugin's
  `pytest_ignore_collect` skips directories that hold neither the working folder
  nor anything asked for. Left alone, pytest builds a collector for every parent
  up to the rootdir and lists each one, so a stray `pyproject.toml` in a home
  directory (or `-c os.devnull`, which puts the rootdir at `/dev`) makes one
  project's tests read the whole home directory — and hang on the first
  cloud-synced placeholder folder they stat.
- A run in which *nothing* ran is not a pass. `_build_report` turns a non-zero
  pytest exit code with no outcomes into a `collect_error`; without it an empty
  report satisfies "no failures, no undefined names" and renders as all-clear.
- Grade/auto-marking mode is deferred.
- **The report must ship in `comm_open`, not follow-up `update`s.**
  `TestResultWidget.__init__` works the report out into locals and hands the
  whole lot to `super().__init__()` as kwargs. This is load-bearing, not style:
  `ipywidgets.Widget.__init__` applies kwargs to the traits and only then calls
  `open()`, which publishes `comm_open` carrying `get_state()`. Assigning them
  afterwards (as it originally did) left `comm_open` advertising the empty
  defaults and pushed the entire report out as seven separate `update` messages
  -- which the frontend drops for the *first* anywidget of a browser session,
  while it is still asynchronously loading the anywidget package and this
  widget's `_esm`: the comm's message handler is not attached until that load
  resolves. A student's first `check()` of a session then drew an empty panel
  and never recovered, since no `change:` event follows for `render()`'s
  listener to catch. **`ok` is the sharp edge**: it defaults to `True`, so the
  lost update leaves the summary bar styled in the pass colour on a run that
  failed. `layout` is built from a dict in the same call so the Layout
  sub-widget's own `comm_open` carries the width rather than an update chasing
  it. `test/test_widget.py` pins all of this across all three report shapes
  (normal, `collect_error`, `import_error`) -- it spies on
  `ipywidgets.Widget.open`, the call that actually creates the comm, filtered to
  this widget because it fires for `layout` too. `steps-widget`,
  `puzzle-widget`, `turtle-widget`, `sandbox-widget` and `codelens-widget` all
  carry the same fix.
- **`pyproject.toml` carries a `[tool.pytest.ini_options]` table -- keep it.**
  A `pyproject.toml` without that table is not a config file as far as pytest is
  concerned, so pytest keeps walking *up* the tree looking for one and adopts the
  first it finds. On a machine with a stray `pyproject.toml` carrying that table
  in the home directory (which is how this was found), rootdir became
  `/Users/<name>`: `confcutdir` defaults to rootdir, so conftest collection then
  spanned the entire home directory, and one unresponsive path in it -- a
  cloud-sync folder whose `stat` hangs -- failed the run with
  `TimeoutError: [Errno 60] Operation timed out` before a single test was
  collected. That home file's `addopts` and `testpaths` applied here too. The
  symptom looks nothing like its cause, and it moves from machine to machine, so
  the two lines are not optional. Every sibling widget repo has them.
- **`install-dev` is a snapshot install, not an editable one.** The task is
  `pip install --no-build-isolation --force-reinstall --no-deps .` -- no `-e` --
  so the copy under `site-packages` freezes at the moment it was run, and the
  test suite imports *that*, not `src/`. An env left on an old install produces
  failures that belong to code no longer in the tree (this is real: the env sat
  at 0.1.21 against a 0.1.32 source, and ten tests failed for reasons that had
  been fixed long before). Re-run `pixi run install-dev` after editing `src/`,
  and suspect it first when a failure makes no sense against the code in front
  of you.
- **`test/test_dummy.py` is not part of the suite** -- it is a scratch file of
  pytest's own documentation examples (`# %% [markdown]` cells about writing
  assert statements), kept as notes. It tests nothing here and imports `numpy`,
  which is not a dependency, so collecting it aborted the entire run. It is
  listed in `test/conftest.py`'s `collect_ignore` alongside the `fixtures/*`
  glob, rather than being renamed or deleted.

## Course integration status

The translation project is ported and lives as a fixture in `test/fixtures/`.
Porting the remaining projects (orf, codonbias, seqdist, hiv, folding, alignment,
assembly), fixing their known test-suite bugs, and placing them in the course repo
is a later milestone tracked in the course plan.
