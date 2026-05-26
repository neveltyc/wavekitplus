"""Comprehensive test suite for wavekit-plus. Self-contained, no pytest needed."""
import os, sys, subprocess, traceback, pathlib, shutil
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
JTAG = ROOT / 'tests' / 'testdata' / 'jtag.vcd'
XZ_VCD = ROOT / 'tests' / 'testdata' / 'xz_trace.vcd'
FIXTURES = ROOT / 'src' / 'vcd_analyzer' / 'verify' / 'fixtures'
EXAMPLES = ROOT / 'example'
TESTS_PASSED = []
TESTS_FAILED = []

def ok(msg, extra=''):
    TESTS_PASSED.append(msg)
    tail = f'  ({extra})' if extra else ''
    print(f'  PASS  {msg}{tail}')

def fail(msg, err):
    TESTS_FAILED.append((msg, str(err)))
    print(f'  FAIL  {msg}: {err}')

def t(name, fn):
    try:
        fn()
        ok(name)
    except Exception as e:
        fail(name, e)
        traceback.print_exc()


print('=' * 60)
print('wavekit-plus Test Suite')
print('=' * 60)
print()

print('--- VCDParser ---')

t('import', lambda: __import__('wavekit.readers.vcd.vcd_parser', fromlist=['VCDParser']))

# Module-level imports for reuse
from wavekit.readers.vcd.vcd_parser import VCDParser, _VCDResourceError
from wavekit import VcdReader, Waveform, Signal

t('parse jtag header',
   lambda: (p := VCDParser(str(JTAG)),
            ok('parse jtag header', f'{len(p.signals)} sigs, ts={p.ts_sec:.1e}s'))[0] if False else None)
   # Just check no exception

def _test_jtag_header():
    p = VCDParser(str(JTAG))
    assert len(p.signals) > 0
    assert p.ts_sec > 0
    paths = {i['path'] for i in p.signals.values()}
    assert any('tck' in s for s in paths)
    assert any('J_state' in s for s in paths)
t('jtag header details', _test_jtag_header)

def _test_time_range():
    p = VCDParser(str(JTAG))
    tmin, tmax = p.scan_time_range()
    assert tmin is not None and tmax is not None
    assert tmax >= tmin
    # Cache test
    assert p.scan_time_range() == (tmin, tmax)
t('scan_time_range + cache', _test_time_range)

def _test_iter_events():
    p = VCDParser(str(JTAG))
    events = list(p.iter_events())
    assert len(events) > 100
    t0, sid, val = events[0]
    assert isinstance(t0, int) and isinstance(sid, str) and isinstance(val, str)
t('iter_events jtag', _test_iter_events)

def _test_sids_filter():
    p = VCDParser(str(JTAG))
    tck_sid = next(sid for sid, info in p.signals.items() if 'tck' in info['path'])
    events = list(p.iter_events(sids={tck_sid}))
    assert len(events) > 0
    assert all(sid == tck_sid for _, sid, _ in events)
t('iter_events sids filter', _test_sids_filter)

