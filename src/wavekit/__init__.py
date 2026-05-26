#   -------------------------------------------------------------
#   Copyright (c) Microsoft Corporation. All rights reserved.
#   Licensed under the MIT License. See LICENSE in project root for information.
#   -------------------------------------------------------------
"""Python Package Template"""

from __future__ import annotations

from importlib import metadata

try:
    __version__ = metadata.version('wavekit')
except metadata.PackageNotFoundError:
    __version__ = 'unknown'

from .pattern import Channel as Channel
from .pattern import MatchResult as MatchResult
from .pattern import MatchStatus as MatchStatus
from .pattern import Pattern as Pattern
from .pattern import PatternError as PatternError
from .readers.vcd.reader import VcdReader as VcdReader
from .scope import Scope as Scope
from .signal import Signal as Signal
from .signal import SignalCompositeType as SignalCompositeType
from .waveform import Waveform as Waveform

__all__ = [
    'Waveform',
    'VcdReader',
    'FsdbReader',
    'FstReader',
    'Scope',
    'Signal',
    'SignalCompositeType',
    'Pattern',
    'MatchResult',
    'MatchStatus',
    'PatternError',
    'Channel',
    'has_fsdb_support',
]

try:
    from .readers.fst.reader import FstReader as FstReader
except Exception as _exc:
    _fst_err_msg = repr(_exc)
    class FstReader:  # type: ignore[no-redef]
        """Placeholder when pylibfst is unavailable."""
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                'FstReader requires pylibfst.\n\n'
                'Install it with: pip install pylibfst\n\n'
                f'Import error: {_fst_err_msg}'
            )

try:
    from .readers.fsdb.npi_fsdb_reader import fsdb_runtime_available as _fsdb_runtime_available
    from .readers.fsdb.reader import FsdbReader as FsdbReader
except Exception as _exc:
    _fsdb_err_msg = repr(_exc)
    _fsdb_available = False

    def has_fsdb_support() -> bool:
        """Check whether the Verdi FSDB runtime is available."""
        return False

    class _FsdbReaderStub:
        """Placeholder that raises an error when the Verdi FSDB runtime is unavailable."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                'FsdbReader requires the Verdi FSDB runtime (libNPI.so).\n\n'
                'Set WAVEKIT_NPI_LIB to the library path, set VERDI_HOME to the Verdi '
                'installation directory, or ensure libNPI.so is in LD_LIBRARY_PATH.\n\n'
                f'Import error: {_fsdb_err_msg}'
            )

    FsdbReader = _FsdbReaderStub  # type: ignore[assignment]
else:
    _fsdb_available = True

    def has_fsdb_support() -> bool:
        """Check whether the Verdi FSDB runtime is available right now."""
        return _fsdb_runtime_available()
