"""``--nice`` (``%%test``, ``check()``, ``pytest-check``): a failed
``module.f(...) == value`` said in a sentence.

Same discipline as ``test_runner.py``: every case runs in a fresh subprocess from
a temp working folder, never by nesting ``pytest.main`` inside the outer run.
"""
import json
import os
import subprocess
import sys

import pytest

# The first test fails, so it is the one a (fail-fast) %%test run reports.
_TESTS = '''
from pytest import approx
from im_pytest import requires

DATA = "ATGTAA"
EIGHT = ["A*", "B*", "C*", "D*", "E*", "F*", "G*", "H*"]


def _check(actual, expected):
    assert actual == expected


@requires("f")
def test_left_call(module):
    assert module.f("AAAATGATGTAGAAAATGATGTAGAAA") == ["MM*", "M*", "MM*", "M*"]

@requires("f")
def test_right_call(module):
    assert ["MM*"] == module.f("x")

@requires("g")
def test_is_none(module):
    assert module.g(1, 2) is None

@requires("h")
def test_approx(module):
    assert module.h("AGTC", "AGTT") == approx(0.75, abs=1e-4)

@requires("f")
def test_multiline_call(module):
    assert module.f(
        "ATG",
        "TAA") == ["M*"]

@requires("f")
def test_variable_arg(module):
    assert module.f(DATA) == ["M*"]

@requires("seven")
def test_long_list(module):
    assert module.seven() == EIGHT

@requires("f")
def test_very_long(module):
    assert module.f() == "A" * 1000

@requires("f")
def test_isinstance(module):
    assert isinstance(module.f("x"), dict)

@requires("CONST")
def test_attribute(module):
    assert module.CONST == 3

@requires("f")
def test_own_message(module):
    assert module.f("x") == ["M*"], "custom words"

@requires("f")
def test_len(module):
    assert len(module.f("x")) == 1

@requires("f")
def test_helper(module):
    _check(module.f("x"), ["M*"])

@requires("f")
def test_not_equal(module):
    assert module.f("x") != []

@requires("f")
def test_chained(module):
    assert [] == module.f("x") == ["M*"]
'''

_CELL = '''
def f(*args):
    return []

def g(a, b):
    return a + b

def h(a, b):
    return 0.5

def seven():
    return ["A*", "B*", "C*", "D*", "E*", "F*", "G*"]

CONST = 4
'''

# every shape at once: run_injected is what %%test calls, without its fail-fast
_RUN_SNIPPET = '''
import json, sys, types
from im_pytest import run_injected
module = types.ModuleType("shapes"); module.__file__ = "<shapes>"
exec(compile(sys.argv[1], "<shapes>", "exec"), module.__dict__)
print(json.dumps({
    mode: {o.name: o.message for o in run_injected(
        "shapes", module, "test_shapes.py", failfast=False, nice=mode == "nice").outcomes}
    for mode in ("nice", "plain")
}))
'''

# the magic itself, with the widget swapped for a list the report lands in
_MAGIC_SNIPPET = '''
import contextlib, io, json, sys
from IPython.core.interactiveshell import InteractiveShell
import im_pytest.widget as widget
ip = InteractiveShell.instance()
widget.register_test_magic(ip)
reports = []
widget._show = lambda report, raw=False: reports.append(report)
printed = io.StringIO()
with contextlib.redirect_stdout(printed):
    ip.run_cell_magic("test", sys.argv[1], sys.argv[2])
print(json.dumps({"printed": printed.getvalue(),
                  "reports": [{o.name: o.message for o in r.outcomes} for r in reports]}))
'''


