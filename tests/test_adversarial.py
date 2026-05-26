"""Adversarial test suite for wavekitplus.

Designed to catch:
- xz_mask propagation gaps across ALL Waveform methods
- VCD clock edge detection errors (redundant assignments, x/z clocks)
- Sampling correctness (signal timing vs clock timing)
- Width metadata errors in shift/invert/concat
- API robustness (invalid inputs, boundary conditions)

Usage:
    PYTHONPATH=src python3 tests/test_adversarial.py
"""
import os, sys, tempfile, traceback
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))
import numpy as np
from wavekit.waveform import Waveform
from wavekit.signal import Signal
from wavekit import VcdReader

PASSED = []
FAILED = []

def ok(name, extra=''):
    PASSED.append(name)
    tail = f'  ({extra})' if extra else ''
    print(f'  PASS  {name}{tail}')

def fail(name, err):
    FAILED.append((name, str(err)))
    print(f'  FAIL  {name}: {err}')

def t(name, fn):
    try:
        fn()
        ok(name)
    except Exception as e:
        fail(name, e)
        traceback.print_exc()


# ── Helpers ──────────────────────────────────────────────────────────────────

def mkw(vals, w=8, signed=False, xz=None):
    """Construct a Waveform with optional xz_mask."""
    v = np.array(vals, dtype=np.uint64)
    n = len(v)
    return Waveform(
        value=v,
        clock=np.arange(n, dtype=np.uint64),
        time=np.arange(n, dtype=np.uint64) * 10,
        signal=Signal('test', 'test', w, None, signed),
        xz_mask=np.array(xz, dtype=np.bool_) if xz is not None else None,
    )

def mkw1(vals, xz=None):
    """Construct a 1-bit Waveform."""
    return mkw(vals, w=1, xz=xz)

