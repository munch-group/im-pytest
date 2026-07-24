# im-pytest

A thin runner over **pytest** for the *Instructing Machines* course. One set of
per-project test files is surfaced three escalating ways across the term, so
testing grows from a hidden safety net into a tool students wield themselves.

```python
import im_pytest

im_pytest.check("translationproject")   # friendly panel: ✓/✗ per function
```

## The three modes (one artifact)

1. **Hidden friendly runner** — `check("translationproject")` or the `%%test`
   cell magic. Runs the project's bundled tests against the student's
   `translationproject.py` and renders a beginner-friendly panel: a green ✓ or
   red ✗ per function, the failing assertion, and a "functions not defined yet"
   note. No test source, no traceback. For the early weeks, before students know
   what a test is.
2. **Raw pytest** — `pytest test_translationproject.py`. The *same* file, now run
   with the real tool so students learn to read pytest's output. The `sol`
   fixture, the `requires` marker and the not-defined banner are provided
   automatically (this package registers a `pytest11` plugin).
3. **Student-authored** — students write their own `assert`-based tests to
   specify and validate AI-produced code, using the provided files as the model.

There is also a terminal entry point:

```bash
pytest-check translationproject.py      # or: pytest-check translationproject
```

## Writing a project test file

Per-project test files are plain, idiomatic pytest. They receive `sol` (the
student's solution module, imported fresh with the student's own `print` output
suppressed) and mark each test with `requires` so an unwritten function is
reported as "not defined" instead of crashing:

```python
import pytest

@pytest.mark.requires("translate_codon")
def test_translate_codon(sol):
    assert sol.translate_codon("ATG") == "M"
    assert sol.translate_codon("NNN") == "?"     # invalid codon
    assert sol.translate_codon("atg") == "M"     # lowercase
```

`sol` resolves to `<project>.py` in the working folder (the module name is the
test file name minus its `test_` prefix). Project test files and their data live
in the **course repository** and are distributed to students as downloads; set
`IM_PROJECT_TESTS` to point the runner at a shared folder instead of the working
directory.

## Development

```bash
pixi run install-dev
pixi run test
```

## License

MIT