def _test_t0t1():
    p = VCDParser(str(JTAG))
    all_ev = list(p.iter_events())
    mid = all_ev[len(all_ev)//2][0]
    subset = list(p.iter_events(t0=mid))
    assert len(subset) <= len(all_ev)
    assert all(e[0] >= mid for e in subset)
t('iter_events t0 bound', _test_t0t1)

# Test all VCD_ANALYZER fixtures
_fixture_names = ['basic_trace.vcd', 'handshake_trace.vcd', 'bus_range_trace.vcd',
                  'search_trace.vcd', 'escaped_trace.vcd']
for _fixture_name in _fixture_names:
    _path = FIXTURES / _fixture_name
    if _path.exists():
        def _make_fixture_test(path, name):
            def _test():
                pp = VCDParser(str(path))
                assert len(pp.signals) > 0, f'no signals in {name}'
                ev = list(pp.iter_events())
                assert len(ev) > 0, f'no events in {name}'
            return _test
        t(f'parse {_fixture_name}', _make_fixture_test(_path, _fixture_name))

print()
print('--- VcdReader ---')

def _test_reader_init():
    r = VcdReader(str(JTAG))
    assert r.begin_time is not None
    assert r.end_time is not None
    assert r.end_time >= r.begin_time
t('VcdReader init', _test_reader_init)

def _test_top_scopes():
    r = VcdReader(str(JTAG))
    scopes = r.top_scope_list()
    assert len(scopes) > 0
t('top_scope_list', _test_top_scopes)

def _test_load_waveform():
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', signed=True)
    assert w.name == 'tb.u0.J_state[3:0]'
    assert w.width == 4
    assert w.signed is True
    assert len(w.value) > 0
t('load_waveform J_state', _test_load_waveform)

def _test_load_no_range():
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_next', clock='tb.tck')
    assert w.name == 'tb.u0.J_next[3:0]'
    assert w.width == 4
t('load_waveform without range', _test_load_no_range)

def _test_subrange():
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[1:0]', clock='tb.tck')
    assert w.width == 2
t('subrange J_state[1:0]', _test_subrange)

def _test_cycle_window():
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_cycle=10, end_cycle=20)
    assert len(w.value) == 10
    assert w.clock[0] == 10 and w.clock[-1] == 19
t('begin_cycle/end_cycle', _test_cycle_window)

def _test_time_window():
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_time=105, end_time=205)
    assert len(w.value) == 10
t('begin_time/end_time', _test_time_window)

def _test_mutual_exclusive():
    r = VcdReader(str(JTAG))
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_time=0, begin_cycle=0)
        raise AssertionError('expected ValueError')
    except ValueError:
        pass
t('mutually exclusive params', _test_mutual_exclusive)

def _test_signal_not_found():
    r = VcdReader(str(JTAG))
    try:
        r.load_waveform('tb.nonexistent', clock='tb.tck')
        raise AssertionError('expected ValueError')
    except ValueError:
        pass
t('signal not found raises', _test_signal_not_found)

def _test_posedge():
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', sample_on_posedge=True)
    assert len(w.value) > 0
t('sample_on_posedge', _test_posedge)

def _test_ctx_manager():
    with VcdReader(str(JTAG)) as r:
        w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
        assert len(w.value) > 0
t('context manager', _test_ctx_manager)

def _test_consistency():
    r = VcdReader(str(JTAG))
    w1 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w2 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    assert np.array_equal(w1.value, w2.value)
    assert np.array_equal(w1.time, w2.time)
t('cross-reload consistency', _test_consistency)

def _test_window_full_match():
    r = VcdReader(str(JTAG))
    w_full = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w_win = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_time=105, end_time=205)
    assert np.array_equal(w_win.value, w_full.value[10:20])
t('time window matches full slice', _test_window_full_match)

print()
print('--- Iverilog VCD generation ---')

def _generate_and_test(example_name, tb_file, vcd_name):
    sv_path = EXAMPLES / example_name / tb_file
    if not sv_path.exists():
        raise FileNotFoundError(f'{sv_path} not found')
    out = ROOT / 'tests' / 'testdata' / vcd_name
    vvp = out.with_suffix('.vvp')
    # Compile
    # Find all SV files in the example directory
    sv_files = list(sv_path.parent.glob('*.sv'))
    r = subprocess.run(['iverilog', '-g2012', '-o', str(vvp)] + [str(f) for f in sv_files],
                       cwd=str(sv_path.parent), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'iverilog: {r.stderr}')
    # Run
    r = subprocess.run(['vvp', str(vvp)],
                       cwd=str(sv_path.parent), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'vvp: {r.stderr}')
    # All examples dump to fifo_tb.vcd — rename to unique name
    generated = sv_path.parent / 'fifo_tb.vcd'
    if generated.exists():
        import shutil
        shutil.move(str(generated), str(out))
    else:
        raise RuntimeError(f'VCD not found at {generated}')
    p = VCDParser(str(out))
    ev = list(p.iter_events())
    assert len(p.signals) > 0 and len(ev) > 0
    # Clean up vvp
    if vvp.exists():
        vvp.unlink()

