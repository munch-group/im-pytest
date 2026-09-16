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

import ast
import io
import linecache
import os
import re
import sys
import tempfile
import types
from contextlib import nullcontext, redirect_stdout, redirect_stderr

import pytest
from _pytest.assertion.rewrite import rewrite_asserts

from . import plugin as _plugin
from .report import Report, Outcome, PASS, FAIL, ERROR, _strip_ansi

try:
    from IPython import get_ipython
except Exception:  # pragma: no cover
    def get_ipython():
        return None


def _clean_name(nodeid: str) -> str:
    func = nodeid.rsplit("::", 1)[-1]
    return func[5:] if func.startswith("test_") else func


# pytest words parts of an assertion explanation as instructions for its own
# command line: "Use -v to get more diff" on a line of its own, and ", use -vv to
# show" tacked onto "Omitting 2 identical items" and "...Full output truncated
# (15 lines hidden)". Nothing a student types reaches pytest's command line from
# check() or %%test, so the instructions go; the facts they hang off stay.
_FLAG_HINT_LINE = re.compile(r"^\s*Use -v+ to get .* diff\s*$")
_FLAG_HINT_SUFFIX = re.compile(r",\s*use '?-v+'? to show")


def _assert_message(report) -> str:
    lr = getattr(report, "longrepr", None)
    crash = getattr(lr, "reprcrash", None)
    msg = getattr(crash, "message", None) or (str(lr) if lr else "")
    msg = _strip_ansi(msg)      # a raw run has pytest colour its output, messages too
    lines = [_FLAG_HINT_SUFFIX.sub("", ln) for ln in msg.splitlines()
             if ln.strip() and not _FLAG_HINT_LINE.match(ln)]
    if len(lines) > 6:
        # No line count: what is cut can be pytest's own "(11 lines hidden)",
        # so counting the lines cut here would understate what is missing.
        lines = lines[:6] + ["... (more not shown)"]
    return "\n".join(lines)


# --- %%test --nice --------------------------------------------------------- #
# Instead of pytest's explanation of *how* two values differ ("Right contains 4
# more items, first extra item: 'MM*'"), say what the student's function was
# asked and what it answered:
#
#     find_candidate_proteins("AAAATGATGTAGAAAATGATGTAGAAA") should return
#     ['MM*', 'M*', 'MM*', 'M*'] but returns []
#
# The function name and its arguments are read from the failing assert in the
# test file, as written there; the two values are the objects pytest compared,
# handed over by its pytest_assertrepr_compare hook. Only an assert of the form
# `module.f(...) == value` (either way round, or `is`) says this -- or, in a
# `%%test` cell that holds its own tests, `f(...) == value` for a function the
# cell defines. Anything else -- isinstance(...), len(...), module.codon_map ==
# ..., an assert inside a helper, an assert with its own message -- keeps
# pytest's explanation.

_NICE_OPS = {ast.Eq: "==", ast.Is: "is"}
# Long enough for every literal expected value in the course's test files (the
# longest is 80 characters) and for orfproject's list of eight proteins (187).
_NICE_REPR_MAX = 300


def _nice_repr(obj) -> str:
    # Not pytest's saferepr: that stops a list at 6 items and a dict at 4 whatever
    # their length, so a returned list that is wrong only in its last two items
    # printed exactly like the expected one. Shortened by characters instead.
    try:
        text = repr(obj)
    except Exception as exc:                            # noqa: BLE001
        return f"<{type(obj).__name__} object; repr() raised {type(exc).__name__}>"
    if len(text) > _NICE_REPR_MAX:
        half = (_NICE_REPR_MAX - 3) // 2
        text = text[:half] + "..." + text[-half:]
    return text


def _failing_assert(tb, test_file):
    """The ``assert`` the failure was raised at, with its file's source and syntax tree.

    ``test_file`` is the test module's ``__file__``: a path, or the ``<cell>``
    name a ``%%test`` cell was compiled under, whose source is in linecache.
    """
    while tb.tb_next is not None:
        tb = tb.tb_next
    filename = tb.tb_frame.f_code.co_filename
    if os.path.abspath(filename) != os.path.abspath(str(test_file)):
        return None, "", None
    # The file as it is now, not as linecache last saw it: _forget_test_module
    # has pytest import the test file afresh on every run, so this is the text
    # the failing code was compiled from. (A cell's entry has no mtime, and
    # checkcache leaves it alone.)
    linecache.checkcache(filename)
    source = "".join(linecache.getlines(filename))
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, "", None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.lineno <= tb.tb_lineno <= node.end_lineno:
            return node, source, tree
    return None, "", None


