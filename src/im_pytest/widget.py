"""The notebook front door: the ``check()`` function and the ``%%test`` magic,
rendered as an anywidget styled like ``script-widget``'s ``%%exercise`` output.

The widget is one card, **TESTS - <where the tests came from>**: a ✓/✗ row per
tested function, with the failing assertion, a "not defined yet" note, and a
summary line.

Nothing else is drawn in a card. What the student's code printed is printed under
the widget, and an error it raised is shown there by IPython -- both exactly as
they would look run without ``%%test``.
"""
from __future__ import annotations

import io
import linecache
import sys
import types
from contextlib import redirect_stdout, redirect_stderr

import anywidget
import traitlets

from .report import Report, PASS, FAIL, ERROR
from .resources import resolve_target, resolve_test
from .runner import (compile_test_cell, format_traceback, run, run_injected,
                     student_traceback)

try:
    from IPython import get_ipython
    from IPython.display import display as _ipy_display
except Exception:  # pragma: no cover
    def get_ipython():
        return None

    def _ipy_display(*a, **k):
        pass


__all__ = ["TestResultWidget", "check", "register_test_magic"]


_ESM = r"""
function fillAncestors(el){let a=el;for(let i=0;i<4&&a;i++){a.style.width="100%";a.style.boxSizing="border-box";a=a.parentElement;}}

function card(title,keepCase){
  const root=document.createElement("div");root.className="imp-root";
  const h=document.createElement("div");h.className="imp-header"+(keepCase?" imp-keep-case":"");h.textContent=title;root.appendChild(h);
  const body=document.createElement("div");body.className="imp-body";root.appendChild(body);
  return {root, body};
}

function render({model, el}){
  fillAncestors(el);
  const wrap=document.createElement("div");

  // ---- checks card ----
  // "TESTS - " in capitals, the name after it as written: a file name is case-sensitive
  const {root, body}=card("TESTS - "+(model.get("tests_from")||""), true);
  (model.get("results")||[]).forEach(r=>{
    const row=document.createElement("div");row.className="imp-row";
    const mark=document.createElement("span");
    mark.className="imp-mark "+(r.status==="pass"?"imp-ok":"imp-bad");
    mark.textContent=r.status==="pass"?"✓":"✗";
    const nm=document.createElement("span");nm.className="imp-name"+(r.status==="pass"?"":" imp-name-bad");nm.textContent=r.name;
    row.appendChild(mark);row.appendChild(nm);body.appendChild(row);
    if(r.status!=="pass"&&r.message){const msg=document.createElement("pre");msg.className="imp-msg";msg.textContent=r.message;body.appendChild(msg);}
  });
  const undef=model.get("undefined")||[];
  if(undef.length){
    const b=document.createElement("div");b.className="imp-undef";
    const t=document.createElement("b");t.textContent="Not defined yet: ";b.appendChild(t);
    b.appendChild(document.createTextNode(undef.join(", ")));
    const note=document.createElement("div");note.className="imp-undef-note";
    note.textContent="These are misspelled or not written yet — their checks were skipped.";
    b.appendChild(note);body.appendChild(b);
  }
  const summary=document.createElement("div");
  summary.className="imp-summary "+(model.get("ok")?"imp-ok":"imp-bad");
  summary.textContent=model.get("summary")||"";
  body.appendChild(summary);
  wrap.appendChild(root);
  el.appendChild(wrap);
}
export default { render };
"""

_CSS = r"""
.imp-root { width:100%; box-sizing:border-box; margin-top:8px;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  background:#f3f4f6; border-radius:6px; padding:8px; border:1px solid #9ca3af; }
.imp-root + .imp-root { margin-top:10px; }
.imp-header { font-size:11.5px; font-weight:600; letter-spacing:.02em; color:#6b7280;
  text-transform:uppercase; margin:2px 4px 6px; }
.imp-header.imp-keep-case { text-transform:none; }
.imp-body { background:#ffffff; border-radius:4px; padding:10px 14px; }
.imp-row { display:flex; gap:8px; align-items:baseline; padding:2px 0; }
.imp-mark { font-weight:700; }
.imp-ok { color:#1f7a68; }
.imp-bad { color:#b23b3b; }
.imp-name { color:#26313f; }
.imp-name-bad { color:#26313f; font-weight:600; }
.imp-msg { margin:2px 0 6px 22px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12.5px; line-height:18px; white-space:pre-wrap; word-break:break-word; color:#7a2e2e; }
.imp-undef { margin:6px 0 2px; border-left:4px solid #b26a1f; background:#fbf1e2;
  border-radius:6px; padding:8px 12px; color:#5a6675; font-size:13px; }
.imp-undef b { color:#b26a1f; }
.imp-undef-note { margin-top:4px; font-size:12px; }
.imp-summary { margin-top:10px; padding-top:8px; border-top:1px solid #eee; font-weight:600; }
"""