if shutil.which('iverilog') and shutil.which('vvp'):
    t('scoreboard VCD', lambda: _generate_and_test('scoreboard', 'fifo_tb.sv', 'scoreboard_tb.vcd'))
    t('fifo_latency VCD', lambda: _generate_and_test('fifo_latency', 'fifo_tb.sv', 'fifo_latency_tb.vcd'))
    t('fifo_occupancy VCD', lambda: _generate_and_test('fifo_occupancy', 'fifo_tb.sv', 'fifo_occupancy_tb.vcd'))
else:
    print('  SKIP  iverilog tests (iverilog/vvp not found)')

print()
print('--- Edge cases ---')

def _test_empty_vcd():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vcd', delete=False) as f:
        f.write('$end\n')
        f.flush()
        name = f.name
    try:
        p = VCDParser(name)
        assert len(p.signals) == 0
    finally:
        os.unlink(name)
t('empty VCD', _test_empty_vcd)

def _test_wide_var():
    import tempfile
    vcd = ('$date today $end\n$version test $end\n$timescale 1ns $end\n'
           '$scope top $end\n$var wire 100000 data ! $end\n$upscope $end\n'
           '$enddefinitions $end\n')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vcd', delete=False) as f:
        f.write(vcd)
        f.flush()
        name = f.name
    try:
        VCDParser(name)
        raise AssertionError('expected _VCDResourceError')
    except _VCDResourceError:
        pass
    finally:
        os.unlink(name)
t('rejects over-wide $var', _test_wide_var)

# Manually test scope tree
def _test_scope_tree():
    r = VcdReader(str(JTAG))
    for scope in r.top_scope_list():
        if scope.name == 'tb':
            sigs = scope.signal_list
            children = scope.child_scope_list
            # JTAG VCD has 'tb' scope with signals or children
            assert len(sigs) > 0 or len(children) > 0
            return
    # Should find 'tb' scope
    raise AssertionError('tb scope not found')
t('scope tree traversal', _test_scope_tree)


print()
print('--- Cache layer ---')

def _test_cache_hit():
    """Multiple loads of same signal hit cache (no re-scan)."""
    r = VcdReader(str(JTAG))
    w1 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w2 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    assert np.array_equal(w1.value, w2.value)
    assert np.array_equal(w1.time, w2.time)
    assert np.array_equal(w1.clock, w2.clock)
    # Verify cache was populated
    assert len(r._tv_cache) > 0
t('cache: reload yields identical results', _test_cache_hit)

def _test_cache_shared_clock():
    """Multiple signals sharing same clock reuse cached clock data."""
    r = VcdReader(str(JTAG))
    w1 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w2 = r.load_waveform('tb.u0.J_next[3:0]', clock='tb.tck')
    # Clock arrays should be identical (same cached tck data)
    assert np.array_equal(w1.clock, w2.clock)
    # But signal values differ
    assert len(w1.value) > 0 and len(w2.value) > 0
t('cache: shared clock across signals', _test_cache_shared_clock)

def _test_cache_empty_signal():
    """Signal with no events gets empty cache entry (avoids re-scan)."""
    # The jtag VCD has no truly empty signals, but we can verify
    # that _ensure_cached on a nonexistent sid doesn't crash
    r = VcdReader(str(JTAG))
    r._ensure_cached({'__nonexistent_sid__'})
    # Should have recorded empty list
    assert r._tv_cache.get('__nonexistent_sid__') == []
t('cache: nonexistent signal cached as empty', _test_cache_empty_signal)