def _call_text(call, source) -> str:
    """``find_orfs("ATGTAA")`` for ``module.find_orfs("ATGTAA")``, as the test wrote it."""
    name = call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id
    text = ast.get_source_segment(source, call)
    func = ast.get_source_segment(source, call.func)
    if text and func and "\n" not in text:
        return name + text[len(func):]
    # a call spread over several lines: one line, at the cost of the test's own quoting
    return name + ast.unparse(call)[len(ast.unparse(call.func)):]


def _is_student_call(side, own_functions) -> bool:
    if not isinstance(side, ast.Call):
        return False
    if isinstance(side.func, ast.Attribute):            # module.f(...), the plugin's fixture
        return isinstance(side.func.value, ast.Name) and side.func.value.id == "module"
    return isinstance(side.func, ast.Name) and side.func.id in own_functions


def _nice_sentence(assert_node, source, tree, compared, cell=False) -> str | None:
    test = assert_node.test
    if (assert_node.msg is not None or not isinstance(test, ast.Compare)
            or len(test.ops) != 1 or compared is None):
        return None
    op, left, right = compared
    if _NICE_OPS.get(type(test.ops[0])) != op:
        return None
    # In a cell that holds its own tests, the functions it defines are the code
    # under test. In a test file they are helpers, so only module.f(...) counts.
    own_functions = {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("test")
    } if cell else set()
    for side, actual, expected in ((test.left, left, right),
                                   (test.comparators[0], right, left)):
        if _is_student_call(side, own_functions):
            return (f"{_call_text(side, source)} should return {_nice_repr(expected)}"
                    f" but returns {_nice_repr(actual)}")
    return None


def compile_test_cell(source: str, filename: str):
    """Compile a ``%%test`` cell that holds its own tests.

    Its asserts are rewritten the way pytest rewrites a test file's, so a failing
    check says what was compared (``assert 2 == 3``, ``where 2 = f(1)``) instead
    of a bare ``AssertionError``. pytest cannot do it for us: it rewrites files as
    it imports them, and the cell is run once, by the magic, never imported.
    """
    tree = ast.parse(source, filename)
    rewrite_asserts(tree, source.encode(), filename)
    return compile(tree, filename, "exec", dont_inherit=True)


class _CellModule(pytest.Module):
    """A test module whose object is a ``%%test`` cell that has already run.

    pytest is pointed at an empty placeholder file, and this collector hands it
    the cell instead of importing the placeholder -- so the cell's code runs
    once, where the magic captured its prints and any error it raised.
    """

    cell = None

    def _getobj(self):
        return self.cell


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


def student_traceback(exc_tb, student_file=None):
    """``exc_tb`` from the first frame inside ``student_file`` on, so that
    pytest's and the runner's own frames are left out; all of it if the error
    never passed through the student's file (a syntax error, say)."""
    if student_file and exc_tb is not None:
        target = os.path.abspath(student_file)
        cur = exc_tb
        while cur is not None:
            fn = cur.tb_frame.f_code.co_filename
            if os.path.abspath(fn) == target or fn == student_file:
                return cur
            cur = cur.tb_next
    return exc_tb


def format_traceback(exc_type, exc_value, exc_tb, student_file=None) -> str:
    """A colored, student-focused traceback, as text (see :func:`student_traceback`)."""
    use_tb = student_traceback(exc_tb, student_file)
    try:
        tbf = _tb_formatter()
        # tb_offset=0: the kernel's InteractiveTB skips one frame by default --
        # the frame IPython runs a cell in -- which here is the student's own
        return tbf.stb2text(tbf.structured_traceback(exc_type, exc_value, use_tb, tb_offset=0))
    except Exception:
        import traceback
        return "".join(traceback.format_exception(exc_type, exc_value, use_tb))


