"""The pytest plugin that makes the course test files work.

Registered as a ``pytest11`` entry point, so it is active whenever pytest runs
against an installed ``im_pytest`` — which is what makes *raw* ``pytest
test_<project>.py`` (course mode 2) work with no boilerplate in the test file.

It provides three things the per-project test files rely on:

* a ``sol`` fixture   — the student's solution, imported fresh from the working
  directory (so edits are picked up on re-run) with the student's own ``print``
  output suppressed;
* a ``requires`` marker — ``@pytest.mark.requires("translate_codon", ...)`` skips
  a test when the student has not defined (or has misspelled) a needed name, and
  collects the missing names;
* a "functions not defined" summary at the end of a raw pytest run.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types

import pytest

# %%test injects a module here so the fixture can return an in-notebook cell
# instead of a file on disk. Keyed by module name.
_INJECTED: dict[str, types.ModuleType] = {}


# --------------------------------------------------------------------------- #
# importing the student's solution
# --------------------------------------------------------------------------- #

def student_module_name(test_module_name: str) -> str:
    """`test_translationproject` -> `translationproject`."""
    base = test_module_name.rsplit(".", 1)[-1]
    return base[5:] if base.startswith("test_") else base


def import_student(name: str, cwd: str | None = None) -> types.ModuleType:
    """Import (or re-import) the student's `<name>.py` from `cwd`.

    Loaded by explicit file path (so it can't accidentally resolve to a stale
    copy left on ``sys.path`` by a previous run), with ``cwd`` also put at the
    front of ``sys.path`` so a solution that imports a *sibling* project file
    still works. Raises on any error in the student's code so callers can report
    it. The student's ``print`` output is *not* suppressed here — the caller
    (the mode-1 runner, or pytest's own capture in mode 2) captures it so it can
    be shown in the widget's terminal-output area.
    """
    if name in _INJECTED:
        return _INJECTED[name]

    cwd = os.path.abspath(cwd or os.getcwd())
    if sys.path and sys.path[0] != cwd:
        # keep cwd first so sibling-file imports resolve to this folder
        while cwd in sys.path:
            sys.path.remove(cwd)
        sys.path.insert(0, cwd)

    sys.modules.pop(name, None)           # drop any cached copy so edits are seen
    importlib.invalidate_caches()

    path = os.path.join(cwd, name + ".py")
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module        # so recursive/self references resolve
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
        return module
    # Fall back to a normal import (e.g. an injected/installed module).
    return importlib.import_module(name)


def _get_student(config, name):
    """Import once per session and cache (module or the exception raised)."""
    cache = getattr(config, "_im_student_cache", None)
    if cache is None:
        cache = config._im_student_cache = {}
    if name not in cache:
        try:
            cache[name] = import_student(name)
        except Exception as exc:                       # noqa: BLE001
            cache[name] = exc
    return cache[name]


# --------------------------------------------------------------------------- #
# pytest hooks
# --------------------------------------------------------------------------- #

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires(*names): skip this test when the student has not defined the named "
        "functions/variables, and report them as not-yet-defined.",
    )
    config._im_undefined = set()


@pytest.fixture
def sol(request):
    """The student's solution module (fresh, prints suppressed)."""
    name = student_module_name(request.module.__name__)
    obj = _get_student(request.config, name)
    if isinstance(obj, Exception):
        pytest.fail(
            "Your code could not be run:\n\n" + "".join(
                __import__("traceback").format_exception_only(type(obj), obj)
            ),
            pytrace=False,
        )
    return obj


def pytest_collection_modifyitems(config, items):
    for item in items:
        marker = item.get_closest_marker("requires")
        if marker is None:
            continue
        name = student_module_name(item.module.__name__)
        obj = _get_student(config, name)
        if isinstance(obj, Exception):
            # the sol fixture will surface the import error; nothing to skip on
            continue
        missing = [n for n in marker.args if not hasattr(obj, n)]
        if missing:
            config._im_undefined.update(missing)
            item.add_marker(
                pytest.mark.skip(reason="not defined: " + ", ".join(missing))
            )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    undefined = sorted(getattr(config, "_im_undefined", ()) or [])
    if undefined:
        tr = terminalreporter
        tr.write_line("")
        tr.write_line("*" * 57)
        tr.write_line("ATTENTION! These functions are not defined (yet):")
        tr.write_line("")
        for n in undefined:
            tr.write_line("\t" + n)
        tr.write_line("")
        tr.write_line("They are either misspelled or not written yet.")
        tr.write_line("*" * 57)