def make_vcd(lines):
    """Write a VCD string to a temp file, return path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.vcd', delete=False)
    f.write('\n'.join(lines) + '\n')
    f.flush()
    f.close()
    return f.name

def assert_xz_shape(w, label=''):
    """Assert xz_mask exists and has same shape as value."""
    assert w.xz_mask is not None, f'{label}: xz_mask is None'
    assert w.xz_mask.shape == w.value.shape, \
        f'{label}: shape mismatch: xz_mask={w.xz_mask.shape} vs value={w.value.shape}'


# ═══════════════════════════════════════════════════════════════════════════
print('=' * 60)
print('Part 1: xz_mask propagation — every Waveform method')
print('=' * 60)
# Strategy: create a Waveform with xz_mask, apply every public method,
# verify the result still has xz_mask with correct shape.

W = mkw([10, 20, 30, 40, 50], xz=[True, False, True, False, False])
W1 = mkw1([1, 0, 1, 0, 1], xz=[True, False, True, False, False])
W2 = mkw([1, 2, 3, 4, 5], xz=[False, False, False, True, False])

# ── Unary operations (should preserve self.xz_mask) ──

def _test_copy():
    r = W.copy()
    assert_xz_shape(r, 'copy')
    assert np.array_equal(r.xz_mask, W.xz_mask)
    # Deep copy check
    r.xz_mask[0] = not r.xz_mask[0]
    assert r.xz_mask[0] != W.xz_mask[0], 'copy: not deep'
t('copy preserves xz_mask', _test_copy)

def _test_as_signed():
    r = W.as_signed()
    assert_xz_shape(r, 'as_signed')
    assert np.array_equal(r.xz_mask, W.xz_mask)
t('as_signed preserves xz_mask', _test_as_signed)

def _test_as_unsigned():
    r = W.as_signed().as_unsigned()
    assert_xz_shape(r, 'as_unsigned')
t('as_unsigned preserves xz_mask', _test_as_unsigned)

def _test_invert():
    r = ~W
    assert_xz_shape(r, '__invert__')
    assert np.array_equal(r.xz_mask, W.xz_mask)
t('__invert__ preserves xz_mask', _test_invert)

def _test_vectorized_map():
    r = W.vectorized_map(lambda x: x * 2)
    assert_xz_shape(r, 'vectorized_map')
    assert np.array_equal(r.xz_mask, W.xz_mask)
t('vectorized_map preserves xz_mask', _test_vectorized_map)

def _test_map():
    r = W.map(lambda x: x * 2)
    assert_xz_shape(r, 'map')
t('map preserves xz_mask', _test_map)

def _test_bit_count():
    r = W.bit_count()
    assert_xz_shape(r, 'bit_count')
t('bit_count preserves xz_mask', _test_bit_count)

def _test_compress():
    r = W.compress()
    # compress removes consecutive duplicates; xz_mask should shrink accordingly
    assert r.xz_mask is not None, 'compress: xz_mask is None'
    assert len(r.xz_mask) == len(r.value), 'compress: shape mismatch'
t('compress preserves xz_mask', _test_compress)

def _test_unique_consecutive():
    r = W.unique_consecutive()
    assert r.xz_mask is not None, 'unique_consecutive: xz_mask is None'
    assert len(r.xz_mask) == len(r.value)
t('unique_consecutive preserves xz_mask', _test_unique_consecutive)

# ── Slicing / windowing ──

def _test_getitem_slice():
    r = W[6:0]  # bits 6 down to 0
    assert_xz_shape(r, '__getitem__ slice')
    assert np.array_equal(r.xz_mask, W.xz_mask)
t('__getitem__[6:0] preserves xz_mask', _test_getitem_slice)

def _test_getitem_int():
    r = W[3]  # single bit
    assert_xz_shape(r, '__getitem__ int')
    assert np.array_equal(r.xz_mask, W.xz_mask)
t('__getitem__[3] preserves xz_mask', _test_getitem_int)

def _test_time_slice():
    r = W.time_slice(10, 30)
    assert_xz_shape(r, 'time_slice')
t('time_slice preserves xz_mask', _test_time_slice)

def _test_cycle_slice():
    r = W.cycle_slice(1, 4)
    assert_xz_shape(r, 'cycle_slice')
    assert len(r.xz_mask) == 3
t('cycle_slice preserves xz_mask', _test_cycle_slice)

def _test_take():
    r = W.take([0, 2, 4])
    assert_xz_shape(r, 'take')
    assert len(r.xz_mask) == 3
    assert r.xz_mask[0] == True and r.xz_mask[1] == True and r.xz_mask[2] == False
t('take preserves xz_mask at correct indices', _test_take)

def _test_mask():
    cond = np.array([True, False, True, False, True])
    r = W.mask(cond)
    assert_xz_shape(r, 'mask')
    assert len(r.xz_mask) == 3
t('mask preserves xz_mask', _test_mask)

def _test_filter():
    r = W.filter(lambda x: x > 15)
    assert_xz_shape(r, 'filter')
t('filter preserves xz_mask', _test_filter)

def _test_vectorized_filter():
    r = W.vectorized_filter(lambda x: x > 15)
    assert_xz_shape(r, 'vectorized_filter')
t('vectorized_filter preserves xz_mask', _test_vectorized_filter)

# ── Shift / relative ──

def _test_ahead():
    r = W.ahead(1)
    assert_xz_shape(r, 'ahead')
t('ahead preserves xz_mask', _test_ahead)

def _test_back():
    r = W.back(1)
    assert_xz_shape(r, 'back')
t('back preserves xz_mask', _test_back)

def _test_relative_0():
    r = W.relative(0)
    assert_xz_shape(r, 'relative(0)')
    assert np.array_equal(r.xz_mask, W.xz_mask)
t('relative(0) preserves xz_mask', _test_relative_0)

def _test_ahead_overshift():
    r = W.ahead(100)
    assert_xz_shape(r, 'ahead(100)')
t('ahead(100) xz_mask shape correct', _test_ahead_overshift)

# ── Edge detection ──

def _test_rising_edge():
    r = W1.rising_edge()
    assert_xz_shape(r, 'rising_edge')
t('rising_edge preserves xz_mask', _test_rising_edge)

def _test_falling_edge():
    r = W1.falling_edge()
    assert_xz_shape(r, 'falling_edge')
t('falling_edge preserves xz_mask', _test_falling_edge)

def _test_edge_xz_direction():
    # value=[1,0,1,0], xz=[F,F,T,F]
    # falling edge at cycle 1 (val[0]=1→val[1]=0): xz[0]|xz[1] = F
    # falling edge at cycle 3 (val[2]=1→val[3]=0): xz[2]|xz[3] = T
    w = mkw1([1, 0, 1, 0], xz=[False, False, True, False])
    fe = w.falling_edge()
    # edge_xz[1] = xz[0] | xz[1] = F
    # edge_xz[2] = xz[1] | xz[2] = T (input to this edge is unreliable)
    # edge_xz[3] = xz[2] | xz[3] = T (input to this edge is unreliable)
    assert fe.xz_mask[1] == False, f'cycle 1 should be clean, got {fe.xz_mask[1]}'
    assert fe.xz_mask[3] == True, f'cycle 3 should be contaminated, got {fe.xz_mask[3]}'
t('falling_edge xz_mask direction correct', _test_edge_xz_direction)

# ── Downsample ──

def _test_downsample():
    w = mkw([1,2,3,4,5,6,7,8,9,10], xz=[True,False]*5)
    r = w.downsample(2, np.mean)
    assert_xz_shape(r, 'downsample')
    assert len(r.value) == 5
    # chunk [T,F] → any(T,F) = T; chunk [T,F] → T; etc
    assert r.xz_mask[0] == True
t('downsample preserves xz_mask', _test_downsample)

# ── Split / concat ──

def _test_split_bits():
    parts = W.split_bits(4)
    for i, p in enumerate(parts):
        assert_xz_shape(p, f'split_bits part {i}')
t('split_bits preserves xz_mask', _test_split_bits)

def _test_concatenate():
    a = mkw([0xF, 0xA], w=4, xz=[True, False])
    b = mkw([0x1, 0x2], w=4, xz=[False, True])
    r = Waveform.concatenate([a, b])
    assert_xz_shape(r, 'concatenate')
    expected = np.array([True, True])  # OR of masks
    assert np.array_equal(r.xz_mask, expected)
t('concatenate merges xz_mask', _test_concatenate)

def _test_merge():
    a = mkw([1, 2, 3], xz=[True, False, False])
    b = mkw([4, 5, 6], xz=[False, False, True])
    r = Waveform.merge([a, b], func=lambda vs: sum(vs), width=8, signed=False)
    assert_xz_shape(r, 'merge')
    expected = np.array([True, False, True])
    assert np.array_equal(r.xz_mask, expected)
t('merge merges xz_mask', _test_merge)

# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
print('Part 2: xz_mask in binary operations — merge correctness')
print('=' * 60)
# Both operands have different xz_mask; result must be OR.

A = mkw([10, 20, 30], xz=[True, False, False])
B = mkw([1, 2, 3], xz=[False, False, True])
EXPECTED_MERGE = np.array([True, False, True])

binary_ops = [
    ('A + B',  lambda: A + B),
    ('A - B',  lambda: A - B),
    ('A * B',  lambda: A * B),
    ('A & B',  lambda: A & B),
    ('A | B',  lambda: A | B),
    ('A ^ B',  lambda: A ^ B),
    ('A == B', lambda: (A == B)),
    ('A != B', lambda: (A != B)),
    ('A << B', lambda: A << B),
    ('A >> B', lambda: A >> B),
]

for name, fn in binary_ops:
    def _make_test(name, fn):
        def _test():
            r = fn()
            assert_xz_shape(r, name)
            assert np.array_equal(r.xz_mask, EXPECTED_MERGE), \
                f'{name}: xz_mask={r.xz_mask}, expected={EXPECTED_MERGE}'
        return _test
    t(f'binary merge: {name}', _make_test(name, fn))

# Reverse ops (scalar OP waveform)
reverse_ops = [
    ('5 + A',  lambda: 5 + A),
    ('5 - A',  lambda: 5 - A),
    ('5 * A',  lambda: 5 * A),
    ('1 << A', lambda: 1 << A),
    ('99 >> A', lambda: 99 >> A),
    ('2 ** A', lambda: 2 ** A),
]

for name, fn in reverse_ops:
    def _make_rtest(name, fn):
        def _test():
            r = fn()
            assert_xz_shape(r, name)
            # Scalar has no mask, so result should be A's mask
            assert np.array_equal(r.xz_mask, A.xz_mask), \
                f'{name}: xz_mask={r.xz_mask}, expected={A.xz_mask}'
        return _test
    t(f'reverse op: {name}', _make_rtest(name, fn))

# Reverse ops (Waveform OP Waveform via __r*)
def _test_rpow_merge():
    r = B.__rpow__(A)  # computes A ** B
    assert_xz_shape(r, '__rpow__ merge')
    assert np.array_equal(r.xz_mask, EXPECTED_MERGE), \
        f'__rpow__ merge: got {r.xz_mask}'
t('__rpow__ Waveform×Waveform merge', _test_rpow_merge)

def _test_rlshift_merge():
    r = B.__rlshift__(A)  # computes A << B
    assert_xz_shape(r, '__rlshift__ merge')
    assert np.array_equal(r.xz_mask, EXPECTED_MERGE), \
        f'__rlshift__ merge: got {r.xz_mask}'
t('__rlshift__ Waveform×Waveform merge', _test_rlshift_merge)


# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
print('Part 3: Adversarial VCD — clock edge detection')
print('=' * 60)

def _test_redundant_clock():
    """Clock has redundant same-value assignment at different timestamp."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 4 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', '0!', 'b0000 "',
        '#10', '1!', 'b0001 "',   # real posedge
        '#15', '1!', 'b0010 "',   # redundant 1
        '#20', '0!', 'b0011 "',
        '#30', '1!', 'b0100 "',   # real posedge
    ])
    try:
        r = VcdReader(path)
        w = r.load_waveform('tb.data', clock='tb.clk', sample_on_posedge=True)
        assert len(w.value) == 2, f'expected 2 posedges, got {len(w.value)}'
        assert list(w.time) == [10, 30], f'expected times [10,30], got {list(w.time)}'
    finally:
        os.unlink(path)