class _Capture:
    """Records outcomes, student prints and a code-error traceback for one run."""

    def __init__(self, student_file=None, nice=False, cell=None):
        self.outcomes: list[Outcome] = []
        self.config = None
        self.student_file = student_file
        self.nice = nice
        self.cell = cell          # a %%test cell holding its own tests, or None
        self.cell_path = ""       # the placeholder file pytest is pointed at for it
        self.stdout_parts: list[str] = []
        self.traceback = ""
        self.exc_info = None      # the error `traceback` is the text of
        self.collect_error = ""
        self.exit_code = 0
        self.pytest_output = ""
        self._done: set[str] = set()
        self._compared = None     # (op, left, right) of this test's failing comparison

    @pytest.hookimpl(trylast=True)
    def pytest_configure(self, config):
        self.config = config
        if self.cell is not None:
            # pytest names test files relative to the folder it was started in,
            # and a cell's placeholder sits in a temp folder: raw output read
            # "../../../../var/folders/.../test_cell.py", long enough to break
            # its progress line. So, for this run's output only, name it from the
            # temp folder, which --rootdir already is: "test_cell.py". Both are
            # read only to print paths. (config.rootpath, not cell_path, which is
            # the realpath: /private/var/... to /var/... is a long way round.)
            # NOT config.invocation_params: pytest chdirs back to that folder
            # when the run ends, which left the kernel in a deleted temp folder.
            # trylast: the terminal reporter exists by then.
            reporter = config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                reporter.startpath = config.rootpath
            config.cwd_relative_nodeid = lambda nodeid: nodeid    # nodeids are rootdir-relative

    def pytest_pycollect_makemodule(self, module_path, parent):
        # Called for each test file before pytest imports it.
        if self.cell is not None and os.path.realpath(module_path) == self.cell_path:
            collector = _CellModule.from_parent(parent, path=module_path)
            collector.cell = self.cell
            return collector
        _forget_test_module(module_path)
        return None               # pytest's own collector

    def pytest_runtest_logstart(self, nodeid):
        self._compared = None

    def pytest_assertrepr_compare(self, op, left, right):
        # pytest calls this as a comparison in an assert fails, just before the
        # AssertionError. Returning None leaves the explanation to pytest.
        if self.nice:
            self._compared = (op, left, right)

    def _record(self, name, status, message=""):
        if name in self._done:
            return
        self._done.add(name)
        self.outcomes.append(Outcome(name, status, message))

    def pytest_exception_interact(self, node, call, report):
        exc = getattr(call, "excinfo", None)
        if exc is None:
            return
        if not isinstance(node, pytest.Item):
            # Collection failed: pytest could not even load the test file (or a
            # folder on the way to it). That is not a check on any function of
            # the student's, and recording it as one names the check after a
            # path component — a run that dies collecting /Users/kmt reports a
            # failed check called "kmt". Keep it separate and say what it is.
            if not self.collect_error:
                self.collect_error = f"{exc.type.__name__}: {exc.value}"
                if not self.traceback:
                    self.traceback = format_traceback(exc.type, exc.value, exc.tb)
                    self.exc_info = (exc.type, exc.value, exc.tb)
            return
        name = _clean_name(report.nodeid)
        if issubclass(exc.type, AssertionError):
            message = _assert_message(report)
            if self.nice:
                test_file = getattr(getattr(node, "module", None), "__file__", None) or node.path
                assert_node, source, tree = _failing_assert(exc.tb, test_file)
                sentence = assert_node and _nice_sentence(
                    assert_node, source, tree, self._compared, cell=self.cell is not None)
                if sentence:
                    message = message.split("\n", 1)[0] + "\n  " + sentence
            self._record(name, FAIL, message)
        else:
            # the student's code raised -> show the error, as Python would
            self._record(name, ERROR, f"raised {exc.type.__name__}: {exc.value}")
            if not self.traceback:
                self.traceback = format_traceback(exc.type, exc.value, exc.tb, self.student_file)
                self.exc_info = (exc.type, exc.value,
                                 student_traceback(exc.tb, self.student_file))

    def pytest_collectreport(self, report):
        if report.failed and not self.collect_error:
            self.collect_error = str(getattr(report, "longrepr", "") or
                                     "the test file could not be collected")

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            cap = getattr(report, "capstdout", "")
            if cap:
                self.stdout_parts.append(cap)
            if report.passed:
                self._record(_clean_name(report.nodeid), PASS)


def _forget_test_module(test_path) -> None:
    """Drop the test file's module from ``sys.modules`` so pytest imports it afresh.

    pytest imports a test file with ``importlib.import_module``, which hands back
    whatever ``sys.modules`` already holds under that name. In-process -- in a
    notebook kernel, where ``check()`` and ``%%test`` run -- that was the test
    file as it stood on the session's first run: an edit to it went unseen until
    the kernel restarted, and a ``test_<project>.py`` of the same name from
    another folder failed as an import-file mismatch. (pytest already does this
    for ``conftest.py``.)
    """
    target = os.path.realpath(str(test_path))
    base = os.path.basename(target)
    for name, mod in list(sys.modules.items()):
        try:
            file = getattr(mod, "__file__", None)
        except Exception:                               # noqa: BLE001 - odd lazy modules
            continue
        if not file or os.path.basename(file) != base:
            continue
        if name == base[:-3] or os.path.realpath(file) == target:
            del sys.modules[name]


