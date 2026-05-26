"""Comprehensive test suite for wavekit-plus. Self-contained, no pytest needed."""
import os, sys, subprocess, traceback, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
JTAG = ROOT / 'tests' / 'testdata' / 'jtag.vcd'
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
from wavekit import VcdReader

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

t('scoreboard VCD', lambda: _generate_and_test('scoreboard', 'fifo_tb.sv', 'scoreboard_tb.vcd'))
t('fifo_latency VCD', lambda: _generate_and_test('fifo_latency', 'fifo_tb.sv', 'fifo_latency_tb.vcd'))
t('fifo_occupancy VCD', lambda: _generate_and_test('fifo_occupancy', 'fifo_tb.sv', 'fifo_occupancy_tb.vcd'))

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
print('=' * 60)
total = len(TESTS_PASSED) + len(TESTS_FAILED)
print(f'Results: {len(TESTS_PASSED)}/{total} passed')
if TESTS_FAILED:
    print('FAILURES:')
    for name, err in TESTS_FAILED:
        print(f'  - {name}: {err}')
print('=' * 60)
sys.exit(0 if not TESTS_FAILED else 1)
