#   -------------------------------------------------------------
#   Copyright (c) Microsoft Corporation. All rights reserved.
#   Licensed under the MIT License. See LICENSE in project root for information.
#   -------------------------------------------------------------
"""JSON serialization for :class:`~wavekit.Waveform` and
:class:`~wavekit.MatchResult`.

Turns the numpy-backed result types into plain, JSON-safe dicts so a caller (for
example an MCP protocol-analysis layer) can return them without touching numpy.
Conventions:

* x/z bits serialize as the string ``'x'`` (the masked positions of a 4-state
  waveform); known values serialize as ``int``/``float``/``bool``/``list``.
* Large results are truncated to ``max_samples`` / ``max_matches`` with a
  ``truncated`` flag, while the ``summary`` always reflects the *full* result.
* Nothing here has side effects or requires a CLI; callers build the Waveform /
  MatchResult with the normal reader / pattern API and call ``to_dict()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from .pattern.result import MatchStatus

if TYPE_CHECKING:
    from .pattern.result import MatchResult
    from .waveform import Waveform


def _coerce(value: Any) -> Any:
    """Coerce a numpy / Python scalar (or nested list) to a JSON-safe value."""
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_coerce(v) for v in value.tolist()]
    item = getattr(value, 'item', None)
    if callable(item):
        return item()
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _value_at(wf: Waveform, i: int) -> Any:
    """The value at index *i*, or ``'x'`` when that sample is x/z masked."""
    if wf.xz_mask is not None and bool(wf.xz_mask[i]):
        return 'x'
    return _coerce(wf.value[i])


def waveform_summary(wf: Waveform) -> dict[str, Any]:
    """Compact stats for a waveform: sample count, time/cycle span, value range,
    and x/z count. Always reflects the full waveform, never a truncated view."""
    n = len(wf.value)
    out: dict[str, Any] = {'samples': n, 'has_xz_mask': wf.has_xz}
    if n:
        out['time_min'] = _coerce(wf.time[0])
        out['time_max'] = _coerce(wf.time[-1])
        out['cycle_min'] = _coerce(wf.clock[0])
        out['cycle_max'] = _coerce(wf.clock[-1])
        if wf.xz_mask is not None:
            out['xz_count'] = int(np.sum(wf.xz_mask))
            known = wf.value[~wf.xz_mask]
        else:
            known = wf.value
        if len(known) and known.dtype != np.object_ and known.dtype != np.bool_:
            out['value_min'] = _coerce(np.min(known))
            out['value_max'] = _coerce(np.max(known))
    return out


def waveform_to_dict(
    wf: Waveform, max_samples: int | None = 1024, include_values: bool = True
) -> dict[str, Any]:
    """Serialize a waveform to a JSON-safe dict.

    Parameters
    ----------
    max_samples:
        Cap on the number of per-sample rows emitted (``None`` = all). The
        ``summary`` is unaffected.
    include_values:
        When ``False``, emit only metadata + summary (no per-sample rows).
    """
    n = len(wf.value)
    shown = n if max_samples is None else min(n, int(max_samples))
    out: dict[str, Any] = {
        'name': wf.name,
        'width': wf.width,
        'signed': bool(wf.signed) if wf.signed is not None else None,
        'length': n,
        'shown': shown,
        'truncated': shown < n,
        'summary': waveform_summary(wf),
    }
    if include_values:
        out['samples'] = [
            {
                'time': _coerce(wf.time[i]),
                'cycle': _coerce(wf.clock[i]),
                'value': _value_at(wf, i),
            }
            for i in range(shown)
        ]
    return out


def _status_name(status: int) -> str:
    try:
        return MatchStatus(status).name
    except ValueError:
        return str(status)


def _status_counts(status_values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in np.unique(status_values):
        counts[_status_name(int(s))] = int(np.sum(status_values == s))
    return counts


def matchresult_summary(mr: MatchResult) -> dict[str, Any]:
    """Compact stats for a match result: total matches and per-status counts."""
    return {'matches_total': len(mr), 'status_counts': _status_counts(mr.status.value)}


def matchresult_to_dict(
    mr: MatchResult, max_matches: int | None = 1024, include_captures: bool = True
) -> dict[str, Any]:
    """Serialize a pattern match result to a JSON-safe dict.

    Each match carries ``start``/``end``/``duration`` (simulation cycles),
    ``status``/``status_name``, and its named ``captures`` (x/z-aware). ``summary``
    reflects the full result even when the per-match list is truncated.
    """
    n = len(mr)
    shown = n if max_matches is None else min(n, int(max_matches))
    starts = mr.start.value
    ends = mr.end.value
    durations = mr.duration.value
    statuses = mr.status.value
    matches: list[dict[str, Any]] = []
    for i in range(shown):
        status = int(statuses[i])
        entry: dict[str, Any] = {
            'start': _coerce(starts[i]),
            'end': _coerce(ends[i]),
            'duration': _coerce(durations[i]),
            'status': status,
            'status_name': _status_name(status),
        }
        if include_captures and mr.captures:
            entry['captures'] = {name: _value_at(wf, i) for name, wf in mr.captures.items()}
        matches.append(entry)
    return {
        'matches_total': n,
        'shown': shown,
        'truncated': shown < n,
        'status_counts': _status_counts(statuses),
        'matches': matches,
    }
