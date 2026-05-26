# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/).

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
