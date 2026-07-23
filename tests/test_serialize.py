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


def _wf(values, *, width=8, signed=False, xz_mask=None):
    value = np.array(values, dtype=np.int64 if signed else np.uint64)
    clock = np.arange(len(values), dtype=np.uint64)
    time = clock * 10
    signal = Signal('sig', 'tb.sig', width, signed)
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
