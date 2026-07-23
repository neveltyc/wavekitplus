#   -------------------------------------------------------------
#   Copyright (c) Microsoft Corporation. All rights reserved.
#   Licensed under the MIT License. See LICENSE in project root for information.
#   -------------------------------------------------------------
"""Tests for JSON serialization of Waveform and MatchResult."""

from __future__ import annotations

import json

import numpy as np

from wavekit.pattern.result import MatchResult, MatchStatus
from wavekit.signal import Signal
from wavekit.waveform import Waveform


def _wf(values, *, width=8, signed=False, xz_mask=None, dtype=None):
    if dtype is None:
        dtype = np.int64 if signed else np.uint64
    value = np.array(values, dtype=dtype)
    clock = np.arange(len(values), dtype=np.uint64)
    time = clock * 10
    # NB: Signal(name, full_name, width, range, signed=...) — `signed` is the 5th
    # positional; pass range=None explicitly so it is not mistaken for `signed`.
    signal = Signal('sig', 'tb.sig', width, None, signed)
    return Waveform(value, clock, time, signal=signal, xz_mask=xz_mask)


def test_waveform_to_dict_is_json_safe():
    wf = _wf([0, 1, 2, 3])
    d = wf.to_dict()
    json.dumps(d)  # must not raise
    assert d['name'] == 'sig'
    assert d['width'] == 8
    assert d['length'] == 4
    assert d['truncated'] is False
    assert [s['value'] for s in d['samples']] == [0, 1, 2, 3]
    assert [s['cycle'] for s in d['samples']] == [0, 1, 2, 3]
    assert [s['time'] for s in d['samples']] == [0, 10, 20, 30]


def test_waveform_xz_serializes_as_x():
    wf = _wf([5, 6, 7], xz_mask=np.array([False, True, False]))
    d = wf.to_dict()
    values = [s['value'] for s in d['samples']]
    assert values == [5, 'x', 7]
    assert d['summary']['xz_count'] == 1
    # value range is computed over known (non-x/z) values only
    assert d['summary']['value_min'] == 5
    assert d['summary']['value_max'] == 7


def test_waveform_truncation_keeps_full_summary():
    wf = _wf(list(range(100)))
    d = wf.to_dict(max_samples=10)
    assert d['truncated'] is True
    assert d['shown'] == 10
    assert len(d['samples']) == 10
    assert d['summary']['samples'] == 100  # summary reflects the full waveform


def test_waveform_include_values_false():
    wf = _wf([1, 2, 3])
    d = wf.to_dict(include_values=False)
    assert 'samples' not in d
    assert d['summary']['samples'] == 3


def test_waveform_summary_empty():
    wf = _wf([])
    s = wf.summary()
    assert s['samples'] == 0
    assert 'time_min' not in s


def test_matchresult_to_dict():
    mr = MatchResult(
        start=_wf([0, 5]),
        end=_wf([2, 7]),
        duration=_wf([3, 3]),
        status=_wf([MatchStatus.OK, MatchStatus.TIMEOUT]),
        captures={'val': _wf([42, 99])},
    )
    d = mr.to_dict()
    json.dumps(d)
    assert d['matches_total'] == 2
    assert d['status_counts'] == {'OK': 1, 'TIMEOUT': 1}
    assert d['matches'][0]['status_name'] == 'OK'
    assert d['matches'][0]['captures']['val'] == 42
    assert d['matches'][1]['status_name'] == 'TIMEOUT'


def test_matchresult_summary_and_truncation():
    n = 50
    mr = MatchResult(
        start=_wf(list(range(n))),
        end=_wf(list(range(n))),
        duration=_wf([1] * n),
        status=_wf([MatchStatus.OK] * n),
        captures={},
    )
    assert mr.summary() == {'matches_total': 50, 'status_counts': {'OK': 50}}
    d = mr.to_dict(max_matches=5)
    assert d['truncated'] is True
    assert len(d['matches']) == 5
    assert d['matches_total'] == 50


def test_matchresult_capture_xz():
    mr = MatchResult(
        start=_wf([0]),
        end=_wf([1]),
        duration=_wf([2]),
        status=_wf([MatchStatus.OK]),
        captures={'d': _wf([7], xz_mask=np.array([True]))},
    )
    d = mr.to_dict()
    assert d['matches'][0]['captures']['d'] == 'x'


def test_waveform_signed_negative_values():
    wf = _wf([-3, -1, 5], signed=True)
    d = wf.to_dict()
    json.dumps(d)  # must not raise
    assert d['signed'] is True
    assert [s['value'] for s in d['samples']] == [-3, -1, 5]
    # value range is signed-aware
    assert d['summary']['value_min'] == -3
    assert d['summary']['value_max'] == 5


def test_non_finite_floats_serialize_as_null():
    # NaN / +-inf are not valid JSON; they must be coerced to None so a strict
    # parser (allow_nan=False / JavaScript JSON.parse) accepts the payload.
    wf = _wf([1.5, float('inf'), float('-inf'), float('nan')], width=None, dtype=np.float64)
    d = wf.to_dict()
    json.dumps(d, allow_nan=False)  # must not raise
    assert [s['value'] for s in d['samples']] == [1.5, None, None, None]


def test_non_finite_float_via_division_is_json_safe():
    # Reachable through the public API: division by zero yields +inf.
    res = _wf([10, 20, 30], width=None) / _wf([2, 0, 5], width=None)
    d = res.to_dict()
    json.dumps(d, allow_nan=False)  # must not raise
    values = [s['value'] for s in d['samples']]
    assert values[0] == 5.0
    assert values[1] is None  # 20 / 0 -> inf -> None
    assert values[2] == 6.0


def test_large_integers_serialize_as_strings():
    # Values beyond the JS safe-integer range (2**53 - 1) become decimal strings
    # so a double-based JSON consumer does not silently lose precision.
    safe = (1 << 53) - 1
    wf = _wf([safe, safe + 1, 1 << 60], width=64)
    d = wf.to_dict()
    json.dumps(d)  # must not raise
    values = [s['value'] for s in d['samples']]
    assert values[0] == safe  # still an int (fits a double)
    assert values[1] == str(safe + 1)  # stringified
    assert values[2] == str(1 << 60)
    assert int(values[2]) == 1 << 60  # round-trips


def test_wide_object_integers_serialize_as_strings():
    big = (1 << 100) + 7
    wf = _wf([big], width=128, dtype=np.object_)
    d = wf.to_dict()
    json.dumps(d)
    assert d['samples'][0]['value'] == str(big)
    assert int(d['samples'][0]['value']) == big


def test_matchresult_empty_captures_key_present():
    mr = MatchResult(
        start=_wf([0, 5]),
        end=_wf([2, 7]),
        duration=_wf([3, 3]),
        status=_wf([MatchStatus.OK, MatchStatus.OK]),
        captures={},
    )
    d = mr.to_dict()
    # captures key is always present (as {}) for a consistent consumer shape
    assert all(m['captures'] == {} for m in d['matches'])


def test_negative_max_is_clamped():
    wf = _wf(list(range(10)))
    d = wf.to_dict(max_samples=-5)
    assert d['shown'] == 0
    assert d['samples'] == []
    assert d['truncated'] is True
