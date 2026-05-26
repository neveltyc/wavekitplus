<p align="center">
  <h1 align="center">wavekit-plus</h1>
  <p align="center">
    A Python library for digital waveform analysis —
    load VCD/FST/FSDB signals as NumPy arrays, run pattern matching, and compute in one pass.
  </p>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.1-3366cc?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9+-3366cc?style=flat-square&logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-3366cc?style=flat-square">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-22aa55?style=flat-square">
</p>

<p align="center">
  <b>Forked from <a href="https://github.com/cxzzzz/wavekit">cxzzzz/wavekit</a></b> —
  replacing vcdvcd with a streaming, IEEE-compliant VCD parser from
  <a href="https://github.com/neveltyc/VCD_ANALYZER">VCD_ANALYZER</a>.
</p>

---

## Why wavekit-plus?

The original wavekit depends on [vcdvcd](https://github.com/zylin/Verilog_VCD), which loads
an entire VCD file into memory before you can access a single signal. It also carries
Artistic 1.0 / GPL v1 license terms.

**wavekit-plus** replaces that parser with `VCDParser` from
[VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9:

- **Streaming parse** — `iter_events()` yields one value change at a time. Loading one
  signal does not pay the memory cost of loading all signals.
- **Bit-explosion auto-reassembly** — QuestaSim's per-bit `$var` declarations are
  automatically merged back into multi-bit buses.
- **Extended VCD** — `$dumpports` port states are decoded to 4-state (`0`/`1`/`x`/`z`).
- **Input hardening** — 16 resource caps defend against pathological VCDs (DoS, corruption).
- **4-state masking** — optional `xz_mask=True` marks every cycle where x or z was present,
  and the mask propagates through arithmetic, slicing, and filtering.
- **Signal cache** — each signal's value-change list is read once and reused across
  `load_waveform` calls within the same reader instance.
- **License clarity** — dependency chain is now MIT + BSD (NumPy). No GPL or Artistic terms.

All wavekit APIs, the `Waveform` class, and the `Pattern` engine are unchanged.
Every existing test passes identically.

## Setup

```bash
git clone --recurse-submodules https://github.com/neveltyc/wavekitplus.git
cd wavekitplus
pip install numpy

# Ready to go
export PYTHONPATH="$PWD/src:$PYTHONPATH"    # Linux / macOS
$env:PYTHONPATH = "$PWD\src"               # PowerShell
```

No C compiler needed — a pure Python fallback is included for the Cython `value_change` module.

**Optional:** `pip install pylibfst` for FST support, `Cython` for native-speed resampling.
FSDB support requires a Verdi runtime (`libNPI.so`).

## Quick start

```python
from wavekit import VcdReader

with VcdReader("sim.vcd") as r:
    # Load a single signal, sampled on clock edges
    addr = r.load_waveform("tb.dut.addr[31:0]", clock="tb.clk")

    # Batch-load with brace expansion
    waves = r.load_matched_waveforms(
        "tb.dut.J_{state,next}[3:0]",
        clock_pattern="tb.tck",
    )

    # Evaluate an expression directly
    occupancy = r.eval(
        "tb.dut.w_ptr[2:0] - tb.dut.r_ptr[2:0]",
        clock="tb.clk",
    )

    # Load with x/z detection
    state = r.load_waveform("tb.state[2:0]", clock="tb.clk", xz_mask=True)
    clean = state.drop_xz()  # remove cycles with unknown values
```

## Core API

### Reader

| Method | Description |
|:-------|:------------|
| `VcdReader(file)` | Open a VCD file. Supports context manager. |
| `load_waveform(signal, clock, ...)` | Load one signal sampled on clock edges. Returns `Waveform`. |
| `load_matched_waveforms(pattern, clock_pattern, ...)` | Batch-load signals matching a brace/regex pattern. |
| `eval(expr, clock, mode="single"\|"zip")` | Evaluate an expression with embedded signal paths. |
| `get_matched_signals(pattern)` | Resolve a pattern to `Signal` objects without loading data. |
| `top_scope_list()` | Return root `Scope` nodes of the hierarchy. |

**Signal path patterns:** `{a,b}` enumerates, `{0..7}` ranges, `@([a-z]+)` regex captures.

### Waveform

A `Waveform` wraps three parallel NumPy arrays: `.value`, `.clock`, `.time`.

| Category | Operations |
|:---------|:-----------|
| **Arithmetic** | `+` `-` `*` `//` `%` `**` `/` `&` `|` `^` `~` `<<` `>>` `==` `!=` |
| **Filtering** | `.mask(cond)`, `.filter(fn)`, `.drop_xz()` |
| **Slicing** | `.time_slice(t0, t1)`, `.cycle_slice(c0, c1)`, `.slice(i0, i1)`, `.take(indices)` |
| **Edges** | `.rising_edge()`, `.falling_edge()` (1-bit only) |
| **Transform** | `.map(fn)`, `.unique_consecutive()`, `.compress()`, `.downsample(n, fn)` |
| **Bits** | `wave[7:0]` (bit slice), `.split_bits(n)`, `Waveform.concatenate([a,b])` |
| **Shift** | `.ahead(n)`, `.back(n)`, `.relative(offset)` |
| **4-state** | `.has_xz`, `.xz_cycles`, `.drop_xz()` |

### Pattern engine

Describe a temporal sequence; the NFA engine finds all matches in one pass.

```python
from wavekit import Pattern

result = (
    Pattern()
    .wait(arvalid & arready)    # wait for AR handshake
    .wait(rvalid & rready)      # wait for R handshake
    .capture("rdata", rdata)    # record read data
    .timeout(256)
    .match()
)

for m in result.filter_valid():
    print(f"Latency: {m.duration.value} cycles, data: {m.captures['rdata'].value}")
```

| Step | Description |
|:-----|:------------|
| `.wait(cond)` | Block until condition is true. |
| `.delay(n)` | Advance n cycles. |
| `.capture(name, signal)` | Record signal value. |
| `.require(cond)` | Assert condition; fail with `REQUIRE_VIOLATED`. |
| `.loop(body, until=\|when=)` | Repeat body until/when condition. |
| `.repeat(body, n)` | Execute body n times. |
| `.branch(cond, T, F)` | Conditional branch. |
| `.timeout(max)` | Mark unfinished instances as `TIMEOUT`. |
| `.match()` | Run the engine; returns `MatchResult` with `.start`, `.end`, `.duration`, `.captures`, `.filter_valid()`. |

## Version history

| Version | Highlight |
|:--------|:----------|
| `0.8.1` | Fix xz_mask propagation in binary ops, relative, concatenate |
| `0.8.0` | 4-state x/z masking layer |
| `0.7.2` | Signal value-change cache (single-scan batch loading) |
| `0.7.1` | Code hygiene + comprehensive test suite |
| `0.7.0` | Replace vcdvcd with VCD_ANALYZER VCDParser |

Full changelog: [CHANGELOG.md](CHANGELOG.md)

## Tests

```bash
PYTHONPATH=src python tests/run_tests.py
```

46 tests covering VCDParser, VcdReader, iverilog-generated VCDs, cache layer, xz_mask,
and edge cases. No pytest required.

## License

MIT — see [LICENSE](LICENSE).

The embedded VCD parser (`src/wavekit/readers/vcd/vcd_parser.py`)
is adapted from [VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9, also MIT.

[中文说明](README_ZH.md)