def _python(tmp_path, snippet, *argv):
    (tmp_path / "test_shapes.py").write_text(_TESTS)
    # ipykernel sets FORCE_COLOR=1 in the kernel, which is where %%test runs
    env = {k: v for k, v in os.environ.items() if k not in ("PY_COLORS", "NO_COLOR")}
    env["FORCE_COLOR"] = "1"
    proc = subprocess.run([sys.executable, "-c", snippet, *argv], cwd=tmp_path,
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def messages(tmp_path_factory):
    return _python(tmp_path_factory.mktemp("shapes"), _RUN_SNIPPET, _CELL)


# --- the sentence ---------------------------------------------------------- #

def test_the_explanation_is_replaced_by_the_sentence(messages):
    assert messages["nice"]["left_call"] == (
        "AssertionError: assert [] == ['MM*', 'M*', 'MM*', 'M*']\n"
        "  f(\"AAAATGATGTAGAAAATGATGTAGAAA\") should return ['MM*', 'M*', 'MM*', 'M*']"
        " but returns []"
    )
    assert messages["plain"]["left_call"] == (
        "AssertionError: assert [] == ['MM*', 'M*', 'MM*', 'M*']\n"
        "  Right contains 4 more items, first extra item: 'MM*'"
    )


@pytest.mark.parametrize("name, sentence", [
    ("right_call", "f(\"x\") should return ['MM*'] but returns []"),
    ("is_none", "g(1, 2) should return None but returns 3"),
    ("approx", "h(\"AGTC\", \"AGTT\") should return 0.75 ± 1.0e-04 but returns 0.5"),
    # a call over several lines is put on one, in ast.unparse's quoting
    ("multiline_call", "f('ATG', 'TAA') should return ['M*'] but returns []"),
    # arguments are shown as the test wrote them, not evaluated
    ("variable_arg", "f(DATA) should return ['M*'] but returns []"),
    # all eight and all seven items: pytest's saferepr stops a list at six, which
    # would print these two identically -- the difference is in the last items
    ("long_list", "seven() should return ['A*', 'B*', 'C*', 'D*', 'E*', 'F*', 'G*', 'H*']"
                  " but returns ['A*', 'B*', 'C*', 'D*', 'E*', 'F*', 'G*']"),
])
def test_sentence_for_each_supported_shape(messages, name, sentence):
    first, second = messages["nice"][name].split("\n")
    assert first == messages["plain"][name].split("\n")[0]
    assert second == "  " + sentence


def test_a_very_long_value_is_shortened_in_the_middle(messages):
    sentence = messages["nice"]["very_long"].split("\n")[1]
    assert sentence.startswith("  f() should return 'AAAA")
    assert sentence.endswith("AAAA' but returns []")
    assert "..." in sentence and len(sentence) < 400


@pytest.mark.parametrize("name", ["isinstance", "attribute", "own_message", "len",
                                  "helper", "not_equal", "chained"])
def test_other_asserts_keep_pytests_explanation(messages, name):
    assert messages["nice"][name] == messages["plain"][name]


# --- the flag -------------------------------------------------------------- #

@pytest.mark.parametrize("line", ["shapes --nice", "--nice shapes"])
def test_nice_flag_on_the_magic(tmp_path, line):
    d = _python(tmp_path, _MAGIC_SNIPPET, line, _CELL)
    assert d["printed"] == ""
    [report] = d["reports"]
    assert "should return ['MM*', 'M*', 'MM*', 'M*'] but returns []" in report["left_call"]


def test_magic_without_the_flag_is_unchanged(tmp_path):
    d = _python(tmp_path, _MAGIC_SNIPPET, "shapes", _CELL)
    [report] = d["reports"]
    assert "Right contains 4 more items" in report["left_call"]
    assert "should return" not in report["left_call"]


@pytest.mark.parametrize("line", ["shapes --nicer", "shapes -v", "shapes other"])
def test_magic_refuses_what_it_does_not_understand(tmp_path, line):
    d = _python(tmp_path, _MAGIC_SNIPPET, line, _CELL)
    assert d["reports"] == []
    assert d["printed"].strip() == "Usage: %%test [<project> | <test file> | <folder>] [--nice | --raw]"


# check() and pytest-check read the student's shapes.py from the working folder
_SENTENCE = ("f(\"AAAATGATGTAGAAAATGATGTAGAAA\") should return ['MM*', 'M*', 'MM*', 'M*']"
             " but returns []")


def _printed(tmp_path, *args):
    (tmp_path / "test_shapes.py").write_text(_TESTS)
    (tmp_path / "shapes.py").write_text(_CELL)
    proc = subprocess.run([sys.executable, *args], cwd=tmp_path,
                          capture_output=True, text=True)
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc


@pytest.mark.parametrize("args, nice", [
    (["-m", "im_pytest.cli", "--nice", "shapes.py"], True),
    (["-m", "im_pytest.cli", "shapes.py", "--nice"], True),
    (["-m", "im_pytest.cli", "shapes.py"], False),
    (["-c", "from im_pytest import check; check('shapes', nice=True)"], True),
    (["-c", "from im_pytest import check; check('shapes')"], False),
])
def test_nice_in_check_and_pytest_check(tmp_path, args, nice):
    out = _printed(tmp_path, *args).stdout
    assert "[FAIL] left_call" in out
    assert (_SENTENCE in out) is nice
    assert ("Right contains 4 more items" in out) is not nice


def test_pytest_check_nice_still_fails_the_run(tmp_path):
    assert _printed(tmp_path, "-m", "im_pytest.cli", "--nice", "shapes.py").returncode == 1
