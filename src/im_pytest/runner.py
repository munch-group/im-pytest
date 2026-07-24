"""Run a project's pytest file in-process and return a :class:`Report`.

pytest does the real work; this collects results into a plain object and, crucially,
separates the two kinds of outcome the widget shows differently:

* an **assertion** about a return value failing → a ``FAIL`` check;
* the student's **own code raising** (a runtime error, or an import/syntax error
  that stops the file running) → an ``ERROR`` check *and* a colored traceback +
  their captured prints in the widget's terminal-output area, just like
  ``%%exercise``.
"""
from __future__ import annotations

import io
import os
import types
from contextlib import redirect_stdout, redirect_stderr

import pytest

from . import plugin as _plugin
from .report import Report, Outcome, PASS, FAIL, ERROR

try:
    from IPython import get_ipython
except Exception:  # pragma: no cover
    def get_ipython():
        return None


def _clean_name(nodeid: str) -> str:
    func = nodeid.rsplit("::", 1)[-1]
    return func[5:] if func.startswith("test_") else func


def _assert_message(report) -> str:
    lr = getattr(report, "longrepr", None)
    crash = getattr(lr, "reprcrash", None)
    msg = getattr(crash, "message", None) or (str(lr) if lr else "")
    lines = [ln for ln in msg.splitlines() if ln.strip()]
    if len(lines) > 6:
        lines = lines[:6] + ["... (run `pytest` for the full diff)"]
    return "\n".join(lines)


def _tb_formatter():
    """The traceback formatter to use, in order of fidelity.

    In a live notebook, the kernel's own ``InteractiveTB`` renders tracebacks
    exactly as the notebook does for uncaught exceptions — the truest match to
    ``%%exercise``. Off a kernel (the CLI), fall back to a standalone
    ``FormattedTB`` on the *neutral* theme (the same theme ``%%exercise`` forces),
    handling the IPython 9 ``theme_name`` / pre-9 ``color_scheme`` API split.
    """
    ip = get_ipython()
    itb = getattr(ip, "InteractiveTB", None) if ip is not None else None
    if itb is not None:
        return itb
    from IPython.core.ultratb import FormattedTB
    try:
        return FormattedTB(mode="Context", theme_name="neutral")   # IPython >= 9
    except TypeError:  # pragma: no cover - older IPython
        tb = FormattedTB(mode="Context")
        try:
            tb.set_colors("Neutral")
        except Exception:
            pass
        return tb


def format_traceback(exc_type, exc_value, exc_tb, student_file=None) -> str:
    """A colored, student-focused traceback — same look as the ``%%exercise`` widget.

    If ``student_file`` is given, the traceback is sliced to start at the first
    frame inside the student's own file, so pytest/plumbing frames are hidden.
    """
    use_tb = exc_tb
    if student_file and exc_tb is not None:
        target = os.path.abspath(student_file)
        cur = exc_tb
        while cur is not None:
            fn = cur.tb_frame.f_code.co_filename
            if os.path.abspath(fn) == target or fn == student_file:
                use_tb = cur
                break
            cur = cur.tb_next
    try:
        tbf = _tb_formatter()
        return tbf.stb2text(tbf.structured_traceback(exc_type, exc_value, use_tb))
    except Exception:
        import traceback
        return "".join(traceback.format_exception(exc_type, exc_value, use_tb))


class _Capture:
    """Records outcomes, student prints and a code-error traceback for one run."""

    def __init__(self, student_file=None):
        self.outcomes: list[Outcome] = []
        self.config = None
        self.student_file = student_file
        self.stdout_parts: list[str] = []
        self.traceback = ""
        self._done: set[str] = set()

    def pytest_configure(self, config):
        self.config = config

    def _record(self, name, status, message=""):
        if name in self._done:
            return
        self._done.add(name)
        self.outcomes.append(Outcome(name, status, message))

    def pytest_exception_interact(self, node, call, report):
        exc = getattr(call, "excinfo", None)
        if exc is None:
            return
        name = _clean_name(report.nodeid)
        if issubclass(exc.type, AssertionError):
            self._record(name, FAIL, _assert_message(report))
        else:
            # the student's code raised -> show it in the terminal-output area
            self._record(name, ERROR, f"raised {exc.type.__name__}: {exc.value}")
            if not self.traceback:
                self.traceback = format_traceback(exc.type, exc.value, exc.tb, self.student_file)

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            cap = getattr(report, "capstdout", "")
            if cap:
                self.stdout_parts.append(cap)
            if report.passed:
                self._record(_clean_name(report.nodeid), PASS)


def _run_pytest(test_path, student_file, failfast) -> _Capture:
    cap = _Capture(student_file=student_file)
    args = [str(test_path), "-p", "no:cacheprovider", "-q", "--no-header"]
    if failfast:
        args.append("-x")
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        pytest.main(args, plugins=[cap])
    return cap


def _build_report(project, cap, pre_stdout="") -> Report:
    rep = Report(project=project, outcomes=cap.outcomes)
    if cap.config is not None:
        rep.undefined = sorted(getattr(cap.config, "_im_undefined", set()) or [])
    stdout = (pre_stdout or "") + "".join(cap.stdout_parts)
    rep.stdout = stdout.rstrip("\n")
    rep.traceback = cap.traceback
    return rep


def run(test_path: str, *, project: str = "", failfast: bool = True) -> Report:
    """Run ``test_path`` against the student's ``<project>.py`` in the cwd."""
    project = project or _plugin.student_module_name(os.path.basename(test_path).rsplit(".", 1)[0])

    # Import the student's file *once*, capturing its own prints; a failure here
    # (syntax error, exception at import time) becomes a friendly "cannot run".
    pre = io.StringIO()
    already_injected = project in _plugin._INJECTED
    try:
        with redirect_stdout(pre), redirect_stderr(pre):
            module = _plugin.import_student(project)
    except Exception as exc:  # noqa: BLE001
        student_file = os.path.join(os.getcwd(), project + ".py")
        return Report(
            project=project,
            import_error=f"{type(exc).__name__}: {exc}",
            traceback=format_traceback(type(exc), exc, exc.__traceback__, student_file),
            stdout=pre.getvalue().rstrip("\n"),
        )

    # Reuse this exact module inside pytest (no second import, no double prints).
    if not already_injected:
        _plugin._INJECTED[project] = module
    try:
        cap = _run_pytest(test_path, getattr(module, "__file__", None), failfast)
    finally:
        if not already_injected:
            _plugin._INJECTED.pop(project, None)
    return _build_report(project, cap, pre_stdout=pre.getvalue())


def run_injected(project: str, module: types.ModuleType, test_path: str, *,
                 pre_stdout: str = "", failfast: bool = True) -> Report:
    """Run against an in-notebook module built by the ``%%test`` cell magic."""
    _plugin._INJECTED[project] = module
    try:
        cap = _run_pytest(test_path, getattr(module, "__file__", None), failfast)
    finally:
        _plugin._INJECTED.pop(project, None)
    return _build_report(project, cap, pre_stdout=pre_stdout)
