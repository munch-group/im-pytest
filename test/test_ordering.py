import pytest

from im_pytest import ordered


def test_dict_sorted_by_value():
    d = {"a": 3, "b": 1, "c": 2}
    assert list(ordered(d).items()) == [("b", 1), ("c", 2), ("a", 3)]


def test_list_sorted_same_type():
    result = ordered([3, 1, 2])
    assert result == [1, 2, 3]
    assert type(result) is list


def test_tuple_sorted_same_type():
    result = ordered((3, 1, 2))
    assert result == (1, 2, 3)
    assert type(result) is tuple


def test_set_sorted_returns_list():
    result = ordered({3, 1, 2})
    assert result == [1, 2, 3]
    assert type(result) is list


def test_generic_iterable_sorted_returns_list():
    result = ordered(x for x in [3, 1, 2])
    assert result == [1, 2, 3]


def test_non_iterable_raises_type_error():
    with pytest.raises(TypeError, match="not iterable"):
        ordered(42)


def test_uncomparable_elements_raises_natural_type_error():
    with pytest.raises(TypeError, match="not supported between instances"):
        ordered([1, "a"])