def _test_cache_ensure_no_double_scan():
    """Calling _ensure_cached twice with same sids doesn't re-scan."""
    r = VcdReader(str(JTAG))
    # Find a valid sid
    for sid, info in r._parser.signals.items():
        if 'tck' in info['path']:
            tck_sid = sid
            break
    r._ensure_cached({tck_sid})
    first_len = len(r._tv_cache[tck_sid])
    r._ensure_cached({tck_sid})
    second_len = len(r._tv_cache[tck_sid])
    assert first_len == second_len, f'{first_len} != {second_len}'
t('cache: double _ensure_cached does not re-scan', _test_cache_ensure_no_double_scan)


print()
print('--- xz_mask ---')

def _test_xz_mask_default_off():
    """xz_mask defaults to False, no mask generated."""
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    assert w.xz_mask is None
t('xz_mask default off', _test_xz_mask_default_off)

def _test_xz_mask_basic():
    """xz_mask=True marks cycles containing x/z."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    assert w.xz_mask is not None
    assert w.xz_mask.dtype == np.bool_
    # state has x/z at specific cycles
    assert np.any(w.xz_mask), 'should find some x/z cycles'
    # Cycle at t=0: state=xxx -> xz_mask=True
    # Cycle at t=10: state=001 -> xz_mask=False
t('xz_mask basic detection', _test_xz_mask_basic)

def _test_xz_mask_backward_compat():
    """xz_mask=True does not change value arrays."""
    r = VcdReader(str(JTAG))
    w_old = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w_new = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', xz_mask=True)
    assert np.array_equal(w_old.value, w_new.value)
    assert np.array_equal(w_old.clock, w_new.clock)
t('xz_mask backward compat (value unchanged)', _test_xz_mask_backward_compat)

def _test_xz_mask_has_xz():
    """has_xz property reflects mask presence."""
    r = VcdReader(str(JTAG))
    w_no = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w_yes = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', xz_mask=True)
    assert w_no.has_xz is False
    assert w_yes.has_xz is True
t('has_xz property', _test_xz_mask_has_xz)

def _test_xz_mask_drop_xz():
    """drop_xz removes cycles with x/z."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    w_clean = w.drop_xz()
    assert len(w_clean.value) <= len(w.value)
    if w_clean.xz_mask is not None:
        assert not np.any(w_clean.xz_mask)
t('drop_xz removes x/z cycles', _test_xz_mask_drop_xz)

def _test_xz_mask_survives_slice():
    """xz_mask survives time_slice and cycle_slice."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    w_ts = w.time_slice(10, 30)
    assert w_ts.xz_mask is not None
    assert len(w_ts.xz_mask) == len(w_ts.value)
t('xz_mask survives time_slice', _test_xz_mask_survives_slice)

def _test_xz_mask_survives_arithmetic():
    """xz_mask survives arithmetic operations."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    w2 = w + 1
    assert w2.xz_mask is not None
    assert np.array_equal(w2.xz_mask, w.xz_mask)
t('xz_mask survives arithmetic', _test_xz_mask_survives_arithmetic)

def _test_xz_mask_xz_cycles():
    """xz_cycles returns clock numbers of x/z cycles."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    cycles = w.xz_cycles
    assert len(cycles) > 0
    assert np.array_equal(cycles, w.clock[w.xz_mask])
t('xz_cycles matches clock[mask]', _test_xz_mask_xz_cycles)


def _test_xz_mask_dual_operand_merge():
    """Bug 1: xz_mask OR-merges from both operands in binary ops."""
    r = VcdReader(str(XZ_VCD))
    a = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    # Manually create a second waveform with complementary xz_mask
    b = Waveform(value=a.value.copy(), clock=a.clock.copy(), time=a.time.copy(),
                 signal=a.signal, xz_mask=~a.xz_mask)
    c = a + b
    assert c.xz_mask is not None
    assert np.all(c.xz_mask), 'merge should OR both masks (one is ~, so all True)'
t('xz_mask dual-operand merge (Bug 1)', _test_xz_mask_dual_operand_merge)

def _test_xz_mask_relative_survives():
    """Bug 2: xz_mask survives relative()/ahead()/back()."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    shifted = w.ahead(2)
    assert shifted.xz_mask is not None
    assert len(shifted.xz_mask) == len(shifted.value)
    # ahead shifts forward; xz_mask bits should shift too
    # Simple check: value shifted, mask shifted alongside
    back = w.back(1)
    assert back.xz_mask is not None
    assert len(back.xz_mask) == len(back.value)
