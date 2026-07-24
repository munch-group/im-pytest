"""The ``pytest-check`` command: the terminal way to run a project's tests.

    pytest-check translationproject.py     # point at your solution file
    pytest-check translationproject        # or just the project name

Finds ``test_<project>.py`` (in the working folder or IM_PROJECT_TESTS), runs it
against your solution, and prints friendly output.
"""
from __future__ import annotations

import os
import sys

from .resources import resolve_test
from .runner import run


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    target = argv[0]
    all_tests = "--all" in argv[1:]

    project = os.path.basename(target)
    if project.endswith(".py"):
        project = project[:-3]

    try:
        test_path = resolve_test(project)
    except FileNotFoundError as exc:
        print(exc)
        return 2

    report = run(test_path, project=project, failfast=not all_tests)
    print(report.to_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
