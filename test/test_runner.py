"""Integration tests for the im_pytest runner.

Each case runs in a *fresh subprocess* from a temp working folder — exactly how a
student invokes it — rather than nesting pytest inside pytest.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

_SNIPPET = (
    "import json;from im_pytest import run;"
    "r=run('test_translationproject.py',project='translationproject',failfast=False);"
    "print(json.dumps({'ok':r.ok,'passed':r.passed,'failed':r.failed,"
    "'undefined':sorted(r.undefined),'import_error':bool(r.import_error),"
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
