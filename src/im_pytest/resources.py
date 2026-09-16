"""Find a project's test file.

Course projects ship as a downloadable ``test_<project>.py`` (plus any data)
that lands in the student's working folder, so by default we look there. The
``IM_PROJECT_TESTS`` environment variable (or an explicit ``search`` dir) points
at a shared course-repo directory instead.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def _candidates(project: str, search: Optional[str] = None) -> list:
    fname = f"test_{project}.py"
    candidates = []
    if search:
        candidates.append(Path(search) / fname)
    env = os.environ.get("IM_PROJECT_TESTS")
    if env:
        candidates.append(Path(env) / fname)
    candidates.append(Path.cwd() / fname)
    candidates.append(Path.cwd() / "project_tests" / fname)
    return candidates


def resolve_target(target: str, search: Optional[str] = None) -> Tuple[str, str, str]:
    """What ``%%test <target>`` runs: ``(test file or folder, label, tests_from)``.

    ``target`` is one of

    * a project name — ``orfproject`` runs ``test_orfproject.py``, found as
      :func:`resolve_test` finds it;
    * a test file — ``test_orfproject.py``, ``tests/test_extra.py``;
    * a folder — ``tests``, ``../tests``: every ``test_*.py`` in it and below.

    Anything ending in ``.py`` or holding a path separator is a path. A plain
    word is a project name first, so ``%%test orfproject`` means what it always
    has even where a folder called ``orfproject`` sits next to the notebook, and
    a folder only when there is no such project.

    The label names the code under test: the project, the file without
    ``test_``, or the folder's name. ``tests_from`` names where the tests were
    read, for the widget's header: the project, the file's name, the folder's
    name -- or "current folder" when that folder is the working folder.
    """
    expanded = os.path.expanduser(target)
    is_path = (target.endswith(".py") or "/" in target or os.sep in target
               or target in (".", "..") or expanded != target)
    if not is_path:
        try:
            return resolve_test(target, search), target, target
        except FileNotFoundError:
            if not os.path.isdir(target):
                looked = "\n  ".join(str(c) for c in _candidates(target, search))
                raise FileNotFoundError(
                    f"Could not find tests for {target!r}: there is no test file "
                    f"test_{target}.py and no folder named {target!r}.\n"
                    f"Looked for the test file in:\n  {looked}\n"
                    f"and for the folder in:\n  {os.getcwd()}"
                ) from None
    path = os.path.abspath(expanded)
    if os.path.isdir(path):
        here = os.path.realpath(path) == os.path.realpath(os.getcwd())
        name = os.path.basename(path)
        return path, name, "current folder" if here else name
    if os.path.isfile(path):
        stem = os.path.basename(path)[:-3] if path.endswith(".py") else os.path.basename(path)
        return path, stem[5:] if stem.startswith("test_") else stem, os.path.basename(path)
    raise FileNotFoundError(f"There is no test file or folder {target!r}.\n"
                            f"Looked in:\n  {os.getcwd()}")


def resolve_test(project: str, search: Optional[str] = None) -> str:
    fname = f"test_{project}.py"
    candidates = _candidates(project, search)
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
