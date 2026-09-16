"""Headless tests for ``TestResultWidget``.

The widget is constructed directly from a :class:`Report`, which is a plain
dataclass -- no pytest run, no IPython, no browser needed.
"""
import shutil

import ipywidgets
import pytest

from im_pytest.report import Report, Outcome, PASS, FAIL
# Aliased on import: pytest tries to collect any module-level name starting
# with 'Test' as a test class, and warns that it cannot because the widget
# has an __init__.
from im_pytest.widget import TestResultWidget as ResultWidget


@pytest.fixture
def captured(monkeypatch):
    """State the widget published in its ``comm_open``, captured as it opened.

    The spy goes on ``ipywidgets.Widget.open`` -- the call that actually creates
    the comm -- and is filtered to this widget because it fires for the
    ``layout`` sub-widget too.
    """
    seen = {}
    original_open = ipywidgets.Widget.open

    def spy_open(self):
        if isinstance(self, ResultWidget):
            seen.clear()
            seen.update(self.get_state())
        return original_open(self)

    monkeypatch.setattr(ipywidgets.Widget, "open", spy_open)
    return seen


REPORTS = {
    "mixed": Report(project="p", outcomes=[Outcome("f", PASS),
                                           Outcome("g", FAIL, "assert 1 == 2")],
                    undefined=["h"], stdout="hello\n"),
    "collect_error": Report(project="p", collect_error="boom"),
    "import_error": Report(project="p", import_error="SyntaxError: bad"),
}


@pytest.mark.parametrize("name", list(REPORTS))
def test_report_is_populated_before_the_comm_opens(name, captured):
    """The report must be part of the widget's *initial* state, not pushed afterwards.

    ``ipywidgets.Widget.__init__`` applies constructor kwargs to the traits and
    only then calls ``open()``, which publishes ``comm_open`` carrying
    ``get_state()``. Assigning them after ``super().__init__()`` instead left
    ``comm_open`` advertising the empty defaults and pushed the whole report out
    as separate ``update`` comm messages -- which the frontend drops while it is
    still asynchronously loading the anywidget package and this widget's
    ``_esm`` (the first anywidget of a browser session), leaving an empty result
    panel with no ``change:`` event to recover from. Every synced trait is
    checked, for each of the three shapes of report, so the regression cannot
    come back through whichever branch happens not to be exercised.
    """
    report = REPORTS[name]
    w = ResultWidget(report)

    for trait in ("project", "tests_from", "results", "summary", "ok", "undefined"):
        assert captured[trait] == getattr(w, trait), f"{trait} missing from comm_open"

    assert captured["results"], "the checks themselves did not ride in comm_open"


def test_ok_is_not_left_at_its_default_when_the_run_failed(captured):
    """``ok`` defaults to True, so losing its update is worse than losing the rest:
    a failed run would draw as a passing one."""
    w = ResultWidget(REPORTS["mixed"])
    assert w.ok is False
    assert captured["ok"] is False


def test_prints_and_errors_are_not_in_the_widget():
    """Both go under it, printed and shown by IPython (see ``_show``), so the
    widget carries neither -- and its only card is the checks."""
    w = ResultWidget(Report(project="p", outcomes=[Outcome("g", FAIL, "raised")],
                            stdout="hello", traceback="TypeError: boom"))
    assert not w.has_trait("stdout") and not w.has_trait("traceback")
    from im_pytest.widget import _CSS, _ESM
    assert "Terminal output" not in _ESM and "imp-term" not in _ESM + _CSS


def test_the_header_names_where_the_tests_came_from():
    """``check("orfproject")`` leaves ``tests_from`` empty: the project names it."""
    assert ResultWidget(Report(project="orfproject")).tests_from == "orfproject"
    assert ResultWidget(Report(project="cell", tests_from="this cell")).tests_from == "this cell"


_FAKE_DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this.style = {}; this._text = null; this.parentElement = null; }
  appendChild(c) { if (c.tag === "#fragment") { c.children.forEach(x => this.appendChild(x)); } else { c.parentElement = this; this.children.push(c); } return c; }
  set textContent(t) { this._text = t; this.children = []; }
  get textContent() { return this._text !== null ? this._text : this.children.map(c => c.textContent).join(""); }
}
globalThis.document = {
  createElement: t => new Node(t),
  createTextNode: t => { const n = new Node("#text"); n._text = t; return n; },
  createDocumentFragment: () => new Node("#fragment"),
};
const { default: widget } = await import(process.argv[2]);
const state = JSON.parse(process.argv[3]);
const el = new Node("div");
widget.render({ model: { get: k => state[k] }, el });
const headers = [];
(function walk(n) { if (n.className.includes("imp-header")) headers.push([n.className, n.textContent]); n.children.forEach(walk); })(el);
console.log(JSON.stringify(headers));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_header_as_rendered(tmp_path):
    """The widget's own render(), run under node with a minimal DOM: one card,
    headed "TESTS - " and the name, which keeps its case (a file name is
    case-sensitive) where the CSS would otherwise upper-case it."""
    import json
    import subprocess
    from im_pytest.widget import _CSS, _ESM
    (tmp_path / "widget.mjs").write_text(_ESM)
    (tmp_path / "render.mjs").write_text(_FAKE_DOM)
    w = ResultWidget(Report(project="x", outcomes=[Outcome("f", FAIL, "m")], stdout="hi",
                            tests_from="test_X.py"))
    proc = subprocess.run(["node", str(tmp_path / "render.mjs"), str(tmp_path / "widget.mjs"),
                           json.dumps(w.get_state())], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [["imp-header imp-keep-case", "TESTS - test_X.py"]]
    assert ".imp-header.imp-keep-case { text-transform:none; }" in _CSS


def test_layout_width_rides_in_the_layout_widgets_own_comm_open():
    """``layout`` is built from a dict in the constructor so the Layout
    sub-widget opens with the width already set, rather than an update chasing it."""
    w = ResultWidget(REPORTS["mixed"])
    assert w.layout.width == "100%"