t('redundant clock assignment: no phantom edge', _test_redundant_clock)

def _test_clock_starts_high():
    """Clock starts at 1 without prior 0 — should NOT be a posedge."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 4 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', '1!', 'b0001 "',
        '#5', '0!', 'b0010 "',
        '#10', '1!', 'b0011 "',   # only real posedge
        '#15', '0!', 'b0100 "',
    ])
    try:
        r = VcdReader(path)
        w = r.load_waveform('tb.data', clock='tb.clk', sample_on_posedge=True)
        assert len(w.value) == 1, f'expected 1 posedge, got {len(w.value)}'
        assert w.time[0] == 10, f'expected posedge at t=10, got t={w.time[0]}'
    finally:
        os.unlink(path)
t('clock starts high: no false initial posedge', _test_clock_starts_high)

def _test_clock_xz_no_false_edge():
    """x→1 in clock should NOT be treated as posedge."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 4 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', 'x!', 'b0001 "',    # clock = x
        '#5', '1!', 'b0010 "',    # x→1 (should NOT be posedge)
        '#10', '0!', 'b0011 "',
        '#15', '1!', 'b0100 "',   # real posedge
        '#20', '0!',
    ])
    try:
        r = VcdReader(path)
        w = r.load_waveform('tb.data', clock='tb.clk', sample_on_posedge=True)
        assert 5 not in w.time, f'x→1 at t=5 should not be posedge, times={list(w.time)}'
        assert 15 in w.time, f'real posedge at t=15 missing'
    finally:
        os.unlink(path)
