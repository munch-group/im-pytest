"""The ``pytest-check`` command: the terminal way to run a project's tests.

    pytest-check translationproject.py     # point at your solution file
    pytest-check translationproject        # or just the project name

Finds ``test_<project>.py`` (in the working folder or IM_PROJECT_TESTS), runs it
against your solution, and prints friendly output.

Two teacher-side forms run the *reference* solution instead of the student stub,
so a broken test file is caught before a class meets it:

    pytest-check --solution translationproject     # <project>_solution.py
    pytest-check --sweep project-files/            # every project under a folder

Neither reads or writes ``<project>.py``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .resources import resolve_test
from .runner import run


def sweep(directory: str) -> int:
    """Run every project under `directory` against its own reference solution.

    One subprocess per project, each with its working directory set to that
    project's folder: a project whose test file opens a data file by a plain
    relative name (several do) only works from there, and eight solutions
    imported into one interpreter would otherwise shadow each other.
    """
    root = Path(directory)
    if not root.is_dir():
        print(f"Not a folder: {root}")
        return 2

    subdirs = sorted(d for d in root.iterdir() if d.is_dir())
    projects = [d for d in subdirs if (d / f"test_{d.name}.py").is_file()]
    skipped = [d.name for d in subdirs if d not in projects and not d.name.startswith(".")]
    if not projects:
        print(f"No project folder under {root} holds a matching test_<name>.py")
        return 2

    failures = []
    for d in projects:
        proc = subprocess.run(
            [sys.executable, "-m", "im_pytest.cli", "--solution", "--all", d.name],
            cwd=str(d), capture_output=True, text=True,
        )
        ok = proc.returncode == 0
        print(f"{'ok  ' if ok else 'FAIL'}  {d.name}")
        if not ok:
            failures.append((d.name, (proc.stdout + proc.stderr).rstrip()))

    for name, output in failures:
        print("\n" + "=" * 60)
        print(name)
        print("=" * 60)
        print(output)

    print()
    if skipped:
        print(f"Not run (no test_<name>.py): {', '.join(skipped)}")
    print(f"{len(projects) - len(failures)} of {len(projects)} reference solutions pass their tests.")
    return 1 if failures else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    flags = {a for a in argv if a.startswith("-")}
    positional = [a for a in argv if not a.startswith("-")]

    if "--sweep" in flags:
        return sweep(positional[0] if positional else ".")

    if not positional:
        print(__doc__)
        return 2

    target = positional[0]
    all_tests = "--all" in flags
    solution = "--solution" in flags

    project = os.path.basename(target)
    if project.endswith(".py"):
        project = project[:-3]
    # `pytest-check --solution translationproject_solution.py` is the natural
    # thing to type; take the suffix off rather than looking for a solution of
    # a solution.
    if solution and project.endswith("_solution"):
        project = project[: -len("_solution")]

    try:
        test_path = resolve_test(project)
    except FileNotFoundError as exc:
        print(exc)
        return 2

    report = run(test_path, project=project, failfast=not all_tests, solution=solution)
    print(report.to_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
