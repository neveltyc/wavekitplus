# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## v0.8.3 - 2026-05-26

### Fixed
- Bug 6: load_matched_waveforms and eval now accept and forward xz_mask parameter
- Cosmetic: fix split_bits closing bracket indentation regression from v0.8.0

## v0.8.2 - 2026-05-26

### Fixed
- Bug 4: relative() xz_mask pad used offset instead of pad_count, causing wrong length on overshift
- Bug 5: __eq__ / __ne__ missing _merge_xz_mask call (lost other operands x/z info)

## v0.8.1 - 2026-05-26

### Fixed
- Bug 1: dual-operand arithmetic now merges xz_mask from both waveforms (affects +, -, *, /, //, %, &, |, ^, <<, >>)
- Bug 2: relative() / ahead() / back() now propagate xz_mask with the same shift/pad logic as value
- Bug 3: concatenate() now OR-merges xz_masks from all input waveforms

### Added
- Waveform._merge_xz_mask() static helper for centralized mask merging
- 3 regression tests (dual-operand merge, relative propagation, concatenate merge)

## v0.8.0 - 2026-05-26

### Added
- 4-state x/z masking in Waveform: xz_mask attribute, has_xz, xz_cycles, drop_xz
- load_waveform(xz_mask=True) generates per-cycle x/z presence flags from raw VCD values
- xz_mask propagation through: mask, filter, time_slice, cycle_slice, take, copy, arithmetic
- xz_trace.vcd test fixture with xxx/zzz/x10 values
- 8 xz_mask tests (default off, detection, backward compat, drop, slice survival, arithmetic)

### Changed
- Waveform.__init__ accepts optional xz_mask parameter
- vectorized_map propagates xz_mask from source Waveform
- All Waveform constructors in slice/filter/index methods pass xz_mask

## v0.7.2 - 2026-05-26

### Added
- Signal value-change cache in VcdReader (per-signal tv lists, lazy-fill via _ensure_cached)
- Single-scan batch caching: loading N signals triggers at most one iter_events pass
- Cache consistency tests (reload, shared clock, empty signal, no re-scan)

### Changed
- load_waveform reads value changes from cache instead of direct iter_events call

## v0.7.1 - 2026-05-26

### Added
- Comprehensive test suite (31 tests covering VCDParser, VcdReader, iverilog VCDs, edge cases)

### Fixed
- Remove dead _check_time_range() referencing missing _TimeParseError
- Remove dead _DEFAULT_LIMIT CLI constant
- Fix outdated comments referencing removed functions (parse_time, fmt_val, _build_snapshot)
- Make iverilog tests optional (skip when tools unavailable)

### Docs
- Add VCD_ANALYZER copyright to LICENSE
- Add v0.7.x entries to CHANGELOG

## v0.7.0 - 2026-05-26

### Changed
- Replace vcdvcd dependency with VCD_ANALYZER VCDParser (streaming, IEEE-compliant)
- Remove Artistic 1.0 / GPL v1 license from dependency chain
- VCD_ANALYZER referenced as git submodule under src/vcd_analyzer/

### Added
- QuestaSim bit-exploded bus auto-reassembly
- Extended VCD port state support ($dumpports)
- Input defense: 16 resource limits against DoS/malicious VCD
- Streaming parse via iter_events() with sids filtering
- Pure Python fallback for Cython value_change module (no C compiler required)

### Removed
- vcdvcd dependency (replaced by embedded VCDParser)

## Unreleased

## v0.6.1 - 2026-05-23

### Fixed
- Fix wheel packaging for Cython reader extensions so installed wheels expose `wavekit.readers.value_change` and FSDB extension modules at their runtime import paths.

## v0.6.0 - 2026-05-23

### Added
- Add `FstReader` for loading FST waveform files through the same reader APIs as VCD and FSDB.
- Add `Channel`-based FIFO consumption to `Pattern.wait()` for ordered request/response pairing and per-ID routing.
- Add relative time access helpers for waveform analysis.
- Add Chinese README documentation.

### Changed
- Refactor the pattern API around tick, channel, capture mode, and require semantics.
- Improve VCD reader error reporting for empty value-change data and unsupported sub-range access.

### Fixed
- Fix FSDB array signal value parsing and reader resource handling.
- Restrict pattern trigger optimization to `wait()` steps.