class TestResultWidget(anywidget.AnyWidget):
    _esm = _ESM
    _css = _CSS

    project = traitlets.Unicode("").tag(sync=True)
    tests_from = traitlets.Unicode("").tag(sync=True)
    results = traitlets.List(traitlets.Dict()).tag(sync=True)
    undefined = traitlets.List(traitlets.Unicode()).tag(sync=True)
    summary = traitlets.Unicode("").tag(sync=True)
    ok = traitlets.Bool(True).tag(sync=True)

    def __init__(self, report: Report):
        # Work the report out into locals first, then hand the whole lot to
        # super().__init__() as kwargs. This is load-bearing, not style:
        # ipywidgets' Widget.__init__ applies kwargs to the traits and only then
        # calls open(), which publishes comm_open carrying get_state(). Assigning
        # them afterwards instead (as this did) left comm_open advertising the
        # empty defaults and pushed the entire report out as seven separate
        # `update` comm messages -- which the frontend drops for the first
        # anywidget of a browser session, while it is still asynchronously
        # loading the anywidget package and this widget's `_esm`: the comm's
        # message handler is not attached until that load resolves. The panel
        # then rendered from the defaults -- no checks, no summary, and `ok`
        # defaulting to True -- and never recovered, because no `change:` event
        # follows for render()'s listener to catch. A student's first `check()`
        # of a session showed an empty result panel; the next one was fine.
        # `layout` goes in the same way, for the same reason: constructing it
        # from a dict here means the Layout sub-widget's own comm_open already
        # carries the width, rather than an update chasing it.
        if report.collect_error is not None:
            results = [{"name": "the tests could not be started", "status": ERROR,
                        "message": report.collect_error}]
            summary = "Something stopped pytest before it reached your code."
            ok = False
        elif report.import_error is not None:
            results = [{"name": report.import_error, "status": ERROR,
                        "message": "Your code could not be run — see the error below."}]
            summary = "Fix the error below, then run the checks again."
            ok = False
        else:
            results = [{"name": o.name, "status": o.status, "message": o.message}
                       for o in report.outcomes]
            if report.ok:
                summary = f"All {report.passed} checks passed — nice work!"
            else:
                bits = f"{report.passed} passed, {report.failed} to fix"
                if report.undefined:
                    bits += f", {len(report.undefined)} not defined"
                summary = bits
            ok = report.ok
        super().__init__(
            layout={"width": "100%"},
            project=report.project,
            tests_from=report.tests_from or report.project,
            results=results,
            summary=summary,
            ok=ok,
            undefined=list(report.undefined),
        )


def _show(report: Report, raw: bool = False) -> None:
    """Render a report, and return nothing.

    Returning the report would make Jupyter echo its ``repr`` under the widget —
    a screenful of dataclass fields and escaped ANSI codes below the friendly
    output the widget just drew. Anyone who wants the object calls ``run()``.

    Under the widget go the code's prints, and then, through IPython's own
    ``showtraceback``, an error it raised -- both as they would look without
    ``%%test``, neither in a card. (A "traceback" that is a plain explanation
    rather than an error, such as a missing solution file, is printed too.) When
    the error stopped the code running at all (a syntax error, say) there are no
    checks, so there is no widget either: what is shown is what Python would show,
    the prints and then the error. The cell itself still completes, as it did when
    these were drawn in the widget.

    With ``raw`` there is no widget: what is shown is what a terminal would show,
    the code's prints and then pytest's own coloured output, errors in the tests
    included. An error that stopped the code before pytest started is still shown
    as above, since pytest never saw it.
    """
    ip = get_ipython()
    could_not_run = report.import_error is not None and report.exc_info is not None
    if ip is None or (raw and not could_not_run):
        print((report.output if raw and report.output else report.to_text()).rstrip("\n"))
        return
    try:
        if not could_not_run:
            _ipy_display(TestResultWidget(report))
    except Exception:  # pragma: no cover
        print(report.to_text())
        return
    if report.stdout:
        print(report.stdout)
    if report.exc_info is not None:
        # tb_offset=0: by default IPython drops the first frame, which in a cell
        # is its own; here the traceback already starts at the student's code
        ip.showtraceback(report.exc_info, tb_offset=0)
    elif report.traceback:
        print(report.traceback)


def check(project: str, *, tests: str | None = None, failfast: bool = True,
          solution: bool | str = False, nice: bool | None = None,
          raw: bool = False) -> None:
    """Test the student's ``<project>.py`` in the working folder.

    >>> check("translationproject")

    ``solution=True`` runs the reference ``<project>_solution.py`` instead — a
    teacher-side check, and the way a ``solution_walkthrough.ipynb`` can prove
    itself against the tests it is a walkthrough of.

    A failed ``assert module.f(...) == value`` is explained as "f(...) should
    return <value> but returns <what it returned>" instead of pytest's
    description of how the two values differ; ``nice=False`` keeps pytest's.

    ``raw=True`` shows pytest's own coloured output instead of the widget, as
    ``pytest -v test_<project>.py`` prints it. It cannot be combined with ``nice=True``.
    """
    test_path = tests or resolve_test(project)
    _show(run(test_path, project=project, failfast=failfast, solution=solution,
              nice=nice, raw=raw), raw=raw)


