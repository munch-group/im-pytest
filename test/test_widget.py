"""Headless tests for ``TestResultWidget``.

The widget is constructed directly from a :class:`Report`, which is a plain
dataclass -- no pytest run, no IPython, no browser needed.
"""
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

    for trait in ("project", "results", "summary", "ok",
                  "undefined", "stdout", "traceback"):
        assert captured[trait] == getattr(w, trait), f"{trait} missing from comm_open"

    assert captured["results"], "the checks themselves did not ride in comm_open"


def test_ok_is_not_left_at_its_default_when_the_run_failed(captured):
    """``ok`` defaults to True, so losing its update is worse than losing the rest:
    a failed run would draw as a passing one."""
    w = ResultWidget(REPORTS["mixed"])
    assert w.ok is False
    assert captured["ok"] is False


def test_layout_width_rides_in_the_layout_widgets_own_comm_open():
    """``layout`` is built from a dict in the constructor so the Layout
    sub-widget opens with the width already set, rather than an update chasing it."""
    w = ResultWidget(REPORTS["mixed"])
    assert w.layout.width == "100%"