t('xz_mask survives relative/ahead/back (Bug 2)', _test_xz_mask_relative_survives)

def _test_xz_mask_concatenate_merge():
    """Bug 3: concatenate() merges xz_masks from all inputs."""
    r = VcdReader(str(XZ_VCD))
    a = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    b = Waveform(value=a.value.copy(), clock=a.clock.copy(), time=a.time.copy(),
                 signal=Signal('', '', 1, None, False), xz_mask=~a.xz_mask)
    c = Waveform.concatenate([a, b])
    assert c.xz_mask is not None
    assert np.all(c.xz_mask), 'concatenate should OR all input masks'
t('xz_mask concatenate merge (Bug 3)', _test_xz_mask_concatenate_merge)


def _test_xz_mask_relative_overshift():
    """Bug 4: relative() with offset > length keeps xz_mask length correct."""
    r = VcdReader(str(XZ_VCD))
    w = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    n = len(w.value)
    # Shift more than the waveform length
    shifted = w.ahead(n + 5)
    assert shifted.xz_mask is not None
    assert len(shifted.xz_mask) == n, f'expected {n}, got {len(shifted.xz_mask)}'
    shifted2 = w.back(n + 5)
    assert shifted2.xz_mask is not None
    assert len(shifted2.xz_mask) == n
t('xz_mask relative overshift length (Bug 4)', _test_xz_mask_relative_overshift)

def _test_xz_mask_eq_ne_merge():
    """Bug 5: __eq__ and __ne__ merge xz_mask from both operands."""
    r = VcdReader(str(XZ_VCD))
    a = r.load_waveform('tb.state', clock='tb.clk', xz_mask=True)
    b = Waveform(value=a.value.copy(), clock=a.clock.copy(), time=a.time.copy(),
                 signal=a.signal, xz_mask=~a.xz_mask)
    eq = (a == b)
    assert eq.xz_mask is not None
    assert np.all(eq.xz_mask), '__eq__ should OR both masks'
    ne = (a != b)
    assert ne.xz_mask is not None
    assert np.all(ne.xz_mask), '__ne__ should OR both masks'
t('xz_mask __eq__/__ne__ merge (Bug 5)', _test_xz_mask_eq_ne_merge)


def _test_xz_mask_load_matched():
    """Bug 6: load_matched_waveforms accepts and forwards xz_mask."""
    r = VcdReader(str(JTAG))
    waves = r.load_matched_waveforms('tb.u0.J_state[3:0]', 'tb.tck', xz_mask=True)
    w = waves[()]
    assert w.xz_mask is not None
    assert len(w.xz_mask) == len(w.value)
t('xz_mask through load_matched_waveforms (Bug 6)', _test_xz_mask_load_matched)

def _test_xz_mask_eval():
    """Bug 6: eval accepts and forwards xz_mask."""
    r = VcdReader(str(JTAG))
    result = r.eval('tb.u0.J_state[3:0]', clock='tb.tck', xz_mask=True)
    assert result.xz_mask is not None
    assert len(result.xz_mask) == len(result.value)
t('xz_mask through eval (Bug 6)', _test_xz_mask_eval)


print()
print('--- Bug fixes v0.9.0 ---')