_USAGE = "Usage: %%test [<project> | <test file> | <folder>] [--no-nice | --raw]"


def _cell_number(ip):
    """The ``n`` of ``In[n]`` for the cell this magic runs in, or None.

    Read off the frame of the cell's own code, which IPython compiled under a
    name it maps to that number -- not from ``ip.execution_count``, which
    IPython 9 advances before a cell runs and IPython 8 after.
    """
    numbers = getattr(getattr(ip, "compile", None), "_filename_map", None)
    if not numbers:
        return None
    frame = sys._getframe(1)
    while frame is not None:
        number = numbers.get(frame.f_code.co_filename)
        if number is not None:
            return number
        frame = frame.f_back
    return None


def _cell_source(ip, cell, project):
    """The source to compile a ``%%test`` cell from, and the filename to compile it under.

    Where the cell has an ``In[n]``, its code is registered with IPython's own
    compiler under that number, so its frames in a traceback read ``Cell In[n],
    line 3`` as they would without ``%%test``. A blank first line stands in for
    the ``%%test`` line, so those line numbers are the ones the cell shows.
    Otherwise (the magic called from code, not typed in a cell) the name is
    ``<project>``.
    """
    number = _cell_number(ip)
    if number is not None:
        source = "\n" + cell
        return source, ip.compile.cache(source, number)
    filename = f"<{project}>"
    # register the cell source so tracebacks can show the offending line
    linecache.cache[filename] = (len(cell), None, cell.splitlines(keepends=True), filename)
    return cell, filename


def register_test_magic(ipython=None):
    """Register the ``%%test`` cell magic (idempotent).

    The cell is the code under test, and the line says where the tests are:

    * ``%%test orfproject`` — ``test_orfproject.py``, found as ``check()`` finds it;
    * ``%%test tests/test_extra.py`` — that test file;
    * ``%%test tests`` — every ``test_*.py`` in the folder ``tests`` and below;
    * ``%%test`` — in the cell itself: its ``test_...`` functions test the
      functions it defines.

    In a test file, the ``module`` fixture is the cell, whatever the file is called.

    A failed ``assert module.f(...) == value`` (in a cell with its own tests,
    ``assert f(...) == value``) is explained as "f(...) should return <value> but
    returns <what it returned>" instead of pytest's description of how the two
    values differ. ``--no-nice`` keeps pytest's. (``--nice``, which asked for it
    before it was the default, is still accepted.)

    ``--raw`` shows pytest's own coloured output instead of the widget, as
    ``pytest -v`` prints it in a terminal.
    """
    try:
        from IPython.core.magic import register_cell_magic  # noqa: F401
    except Exception:
        return
    ip = ipython or get_ipython()
    if ip is None:
        return

    def test(line, cell):
        words = line.split()
        targets = [w for w in words if not w.startswith("-")]
        options = [w for w in words if w.startswith("-")]
        # An option this magic does not know is refused rather than ignored, so a
        # typo like --nicer does not quietly run the checks without it.
        if len(targets) > 1 or any(o not in ("--nice", "--no-nice", "--raw") for o in options):
            print(_USAGE)
            return
        raw = "--raw" in options
        if "--nice" in options and "--no-nice" in options:
            print("--nice and --no-nice cannot be used together.")
            return
        if "--nice" in options and raw:
            print("--nice and --raw cannot be used together: --raw shows pytest's own "
                  "output, which --nice does not change.")
            return
        nice = False if "--no-nice" in options else None     # None: nice unless --raw
        if targets:
            try:
                test_path, project, tests_from = resolve_target(targets[0])
            except FileNotFoundError as exc:
                print(exc)
                return
        else:
            test_path, project, tests_from = None, "cell", "this cell"   # tests in the cell
        source, filename = _cell_source(ip, cell, project)
        module = types.ModuleType(project)
        module.__file__ = filename
        buf = io.StringIO()
        try:
            if test_path is None:
                code = compile_test_cell(source, filename)
            else:
                code = compile(source, filename, "exec")
            with redirect_stdout(buf), redirect_stderr(buf):
                exec(code, module.__dict__)
        except Exception as exc:  # noqa: BLE001
            rep = Report(project=project,
                         import_error=f"{type(exc).__name__}: {exc}",
                         traceback=format_traceback(type(exc), exc, exc.__traceback__, filename),
                         exc_info=(type(exc), exc, student_traceback(exc.__traceback__, filename)),
                         stdout=buf.getvalue().rstrip("\n"), tests_from=tests_from)
            _show(rep, raw=raw)
            return
        rep = run_injected(project, module, test_path, pre_stdout=buf.getvalue(),
                           nice=nice, raw=raw)
        rep.tests_from = tests_from
        # isidentifier(): a cell with its own tests also holds the helpers pytest's
        # assert rewriting adds, under names like "@py_builtins"
        ip.user_ns.update({k: v for k, v in module.__dict__.items()
                           if not k.startswith("__") and k.isidentifier()})
        _show(rep, raw=raw)

    ip.register_magic_function(test, magic_kind="cell", magic_name="test")