def _run_pytest(test_path, student_file, failfast, suffix="", nice=False,
                cell=None, raw=False) -> _Capture:
    """Run pytest on ``test_path`` -- a test file or a folder of them -- or, with
    ``cell``, on the tests a ``%%test`` cell holds itself. With ``raw``, pytest's
    own output is kept as ``pytest -v`` prints it in a terminal, in colour."""
    cap = _Capture(student_file=student_file, nice=nice, cell=cell)
    with tempfile.TemporaryDirectory() if cell is not None else nullcontext() as tmp:
        if cell is not None:
            test_path = os.path.join(tmp, "test_cell.py")
            open(test_path, "w").close()
            cap.cell_path = os.path.realpath(test_path)
        test_path = os.path.abspath(str(test_path))
        # rootdir and confcutdir are pinned to the folder holding the test file
        # (or to the folder asked for). Left to itself pytest walks *up* from the
        # test file, building a collector for every parent inside confcutdir and
        # listing each one; `-c os.devnull` puts the rootdir at /dev, which is
        # above nothing, so the walk runs to "/" and the listing takes in the whole
        # home directory on the way. Pinned, a run of one project's tests looks at
        # exactly one folder: the project's own.
        here = test_path if os.path.isdir(test_path) else os.path.dirname(test_path)
        # python_files: in a folder, test files are the ones named test_*.py --
        # not also pytest's default *_test.py.
        # --no-header: the platform/rootdir/configfile/plugins lines describe this
        # in-process run, not the tests ("configfile: ../../dev/null").
        # -W: every in-process run warns that im_pytest, imported before pytest
        # started, "cannot be rewritten" -- true, harmless, and not about the
        # tests, but in raw output it was a warnings section of its own.
        args = [test_path, "-c", os.devnull, "--rootdir", here, "--confcutdir", here,
                "-p", "no:cacheprovider", "--no-header", "-o", "python_files=test_*.py",
                "-W", "ignore:Module already imported so cannot be rewritten; im_pytest"
                      ":pytest.PytestAssertRewriteWarning"]
        if raw:
            # as `pytest -v` prints it: a line per test, and full assertion diffs
            args += ["-v", "--color=yes"]
        else:
            # --color=no, because ipykernel sets FORCE_COLOR=1 in the kernel's own
            # environment: pytest then takes a StringIO for a colour terminal and
            # runs every value in an assertion diff through pygments, and the
            # escape codes land in the check message, which is plain text in the
            # widget and the CLI.
            args += ["-q", "--color=no"]
        if failfast:
            args.append("-x")
        if suffix:
            args += ["--solution", "--solution-suffix", suffix]
        sink = io.StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            cap.exit_code = pytest.main(args, plugins=[cap])
        cap.pytest_output = sink.getvalue()
    return cap


def _first_lines(text, n=12) -> str:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[:n])


def _build_report(project, cap, pre_stdout="") -> Report:
    rep = Report(project=project, outcomes=cap.outcomes)
    rep.collect_error = cap.collect_error or None
    if rep.collect_error is None and not cap.outcomes and cap.exit_code != 0:
        # Nothing ran, and pytest is unhappy — a conftest that raises, a test
        # file with no tests, a usage error. None of those hooks fire through
        # the plugin, so without this the report is empty *and* content: no
        # failures, no undefined names, therefore "all checks passed".
        if cap.exit_code == pytest.ExitCode.NO_TESTS_COLLECTED:
            # pytest's own words are "no tests ran in 0.01s"; a cell or a folder
            # with tests that are not named test_... says why.
            rep.collect_error = ("No tests were found. pytest runs the functions whose "
                                 "names start with test_, in files whose names start "
                                 "with test_.")
        else:
            rep.collect_error = (_first_lines(_strip_ansi(cap.pytest_output))
                                 or f"pytest stopped with exit code {int(cap.exit_code)} "
                                    "before running any checks")
    if cap.config is not None:
        rep.undefined = sorted(getattr(cap.config, "_im_undefined", set()) or [])
    stdout = (pre_stdout or "") + "".join(cap.stdout_parts)
    rep.stdout = stdout.rstrip("\n")
    rep.traceback = cap.traceback
    rep.exc_info = cap.exc_info
    pre = pre_stdout or ""
    rep.output = pre + ("\n" if pre and not pre.endswith("\n") else "") + cap.pytest_output
    return rep


