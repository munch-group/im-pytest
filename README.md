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
   with the real tool so students learn to read pytest's output. The `module`
   fixture, the `requires` marker and the not-defined banner are provided
   automatically (this package registers a `pytest11` plugin).
3. **Student-authored** — students write their own `assert`-based tests to
   specify and validate AI-produced code, using the provided files as the model.

There is also a terminal entry point:

```bash
pytest-check translationproject.py      # or: pytest-check translationproject
```

## Writing a project test file

Per-project test files are plain, idiomatic pytest. They receive `module` (the
student's solution module, imported fresh with the student's own `print` output
suppressed) and mark each test with `requires` so an unwritten function is
reported as "not defined" instead of crashing:

```python
from im_pytest import requires

@requires.translate_codon
def test_translate_codon(module):
    assert module.translate_codon("ATG") == "M"
    assert module.translate_codon("NNN") == "?"     # invalid codon
    assert module.translate_codon("atg") == "M"     # lowercase
```

`@requires.translate_codon` is sugar for `@pytest.mark.requires("translate_codon")`
(and stacks equivalently if two are put on the same test); for several names at
once use the call form, `@requires("translate_codon", "split_codons")`.

`module` resolves to `<project>.py` in the working folder (its name is the test
file name minus its `test_` prefix). Project test files and their data live
in the **course repository** and are distributed to students as downloads; set
`IM_PROJECT_TESTS` to point the runner at a shared folder instead of the working
directory.

Dict/set equality ignores order, so a plain `==` can't catch a correctly-valued
but wrongly-ordered result. `ordered(value)` sorts by type — a dict by its
values, a list/tuple in place (same type back), anything else iterable via
`sorted()` — so an order-sensitive check is one line:

```python
from im_pytest import ordered

@requires.codon_bias
def test_codon_bias(module):
    assert list(module.codon_bias(seq).items()) == list(ordered(expected).items())
```

## Development

```bash
pixi run install-dev
pixi run test
```

## License

MIT
