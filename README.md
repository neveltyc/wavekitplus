<p align="center">
  <h1 align="center">wavekit-plus</h1>
  <p align="center">
    Turn simulation waveforms into NumPy arrays.<br>
    Measure latency, check protocols, find timing bugs &mdash; in Python, not in a waveform viewer.
  </p>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.9.8-3366cc?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9+-3366cc?style=flat-square&logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-3366cc?style=flat-square">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-22aa55?style=flat-square">
</p>

<p align="center">
  <b>Forked from <a href="https://github.com/cxzzzz/wavekit">cxzzzz/wavekit</a></b> &mdash;
  replacing vcdvcd with a streaming, IEEE-compliant VCD parser.
</p>

---

## What is this?

You run an RTL simulation (Verilator, Icarus, QuestaSim, VCS) and it produces a `.vcd`
file &mdash; a recording of every signal change over time. Normally you open this in GTKWave
or Verdi, zoom in, squint at values, and manually measure things.

**wavekit-plus** loads that `.vcd` into Python as NumPy arrays, so you can write scripts
to answer questions like:

- "What's the average latency between `arvalid & arready` and `rvalid & rready`?"
- "Does this FIFO ever overflow? Show me every cycle where `w_ptr == r_ptr` and `wr_en`."
- "Find every time `state` was `x` or `z` between 100 ns and 500 ns."
- "Does the write data on port A ever collide with port B on the same cycle?"

It also reads FST (fast Verilator traces) and FSDB (Verdi), and includes a pattern
matching engine that finds temporal sequences &mdash; handshakes, bursts, stalls &mdash; in a
single pass over the data.

## Why this fork?