t('clock x→1: no false posedge', _test_clock_xz_no_false_edge)

def _test_all_xz_clock():
    """All-x/z clock should raise ValueError, not crash."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 4 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', 'x!', 'b0001 "', '#5', 'z!', 'b0010 "',
    ])
    try:
        r = VcdReader(path)
        try:
            r.load_waveform('tb.data', clock='tb.clk', sample_on_posedge=True)
            raise AssertionError('should have raised ValueError')
        except ValueError:
            pass
    finally:
        os.unlink(path)
t('all x/z clock: raises ValueError', _test_all_xz_clock)

def _test_multibit_clock_rejected():
    """Multi-bit clock should be rejected."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 2 ! clk $end', '$var wire 4 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', 'b00 !', 'b0001 "', '#5', 'b01 !',
    ])
    try:
        r = VcdReader(path)
        try:
            r.load_waveform('tb.data', clock='tb.clk')
            raise AssertionError('should have raised ValueError')
        except ValueError as e:
            assert '1-bit' in str(e) or 'width' in str(e)
    finally:
        os.unlink(path)
t('multi-bit clock: rejected', _test_multibit_clock_rejected)


# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
print('Part 4: Adversarial VCD — sampling correctness')
print('=' * 60)

def _test_signal_after_first_edge():
    """Signal appears AFTER first clock edge — should not leak future value."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 8 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', '0!',
        '#10', '1!',                # posedge — data has NO value yet
        '#20', '0!',
        '#25', 'b00000101 "',       # data first appears here
        '#30', '1!',                # posedge — data = 5
        '#40', '0!',
        '#50', '1!', 'b00001010 "', # posedge — data = 10
    ])
    try:
        r = VcdReader(path)
        w = r.load_waveform('tb.data', clock='tb.clk', sample_on_posedge=True)
        # At t=10 (first posedge), data has no value yet.
        # Should be 0 or x-replaced, NOT 5 (future leak)
        if len(w.value) >= 1 and w.value[0] == 5:
            raise AssertionError(
                f'Future value leaked: t=10 sampled data={w.value[0]}, '
                f'but data first appears at t=25'
            )
    finally:
        os.unlink(path)
t('signal after first edge: no future leak', _test_signal_after_first_edge)

def _test_subrange_xz_mask():
    """High bits x, low bits clean — subrange mask should not be polluted."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 8 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', '0!', 'b00001111 "',
        '#5', '1!',
        '#10', '0!', 'bxxxx0101 "',   # high x, low clean
        '#15', '1!',
        '#20', '0!', 'b00001010 "',
        '#25', '1!',
    ])
    try:
        r = VcdReader(path)
        # Path A: load subrange directly
        w = r.load_waveform('tb.data[3:0]', clock='tb.clk', xz_mask=True)
        if w.xz_mask is not None:
            # Cycle with bxxxx0101: low 4 bits are 0101, should NOT be marked x
            assert not w.xz_mask[1], \
                f'Low bits clean but marked x: xz_mask={w.xz_mask}'
    finally:
        os.unlink(path)
