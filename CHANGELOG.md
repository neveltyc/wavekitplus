# Changelog

All notable changes to this project are documented in this file.

## v0.9.4 - 2026-05-27

### Fixed
- value_transformer hook in _binary_op: runs BEFORE op (was dead code after op)
- test_adversarial.py: fully integrated into pytest collection (was excluded by collect_ignore)
- test_examples.py: cross-platform runner with iverilog+vvp fallback (no longer requires make)
- conftest.py: removed stale collect_ignore

### Added
- test_binary_op_value_transformer_runs_before_op regression test
- example/*.json configs for platform-independent example execution

## v0.9.3 - 2026-05-26

### Changed
- test_adversarial.py: renamed to pytest format, fully collected by default
- _assert_waveform_invariants: AssertionError -> ValueError
- _binary_op: added optional value_transformer hook (backward compatible, v0.10 prep)

### Added
- test_scalar_pow_waveform_rejected (explicit NotImplementedError check)
- test_shift_matrix.py parameterized skeleton (skip, v0.10 prep)
- README: API notes — scalar**wave, unsigned subtraction wraparound, bitwise signedness

## v0.9.2 - 2026-05-26

### Added
- release_tag.ps1: repeatable release helper that runs tests, preserves generated
  VCD fixtures, commits staged release changes, and creates an annotated tag.

### Changed
- Documentation refreshed for current v0.9.x behavior and release workflow.
- AGENTS.md shortened into a quick orientation guide for future agents.

### Fixed
- get_matched_signals(root_scope=...) now delegates to the relative signal
  matcher, preserving nested paths, range suffixes, and full signal names.
- VCD subrange loads now keep requested-range metadata, e.g. data[3:0] stays
  data[3:0] instead of reporting the resolved full-width alias.
- scalar << waveform now computes exact values above 64 bits by using object
  dtype when needed; scalar ** waveform is rejected with an explicit map()
  alternative.
- Waveform bit selection now raises ValueError for width=None, negative indices,
  stepped slices, and reverse slices.
- Reader finalization now checks waveform value/clock/time/xz_mask invariants.

## v0.9.1 - 2026-05-26

### Changed
- root_scope helpers added as match_signals_relative/match_scopes_relative in
  scope.py (nested paths, regex groups, range suffixes, brace expansion).
- get_matched_scopes(root_scope=...) now delegates to the relative scope matcher.
  get_matched_signals(root_scope=...) keeps its compatibility branch in base.py.

## v0.9.0 - 2026-05-26

### Changed
- **Binary ops refactored** — non-shift binary operators use the _binary_op
  factory and _check_binary_compat. Shift operators keep specialized paths but
  share the same compatibility checks where applicable.
- **Reader finalize unified** — _finalize_loaded_waveform() shared by VCD/FST/FSDB.
  Always loads unsigned first, slices, then converts to signed. Ensures name
  and signal metadata consistency across all three backends.
- **__sub__ width** — restores upstream behavior: subtraction does not increase
  bit width. __add__ width=max+1 behavior retained.
- Exception type standardized — edge ops use ValueError not bare Exception.

### Fixed
- unsigned subrange name was empty (now set via shared finalize)
- empty waveform rising_edge/falling_edge no longer crash
- empty edge result preserves correct signed metadata

## v0.8.16 - 2026-05-26

### Fixed
- edge_detect.py: add from __future__ import annotations for Python 3.9 compat
- __rfloordiv__/__rmod__/__rpow__: add _check_arithmetic_op_width for width>64 guard
- __getitem__: bit/slice bounds validation (negative, out-of-range)
- root_scope: support nested relative paths (e.g. sub.sig via root_scope=dut)
- FSDB: clock width from npi_clock.width() instead of string guesswork

## v0.8.15 - 2026-05-26

### Fixed
- signed=True + subrange: bit-sliced signed signals no longer crash (signed conversion after slice)
- Waveform.mask(mask_waveform): added clock/time alignment check
- __rlshift__: guard empty waveform against np.max() on zero-size array
- width>64 arithmetic: _check_arithmetic_op_width added to sub, mul, floordiv, mod, pow
- FST: clock_name uses fst_clock.full_name (was undefined clock_path)
- test_examples: skip condition checks make + iverilog + vvp
- root_scope: single-element patterns match signals relative to scope
- VCD: scope tree built from all alias scopes, signal_list includes all aliases
- pytest: external deps (make, iverilog, pylibfst) correctly skipped — 140 passed, 4 skipped

## v0.8.14 - 2026-05-26

### Fixed
- signed=True + subrange: bit-sliced signed signals no longer crash (signed conversion after slice)
- Waveform.mask(mask_waveform): added clock/time alignment check
- __rlshift__: guard empty waveform against np.max() on zero-size array
- width>64 arithmetic: _check_arithmetic_op_width added to sub, mul, floordiv, mod, pow
- __rpow__: add missing _merge_xz_mask call
- pytest: external deps (make, pylibfst, iverilog) correctly skipped in CI

## v0.8.13 - 2026-05-26

### Fixed
- Cython value_change_to_value_array: add future-value guard (same as Python fallback)
- Binary op alignment check: moved into _check_sign to cover all 14 ops (was only 4)
- FST/FSDB readers: cycle bounds validation (begin_cycle, end_cycle) synced with VCD
- FST/FSDB readers: use true edge detection (compute_clock_edge_mask) instead of level match
- conftest.py: remove duplicate definitions

## v0.8.12 - 2026-05-26

### Fixed
- signed=True now does two's-complement interpretation (not just astype(int64))
- FstReader/FsdbReader import stubs: fix NameError on except variable cleanup
- VCD real/realtime signals: raise NotImplementedError instead of ValueError crash
- Empty time/cycle slice: guard against IndexError on empty waveform
- split_bits() padding: off-by-one in last group width (width -> width-1)
- Binary ops now check clock/time alignment via _check_alignment()
- FST/FSDB xz_mask: raise NotImplementedError (was silently ignored)

## v0.8.11 - 2026-05-26

### Fixed
- as_signed() for width==64 uses int64 view (was subtracting 2**64 from uint64 causing OverflowError)
- Waveform.mask() conservatively excludes xz_mask cycles from boolean mask waveform
- FST/FSDB reader clock edge: documented as known limitation (level matching, no x/z exclusion)
- conftest.py with clear comment explaining adversarial test exclusion from pytest

## v0.8.10 - 2026-05-26

### Fixed
- pyproject.toml version sync (was stuck at 0.8.6 across multiple releases)
- module pattern now uses depth=-1 (unlimited recursion) — matches documented semantics
- as_signed() handles >64-bit object-dtype waveforms without overflow
- value_change_to_value_array() guards against future-value leak at clock edges before first signal change
- __rrshift__ width metadata for scalar >> wave now uses max(other.bit_length(), self.width)

## v0.8.9 - 2026-05-26

### Fixed
- __rpow__ now calls _merge_xz_mask for dual-operand xz propagation
- __invert__ handles >64 bit object-dtype waveforms without overflow
- __rlshift__ width accommodates max possible shift value (scalar << wave)
- VCD signal with no value at t=0 no longer leaks future values at early clock edges

### Added
- Adversarial test suite (66 tests): xz_mask propagation, clock edge detection, subrange xz, cycle bounds
- conftest.py to exclude standalone test script from pytest collection

## v0.8.8 - 2026-05-26

### Fixed
- downsample() regression: remove spurious _merge_xz_mask call causing NameError

## v0.8.7 - 2026-05-26

### Fixed
- clock_value_change now filtered to edge events only (was level match causing fake cycles)
- rising_edge() / falling_edge() xz_mask uses prev|curr (was roll(-1) giving wrong direction)
- __rlshift__ / __rpow__ now propagate xz_mask and merge dual-operand masks
- bit-sliced signals (e.g. data[3:0]) xz_mask checks only selected bit range
- end_cycle == len(clock_edges) no longer IndexError
- find_scope_by_module() depth=0 stops at self (was infinite recursion)
- clock x/z transitions excluded from edge detection (no false edges)
- merge() validates inputs (empty, length, clock) and propagates xz_mask (was assert)
- expr_parser recognizes bare signal names when root_scope is set
- pylibfst marked optional=true in pyproject.toml extras

## v0.8.6 - 2026-05-26

### Fixed
- regex signal matching: try sig_bare first, fall back to sig.name (fixes @data and @J_([a-z]+\[3:0\]))
- module_name_matching test updated for implemented find_scope_by_module()

## v0.8.5 - 2026-05-26

### Fixed
- xz_mask now propagates through rising_edge() and falling_edge() (edge involving unknown = unknown)
- downsample() validates chunk_size > 0 and propagates xz_mask (chunk-level any())
- VcdScope.child_scope_list now correctly sets parent_scope on children
- VcdScope.find_scope_by_module() implemented for $module/$module pattern matching

## v0.8.4 - 2026-05-26

Upstream bug fixes inherited from original wavekit.

### Fixed
- Clock edge detection: use 0->1/1->0 transitions (not level match); validate 1-bit clock
- __rlshift__ / __rrshift__ / __rpow__ compute correct direction (scalar << wave, etc.)
- Regex signal matching strips range suffix (@J_state now matches J_state[3:0])
- load_matched_waveforms raises ValueError on no signal match (was silent empty dict)
- concatenate() validates empty list, length consistency, and clock alignment
- begin_cycle / end_cycle out-of-bounds raises clean ValueError
- Waveform.__getitem__ rejects None slice bounds with clear error
- pylibfst moved to optional extras[fst], pytest moved to dev dependencies

## v0.8.3 - 2026-05-26

### Fixed
- load_matched_waveforms and eval now accept and forward xz_mask parameter
- FstReader and FsdbReader load_waveform signatures synced with xz_mask parameter

## v0.8.2 - 2026-05-26

### Fixed
- relative() / ahead() / back() xz_mask pad uses pad_count (not raw offset) to fix overshift length
- __eq__ / __ne__ now merge xz_mask from both operands

## v0.8.1 - 2026-05-26

### Fixed
- Dual-operand arithmetic merges xz_mask from both waveforms (+, -, *, /, //, %, &, |, ^, <<, >>)
- relative() / ahead() / back() propagate xz_mask with same shift/pad logic as value
- concatenate() OR-merges xz_masks from all input waveforms

### Added
- Waveform._merge_xz_mask() static helper for centralized mask merging

## v0.8.0 - 2026-05-26

### Added
- 4-state x/z masking layer: xz_mask attribute on Waveform, has_xz, xz_cycles, drop_xz
- load_waveform(xz_mask=True) generates per-cycle x/z presence flags from raw VCD values
- xz_mask propagation through mask, filter, slice, take, copy, arithmetic, relative, concatenate
- xz_trace.vcd test fixture with xxx/zzz/x10 values

### Changed
- Waveform.__init__ accepts optional xz_mask parameter (defaults to None, backward compatible)

## v0.7.2 - 2026-05-26

### Added
- Signal value-change cache in VcdReader (_tv_cache + _ensure_cached)
- Single-scan batch caching: loading N signals from same reader triggers at most one iter_events pass

### Changed
- load_waveform reads value changes from cache instead of direct iter_events call

## v0.7.1 - 2026-05-26

### Added
- Comprehensive test suite (31 tests, later grown to 61)

### Fixed
- Remove dead _check_time_range() referencing missing _TimeParseError
- Remove stale CLI constant _DEFAULT_LIMIT
- Fix comments referencing removed functions (parse_time, fmt_val, _build_snapshot)

### Docs
- Add VCD_ANALYZER copyright to LICENSE

## v0.7.0 - 2026-05-26

### Changed
- Replace vcdvcd dependency with VCD_ANALYZER VCDParser (streaming, IEEE-compliant)
- Remove Artistic 1.0 / GPL v1 license from dependency chain
- VCD_ANALYZER referenced as git submodule under src/vcd_analyzer/

### Added
- QuestaSim bit-exploded bus auto-reassembly
- Extended VCD port state support ($dumpports)
- Input defense: 16 resource limits against DoS/malicious VCD
- Pure Python fallback for Cython value_change module (no C compiler required)

### Removed
- vcdvcd dependency

---

## v0.6.1 and earlier

See the [original wavekit changelog](https://github.com/cxzzzz/wavekit/blob/main/CHANGELOG.md).
