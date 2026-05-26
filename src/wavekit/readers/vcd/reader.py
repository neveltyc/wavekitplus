from __future__ import annotations

import re
from collections.abc import Sequence
from functools import cached_property

import numpy as np

from ...scope import Scope
from ...signal import Signal
from ...waveform import Waveform
from ..base import Reader
from ..pattern_parser import split_by_range_expr
from .vcd_parser import VCDParser


class VcdScope(Scope):
    """Scope implementation that builds the scope tree from VCDParser signals."""

    def __init__(
        self,
        name: str,
        full_path: str,
        parser: VCDParser,
        reader: 'VcdReader',
    ):
        super().__init__(name=name)
        self._full_path = full_path
        self._parser = parser
        self._reader = reader

    @cached_property
    def signal_list(self) -> Sequence[Signal]:
        signals: list[Signal] = []
        for sid, info in self._parser.signals.items():
            if info.get('scope') == self._full_path:
                # From the full path, extract the local name (last component)
                local_name = info['path'].split('.')[-1]
                signals.append(
                    Signal(
                        name=local_name,
                        full_name=info['path'],
                        width=info['width'],
                        range=None,
                        signed=False,
                    )
                )
        return signals

    @cached_property
    def child_scope_list(self) -> Sequence[Scope]:
        """Find all direct child scopes under this scope's full_path."""
        prefix = self._full_path + '.' if self._full_path else ''
        children: set[str] = set()
        for sid, info in self._parser.signals.items():
            scope = info.get('scope', '')
            if scope and scope.startswith(prefix):
                remainder = scope[len(prefix):]
                child_name = remainder.split('.')[0]
                children.add(child_name)
        return [
            VcdScope(
                name=c,
                full_path=f'{self._full_path}.{c}' if self._full_path else c,
                parser=self._parser,
                reader=self._reader,
            )
            for c in sorted(children)
        ]