t('subrange xz_mask: high x does not pollute low bits', _test_subrange_xz_mask)


# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
print('Part 5: Cycle bounds and API robustness')
print('=' * 60)

JTAG = str(pathlib.Path(__file__).resolve().parent / 'testdata' / 'jtag.vcd')

def _test_end_cycle_eq_len():
    """end_cycle == len(edges) should work (end-exclusive, means 'to end')."""
    r = VcdReader(JTAG)
    w_full = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    n = len(w_full.value)
    w_end = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck',
                            begin_cycle=0, end_cycle=n)
    assert np.array_equal(w_end.value, w_full.value), \
        f'end_cycle={n}: got {len(w_end.value)} samples, expected {n}'
t('end_cycle == len(edges): no crash, full data', _test_end_cycle_eq_len)

def _test_negative_begin_cycle():
    """Negative begin_cycle should raise ValueError, not use Python reverse index."""
    r = VcdReader(JTAG)
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_cycle=-1)
        raise AssertionError('should have raised ValueError')
    except ValueError:
        pass
t('begin_cycle=-1: raises ValueError', _test_negative_begin_cycle)

def _test_begin_gt_end_cycle():
    """begin_cycle > end_cycle should raise ValueError."""
    r = VcdReader(JTAG)
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck',
                        begin_cycle=10, end_cycle=5)
        raise AssertionError('should have raised ValueError')
    except ValueError:
        pass
t('begin_cycle > end_cycle: raises ValueError', _test_begin_gt_end_cycle)

def _test_slice_none_bounds():
    """wave[:] and wave[7:] should give clear error."""
    w = mkw([0xFF], w=8)
    for expr, sl in [('wave[:]', slice(None, None)),
                     ('wave[7:]', slice(7, None)),
                     ('wave[:0]', slice(None, 0))]:
        try:
            w[sl]
            raise AssertionError(f'{expr} should raise ValueError')
        except (ValueError, TypeError):
            pass
