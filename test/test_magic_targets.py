"""Where ``%%test`` finds its tests: a project, a test file, a folder, or the cell.

Every case drives the real magic in a fresh subprocess from a temp working
folder (never nesting ``pytest.main`` in the outer run), with the widget swapped
for a list the reports land in.
"""
import json
import re
import subprocess
import sys

import pytest

_SNIPPET = '''
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
print(json.dumps({
    "printed": printed.getvalue(),
    "names": sorted(k for k in ip.user_ns if not k.startswith("_")),
    "reports": [{
        "project": r.project, "tests_from": r.tests_from, "ok": r.ok, "undefined": r.undefined, "stdout": r.stdout,
        "import_error": r.import_error, "collect_error": r.collect_error,
        "traceback": r.traceback,
        "outcomes": {o.name: [o.status, o.message] for o in r.outcomes},
    } for r in reports],
}))
'''

# the code under test, for every target that is not the cell itself
_CODE = "def f(x):\n    return x + 1\n\ndef g(s):\n    return s * 2\n"


def _magic(cwd, line, cell=_CODE):
    proc = subprocess.run([sys.executable, "-c", _SNIPPET, line, cell], cwd=cwd,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _only_report(d):
    assert d["printed"] == ""
    [report] = d["reports"]
    return report


@pytest.fixture
def tests_folder(tmp_path):
    """nb/ is the notebook's folder; nb/tests and outside/ hold test files."""
    nb = tmp_path / "nb"
    (nb / "tests" / "sub").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (nb / "tests" / "test_a.py").write_text(
        "def test_f_in_a(module):\n    assert module.f(1) == 2\n")
    (nb / "tests" / "sub" / "test_b.py").write_text(
        "def test_g_in_b(module):\n    assert module.g('x') == 'xx'\n")
    # pytest's default python_files takes this one too; %%test takes test_*.py only
    (nb / "tests" / "b_test.py").write_text(
        "def test_not_collected(module):\n    assert False\n")
    (tmp_path / "outside" / "test_out.py").write_text(
        "def test_g_outside(module):\n    assert module.g('y') == 'yy'\n")
    return nb


# --- a test file or a folder ----------------------------------------------- #

def test_a_folder_runs_every_test_file_in_it_against_the_cell(tests_folder):
    r = _only_report(_magic(tests_folder, "tests"))
    assert r["project"] == "tests"
    assert r["outcomes"] == {"f_in_a": ["pass", ""], "g_in_b": ["pass", ""]}
    assert r["ok"]


@pytest.mark.parametrize("line, project, check", [
    ("tests/test_a.py", "a", "f_in_a"),
    ("tests/sub/test_b.py", "b", "g_in_b"),
    ("../outside/test_out.py", "out", "g_outside"),
])
def test_a_test_file(tests_folder, line, project, check):
    r = _only_report(_magic(tests_folder, line))
    assert r["project"] == project
    assert r["outcomes"] == {check: ["pass", ""]}


def test_a_folder_outside_the_working_folder(tests_folder):
    # the plugin's guard against collecting the whole home directory used to skip
    # every file inside a folder given as ../something, and report nothing ran
    r = _only_report(_magic(tests_folder, "../outside"))
    assert r["outcomes"] == {"g_outside": ["pass", ""]}


def test_the_cell_is_what_the_tests_get(tests_folder):
    wrong = "def f(x):\n    return x\n\ndef g(s):\n    return s\n"
    r = _only_report(_magic(tests_folder, "tests/sub/test_b.py --nice", cell=wrong))
    assert r["outcomes"]["g_in_b"] == [
        "fail", "AssertionError: assert 'x' == 'xx'\n  g('x') should return 'xx' but returns 'x'"]


@pytest.mark.parametrize("line, tests_from", [
    ("tests", "tests"),
    ("tests/sub/test_b.py", "test_b.py"),
    ("../outside", "outside"),
    (".", "current folder"),
])
def test_the_header_names_where_the_tests_were_read(tests_folder, line, tests_from):
    d = _magic(tests_folder, line)
    assert [r["tests_from"] for r in d["reports"]] == [tests_from]


def test_the_header_names_a_project_or_the_cell(tmp_path):
    (tmp_path / "test_proj.py").write_text("def test_x(module):\n    pass\n")
    assert _only_report(_magic(tmp_path, "proj"))["tests_from"] == "proj"
    assert _only_report(_magic(tmp_path, "", cell="def test_y():\n    pass\n"))["tests_from"] == "this cell"


def test_a_project_name_wins_over_a_folder_of_the_same_name(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "test_inside.py").write_text("def test_inside():\n    pass\n")
    (tmp_path / "test_proj.py").write_text("def test_project():\n    pass\n")
    r = _only_report(_magic(tmp_path, "proj"))
    assert r["project"] == "proj" and list(r["outcomes"]) == ["project"]

    (tmp_path / "test_proj.py").unlink()        # no project: now the folder is meant
    r = _only_report(_magic(tmp_path, "proj"))
    assert list(r["outcomes"]) == ["inside"]


@pytest.mark.parametrize("line, words", [
    ("nosuchthing", ["test_nosuchthing.py", "no folder named 'nosuchthing'"]),
    ("tests/test_nope.py", ["no test file or folder 'tests/test_nope.py'"]),
])
def test_tests_that_are_not_there_are_said_so(tests_folder, line, words):
    d = _magic(tests_folder, line)
    assert d["reports"] == []
    for w in words:
        assert w in d["printed"]
    assert "Traceback" not in d["printed"]


# --- tests in the cell itself ---------------------------------------------- #

_CELL = '''print("defining")
from im_pytest import requires

def f(x):
    return x + 1

def test_passes():
    assert f(1) == 2

def test_the_fixture_is_the_cell(module):
    assert module.f(2) == 3

@requires("not_written_yet")
def test_skipped():
    pass

def test_fails():
    print("inside a test")
    assert f(1) == 3
'''


def test_a_cell_with_its_own_tests(tmp_path):
    # --no-nice, so the message is pytest's own, which shows the rewriting
    r = _only_report(_magic(tmp_path, "--no-nice", cell=_CELL))
    assert r["project"] == "cell"
    assert r["outcomes"] == {
        "passes": ["pass", ""],
        "the_fixture_is_the_cell": ["pass", ""],
        # pytest's assert rewriting reached the cell: not a bare AssertionError
        "fails": ["fail", "assert 2 == 3\n +  where 2 = f(1)"],
    }
    assert r["undefined"] == ["not_written_yet"]
    # the cell ran once: "defining" is printed once, by the magic, not again by pytest
    assert r["stdout"] == "defining\ninside a test"
    assert not r["ok"]


def test_a_cell_with_its_own_tests_is_nice_by_default(tmp_path):
    r = _only_report(_magic(tmp_path, "", cell=_CELL))
    assert r["outcomes"]["fails"] == ["fail", "assert 2 == 3\n  f(1) should return 3 but returns 2"]


def test_a_cell_with_its_own_tests_leaves_its_names_in_the_notebook(tmp_path):
    d = _magic(tmp_path, "", cell=_CELL)
    assert {"f", "test_passes", "requires"} <= set(d["names"])
    assert not [n for n in d["names"] if not n.isidentifier()]     # no "@py_builtins"


def test_an_error_in_a_cell_test_is_kept_on_the_report(tmp_path):
    cell = "def f(x):\n    return x + 1\n\ndef test_raises():\n    f('a')\n"
    r = _only_report(_magic(tmp_path, "", cell=cell))
    assert r["outcomes"]["raises"][0] == "error"
    assert "<cell>" in r["traceback"] and "TypeError" in r["traceback"]


def test_a_cell_without_tests(tmp_path):
    r = _only_report(_magic(tmp_path, "", cell=_CODE))
    assert r["collect_error"].startswith("No tests were found.")
    assert "test_" in r["collect_error"] and not r["ok"]


# --- errors are shown by IPython, as without %%test ------------------------ #

# The magic typed in a cell (ip.run_cell), with the widget and IPython's
# showtraceback swapped for recorders: what was drawn, and what error went to
# IPython -- with each frame's label as IPython's tracebacks print it.
_SHOW_SNIPPET = '''
import contextlib, io, json, os, sys, traceback
start = os.getcwd()
from IPython.core.interactiveshell import InteractiveShell
import im_pytest.widget as widget
ip = InteractiveShell.instance()
widget.register_test_magic(ip)
shown = []
widget._ipy_display = lambda w: shown.append({"widget": w.summary})

def label(filename, lineno):
    named = ip.compile.format_code_name(filename)
    return f"{named[0]} {named[1]}, line {lineno}" if named else f"{filename}:{lineno}"

def showtraceback(exc_tuple=None, filename=None, tb_offset=None, **kwargs):
    etype, value, tb = exc_tuple
    if issubclass(etype, SyntaxError):
        frames = [label(value.filename, value.lineno)]
    else:
        frames = [label(f.filename, f.lineno) for f in traceback.extract_tb(tb)]
    shown.append({"error": etype.__name__, "tb_offset": tb_offset, "frames": frames})

ip.showtraceback = showtraceback
printed = io.StringIO()
with contextlib.redirect_stdout(printed):
    result = ip.run_cell(sys.argv[1], store_history=True)
print(json.dumps({"shown": shown, "printed": printed.getvalue(),
                  "cwd_kept": os.getcwd() == start,
                  "magic_raised": repr(result.error_in_exec or result.error_before_exec)}))
'''


def _typed(cwd, source):
    proc = subprocess.run([sys.executable, "-c", _SHOW_SNIPPET, source], cwd=cwd,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    d = json.loads(proc.stdout.strip().splitlines()[-1])
    assert d["magic_raised"] == "None"          # nothing escaped the magic itself
    # pytest chdirs back to where it thinks it started when a run ends; telling
    # it the wrong place once left the kernel in a deleted temp folder
    assert d["cwd_kept"]
    return d


def test_a_syntax_error_is_only_the_error(tmp_path):
    # no widget: nothing ran, so there are no checks -- just what Python shows.
    # The cell's line 3 (the %%test line is line 1) is where the error is.
    d = _typed(tmp_path, "%%test\ndef f(x):\n    return x +\n\ndef test_f():\n    pass\n")
    assert d["shown"] == [{"error": "SyntaxError", "tb_offset": 0, "frames": ["Cell In[1], line 3"]}]


def test_an_error_while_the_cell_runs_follows_its_prints(tmp_path):
    (tmp_path / "test_proj.py").write_text("def test_x(module):\n    pass\n")
    d = _typed(tmp_path, "%%test proj\nprint('loading')\n{}['ATG']\n")
    assert d["printed"] == "loading\n"
    assert d["shown"] == [{"error": "KeyError", "tb_offset": 0, "frames": ["Cell In[1], line 3"]}]


def test_an_error_inside_a_test_comes_under_the_widget(tmp_path):
    cell = ("%%test\ndef f(x):\n    return x + 1\n\n"
            "def test_raises():\n    print('about to fail')\n    assert f('a') == 'b'\n")
    d = _typed(tmp_path, cell)
    widget_part, error_part = d["shown"]
    assert widget_part == {"widget": "0 passed, 1 to fix"}
    # the print is under the widget, as printing normally is -- not in a card
    assert d["printed"] == "about to fail\n"
    # starting at the student's code, not in pytest, with the cell's own line numbers
    assert error_part == {"error": "TypeError", "tb_offset": 0,
                          "frames": ["Cell In[1], line 7", "Cell In[1], line 3"]}


def test_a_failed_check_is_not_an_error(tmp_path):
    d = _typed(tmp_path, "%%test\ndef f(x):\n    return x\n\ndef test_f():\n    assert f(1) == 2\n")
    assert [list(part) for part in d["shown"]] == [["widget"]]


def test_prints_come_under_the_widget(tmp_path):
    cell = ("%%test\nprint('while defining')\ndef f(x):\n    return x + 1\n\n"
            "def test_f():\n    print('while testing')\n    assert f(1) == 2\n")
    d = _typed(tmp_path, cell)
    assert [list(part) for part in d["shown"]] == [["widget"]]      # no error
    assert d["printed"] == "while defining\nwhile testing\n"


def test_a_missing_solution_file_is_explained_under_the_widget(tmp_path):
    """Not every "traceback" is an error: a reference solution that is not there
    is explained in plain words, so it is printed rather than handed to IPython
    -- and still not drawn in a card."""
    (tmp_path / "test_proj.py").write_text("def test_x(module):\n    pass\n")
    (tmp_path / "proj.py").write_text("def f(x):\n    return x\n")
    d = _typed(tmp_path, "import im_pytest\nim_pytest.check('proj', solution=True)\n")
    assert [list(part) for part in d["shown"]] == [["widget"]]      # no error
    assert "proj_solution.py" in d["printed"] and "in this folder" in d["printed"]


def test_check_shows_an_error_in_the_students_file_the_same_way(tmp_path):
    (tmp_path / "test_proj.py").write_text("def test_x(module):\n    pass\n")
    (tmp_path / "proj.py").write_text("def f(x):\n    return [\n")
    d = _typed(tmp_path, "import im_pytest\nim_pytest.check('proj')\n")
    [error] = d["shown"]
    assert error["error"] == "SyntaxError"
    assert error["frames"][0].endswith("proj.py:2")


def test_a_cell_that_does_not_compile(tmp_path):
    r = _only_report(_magic(tmp_path, "", cell="def f(x):\n    return x +\n\ndef test_f():\n    pass\n"))
    assert r["import_error"].startswith("SyntaxError") and "<cell>" in r["import_error"]
    assert r["outcomes"] == {} and r["traceback"]


# --- --raw: pytest's own output -------------------------------------------- #

_PROJECT_TEST = ("def test_passes(module):\n    assert module.f(1) == 2\n\n"
                 "def test_raises(module):\n    assert module.f('a') == 'b'\n")


def test_raw_shows_pytests_own_output_instead_of_the_widget(tmp_path):
    (tmp_path / "test_proj.py").write_text(_PROJECT_TEST)
    d = _typed(tmp_path, "%%test proj --raw\nprint('loading')\ndef f(x):\n    return x + 1\n")
    # no widget, and the error in the test is in pytest's output, not shown again
    assert d["shown"] == []
    out = d["printed"]
    assert "\x1b[" in out                                   # in colour
    text = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert text.startswith("loading\n")                     # the code's prints first
    # as `pytest -v` prints it: a line per test
    for expected in ("test session starts", "test_proj.py::test_passes PASSED",
                     "test_proj.py::test_raises FAILED", "FAILURES",
                     "TypeError", "FAILED test_proj.py::test_raises",
                     "1 failed, 1 passed"):
        assert expected in text, expected
    # plumbing is left out: the header lines, and the warning that im_pytest was
    # imported before pytest started
    assert "rootdir:" not in text and "configfile:" not in text
    assert "warnings summary" not in text


def test_raw_for_a_cell_with_its_own_tests(tmp_path):
    cell = "%%test --raw\ndef f(x):\n    return x + 1\n\ndef test_f():\n    assert [f(1)] == [3]\n"
    text = re.sub(r"\x1b\[[0-9;]*m", "", _typed(tmp_path, cell)["printed"])
    # named from its temp folder, not "../../../var/folders/.../test_cell.py"
    assert "\ntest_cell.py::test_f FAILED" in text and "FAILED test_cell.py::test_f" in text
    assert "../" not in text
    # -v: pytest's full diff, where the default verbosity says "Use -v to get more diff"
    assert "Full diff:" in text and "Use -v" not in text


def test_raw_still_shows_an_error_before_pytest_ran_as_python_would(tmp_path):
    d = _typed(tmp_path, "%%test --raw\ndef f(x):\n    return x +\n")
    assert d["printed"] == ""
    assert [part["error"] for part in d["shown"]] == ["SyntaxError"]


def test_raw_and_nice_together_are_refused(tmp_path):
    (tmp_path / "test_proj.py").write_text(_PROJECT_TEST)
    d = _typed(tmp_path, "%%test proj --raw --nice\ndef f(x):\n    return x\n")
    assert d["shown"] == [] and "--nice and --raw cannot be used together" in d["printed"]


def test_check_raw(tmp_path):
    (tmp_path / "test_proj.py").write_text(_PROJECT_TEST)
    (tmp_path / "proj.py").write_text("def f(x):\n    return x + 1\n")
    snippet = ("from im_pytest import check, run\n"
               "check('proj', raw=True)\n"
               "r = run('test_proj.py', project='proj', raw=True)\n"
               "print('MESSAGES', [o.message for o in r.outcomes])\n"
               "try:\n    check('proj', raw=True, nice=True)\n"
               "except ValueError as exc:\n    print('REFUSED', exc)\n")
    proc = subprocess.run([sys.executable, "-c", snippet], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "\x1b[" in proc.stdout
    text = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout)
    assert "test session starts" in text and "FAILED test_proj.py::test_raises" in text
    # the report's own messages stay plain text, even from a coloured run
    messages = text.split("MESSAGES", 1)[1]
    assert "\\x1b" not in messages and "raised TypeError" in messages
    assert "REFUSED nice and raw cannot be combined" in text
