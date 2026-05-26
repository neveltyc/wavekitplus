# wavekit-plus

> **Forked from [cxzzzz/wavekit](https://github.com/cxzzzz/wavekit).** See [Why this fork?](#why-this-fork) below.

English | [中文](README_ZH.md)

**Wavekit** is a fundamental Python library for digital waveform analysis. By seamlessly converting VCD, FST, and FSDB data into Numpy arrays, it empowers engineers to perform high-performance signal processing, protocol analysis, and automated verification with ease.

> 🤖 **AI Integration**: [wavekit-mcp](https://github.com/cxzzzz/wavekit-mcp) — MCP server for AI-assisted waveform analysis. Let AI load signals and run pattern matching — no manual coding required.

## ✨ Features

- **Flexible Signal Extraction**: Flexible batch signal extraction via brace expansion, integer ranges, and regular expressions — load groups of related signals in one call.
- **Rich Analysis Tools**: Numpy-like API for arithmetic, masking, bit-field manipulation, edge detection, and time/cycle slicing — compose complex signal queries in just a few lines.
- **Pattern Matching**: NFA-based temporal pattern engine that scans waveforms in a single pass to extract protocol transactions, measure latencies, and detect timing violations.
- **High-Performance Parsing & Storage**: VCD, FST, and FSDB readers with Numpy-backed storage for fast loading and memory efficiency, handling large simulation files with ease.

## 📦 Setup

wavekit-plus is a source-only fork. Install dependencies and run from source:

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/neveltyc/wavekitplus.git
cd wavekitplus

# Install dependencies (NumPy is required; Cython is optional for native speed)
pip install numpy pytest

# Add src to PYTHONPATH and you're ready
export PYTHONPATH="$PWD/src:$PYTHONPATH"    # Linux / macOS
$env:PYTHONPATH = "$PWD\src"               # PowerShell
```

**No C compiler required** — a pure-Python fallback for the Cython `value_change` module is included.

**Optional dependencies:**
- `pip install pylibfst` — FST waveform support
- `pip install Cython` + MSVC/GCC — build the native Cython extension for ~3x faster resampling
- FSDB support requires the Verdi runtime (`libNPI.so`). Configure via `WAVEKIT_NPI_LIB`, `VERDI_HOME`, or `LD_LIBRARY_PATH`.

## 🚀 Quick Start

> The examples below use placeholder filenames such as `sim.vcd`. Replace them with the path to your own VCD, FST, or FSDB file, and adjust signal paths to match your design hierarchy.

### 1. Batch Signal Extraction

Use brace expansion or regular expressions to load multiple related signals in one call.

```python
from wavekit import VcdReader

with VcdReader("jtag.vcd") as f:
    # Brace expansion: load J_state and J_next in one call
    # Returns: { ('state',): Waveform, ('next',): Waveform }
    waves = f.load_matched_waveforms(
        "tb.u0.J_{state,next}[3:0]",
        clock_pattern="tb.tck",
    )

    # Regex mode (@ prefix): capture groups become dict keys
    waves = f.load_matched_waveforms(
        r"tb.u0.@J_([a-z]+)",
        clock_pattern="tb.tck",
    )
```

---

### 2. Signal Analysis

Waveforms support Numpy-style arithmetic, masking, and edge detection out of the box.

```python
import numpy as np
from wavekit import VcdReader

with VcdReader("fifo_tb.vcd") as f:
    clock = "fifo_tb.clk"
    depth = 8

    w_ptr = f.load_waveform("fifo_tb.s_fifo.w_ptr[2:0]", clock=clock)
    r_ptr = f.load_waveform("fifo_tb.s_fifo.r_ptr[2:0]", clock=clock)
    wr_en = f.load_waveform("fifo_tb.s_fifo.wr_en",      clock=clock)

    occupancy = (w_ptr + depth - r_ptr) % depth
    print(f"Average occupancy: {np.mean(occupancy.value):.2f}")

    # Filter to cycles where a write is active
    write_occ = occupancy.mask(wr_en == 1)

    # Detect write bursts
    burst_cycles = wr_en.rising_edge()
```

---

### 3. Expression Evaluation

Compute waveform expressions directly from signal path strings without loading each signal manually.

```python
from wavekit import VcdReader

with VcdReader("fifo_tb.vcd") as f:
    # Single mode: paths must each match exactly one signal
    occupancy = f.eval(
        "fifo_tb.s_fifo.w_ptr[2:0] - fifo_tb.s_fifo.r_ptr[2:0]",
        clock="fifo_tb.clk",
    )

    # Zip mode: brace patterns expand per key, evaluated once per match
    # Returns: { (0,): Waveform, (1,): Waveform, (2,): Waveform, (3,): Waveform }
    occupancies = f.eval(
        "tb.fifo_{0..3}.w_ptr[2:0] - tb.fifo_{0..3}.r_ptr[2:0]",
        clock="tb.clk",
        mode="zip",
    )
```

---

### 4. Pattern Matching

Describe a temporal sequence of events; the engine finds all matching transactions in one pass.

**AXI-lite Read Latency**

```python
from wavekit import VcdReader, Pattern

with VcdReader("axi_tb.vcd") as f:
    clk     = "tb.clk"
    arvalid = f.load_waveform("tb.dut.arvalid",     clock=clk)
    arready = f.load_waveform("tb.dut.arready",     clock=clk)
    rvalid  = f.load_waveform("tb.dut.rvalid",      clock=clk)
    rready  = f.load_waveform("tb.dut.rready",      clock=clk)
    rdata   = f.load_waveform("tb.dut.rdata[31:0]", clock=clk)

result = (
    Pattern()
    .wait(arvalid & arready)   # AR handshake → start
    .wait(rvalid  & rready)    # R  handshake → end
    .capture("rdata", rdata)
    .timeout(256)
    .match()
)

valid = result.filter_valid()
print(f"Read latencies (cycles): {valid.duration.value}")
print(f"Read data: {valid.captures['rdata'].value}")
```

**AXI Write Burst (multi-beat)**

```python
beat = Pattern().wait(wvalid & wready).capture("beats", wdata, mode="list")

result = (
    Pattern()
    .wait(awvalid & awready)   # AW handshake → burst start
    .loop(beat, until=wlast)   # collect beats until wlast
    .timeout(512)
    .match()
)

for i, inst in enumerate(result.filter_valid()):
    print(f"Burst {i}: {len(inst.captures['beats'])} beats")
```

**Stall Detection**

```python
stall = valid & (ready == 0)

result = (
    Pattern()
    .wait(stall.rising_edge())             # stall begins
    .loop(Pattern().delay(1), when=stall)  # wait while stalling
    .match()
)

stalls = result.filter_valid()
print(f"Stall durations: {stalls.duration.value} cycles")
```

---

## 📖 API Reference

### Reader

| Method | Description |
|--------|-------------|
| `VcdReader(file)` / `FstReader(file)` / `FsdbReader(file)` | Open a waveform file. Use as a context manager. `FsdbReader` requires Verdi runtime (`WAVEKIT_NPI_LIB`, `VERDI_HOME`, or `LD_LIBRARY_PATH`). |
| `reader.load_waveform(signal, clock, ...)` | Load one signal sampled on every clock edge. Returns `Waveform`. |
| `reader.load_matched_waveforms(pattern, clock_pattern, ...)` | Batch-load signals matching a brace/regex pattern. Returns `dict[tuple, Waveform]`. |
| `reader.eval(expr, clock, mode='single'\|'zip', ...)` | Evaluate an arithmetic expression with embedded signal paths. |
| `reader.get_matched_signals(pattern)` | Resolve a pattern to signal paths without loading data. |
| `reader.top_scope_list()` | Return root `Scope` nodes of the signal hierarchy. |

**Pattern syntax** used in signal paths:

| Syntax | Example | Effect |
|--------|---------|--------|
| `{a,b,c}` | `sig_{read,write}` | Enumerate named variants |
| `{N..M}` | `fifo_{0..3}.ptr` | Integer range |
| `{N..M..step}` | `lane_{0..6..2}` | Stepped range |
| `@<regex>` | `@([a-z]+)_valid` | Regex with capture groups |
| `$ModName` | `tb.$fifo_unit.ptr` | Match a direct-child scope by module/definition name (FSDB only) |
| `$$ModName` | `tb.$$fifo_unit.ptr` | Match any-depth descendant scope by module/definition name (FSDB only) |

---

### Waveform

A `Waveform` wraps three parallel numpy arrays (`.value`, `.clock`, `.time`). All operations return a new `Waveform`.

**Arithmetic & comparison**: `+`, `-`, `*`, `//`, `%`, `**`, `/`, `&`, `|`, `^`, `~`, `==`, `!=`, `<<`, `>>`

**Filtering & slicing**

| Method | Description |
|--------|-------------|
| `wave.mask(mask)` | Keep samples where a boolean Waveform or array is True |
| `wave.filter(fn)` | Keep samples where `fn(value)` is True |
| `wave.cycle_slice(begin, end)` | Trim to clock cycle range `[begin, end)` |
| `wave.time_slice(begin, end)` | Trim to simulation time range |
| `wave.slice(begin_idx, end_idx)` | Trim by array index |
| `wave.take(indices)` | Select samples at given indices |

**Transformation**

| Method | Description |
|--------|-------------|
| `wave.map(fn, width, signed)` | Element-wise transform |
| `wave.unique_consecutive()` | Remove consecutive duplicates |
| `wave.downsample(chunk, fn)` | Aggregate into chunks |
| `wave.as_signed()` / `wave.as_unsigned()` | Reinterpret signedness |

**Bit manipulation**

| Method / Syntax | Description |
|-----------------|-------------|
| `wave[high:low]` | Extract bit field (Verilog convention, returns unsigned) |
| `wave[n]` | Extract single bit |
| `wave.split_bits(n)` | Split into n-bit groups (LSB first) |
| `Waveform.concatenate([w0, w1, ...])` | Concatenate (w0 = LSB) |
| `wave.bit_count()` | Population count |

**Edge detection** (1-bit only)

| Method | Description |
|--------|-------------|
| `wave.rising_edge()` | True at 0→1 transitions |
| `wave.falling_edge()` | True at 1→0 transitions |

**Relative time access**

| Method | Description |
|--------|-------------|
| `wave.relative(offset, pad, pad_value)` | Shift by *offset* cycles (positive = future, negative = past) |
| `wave.ahead(n, pad, pad_value)` | Look *n* cycles into the future (shorthand for `relative(n)`) |
| `wave.back(n, pad, pad_value)` | Look *n* cycles into the past (shorthand for `relative(-n)`) |

`pad` controls boundary handling: `'repeat'` (default) pads with the first/last value, `'value'` pads with a given `pad_value`.

```python
# Rising edge detection
rising = (wave == 0) & wave.ahead()

# Compare current vs 3 cycles ago
changed = wave != wave.back(3)
```

---

### Pattern

| Method | Description |
|--------|-------------|
| `.wait(cond, *, require=None, channel=None, tick=True)` | Block until `cond` is True. `require` is checked each waiting cycle (failure → `REQUIRE_VIOLATED`). `channel` binds the wait to a shared FIFO consumer group (see [Channels](#channels) below). `tick=False` matches on the current cycle without consuming it. |
| `.delay(n, *, require=None)` | Advance `n` cycles. `delay(0)` is a no-op. `require` must hold every cycle. |
| `.capture(name, signal, *, mode='last')` | Record signal value at current cycle. `mode='last'` (default) overwrites; `'first'` keeps the first write; `'list'` appends to a list. |
| `.require(cond)` | Assert condition; fail with `REQUIRE_VIOLATED` if False. |
| `.loop(body, *, until=None, when=None)` | `until`: do-while (exit when True after body). `when`: while (exit when False before body). |
| `.repeat(body, n)` | Execute body exactly `n` times. `n` may be a callable. |
| `.branch(cond, true_body, false_body)` | Conditional branch. |
| `.timeout(max_cycles)` | Terminate unfinished instances with `TIMEOUT`. |
| `.match(start_cycle=None, end_cycle=None)` | Run the engine; return `MatchResult`. |

**Channels**

A `Channel` is an identity object representing a shared FIFO consumer group: at most one in-flight pattern instance may consume per cycle. Each `wait()` step has its own implicit channel, so multiple instances of the same pattern automatically serialize one-per-cycle on that step. Pass an explicit `Channel` (or `callable(index, captures) -> Channel`) when you need to override the default serialization — typically when events arrive on physically parallel buses (multi-bank memory, multi-lane retire) and several instances should consume *concurrently* by routing each to its own per-key channel.

```python
from collections import defaultdict
from wavekit import Channel, Pattern

# Multi-bank cache: each bank has its own response port, so two banks
# can return data in the *same* cycle. Without partitioning, the default
# serialization rule would force one instance to wait an extra cycle.
# A per-bank Channel lets each in-flight read consume from its own bank.
banks = defaultdict(Channel)

result = (
    Pattern()
    .wait(req_valid)
    .capture('bank', req_addr & 1)
    .wait(
        lambda i, cap: bank_valid[cap['bank']].value[i],
        channel=lambda i, cap: banks[cap['bank']],
    )
    .capture('rdata',
        lambda i, cap: bank_data[cap['bank']].value[i])
    .match()
)
```

**`MatchResult`**

| Field | Description |
|-------|-------------|
| `.start` / `.end` | Start and end cycle of each match (both inclusive). |
| `.duration` | `end - start + 1` cycles. |
| `.status` | `MatchStatus.OK`, `TIMEOUT`, or `REQUIRE_VIOLATED`. |
| `.captures` | `dict[str, Waveform]` of captured values. |
| `.filter_valid()` | Return only `OK` matches. |

---

## 🛠️ Development

### Setup

```bash
git clone --recurse-submodules https://github.com/neveltyc/wavekitplus.git
cd wavekitplus
pip install numpy pytest
```

### Running tests

```bash
# Set PYTHONPATH and run
PYTHONPATH=src pytest tests/ -v --ignore=tests/test_examples.py --ignore=tests/test_fstreader.py
```

Tests that require `make` / Icarus Verilog / `pylibfst` are skipped on machines without those tools.

### Building the Cython extension (optional)

```bash
pip install Cython setuptools
python build.py
```

## Why this fork?

**wavekit-plus** replaces the [vcdvcd](https://github.com/zylin/Verilog_VCD) VCD parser with [VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER)'s `VCDParser`, bringing:

- **Streaming parse** -- `iter_events()` yields events one at a time instead of loading the entire file into memory.
- **Extended VCD support** -- `$dumpports` port-state characters decoded to 4-state (`0`/`1`/`x`/`z`).
- **Bit-explosion auto-reassembly** -- QuestaSim per-bit declarations merged back into multi-bit buses.
- **Input hardening** -- Resource caps against pathological VCDs without crashing.
- **License clarity** -- Removes vcdvcd (Artistic 1.0 / GPL v1); now pure MIT + BSD (NumPy).

All wavekit APIs, the `Waveform` class, and the `Pattern` engine are untouched. Tests pass identically.

## 📄 License

MIT License. See [LICENSE](./LICENSE). The embedded VCD parser (`src/wavekit/readers/vcd/vcd_parser.py`) is adapted from [VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9 (also MIT).