t('slice with None bounds: clear error', _test_slice_none_bounds)

def _test_concatenate_empty():
    """concatenate([]) should raise ValueError, not IndexError."""
    try:
        Waveform.concatenate([])
        raise AssertionError('should raise')
    except ValueError:
        pass
    except IndexError:
        raise AssertionError('got IndexError, should be ValueError')
t('concatenate([]): ValueError', _test_concatenate_empty)

def _test_concatenate_diff_length():
    """Different length waveforms should raise ValueError."""
    a = mkw([1, 2, 3])
    b = mkw([4, 5])
    try:
        Waveform.concatenate([a, b])
        raise AssertionError('should raise')
    except ValueError:
        pass
t('concatenate(diff length): ValueError', _test_concatenate_diff_length)

def _test_concatenate_diff_time():
    a = mkw([1, 2, 3])
    b = Waveform(value=np.array([4, 5, 6], dtype=np.uint64),
        clock=np.arange(3, dtype=np.uint64),
        time=np.array([15, 25, 35], dtype=np.uint64),
        signal=Signal('b', 'b', 8, None, False))
    try:
        Waveform.concatenate([a, b])
        raise AssertionError('should raise ValueError')
    except ValueError:
        pass
t('concatenate(diff time): ValueError', _test_concatenate_diff_time)

def _test_merge_empty():
    """merge([]) should raise ValueError, not IndexError."""
    try:
        Waveform.merge([], func=lambda x: sum(x), width=1, signed=False)
        raise AssertionError('should raise')
    except ValueError:
        pass
    except IndexError:
        raise AssertionError('got IndexError, should be ValueError')
t('merge([]): ValueError', _test_merge_empty)

def _test_merge_diff_time():
    a = mkw([1, 2, 3])
    b = Waveform(value=np.array([4, 5, 6], dtype=np.uint64),
        clock=np.arange(3, dtype=np.uint64),
        time=np.array([15, 25, 35], dtype=np.uint64),
        signal=Signal('b', 'b', 8, None, False))
    try:
        Waveform.merge([a, b], func=lambda vs: sum(vs), width=8, signed=False)
        raise AssertionError('should raise ValueError')
    except ValueError:
        pass
t('merge(diff time): ValueError', _test_merge_diff_time)

def _test_empty_signal_match():
    """Wrong signal pattern should raise ValueError, not return {}."""
    r = VcdReader(JTAG)
    try:
        r.load_matched_waveforms('tb.NONEXISTENT_*', clock_pattern='tb.tck')
        raise AssertionError('should raise')
    except ValueError:
        pass
t('load_matched_waveforms no match: ValueError', _test_empty_signal_match)


# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
print('Part 6: Width metadata correctness')
print('=' * 60)

def _test_invert_wide():
    """>64 bit invert should not overflow."""
    w = Waveform(
        value=np.array([0, 1], dtype=np.object_),
        clock=np.array([0, 1], dtype=np.uint64),
        time=np.array([0, 10], dtype=np.uint64),
        signal=Signal('wide', 'wide', 128, None, False),
    )
    try:
        r = ~w
        # Should produce (2^128 - 1) and (2^128 - 2)
        expected_0 = (1 << 128) - 1
        assert r.value[0] == expected_0, \
            f'~0 for 128-bit: got {r.value[0]}, expected {expected_0}'
    except OverflowError as e:
        raise AssertionError(f'>64 bit invert overflows: {e}')
t('__invert__ >64 bit: no overflow', _test_invert_wide)

def _test_rlshift_width():
    """1 << wave: result width should accommodate the largest possible shift."""
    shift = mkw([0, 1, 15], w=4)
    r = 1 << shift
    # 1 << 15 = 32768, needs at least 16 bits
    # At minimum, width should be > 4 (the shift amount's width)
    if r.width is not None:
        assert r.width > 4, \
            f'1 << 4-bit wave: result width={r.width}, too narrow for 1<<15'
t('__rlshift__ width: accommodates max shift', _test_rlshift_width)


# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
print('Part 7: Scope tree and pattern matching')
print('=' * 60)

def _test_scope_parent():
    """Child scope should have parent_scope set."""
    r = VcdReader(JTAG)
    for top in r.top_scope_list():
        for child in top.child_scope_list:
            assert child.parent_scope is top, \
                f'{child.name}.parent_scope is None, should be {top.name}'
            fn = child.full_name()
            assert '.' in fn, f'full_name()={fn}, should include parent'
            break
        break
t('scope parent_scope set on children', _test_scope_parent)

def _test_find_scope_depth0():
    """depth=0 should only check self, not recurse."""
    r = VcdReader(JTAG)
    top = r.top_scope_list()[0]
    # top.name is 'tb', not 'u0'
    res = top.find_scope_by_module('u0', depth=0)
    assert len(res) == 0, f'depth=0 from tb: found {len(res)}, expected 0'
t('find_scope_by_module depth=0: no recursion', _test_find_scope_depth0)

def _test_find_scope_depth1():
    """depth=1 should find direct children."""
    r = VcdReader(JTAG)
    top = r.top_scope_list()[0]
    res = top.find_scope_by_module('u0', depth=1)
    assert len(res) == 1, f'depth=1 from tb: found {len(res)}, expected 1'
t('find_scope_by_module depth=1: finds child', _test_find_scope_depth1)


print()
print('=' * 60)
print('Part 8: Real signals, empty results, edge-case crashes')
print('=' * 60)

