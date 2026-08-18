"""Solution mode, and the collection failures that used to look like check results.

Same discipline as ``test_runner.py``: every case runs in a fresh subprocess from
a temp working folder, never by nesting ``pytest.main`` inside the outer run.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


def _snippet(project="translationproject", solution=True):
    return (
        "import json;from im_pytest import run;"
        f"r=run('test_{project}.py',project='{project}',failfast=False,solution={solution!r});"
        "print(json.dumps({'ok':r.ok,'passed':r.passed,'failed':r.failed,"
        "'undefined':sorted(r.undefined),'import_error':r.import_error,"
        "'collect_error':r.collect_error,'text':r.to_text(),"
        "'names':[o.name for o in r.outcomes],"
        "'errors':[o.name for o in r.outcomes if o.status=='error']}))"
    )


def _run(cwd, project="translationproject", solution=True):
    proc = subprocess.run([sys.executable, "-c", _snippet(project, solution)],
                          cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _project(tmp_path, stub=None, solution=None, name="translationproject"):
    """A project folder: the test file, optionally a stub, optionally a solution."""
    shutil.copy(FIX / "test_translationproject.py", tmp_path / f"test_{name}.py")
    if stub:
        shutil.copy(FIX / stub, tmp_path / f"{name}.py")
    if solution:
        shutil.copy(FIX / solution, tmp_path / f"{name}_solution.py")
    return tmp_path


# --- the solution is what runs, and the stub is left alone ---------------- #

def test_solution_runs_and_the_stub_is_untouched(tmp_path):
    # a *buggy* stub sits where the student's file goes: if it were the file
    # being tested, or if the solution were copied over it, this would fail.
    _project(tmp_path, stub="translationproject_buggy.py",
             solution="translationproject_good.py")
    before = (tmp_path / "translationproject.py").read_bytes()

    d = _run(tmp_path)

    assert d["ok"] and d["passed"] == 4 and d["failed"] == 0
    assert (tmp_path / "translationproject.py").read_bytes() == before
    assert (FIX / "translationproject_buggy.py").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".py") == [
        "test_translationproject.py", "translationproject.py",
        "translationproject_solution.py",
    ]


def test_student_mode_still_reads_the_stub(tmp_path):
    # the same folder, without --solution: now the buggy stub is what is tested
    _project(tmp_path, stub="translationproject_buggy.py",
             solution="translationproject_good.py")
    d = _run(tmp_path, solution=False)
    assert not d["ok"] and d["failed"] >= 1


def test_missing_solution_is_an_error_not_a_fallback(tmp_path):
    # a correct stub, no solution file: solution mode must *not* quietly test the
    # stub and report green — the point of the run was to check the solution.
    _project(tmp_path, stub="translationproject_good.py")
    d = _run(tmp_path)
    assert not d["ok"]
    assert "translationproject_solution.py" in d["import_error"]


def test_incomplete_solution_fails_instead_of_skipping(tmp_path):
    # a student may not have written the function yet, so their run skips. A
    # reference solution that is missing a name the tests require is broken —
    # skipping there would report a misspelling on either side as green.
    _project(tmp_path, solution="translationproject_incomplete.py")
    d = _run(tmp_path)
    assert not d["ok"] and d["failed"] >= 1
    assert {"split_codons", "translate_orf"} <= set(d["errors"])

    # the same content as a student's own file: skipped, not failed
    student = tmp_path / "student"
    student.mkdir()
    _project(student, stub="translationproject_incomplete.py")
    s = _run(student, solution=False)
    assert s["failed"] == 0 and set(s["undefined"]) == {"split_codons", "translate_orf"}


def test_raw_pytest_takes_the_solution_flag(tmp_path):
    _project(tmp_path, stub="translationproject_buggy.py",
             solution="translationproject_good.py")
    ok = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header",
                         "test_translationproject.py", "--solution"],
                        cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    bad = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header",
                          "test_translationproject.py"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode != 0          # the stub is still the stub


def test_solution_mode_via_environment(tmp_path):
    # the switch a notebook or a CI job can throw without owning pytest's argv
    _project(tmp_path, stub="translationproject_buggy.py",
             solution="translationproject_good.py")
    import os
    env = dict(os.environ, IM_SOLUTION_SUFFIX="_solution")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header",
                           "test_translationproject.py"],
                          cwd=tmp_path, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout


# --- the CLI ------------------------------------------------------------- #

def test_cli_solution_exit_codes(tmp_path):
    _project(tmp_path, stub="translationproject_buggy.py",
             solution="translationproject_good.py")
    ok = subprocess.run([sys.executable, "-m", "im_pytest.cli", "--solution",
                         "--all", "translationproject"],
                        cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0 and "passed" in ok.stdout.lower()

    shutil.copy(FIX / "translationproject_buggy.py", tmp_path / "translationproject_solution.py")
    bad = subprocess.run([sys.executable, "-m", "im_pytest.cli", "--solution",
                          "--all", "translationproject"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode == 1


def test_sweep_reports_every_project(tmp_path):
    root = tmp_path / "project-files"
    good = root / "translationproject"
    other = root / "otherproject"
    for d in (good, other):
        d.mkdir(parents=True)
    _project(good, solution="translationproject_good.py")
    _project(other, solution="translationproject_good.py", name="otherproject")
    (root / "notaproject").mkdir()

    ok = subprocess.run([sys.executable, "-m", "im_pytest.cli", "--sweep", str(root)],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    assert "2 of 2 reference solutions pass" in ok.stdout
    assert "notaproject" in ok.stdout              # named, not silently dropped

    shutil.copy(FIX / "translationproject_buggy.py", other / "otherproject_solution.py")
    bad = subprocess.run([sys.executable, "-m", "im_pytest.cli", "--sweep", str(root)],
                         capture_output=True, text=True)
    assert bad.returncode == 1
    assert "FAIL  otherproject" in bad.stdout and "ok    translationproject" in bad.stdout
    assert "1 of 2 reference solutions pass" in bad.stdout


# --- collection failures ------------------------------------------------- #

def test_collection_stays_inside_the_project_folder(tmp_path):
    # A conftest.py above the project folder must never be loaded: pytest reaching
    # upward out of the working folder is what made a run of one project's tests
    # read the whole home directory (and hang on a cloud-synced folder there).
    outer, inner = tmp_path / "outer", tmp_path / "outer" / "inner"
    inner.mkdir(parents=True)
    (outer / "conftest.py").write_text("raise RuntimeError('collected too far up')\n")
    _project(inner, stub="translationproject_good.py")

    d = _run(inner, solution=False)
    assert d["ok"] and d["passed"] == 4
    assert d["collect_error"] is None


def test_collection_error_is_not_reported_as_a_check(tmp_path):
    # When collection *does* fail, it is not a result about any function of the
    # student's: it used to arrive as a failed check named after a directory.
    _project(tmp_path, stub="translationproject_good.py")
    (tmp_path / "conftest.py").write_text("raise RuntimeError('boom')\n")

    d = _run(tmp_path, solution=False)
    assert not d["ok"]
    assert d["names"] == []
    assert "boom" in d["collect_error"]
    assert "THE TESTS COULD NOT BE STARTED" in d["text"]
