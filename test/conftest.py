# The files under test/fixtures are sample project tests exercised *by* the
# runner (nested), not tests of the widget itself — don't collect them directly.
collect_ignore_glob = ["fixtures/*"]

# test_dummy.py is a scratch file of pytest's *own* documentation examples --
# `# %% [markdown]` cells about writing assert statements -- kept as notes. It
# tests nothing in this package, and it imports numpy, which is not a dependency
# here, so collecting it aborted the whole run before any real test was reached.
# Ignored rather than renamed or deleted so the notes stay where they are.
collect_ignore = ["test_dummy.py"]