class VcdReader(Reader):
    def __init__(self, file: str):
        super().__init__()
        self.file = file
        self._parser = VCDParser(file)

       # Cache time range to avoid re-scanning the file
        self._time_range = self._parser.scan_time_range()
        # Cache per-signal value-change lists to avoid re-scanning on reloads
        self._tv_cache: dict[str, list[tuple[int, str]]] = {}

        # Build top-level scopes from signal data
        top_scopes: set[str] = set()
        for sid, info in self._parser.signals.items():
            scope = info.get('scope', '')
            if scope:
                top_scopes.add(scope.split('.')[0])
        self._top_scope_list: list[VcdScope] = [
            VcdScope(name=s, full_path=s, parser=self._parser, reader=self)
            for s in sorted(top_scopes)
        ]

    def top_scope_list(self) -> Sequence[Scope]:
        return self._top_scope_list

    @property
    def begin_time(self) -> int:
        t_min, _ = self._time_range
        return t_min if t_min is not None else 0

    @property
    def end_time(self) -> int:
        _, t_max = self._time_range
        return t_max if t_max is not None else 0

    def _ensure_cached(self, sids: set[str]) -> None:
        """Ensure value-change lists for all sids are cached.

        Missing signals trigger a single iter_events scan.
        Already-cached signals are not re-scanned.
        """
        missing = sids - self._tv_cache.keys()
        if not missing:
            return
        for t, sid, val in self._parser.iter_events(sids=missing):
            self._tv_cache.setdefault(sid, []).append((t, val))
        # Ensure absent signals get empty lists, to avoid re-scanning
        for sid in missing:
            self._tv_cache.setdefault(sid, [])

    def _resolve_signal_path(self, path: str) -> str:
        # Exact match
        for sid, info in self._parser.signals.items():
            if path in info['aliases']:
                return sid

        # Fuzzy match for paths with range suffix
        pattern = re.compile(rf'^{re.escape(path)}\[\d+(?::\d+)?\]$')
        matches: list[str] = []
        for sid, info in self._parser.signals.items():
            for alias in info['aliases']:
                if pattern.fullmatch(alias):
                    matches.append(sid)
                    break
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f'path {path!r} matches multiple signals')
        raise ValueError(f'signal {path!r} not found')

    def load_waveform(
        self,
        signal: Signal | str,
        clock: Signal | str,
        xz_value: int = 0,
        signed: bool = False,
        sample_on_posedge: bool = False,
        begin_time: int | None = None,
        end_time: int | None = None,
        begin_cycle: int | None = None,
        end_cycle: int | None = None,
    ) -> Waveform:
        if begin_time is not None and begin_cycle is not None:
            raise ValueError('begin_time and begin_cycle are mutually exclusive')
        if end_time is not None and end_cycle is not None:
            raise ValueError('end_time and end_cycle are mutually exclusive')

        signal_path = signal.full_name if isinstance(signal, Signal) else signal
        clock_path = clock.full_name if isinstance(clock, Signal) else clock

        # Strip range suffix to get the bare signal path for lookup
        bare_signal_path, range_suffix = split_by_range_expr(signal_path)

        # VCD does not support multi-dimensional (more than one bracket pair)
        if range_suffix and len(re.findall(r'\[[\d:]+\]', range_suffix)) > 1:
            raise ValueError(
                f"VCD does not support multi-dimensional range access: '{signal_path}'. "
                'Use FSDB or load the full signal and slice manually.'
            )

        # Resolve signal and clock to parser IDs
        signal_sid = self._resolve_signal_path(bare_signal_path)
        clock_sid = self._resolve_signal_path(clock_path)
        signal_info = self._parser.signals[signal_sid]
        width = signal_info['width']

        # Determine the lookup path (alias that matched) for range_suffix detection
        lookup_path = bare_signal_path
        for alias in signal_info['aliases']:
            if alias.startswith(bare_signal_path):
                lookup_path = alias
                break
        _, file_range_suffix = split_by_range_expr(lookup_path)

        # Collect value changes from cache (avoids re-scanning on reloads)
        self._ensure_cached({signal_sid, clock_sid})
        signal_tv = self._tv_cache[signal_sid]
        clock_tv = self._tv_cache[clock_sid]

        # Convert clock changes to numpy array (always uint64 for clocks)
        all_clock_changes = np.array(
            [(v[0], int(re.sub(r'[xXzZ]', '0', v[1]), 2)) for v in clock_tv],
            dtype=np.uint64,
        )
        if len(all_clock_changes) == 0:
            raise ValueError(f"clock signal '{clock_path}' has no value changes")

        # Determine clock edge timestamps for the sampling edge
        sample_value = 1 if sample_on_posedge else 0
        clock_edge_times = all_clock_changes[all_clock_changes[:, 1] == sample_value, 0]

        # Convert begin_cycle/end_cycle to begin_time/end_time
        if begin_cycle is not None:
            begin_time = int(clock_edge_times[begin_cycle])
        if end_cycle is not None:
            end_time = int(clock_edge_times[end_cycle])

        # Compute clock_offset = number of sampling edges before begin_time
        begin_time_actual = begin_time if begin_time is not None else 0
        clock_offset = int(np.searchsorted(clock_edge_times, begin_time_actual, side='left'))

        # Trim clock to window [begin_time_actual, end_time] to reduce memory usage
        end_time_actual = end_time if end_time is not None else np.iinfo(np.uint64).max
        clock_mask = all_clock_changes[:, 0] >= begin_time_actual
        if end_time is not None:
            clock_mask &= all_clock_changes[:, 0] <= end_time_actual
        clock_value_change = all_clock_changes[clock_mask]

        # Convert signal changes to numpy array
        signal_value_change = np.array(
            [(v[0], int(re.sub(r'[xXzZ]', str(xz_value), v[1]), 2)) for v in signal_tv],
            dtype=np.object_ if width > 64 else np.uint64,
        )
        if len(signal_value_change) == 0:
            raise ValueError(f"signal '{lookup_path}' has no value changes")

        full_wave = self.value_change_to_waveform(
            signal_value_change,
            clock_value_change,
            width=width,
            signed=signed,
            sample_on_posedge=sample_on_posedge,
            signal=lookup_path,
            clock_offset=clock_offset,
        )

        result = full_wave.time_slice(begin_time, end_time)

        # Apply sub-range slice if user specified a range
        if range_suffix:
            m = re.fullmatch(r'\[(\d+)(?::(\d+))?\]', range_suffix)
            if m:
                high = int(m.group(1))
                low = int(m.group(2)) if m.group(2) is not None else high
                if file_range_suffix:
                    file_range_match = re.fullmatch(r'\[(\d+)(?::(\d+))?\]', file_range_suffix)
                    assert file_range_match is not None
                    file_low = (
                        int(file_range_match.group(2))
                        if file_range_match.group(2) is not None
                        else int(file_range_match.group(1))
                    )
                    if file_low != 0:
                        raise ValueError(
                            f"sub-range access for signal '{lookup_path}' is only supported "
                            'when the stored signal range starts at bit 0'
                        )
                if high >= width:
                    raise ValueError(
                        f"bit index {high} out of range for signal '{lookup_path}' "
                        f'with width {width}'
                    )
                if low < 0:
                    raise ValueError(f'bit index {low} cannot be negative')
                slice_width = high - low + 1
                if slice_width < width:
                    result = result[high:low]

        return result

    def close(self):
        pass