def _refuse_nice_and_raw(nice, raw):
    if nice and raw:
        raise ValueError("nice and raw cannot be combined: raw shows pytest's own "
                         "output, which nice does not change")


def run(test_path: str, *, project: str = "", failfast: bool = True,
        solution: bool | str = False, nice: bool = False, raw: bool = False) -> Report:
    """Run ``test_path`` against the student's ``<project>.py`` in the cwd.

    With ``solution=True`` the reference ``<project>_solution.py`` is run
    instead (or ``solution="<suffix>"`` for another suffix). The student's
    ``<project>.py`` is not read and not written.

    With ``nice=True`` a failed ``assert module.f(...) == value`` is explained as
    "f(...) should return <value> but returns <what it returned>" instead of
    pytest's diff.

    With ``raw=True`` the report's ``output`` is pytest's own, coloured output,
    as ``pytest -v test_<project>.py`` prints it.
    """
    _refuse_nice_and_raw(nice, raw)
    project = project or _plugin.student_module_name(os.path.basename(test_path).rsplit(".", 1)[0])
    suffix = _plugin.SOLUTION_SUFFIX if solution is True else (solution or "")

    # Import the student's file *once*, capturing its own prints; a failure here
    # (syntax error, exception at import time) becomes a friendly "cannot run".
    pre = io.StringIO()
    already_injected = project in _plugin._INJECTED
    try:
        with redirect_stdout(pre), redirect_stderr(pre):
            module = _plugin.import_student(project, suffix=suffix)
    except _plugin.SolutionNotFoundError as exc:
        return Report(
            project=project,
            import_error=f'No file named "{exc.filename}" was found',
            traceback=_plugin.explain_not_found(exc),
            stdout=pre.getvalue().rstrip("\n"),
        )
    except Exception as exc:  # noqa: BLE001
        student_file = os.path.join(os.getcwd(), project + suffix + ".py")
        return Report(
            project=project,
            import_error=f"{type(exc).__name__}: {exc}",
            traceback=format_traceback(type(exc), exc, exc.__traceback__, student_file),
            exc_info=(type(exc), exc, student_traceback(exc.__traceback__, student_file)),
            stdout=pre.getvalue().rstrip("\n"),
        )

    # Reuse this exact module inside pytest (no second import, no double prints).
    if not already_injected:
        _plugin._INJECTED[project] = module
    try:
        cap = _run_pytest(test_path, getattr(module, "__file__", None), failfast, suffix,
                          nice=nice, raw=raw)
    finally:
        if not already_injected:
            _plugin._INJECTED.pop(project, None)
    return _build_report(project, cap, pre_stdout=pre.getvalue())


def run_injected(project: str, module: types.ModuleType, test_path: str | None = None, *,
                 pre_stdout: str = "", failfast: bool = True, nice: bool = False,
                 raw: bool = False) -> Report:
    """Run against an in-notebook module built by the ``%%test`` cell magic.

    ``test_path`` is a test file, or a folder whose ``test_*.py`` files are all
    run; in every one of them the ``module`` fixture is ``module``. With
    ``test_path=None`` the module holds its own tests (``%%test`` with no
    argument), and should have been compiled with :func:`compile_test_cell`.
    ``project`` only labels the result.

    With ``nice=True`` (``%%test <project> --nice``) a failed
    ``assert module.f(...) == value`` is explained as "f(...) should return
    <value> but returns <what it returned>" instead of pytest's diff.

    With ``raw=True`` (``%%test <project> --raw``) the report's ``output`` is
    pytest's own, coloured ``pytest -v`` output, after ``pre_stdout``.
    """
    _refuse_nice_and_raw(nice, raw)
    _plugin._INJECTED_FOR_ALL = module
    try:
        cap = _run_pytest(test_path, getattr(module, "__file__", None), failfast, nice=nice,
                          cell=module if test_path is None else None, raw=raw)
    finally:
        _plugin._INJECTED_FOR_ALL = None
    return _build_report(project, cap, pre_stdout=pre_stdout)
