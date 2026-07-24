"""Data model for a test run plus a plain-text rendering (used by the CLI).

The notebook rendering is a real anywidget — see ``widget.py``. Both consume
*this* object, so the two never drift.

A run has two distinct kinds of result:

* **check results** — one :class:`Outcome` per tested function: it passed, an
  assertion about its return value failed (``FAIL``), or the student's own code
  raised while it was being tested (``ERROR``);
* **terminal output** — anything the student's code printed, plus the traceback
  of a non-assertion error in their code (or an import/syntax error that stopped
  the file running at all). This mirrors what the ``%%exercise`` widget shows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

PASS = "pass"
FAIL = "fail"     # an assertion about the return value failed
ERROR = "error"   # the student's code raised while being tested


@dataclass
class Outcome:
    name: str            # the function being tested, e.g. "translate_codon"
    status: str          # PASS / FAIL / ERROR
    message: str = ""    # the failing assertion, or a short "raised X" note


@dataclass
class Report:
    project: str = ""
    outcomes: List[Outcome] = field(default_factory=list)
    undefined: List[str] = field(default_factory=list)  # required names not defined yet
    stdout: str = ""                                     # captured student prints
    traceback: str = ""                                  # colored traceback of a code error
    import_error: Optional[str] = None                   # short "cannot run" summary

    @property
    def passed(self) -> int:
        return sum(o.status == PASS for o in self.outcomes)

    @property
    def failed(self) -> int:
        return sum(o.status in (FAIL, ERROR) for o in self.outcomes)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def has_terminal(self) -> bool:
        return bool(self.stdout) or bool(self.traceback)

    @property
    def ok(self) -> bool:
        return self.import_error is None and self.failed == 0 and not self.undefined

    # ---- plain-text rendering (CLI) -------------------------------------- #

    def to_text(self) -> str:
        lines = []
        if self.import_error is not None:
            lines.append("YOUR CODE CANNOT BE RUN")
            lines.append("")
            lines.append(self.import_error)
        else:
            for o in self.outcomes:
                lines.append(f"[{'PASS' if o.status == PASS else 'FAIL'}] {o.name}")
                if o.status != PASS and o.message:
                    lines.append(_indent(o.message))
            if self.undefined:
                lines += ["", "*" * 57,
                          "ATTENTION! These functions are not defined (yet):", ""]
                lines += [f"\t{n}" for n in self.undefined]
                lines += ["", "They are either misspelled or not written yet.", "*" * 57]

        if self.has_terminal:
            lines += ["", "----- terminal output -----"]
            if self.stdout:
                lines.append(self.stdout.rstrip("\n"))
            if self.traceback:
                lines.append(_strip_ansi(self.traceback).rstrip("\n"))

        lines.append("")
        if self.import_error is not None:
            lines.append("Fix the error above, then run the tests again.")
        elif self.ok:
            lines.append(f"All {self.passed} checks passed. Nice work!")
        else:
            bits = f"{self.passed} passed, {self.failed} to fix"
            if self.undefined:
                bits += f", {len(self.undefined)} not defined"
            lines.append(bits + ".")
        return "\n".join(lines)


def _indent(text: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in str(text).splitlines())


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)
