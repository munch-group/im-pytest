"""Find a project's test file.

Course projects ship as a downloadable ``test_<project>.py`` (plus any data)
that lands in the student's working folder, so by default we look there. The
``IM_PROJECT_TESTS`` environment variable (or an explicit ``search`` dir) points
at a shared course-repo directory instead.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def resolve_test(project: str, search: Optional[str] = None) -> str:
    fname = f"test_{project}.py"
    candidates = []
    if search:
        candidates.append(Path(search) / fname)
    env = os.environ.get("IM_PROJECT_TESTS")
    if env:
        candidates.append(Path(env) / fname)
    candidates.append(Path.cwd() / fname)
    candidates.append(Path.cwd() / "project_tests" / fname)
    for c in candidates:
        if c.exists():
            return str(c)
    looked = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"Could not find tests for project {project!r} ({fname}).\n"
        f"Looked in:\n  {looked}\n"
        f"Download the project's test file into your working folder, or set "
        f"IM_PROJECT_TESTS to the folder that holds it."
    )
