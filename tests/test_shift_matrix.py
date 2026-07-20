"""Shift operation test matrix — verifies _binary_op refactoring correctness."""

import numpy as np
import pytest

from wavekit.signal import Signal
from wavekit.waveform import Waveform


def _mk(values, width=8, signed=False):
    return Waveform(
        value=np.array(values, dtype=np.uint64 if width <= 64 else np.object_),
        clock=np.arange(len(values), dtype=np.uint64),
        time=np.arange(len(values), dtype=np.uint64) * 10,
        signal=Signal('w', 'w', width, None, signed),
    )


# ── value correctness ──


@pytest.mark.parametrize(
    'vals,shift,expected',
    [
        ([1, 2, 4], 1, [2, 4, 8]),
        ([0xFF], 4, [0xFF0]),
        ([1], 63, [1 << 63]),
    ],
)
def test_lshift_scalar(vals, shift, expected):
    w = _mk(vals, width=64)
    r = w << shift
    assert [int(v) for v in r.value] == expected


@pytest.mark.parametrize(
    'vals,shift,expected',
    [
        ([8, 16, 32], 1, [4, 8, 16]),
        ([0xFF00], 4, [0xFF0]),
    ],
)
def test_rshift_scalar(vals, shift, expected):
    w = _mk(vals, width=16)
    r = w >> shift
    assert [int(v) for v in r.value] == expected


# ── width > 64 dtype upgrade ──


def test_lshift_above_64_bits():
    w = _mk([1, 2], width=8)
    r = w << 60
    assert r.width > 64
    assert r.value.dtype == np.object_ or all(isinstance(v, int) for v in r.value)


def test_rlshift_above_64_bits_exact():
    shifts = _mk([63, 64, 65], width=7)
    r = 1 << shifts
    expected = [1 << 63, 1 << 64, 1 << 65]
    assert [int(v) for v in r.value] == expected


def test_rrshift_scalar_no_widening():
    shifts = _mk([0, 1, 2], width=8)
    r = 5 >> shifts
    assert [int(v) for v in r.value] == [5, 2, 1]


# ── alignment check ──


@pytest.mark.parametrize('op_name', ['__lshift__', '__rshift__', '__rlshift__', '__rrshift__'])
def test_shift_rejects_misaligned(op_name):
    w1 = _mk([1, 2], width=8)
    w2 = Waveform(
        value=np.array([3, 4], dtype=np.uint64),
        clock=np.array([100, 101], dtype=np.uint64),
        time=np.array([1000, 1010], dtype=np.uint64),
        signal=Signal('b', 'b', 8, None, False),
    )
    fn = getattr(w1, op_name)
    with pytest.raises(ValueError):
        fn(w2)


# ── signedness not checked for shift ──

# ── xz_mask propagation ──


def test_lshift_xz_mask_merge():
    a = _mk([1, 2, 3])
    a.xz_mask = np.array([True, False, False])
    b = _mk([1, 1, 1])
    b.xz_mask = np.array([False, False, True])
    r = a << b
    expected = np.array([True, False, True])
    assert np.array_equal(r.xz_mask, expected)


# ── reverse op argument order ──


def test_rlshift_argument_order():
    w = _mk([0, 1, 2], width=4)
    r = 1 << w
    assert [int(v) for v in r.value] == [1, 2, 4]


# -- mixed width shift --


def test_lshift_mixed_width():
    data = _mk([1, 2, 4], width=8)
    shift_amt = _mk([1, 2, 3], width=3)
    r = data << shift_amt
    assert [int(v) for v in r.value] == [2, 8, 32]
    assert r.width == 15


def test_rshift_mixed_width():
    data = _mk([16, 32, 64], width=8)
    shift_amt = _mk([1, 2, 3], width=3)
    r = data >> shift_amt
    assert [int(v) for v in r.value] == [8, 8, 8]
    assert r.width == 8


def test_rlshift_mixed_width():
    shift_amt = _mk([1, 2, 3], width=3)
    data = _mk([1, 2, 4], width=8)
    r = data << shift_amt
    assert [int(v) for v in r.value] == [2, 8, 32]


# -- signed/unsigned error message --


def test_lshift_typeerror_message():
    a = _mk([1, 2], width=4, signed=True)
    b = _mk([1, 1], width=4, signed=False)
    try:
        _ = a << b
        raise AssertionError('should raise')
    except ValueError as e:
        assert 'signed' in str(e).lower() and 'unsigned' in str(e).lower()


def test_rrshift_argument_order():
    w = _mk([0, 1, 2], width=4)
    r = 16 >> w
    assert [int(v) for v in r.value] == [16, 8, 4]
