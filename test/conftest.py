# The files under test/fixtures are sample project tests exercised *by* the
# runner (nested), not tests of the widget itself — don't collect them directly.
collect_ignore_glob = ["fixtures/*"]
