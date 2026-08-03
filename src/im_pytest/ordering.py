"""``ordered(value)`` — a sorted version of ``value``, picked by its type.

Dict equality (and set equality) ignores order, so ``assert module.codon_bias(...)
== expected`` alone can't catch a correctly-valued but wrongly-ordered result.
``ordered()`` gives project test files a one-line way to write an order-sensitive
check, e.g. ``assert list(module.codon_bias(...).items()) == list(ordered(expected).items())``.
"""
from __future__ import annotations

from functools import singledispatch
from typing import Any

__all__ = ["ordered"]


@singledispatch
def ordered(value: Any):
    """Return a sorted version of ``value``, dispatched on its type.

    * ``dict`` — a new dict with items sorted by **value**.
    * ``list`` / ``tuple`` — a sorted copy, same type.
    * any other iterable (``set``, a generator, ...) — ``sorted(value)`` as a list.

    Raises ``TypeError`` for anything that isn't iterable.
    """
    try:
        iter(value)
    except TypeError:
        raise TypeError(
            f"ordered() doesn't know how to sort a {type(value).__name__!r} "
            "(not iterable)"
        ) from None
    return sorted(value)


@ordered.register
def _(value: dict) -> dict:
    return {k: v for k, v in sorted(value.items(), key=lambda item: item[1])}


@ordered.register
def _(value: list) -> list:
    return sorted(value)


@ordered.register
def _(value: tuple) -> tuple:
    return tuple(sorted(value))