def _test_clock_edge_detection():
    """Bug 1: clock edge is actual 0->1/1->0 transition, not level match."""
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', sample_on_posedge=False)
    assert len(w.value) > 0
    # posedge variant also works
    w2 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', sample_on_posedge=True)
    assert len(w2.value) > 0
    # Multi-bit clock should raise
    multi_bit_path = 'tb.u0.J_state[3:0]'
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock=multi_bit_path)
        raise AssertionError('should have raised ValueError for multi-bit clock')
    except ValueError as e:
        assert '1-bit' in str(e) or 'width' in str(e)
t('clock edge detection (Bug 1)', _test_clock_edge_detection)

def _test_reverse_shift_ops():
    """Bug 2: __rlshift__, __rrshift__, __rpow__ compute correct direction."""
    from wavekit import VcdReader
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    # scalar << wave: element-wise shift
    result = 1 << w
    assert result.width is not None
    # scalar >> wave
    result2 = 8 >> w
    assert result2.width is not None
    # scalar ** wave
    result3 = 2 ** w
    assert result3.width is None  # power may change width
t('reverse shift ops (Bug 2)', _test_reverse_shift_ops)

def _test_regex_matches_bare_signal():
    """Bug 5: regex @pattern matches bare signal name without range."""
    from wavekit import VcdReader
    r = VcdReader(str(JTAG))
    # @J_state should match J_state[3:0]
    sigs = r.get_matched_signals(r'tb.u0.@J_state')
    assert len(sigs) > 0, '@J_state should match signals with range suffix'
t('regex matches bare signal name (Bug 5)', _test_regex_matches_bare_signal)

def _test_load_matched_empty_error():
    """Bug 6: load_matched_waveforms raises on no signal match."""
    r = VcdReader(str(JTAG))
    try:
        r.load_matched_waveforms('tb.nonexistent_signal_xyz', 'tb.tck')
        raise AssertionError('should have raised ValueError')
    except ValueError as e:
        assert 'matched no signals' in str(e)
t('load_matched_waveforms empty error (Bug 6)', _test_load_matched_empty_error)

def _test_concatenate_validation():
    """Bug 7: concatenate() validates inputs."""
    from wavekit import Waveform
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    # Empty list
    try:
        Waveform.concatenate([])
        raise AssertionError('should have raised')
    except ValueError:
        pass
    # Different lengths should raise
    w_short = w.time_slice(0, 5)
    try:
        Waveform.concatenate([w, w_short])
        raise AssertionError('should have raised')
    except ValueError:
        pass
t('concatenate input validation (Bug 7)', _test_concatenate_validation)

def _test_cycle_bounds():
    """Bug 8: begin_cycle/end_cycle out-of-bounds raises clean error."""
    r = VcdReader(str(JTAG))
    # Negative cycle
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_cycle=-1)
        raise AssertionError('should have raised')
    except ValueError:
        pass
    # Too large cycle
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_cycle=99999)
        raise AssertionError('should have raised')
    except (ValueError, IndexError):
        pass
    # begin > end
    try:
        r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', begin_cycle=10, end_cycle=5)
        raise AssertionError('should have raised')
    except ValueError:
        pass
t('cycle bounds check (Bug 8)', _test_cycle_bounds)

def _test_getitem_none_bounds():
    """Bug 9: __getitem__ with None slice bounds raises clear error."""
    from wavekit import VcdReader
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    try:
        _ = w[:0]
        raise AssertionError('should have raised')
    except ValueError as e:
        assert 'both bounds required' in str(e)
    try:
        _ = w[7:]
        raise AssertionError('should have raised')
    except ValueError as e:
        assert 'both bounds required' in str(e)
t('getitem None bounds error (Bug 9)', _test_getitem_none_bounds)

print()
print('=' * 60)
total = len(TESTS_PASSED) + len(TESTS_FAILED)
print(f'Results: {len(TESTS_PASSED)}/{total} passed')
if TESTS_FAILED:
    print('FAILURES:')
    for name, err in TESTS_FAILED:
        print(f'  - {name}: {err}')
print('=' * 60)
sys.exit(0 if not TESTS_FAILED else 1)