The original wavekit uses [vcdvcd](https://github.com/zylin/Verilog_VCD) which loads the
entire VCD into memory before you can touch a single signal, and carries Artistic 1.0 /
GPL v1 license terms.

**This fork** replaces it with the streaming parser from
[VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9, plus:

- **Signal cache** &mdash; each signal's value changes are read once and reused
- **4-state masking** &mdash; `xz_mask=True` tags every cycle where x or z appeared
- **Input hardening** &mdash; 16 resource caps against pathological VCDs
- **License clarity** &mdash; MIT + BSD (NumPy), no GPL or Artistic terms

The core wavekit workflow remains backward compatible; new fork-specific features
are exposed as optional parameters and helpers.

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
from wavekit import Pattern, VcdReader

with VcdReader("axi_tb.vcd") as r:
    clk = "tb.clk"
    arvalid = r.load_waveform("tb.dut.arvalid", clock=clk)
    arready = r.load_waveform("tb.dut.arready", clock=clk)
    rvalid  = r.load_waveform("tb.dut.rvalid",  clock=clk)
    rready  = r.load_waveform("tb.dut.rready",  clock=clk)
    rdata   = r.load_waveform("tb.dut.rdata[31:0]", clock=clk)

    result = (
        Pattern(timeout=256)
        .wait(arvalid & arready)   # AR handshake
        .wait(rvalid & rready)     # R handshake
        .capture("rdata", rdata)
        .match()
    )

    ok = result.filter_ok()
    print(f"Latencies (cycles): {ok.duration.value}")
    print(f"Read data: {ok.captures['rdata'].value}")
```

## Core API

### Reader

| Method | Description |
|:-------|:------------|
| `VcdReader(file)` | Open a VCD file |
| `load_waveform(signal, clock, ...)` | Load one signal &rarr; `Waveform` |
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

Describe a temporal sequence; the engine finds all matches in one pass.
There are two authoring styles sharing one runtime:

- **Declarative** &mdash; chain steps like `.wait()`, `.consume()`, `.capture()`, `.loop()`. Best for fixed transaction flows.
- **Programmable** &mdash; pass an async handler to `Pattern(handler)`. Best for dynamic branches and per-ID routing.

| Step | Description |
|:-----|:------------|
| `.wait(cond)` | Observe cycles until condition is true (non-consuming) |
| `.consume(cond, channel)` | Wait and atomically consume a channel event (FIFO arbitration) |
| `.delay(n)` | Advance n cycles |
| `.capture(name, signal)` | Record signal value |
| `.require(cond)` | Assert condition (fail &rarr; `REQUIRE_VIOLATED`) |
| `.loop(body, until=\|when=)` | Repeat until/when condition |
| `.repeat(body, n)` | Execute body n times |
| `.branch(cond, T, F)` | Conditional branch |
| `Pattern(timeout=max)` | Mark unfinished as `TIMEOUT` (`.timeout(max)` is deprecated) |
| `.match()` | Run engine &rarr; `MatchResult` (`.start`, `.end`, `.duration`, `.status`, `.captures`, `.filter_ok()`, `.filter_failed()`, `.filter_status(s)`) |
| `.collect()` | Programmable only: gather non-`None` handler return values into a list |

**Programmable example** &mdash; match out-of-order responses by ID:

```python
arfire = arvalid & arready   # precompute outside the handler
rfire = rvalid & rready

async def read_txn(ctx):
    if ctx.value(arfire):
        my_id = ctx.value(arid)
        await ctx.consume(
            lambda: ctx.value(rfire) and ctx.value(rid) == my_id,
            channel=("r", my_id),
        )
        return {"arid": my_id, "rdata": int(ctx.value(rdata))}
    return None

records = Pattern(read_txn, timeout=64).collect()
```

## API notes

**scalar ** Waveform** is not supported. The result width depends on runtime data
and cannot be expressed as a fixed-width integer. Use wave.map(lambda v: base ** int(v), width=N)
with an explicit output width, or (1 << wave) when the base is 2.

**Unsigned subtraction** has fixed-width wraparound semantics:  - b wraps at
2^width when  < b. This matches hardware subtractor behavior. To avoid wraparound,
use .as_signed() - b.as_signed() or expand width before subtraction.

**Bitwise operations** (& | ^ ~) treat operands as raw bits and do not check
signedness. The result is always unsigned. Arithmetic (+ - * / // % **) and comparison
(== !=) still require matching signedness.


## Version history

| Version | Highlight |
|:--------|:----------|
| `0.9.6` | root_scope signal matching, VCD subrange metadata, strict bit selection |
| `0.9.1` | root_scope relative matching helpers and scoped path cleanup |
| `0.9.0` | Shared binary-op checks and reader finalization across backends |
| `0.8.16` | Python 3.9 compat, __getitem__ bounds, root_scope nested paths |
| `0.8.15` | signed+subrange fix, mask alignment, alias scope tree |
| `0.8.14` | select_clock_edges shared helper, FST/FSDB edge detect |
| `0.8.0` | 4-state x/z masking layer |
| `0.7.0` | Replace vcdvcd with VCD_ANALYZER VCDParser |

Full changelog: [CHANGELOG.md](CHANGELOG.md)

## Tests

```bash
PYTHONPATH=src python tests/run_tests.py
```

Covers VCDParser, VcdReader, iverilog-generated VCDs, cache, xz_mask, and edge cases.
If dev dependencies are installed, `python -m pytest -q` runs the broader pytest suite.

## Release tags

Use the PowerShell release helper from a prepared working tree:

```powershell
.\release_tag.ps1 -Version v0.9.6 -CommitMessage "release: v0.9.6"
```

The script verifies versioned docs, runs `tests/run_tests.py`, runs pytest when
available, preserves tracked VCD fixtures that Iverilog rewrites with new dates,
commits the release changes, and creates an annotated Git tag. Push afterwards with:

```bash
git push origin main --follow-tags
```

## License

MIT &mdash; see [LICENSE](LICENSE).

The embedded VCD parser (`src/wavekit/readers/vcd/vcd_parser.py`) is adapted from
[VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9, also MIT.

[中文说明](README_ZH.md)
