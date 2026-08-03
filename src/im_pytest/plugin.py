"""The pytest plugin that makes the course test files work.

Registered as a ``pytest11`` entry point, so it is active whenever pytest runs
against an installed ``im_pytest`` — which is what makes *raw* ``pytest
test_<project>.py`` (course mode 2) work with no boilerplate in the test file.

It provides three things the per-project test files rely on:

* a ``module`` fixture — the student's solution, imported fresh from the working
  directory (so edits are picked up on re-run) with the student's own ``print``
  output suppressed;
* a ``requires`` marker — ``@pytest.mark.requires("translate_codon", ...)`` skips
  a test when the student has not defined (or has misspelled) a needed name, and
  collects the missing names;
* the ``requires`` decorator sugar (``im_pytest.requires``) — ``@requires.translate_codon``
  for the common single-name case, ``@requires("a", "b")`` for several; both are
  shorthand for the marker above;
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


class SolutionNotFoundError(ModuleNotFoundError):
    """No `<name>.py` exists in `cwd` (and no importable module covers it either).

    Distinguished from an ordinary `ModuleNotFoundError` (a real missing
    dependency inside the student's own code) so callers can show a targeted
    "name your files like this" message instead of a bare Python traceback.
    """

    def __init__(self, name: str, cwd: str):
        self.solution_name = name
        self.cwd = cwd
        super().__init__(f"No module named {name!r}", name=name)


def explain_not_found(exc: SolutionNotFoundError) -> str:
    """A friendly, actionable message for a :class:`SolutionNotFoundError`."""
    try:
        py_files = sorted(
            f for f in os.listdir(exc.cwd)
            if f.endswith(".py") and not f.startswith("test_")
        )
    except OSError:
        py_files = []
    lines = [
        f'No file named "{exc.solution_name}.py" was found in this folder:',
        f"    {exc.cwd}",
    ]
    if py_files:
        lines += ["", "Files found here instead:"] + [f"    {f}" for f in py_files]
    lines += [
        "",
        "Your test file and solution file must be in the SAME folder, and named",
        "to match each other:",
        "",
        f"    test_{exc.solution_name}.py   +   {exc.solution_name}.py",
        "",
        'The solution file\'s name is the test file\'s name with "test_" removed.',
    ]
    return "\n".join(lines)


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
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            raise SolutionNotFoundError(name, cwd) from None
        raise  # a *different* missing import, e.g. a real dependency of the module


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
# requires decorator sugar
# --------------------------------------------------------------------------- #

class _Requires:
    """``@requires.name`` / ``@requires("a", "b")`` — sugar for the ``requires`` marker.

    The attribute form is both shorter and safer than ``@pytest.mark.requires(...)``:
    the required name is baked into the attribute access itself, so — unlike the raw
    marker — there's no way to write it and forget the name (forgetting the call
    parens on ``@pytest.mark.requires`` silently applies an empty, always-passing
    requirement instead of raising an error).
    """

    def __call__(self, *names):
        return pytest.mark.requires(*names)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return pytest.mark.requires(name)


requires = _Requires()


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
def module(request):
    """The student's solution module (fresh, prints suppressed)."""
    name = student_module_name(request.module.__name__)
    obj = _get_student(request.config, name)
    if isinstance(obj, SolutionNotFoundError):
        pytest.fail(
            f'Your code could not be run: no file named "{obj.solution_name}.py" '
            "was found — see the notice at the end of this test run for how to fix it.",
            pytrace=False,
        )
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
        # iter_markers (not get_closest_marker) so stacked marks — e.g. two
        # separate @requires.name decorators on one test — all count, instead
        # of only the closest one silently shadowing the rest.
        names = [n for marker in item.iter_markers("requires") for n in marker.args]
        if not names:
            continue
        name = student_module_name(item.module.__name__)
        obj = _get_student(config, name)
        if isinstance(obj, Exception):
            # the module fixture will surface the import error; nothing to skip on
            continue
        missing = [n for n in dict.fromkeys(names) if not hasattr(obj, n)]
        if missing:
            config._im_undefined.update(missing)
            item.add_marker(
                pytest.mark.skip(reason="not defined: " + ", ".join(missing))
            )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    undefined = sorted(getattr(config, "_im_undefined", ()) or [])
    if undefined:
        tr.write_line("")
        tr.write_line("Test script could not find the following functions,", red=True)
        tr.write_line("which are either misspelled or not defined:", red=True)
        tr.write_line("")
        for n in undefined:
            tr.write_line(n, red=True)

    cache = getattr(config, "_im_student_cache", None) or {}
    not_found = [exc for exc in cache.values() if isinstance(exc, SolutionNotFoundError)]
    if not_found:
        tr.write_line("")
        tr.write_line("*" * 57)
        tr.write_line("COULD NOT FIND YOUR SOLUTION FILE")
        tr.write_line("")
        for exc in not_found:
            for line in explain_not_found(exc).splitlines():
                tr.write_line(line)
            tr.write_line("")
        tr.write_line("*" * 57)
