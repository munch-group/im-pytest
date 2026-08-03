"""im-pytest — run the course's project tests three ways.

* ``check("translationproject")`` or ``%%test translationproject`` — friendly,
  hidden test runner for the early weeks (mode 1).
* ``pytest test_translationproject.py`` — the raw pytest CLI, once students learn
  to read its output (mode 2).
* students write their own ``assert`` tests to validate AI-produced code (mode 3).

Importing the package registers the ``%%test`` cell magic when run in IPython.
"""
from __future__ import annotations

from .plugin import requires
from .report import Report, Outcome
from .runner import run, run_injected
from .widget import check, register_test_magic, TestResultWidget

__all__ = ["check", "run", "run_injected", "requires", "Report", "Outcome",
           "TestResultWidget", "register_test_magic"]

# Auto-register the cell magic in notebooks (mirrors steps-widget / script-widget).
try:  # pragma: no cover
    register_test_magic()
except Exception:  # pragma: no cover
    pass
