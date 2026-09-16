"""Integration tests for the im_pytest runner.

Each case runs in a *fresh subprocess* from a temp working folder — exactly how a
student invokes it — rather than nesting pytest inside pytest.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

_SNIPPET = (
    "import json;from im_pytest import run;"
    "r=run('test_translationproject.py',project='translationproject',failfast=False);"
    "print(json.dumps({'ok':r.ok,'passed':r.passed,'failed':r.failed,"
    "'undefined':sorted(r.undefined),'import_error':r.import_error,"
    "'stdout':r.stdout,'has_tb':bool(r.traceback),"
    "'fails':[o.name for o in r.outcomes if o.status=='fail'],"
    "'errors':[o.name for o in r.outcomes if o.status=='error']}))"
)


def _run(tmp_path, solution):
    shutil.copy(FIX / "test_translationproject.py", tmp_path / "test_translationproject.py")
    shutil.copy(FIX / solution, tmp_path / "translationproject.py")
    proc = subprocess.run([sys.executable, "-c", _SNIPPET],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_good_solution_passes(tmp_path):
    d = _run(tmp_path, "translationproject_good.py")
    assert d["ok"] and d["passed"] == 4 and d["failed"] == 0 and not d["undefined"]


def test_buggy_solution_fails(tmp_path):
    d = _run(tmp_path, "translationproject_buggy.py")
    assert not d["ok"] and d["failed"] >= 1
    assert "translate_codon" in d["fails"]


def test_incomplete_reports_undefined(tmp_path):
    d = _run(tmp_path, "translationproject_incomplete.py")
    assert set(d["undefined"]) == {"split_codons", "translate_orf"} and not d["ok"]


def test_broken_solution_reports_import_error(tmp_path):
    d = _run(tmp_path, "translationproject_broken.py")
    assert d["import_error"] and not d["ok"]


def test_missing_solution_file_reports_naming_hint(tmp_path):
    # only the test file is present — e.g. the student renamed or never saved
    # translationproject.py, or renamed the test file itself away from its pair
    shutil.copy(FIX / "test_translationproject.py", tmp_path / "test_translationproject.py")
    proc = subprocess.run([sys.executable, "-c", _SNIPPET], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    d = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not d["ok"]
    assert "translationproject.py" in d["import_error"]
    assert "same folder" in d["import_error"]


def test_runtime_error_goes_to_terminal(tmp_path):
    d = _run(tmp_path, "translationproject_error.py")
    # a non-assert error is classified as an ERROR, not a FAIL, and yields a traceback
    assert "translate_codon" in d["errors"] and d["has_tb"]
    assert "loading translation solution" in d["stdout"]      # top-level print captured
    assert not d["ok"]


def test_prints_are_captured(tmp_path):
    d = _run(tmp_path, "translationproject_prints.py")
    assert d["ok"] and d["passed"] == 4
    assert "splitting" in d["stdout"] and not d["has_tb"]


# --- what a failing check says --------------------------------------------- #

_MESSAGES_TESTS = '''
from im_pytest import requires

@requires("f")
def test_list(module):
    assert module.f() == ["MM*", "M*", "MM*", "M*"]

@requires("f")
def test_dict(module):
    assert {"TTT": "F", "TTC": "F", "TAA": "X"} == {"TTT": "F", "TTC": "F", "TAA": "*"}

@requires("f")
def test_text(module):
    assert "ATG" * 30 + "TAA" == "ATG" * 30 + "TAG"

@requires("f")
def test_long(module):
    assert {k: "x" for k in "ABCDEFGHIJKLMNOP"} == {k: "y" for k in "ABCDEFGHIJKLMNOP"}
'''

_MESSAGES_SNIPPET = (
    "import json;from im_pytest import run;"
    # nice=False: these are about pytest's own explanations, which --nice replaces
    "r=run('test_msgs.py',project='msgs',failfast=False,nice=False);"
    "print(json.dumps({o.name:o.message for o in r.outcomes}))"
)


def _messages(tmp_path):
    (tmp_path / "test_msgs.py").write_text(_MESSAGES_TESTS)
    (tmp_path / "msgs.py").write_text("def f():\n    return []\n")
    # ipykernel sets FORCE_COLOR=1 in the kernel's own environment, which is
    # where check() and %%test run; the escape codes only appeared there.
    env = {k: v for k, v in os.environ.items() if k not in ("PY_COLORS", "NO_COLOR")}
    env["FORCE_COLOR"] = "1"
    proc = subprocess.run([sys.executable, "-c", _MESSAGES_SNIPPET], cwd=tmp_path,
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_check_messages_have_no_escape_codes_in_a_kernel(tmp_path):
    msgs = _messages(tmp_path)
    assert set(msgs) == {"list", "dict", "text", "long"}
    for name, msg in msgs.items():
        assert "\x1b" not in msg, f"{name}: {msg!r}"
    assert "first extra item: 'MM*'" in msgs["list"]


def test_check_messages_do_not_tell_students_to_pass_pytest_flags(tmp_path):
    # Nothing typed in check() or %%test reaches pytest's command line, so
    # "Use -v to get more diff" is an instruction nobody can follow -- and a
    # student who tries `%%test orfproject -v` gets the same message back.
    msgs = _messages(tmp_path)
    for name, msg in msgs.items():
        assert "-v" not in msg and "pytest" not in msg, f"{name}: {msg!r}"
    # the facts the instructions were attached to stay
    assert "Right contains 4 more items" in msgs["list"]
    assert "Omitting 2 identical items" in msgs["dict"]
    assert "identical leading characters in diff" in msgs["text"]
    assert msgs["long"].endswith("... (more not shown)")


# --- the test file is read afresh on every run ----------------------------- #

_EDIT_TESTS = '''
from im_pytest import requires

@requires("f")
def test_f(module):
    assert module.f(1) == 1
'''

# three runs in one process, as a kernel does them
_EDIT_SNIPPET = '''
import json, os
from im_pytest import run

def outcome(folder):
    r = run(os.path.join(folder, "test_edit.py"), project="edit", nice=True)
    return r.collect_error or [o.status + ": " + o.message for o in r.outcomes]

first = outcome("a")
source = open("a/test_edit.py").read()
with open("a/test_edit.py", "w") as fh:
    fh.write("# edited\\n\\n" + source.replace("== 1", "== 22"))
edited = outcome("a")
other = outcome("b")
print(json.dumps({"first": first, "edited": edited, "other": other}))
'''


def test_the_test_file_is_imported_afresh_on_every_run(tmp_path):
    # pytest.main in-process got the test module back from sys.modules: an edit
    # to the test file went unseen until the kernel restarted, and a same-named
    # test file in another folder failed to import at all.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "test_edit.py").write_text(_EDIT_TESTS)
    (tmp_path / "b" / "test_edit.py").write_text(_EDIT_TESTS.replace("f(1) == 1", "f(3) == 4"))
    (tmp_path / "edit.py").write_text("def f(x):\n    return x\n")
    proc = subprocess.run([sys.executable, "-c", _EDIT_SNIPPET], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    d = json.loads(proc.stdout.strip().splitlines()[-1])

    assert d["first"] == ["pass: "]
    # the edit is what ran -- and --nice read the same lines that ran, moved down two
    assert d["edited"] == ["fail: AssertionError: assert 1 == 22\n"
                           "  f(1) should return 22 but returns 1"]
    assert d["other"] == ["fail: AssertionError: assert 3 == 4\n"
                          "  f(3) should return 4 but returns 3"]


_MISMATCH_SNIPPET = (
    "import json;from im_pytest import run;"
    "r=run('test_tmp.py',project='tmp',failfast=False);"
    "print(json.dumps({'ok':r.ok,'import_error':r.import_error,'traceback':r.traceback}))"
)


def test_mismatched_filename_reports_friendly_error(tmp_path):
    # test_tmp.py expects a solution named tmp.py; only translationproject.py
    # exists here — a filename mismatch, not a missing/broken solution.
    shutil.copy(FIX / "test_translationproject.py", tmp_path / "test_tmp.py")
    shutil.copy(FIX / "translationproject_good.py", tmp_path / "translationproject.py")
    proc = subprocess.run([sys.executable, "-c", _MISMATCH_SNIPPET],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    d = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not d["ok"]
    assert "tmp.py" in d["import_error"]
    assert "test_tmp.py" in d["traceback"] and "tmp.py" in d["traceback"]
    assert "translationproject.py" in d["traceback"]   # points at the file actually present


def test_mismatched_filename_raw_pytest_shows_banner(tmp_path):
    shutil.copy(FIX / "test_translationproject.py", tmp_path / "test_tmp.py")
    shutil.copy(FIX / "translationproject_good.py", tmp_path / "translationproject.py")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "test_tmp.py"],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "COULD NOT FIND YOUR SOLUTION FILE" in proc.stdout
    assert "test_tmp.py   +   tmp.py" in proc.stdout
    assert "translationproject.py" in proc.stdout       # the file actually present, as a hint


def test_cli_exit_codes(tmp_path):
    shutil.copy(FIX / "test_translationproject.py", tmp_path / "test_translationproject.py")
    shutil.copy(FIX / "translationproject_good.py", tmp_path / "translationproject.py")
    ok = subprocess.run([sys.executable, "-m", "im_pytest.cli", "translationproject.py"],
                        cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0 and "passed" in ok.stdout.lower()

    shutil.copy(FIX / "translationproject_buggy.py", tmp_path / "translationproject.py")
    bad = subprocess.run([sys.executable, "-m", "im_pytest.cli", "translationproject.py"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode == 1