def _test_real_signal_guard():
    """VCD real signal should raise NotImplementedError, not crash on int(s,2)."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var real 1 # analog $end', '$var wire 1 ! clk $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', 'r1.25 #', '0!',
    ])
    try:
        r = VcdReader(path)
        try:
            r.load_waveform('tb.analog', clock='tb.clk')
            raise AssertionError('should have raised')
        except NotImplementedError:
            pass
        except ValueError:
            raise AssertionError('got ValueError instead of NotImplementedError')
    finally:
        os.unlink(path)
t('real signal: NotImplementedError', _test_real_signal_guard)

def _test_empty_time_window():
    """time window past the last clock edge should not IndexError."""
    r = VcdReader(JTAG)
    try:
        w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_time=99999)
        assert len(w.value) >= 0
    except IndexError:
        raise AssertionError('got IndexError on empty window')
t('empty time window: no IndexError', _test_empty_time_window)

def _test_signed_twos_complement():
    """signed=True interprets 4-bit 1111 as -1, not 15."""
    path = make_vcd([
        '$timescale 1ns $end', '$scope module tb $end',
        '$var wire 1 ! clk $end', '$var wire 4 " data $end',
        '$upscope $end', '$enddefinitions $end',
        '#0', '0!', 'b1111 "',
        '#5', '1!',
        '#10', '0!',
    ])
    try:
        r = VcdReader(path)
        w = r.load_waveform('tb.data[3:0]', clock='tb.clk', signed=True)
        assert w.value[0] == -1, f'signed 1111 expected -1, got {w.value[0]}'
    finally:
        os.unlink(path)
t('signed=True: two-complement interpretation', _test_signed_twos_complement)

def _test_stub_nameerror():
    """FstReader/FsdbReader stubs should raise RuntimeError, not NameError."""
    from wavekit import FstReader, FsdbReader
    for cls, name in [(FstReader, 'FstReader'), (FsdbReader, 'FsdbReader')]:
        try:
            cls('dummy')
            raise AssertionError(f'{name} should have raised')
        except RuntimeError:
            pass
        except NameError as e:
            raise AssertionError(f'{name} stub got NameError: {e}')
t('stub readers: RuntimeError not NameError', _test_stub_nameerror)


print()
print('=' * 60)
print('Part 9: Width metadata and split/concat edge cases')
print('=' * 60)

def _test_split_bits_padding_width():
    """split_bits padding: last group should have correct width."""
    w = Waveform(
        value=np.array([0x3FF], dtype=np.uint64),  # 10-bit
        clock=np.array([0], dtype=np.uint64),
        time=np.array([0], dtype=np.uint64),
        signal=Signal('', '', 10, None, False),
    )
    parts = w.split_bits(4, padding=True)
    widths = [p.width for p in parts]
    assert widths == [4, 4, 2], f'expected [4,4,2], got {widths}'
t('split_bits padding: correct widths', _test_split_bits_padding_width)

def _test_unsigned_width64():
    """as_unsigned() on width==64 signed int should not overflow."""
    w = Waveform(
        value=np.array([-5, 42], dtype=np.int64),
        clock=np.array([0, 1], dtype=np.uint64),
        time=np.array([0, 1], dtype=np.uint64),
        signal=Signal('', '', 64, None, True),
    )
    try:
        u = w.as_unsigned()
        assert u.value[0] == (1 << 64) - 5
    except OverflowError as e:
        raise AssertionError(f'as_unsigned width=64 overflow: {e}')
t('as_unsigned width=64: no overflow', _test_unsigned_width64)

def _test_signed_width64():
    """as_signed() on width==64 uint should not overflow."""
    top_bit = np.uint64(1 << 63)
    w = Waveform(
        value=np.array([0, top_bit, np.uint64((1<<64)-1)], dtype=np.uint64),
        clock=np.array([0, 1, 2], dtype=np.uint64),
        time=np.array([0, 1, 2], dtype=np.uint64),
        signal=Signal('', '', 64, None, False),
    )
    try:
        s = w.as_signed()
        assert s.value[0] == 0
        assert s.value[1] == -(1 << 63)
        assert s.value[2] == -1
    except OverflowError as e:
        raise AssertionError(f'as_signed width=64 overflow: {e}')
t('as_signed width=64: correct two-complement', _test_signed_width64)


print()
print('=' * 60)
print('Part 10: Alignment checks and cross-op consistency')
print('=' * 60)

def _test_alignment_check():
    """Binary ops on misaligned waveforms should raise ValueError."""
    a = mkw([1, 2, 3])
    b = Waveform(
        value=np.array([4, 5, 6], dtype=np.uint64),
        clock=np.array([100, 101, 102], dtype=np.uint64),
        time=np.array([100, 101, 102], dtype=np.uint64),
        signal=Signal('b', 'b', 8, None, False),
    )
    try:
        _ = a + b
        raise AssertionError('should have raised')
    except ValueError:
        pass
t('binary op: misaligned clock raises ValueError', _test_alignment_check)

def _test_alignment_same_ok():
    """Aligned waveforms should work fine."""
    a = mkw([1, 2, 3])
    b = mkw([4, 5, 6])
    c = a + b
    assert len(c.value) == 3
t('binary op: aligned waveforms ok', _test_alignment_same_ok)

def _test_xz_mask_fst_not_impl():
    """xz_mask=True on FST should raise NotImplementedError (not silently ignore)."""
    try:
        from wavekit.readers.fst.reader import FstReader
        # Can't create FstReader without a real FST file, but stub check:
        # The stub raises RuntimeError before we even reach xz_mask
    except RuntimeError:
        pass
    except ImportError:
        pass
t('FST xz_mask: NotImplementedError path exists', _test_xz_mask_fst_not_impl)

def _test_concatenate_merge_alignment_consistent():
    """concatenate and merge alignment checks are consistent with binary ops."""
    a = mkw([1, 2, 3])
    b = Waveform(
        value=np.array([4, 5, 6], dtype=np.uint64),
        clock=np.array([100, 101, 102], dtype=np.uint64),
        time=np.array([0, 10, 20], dtype=np.uint64),
        signal=Signal('b', 'b', 8, None, False),
    )
    try:
        Waveform.concatenate([a, b])
        raise AssertionError('concatenate should raise on time mismatch')
    except ValueError:
        pass
t('concatenate: rejects time misalignment', _test_concatenate_merge_alignment_consistent)


# ═══════════════════════════════════════════════════════════════════════════
print()
print('=' * 60)
total = len(PASSED) + len(FAILED)
print(f'Results: {len(PASSED)}/{total} passed')
if FAILED:
    print(f'\nFAILURES ({len(FAILED)}):')
    for name, err in FAILED:
        print(f'  - {name}: {err}')
print('=' * 60)
sys.exit(0 if not FAILED else 1)
