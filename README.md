<p align="center">
  <h1 align="center">wavekit-plus</h1>
  <p align="center">
    Turn simulation waveforms into NumPy arrays.<br>
    Measure latency, check protocols, find timing bugs — in Python, not in a waveform viewer.
  </p>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.16-3366cc?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9+-3366cc?style=flat-square&logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-3366cc?style=flat-square">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-22aa55?style=flat-square">
</p>

<p align="center">
  <b>Forked from <a href="https://github.com/cxzzzz/wavekit">cxzzzz/wavekit</a></b> —
  replacing vcdvcd with a streaming, IEEE-compliant VCD parser.
</p>

---

## What is this?

You run an RTL simulation (Verilator, Icarus, QuestaSim, VCS) and it produces a `.vcd`
file — a recording of every signal change over time. Normally you open this in GTKWave
or Verdi, zoom in, squint at values, and manually measure things.

**wavekit-plus** loads that `.vcd` into Python as NumPy arrays, so you can write scripts
to answer questions like:

- "What's the average latency between `arvalid & arready` and `rvalid & rready`?"
- "Does this FIFO ever overflow? Show me every cycle where `w_ptr == r_ptr` and `wr_en`."
- "Find every time `state` was `x` or `z` between 100 ns and 500 ns."
- "Does the write data on port A ever collide with port B on the same cycle?"

It also reads FST (fast Verilator traces) and FSDB (Verdi), and includes a pattern
matching engine that finds temporal sequences — handshakes, bursts, stalls — in a
single pass over the data.

## Why this fork?

The original wavekit uses [vcdvcd](https://github.com/zylin/Verilog_VCD) which loads the
entire VCD into memory before you can touch a single signal, and carries Artistic 1.0 /
GPL v1 license terms.

**This fork** replaces it with the streaming parser from
[VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9, plus:

- **Signal cache** — each signal's value changes are read once and reused
- **4-state masking** — `xz_mask=True` tags every cycle where x or z appeared
- **Input hardening** — 16 resource caps against pathological VCDs
- **License clarity** — MIT + BSD (NumPy), no GPL or Artistic terms

All wavekit APIs are unchanged. Every existing test passes identically.

## Setup

```bash
git clone --recurse-submodules https://github.com/neveltyc/wavekitplus.git
cd wavekitplus
pip install numpy

export PYTHONPATH="$PWD/src:$PYTHONPATH"    # Linux / macOS
$env:PYTHONPATH = "$PWD\src"               # PowerShell
```

No C compiler needed. Optional: `pylibfst` for FST, `Cython` for native-speed resampling,
Verdi runtime for FSDB.

## Quick start

```python
from wavekit import VcdReader

with VcdReader("sim.vcd") as r:
    # Load a signal sampled on clock edges
    addr = r.load_waveform("tb.dut.addr[31:0]", clock="tb.clk")

    # Batch-load with brace expansion
    waves = r.load_matched_waveforms(
        "tb.dut.J_{state,next}[3:0]", clock_pattern="tb.tck"
    )

    # Evaluate an expression directly
    fifo_used = r.eval(
        "tb.dut.w_ptr[2:0] - tb.dut.r_ptr[2:0]", clock="tb.clk"
    )

    # Detect x/z values
    state = r.load_waveform("tb.state[2:0]", clock="tb.clk", xz_mask=True)
    clean = state.drop_xz()
```

### Real example: AXI read latency

```python
with VcdReader("axi_tb.vcd") as r:
    clk = "tb.clk"
    arvalid = r.load_waveform("tb.dut.arvalid", clock=clk)
    arready = r.load_waveform("tb.dut.arready", clock=clk)
    rvalid  = r.load_waveform("tb.dut.rvalid",  clock=clk)
    rready  = r.load_waveform("tb.dut.rready",  clock=clk)
    rdata   = r.load_waveform("tb.dut.rdata[31:0]", clock=clk)

    result = (
        Pattern()
        .wait(arvalid & arready)   # AR handshake
        .wait(rvalid & rready)     # R handshake
        .capture("rdata", rdata)
        .timeout(256)
        .match()
    )

    for m in result.filter_valid():
        print(f"Latency: {m.duration.value} cycles, data: {m.captures['rdata'].value}")
```

## Core API

### Reader

| Method | Description |
|:-------|:------------|
| `VcdReader(file)` | Open a VCD file |
| `load_waveform(signal, clock, ...)` | Load one signal → `Waveform` |
| `load_matched_waveforms(pattern, clock_pattern, ...)` | Batch-load via brace/regex |
| `eval(expr, clock)` | Evaluate an expression with embedded signal paths |
| `get_matched_signals(pattern)` | Resolve a pattern to `Signal` objects |

**Signal path patterns:** `{a,b}` enumerates, `{0..7}` ranges, `@([a-z]+)` regex captures.

### Waveform

A `Waveform` wraps three NumPy arrays: `.value`, `.clock`, `.time`.

| Category | Operations |
|:---------|:-----------|
| Arithmetic | `+` `-` `*` `//` `%` `**` `/` `&` `|` `^` `~` `<<` `>>` `==` `!=` |
| Filtering | `.mask(cond)`, `.filter(fn)`, `.drop_xz()` |
| Slicing | `.time_slice(t0, t1)`, `.cycle_slice(c0, c1)`, `.take(indices)` |
| Edges | `.rising_edge()`, `.falling_edge()` |
| Transform | `.map(fn)`, `.unique_consecutive()`, `.compress()`, `.downsample(n, fn)` |
| Bits | `wave[7:0]`, `.split_bits(n)`, `Waveform.concatenate([a,b])` |
| Shift | `.ahead(n)`, `.back(n)`, `.relative(offset)` |
| 4-state | `.has_xz`, `.xz_cycles`, `.drop_xz()` |

### Pattern engine

Describe a temporal sequence; the NFA engine finds all matches in one pass.

| Step | Description |
|:-----|:------------|
| `.wait(cond)` | Block until condition is true |
| `.delay(n)` | Advance n cycles |
| `.capture(name, signal)` | Record signal value |
| `.require(cond)` | Assert condition (fail → `REQUIRE_VIOLATED`) |
| `.loop(body, until=\|when=)` | Repeat until/when condition |
| `.repeat(body, n)` | Execute body n times |
| `.branch(cond, T, F)` | Conditional branch |
| `.timeout(max)` | Mark unfinished as `TIMEOUT` |
| `.match()` | Run engine → `MatchResult` (`.start`, `.end`, `.duration`, `.captures`, `.filter_valid()`) |

## Version history

| Version | Highlight |
|:--------|:----------|
| `0.8.16` | xz_mask passthrough in load_matched_waveforms / eval / FstReader / FsdbReader |
| `0.8.2` | Fix relative() xz_mask pad length, __eq__/__ne__ xz_mask merge |
| `0.8.1` | Fix xz_mask propagation in binary ops, relative, concatenate |
| `0.8.0` | 4-state x/z masking layer |
| `0.7.0` | Replace vcdvcd with VCD_ANALYZER VCDParser |

Full changelog: [CHANGELOG.md](CHANGELOG.md)

## Tests

```bash
PYTHONPATH=src python tests/run_tests.py
```

Covers VCDParser, VcdReader, iverilog-generated VCDs, cache, xz_mask, and edge cases.

## License

MIT — see [LICENSE](LICENSE).

The embedded VCD parser (`src/wavekit/readers/vcd/vcd_parser.py`) is adapted from
[VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9, also MIT.

[中文说明](README_ZH.md)
