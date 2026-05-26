<p align="center">
  <h1 align="center">wavekit-plus</h1>
  <p align="center">
    数字电路波形分析 Python 库 —
    将 VCD/FST/FSDB 信号加载为 NumPy 数组，运行模式匹配，一次扫描完成计算。
  </p>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.1-3366cc?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9+-3366cc?style=flat-square&logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-3366cc?style=flat-square">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-22aa55?style=flat-square">
</p>

<p align="center">
  <b>Fork 自 <a href="https://github.com/cxzzzz/wavekit">cxzzzz/wavekit</a></b> —
  用 <a href="https://github.com/neveltyc/VCD_ANALYZER">VCD_ANALYZER</a> 的流式解析器替换了原有的 vcdvcd 依赖。
</p>

---

## 为什么有 wavekit-plus？

原始 wavekit 使用 [vcdvcd](https://github.com/zylin/Verilog_VCD) 作为 VCD 解析器，它在访问任何信号
之前必须将整个文件加载到内存中，而且引入了 Artistic 1.0 / GPL v1 许可证条款。

**wavekit-plus** 用 [VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9 的 `VCDParser` 替换了它：

- **流式解析** — `iter_events()` 逐个产出值变化事件。只加载一个信号时，不需要为所有信号付出内存代价。
- **Bit-explosion 自动重组** — QuestaSim 逐比特的 `$var` 声明自动合并回多比特总线。
- **扩展 VCD 支持** — `$dumpports` 端口状态正确解码为 4-state (`0`/`1`/`x`/`z`)。
- **输入防御** — 16 项资源上限抵御畸形的恶意 VCD 文件。
- **4-state 掩码** — `xz_mask=True` 标记每个时钟周期是否包含 x 或 z，掩码随算术、切片、过滤自动传播。
- **信号缓存** — 每个信号的值变化列表只从文件读取一次，同一 reader 实例内重复 `load_waveform` 直接命中缓存。
- **许可证澄清** — 依赖链变为纯 MIT + BSD (NumPy)，不再有 GPL 或 Artistic 条款。

上层 `Waveform` 类和 `Pattern` 引擎完全不变，所有已有测试结果一致。

## 安装

```bash
git clone --recurse-submodules https://github.com/neveltyc/wavekitplus.git
cd wavekitplus
pip install numpy

# 设置 PYTHONPATH 即可使用
export PYTHONPATH="$PWD/src:$PYTHONPATH"    # Linux / macOS
$env:PYTHONPATH = "$PWD\src"               # PowerShell
```

无需 C 编译器 — 已内置 Cython `value_change` 模块的纯 Python 回退。

**可选依赖：** `pip install pylibfst` 支持 FST 格式，`Cython` 编译原生扩展提升重采样性能。
FSDB 支持需要 Verdi 运行时 (`libNPI.so`)。

## 快速上手

```python
from wavekit import VcdReader

with VcdReader("sim.vcd") as r:
    # 加载单个信号，按时钟边沿采样
    addr = r.load_waveform("tb.dut.addr[31:0]", clock="tb.clk")

    # 大括号展开批量加载
    waves = r.load_matched_waveforms(
        "tb.dut.J_{state,next}[3:0]",
        clock_pattern="tb.tck",
    )

    # 表达式直接求值
    occupancy = r.eval(
        "tb.dut.w_ptr[2:0] - tb.dut.r_ptr[2:0]",
        clock="tb.clk",
    )

    # 加载时检测 x/z
    state = r.load_waveform("tb.state[2:0]", clock="tb.clk", xz_mask=True)
    clean = state.drop_xz()  # 移除含未知值的周期
```

## 核心 API

### Reader

| 方法 | 说明 |
|:-----|:-----|
| `VcdReader(file)` | 打开 VCD 文件，支持上下文管理器。 |
| `load_waveform(signal, clock, ...)` | 加载单个信号按时钟边沿采样，返回 `Waveform`。 |
| `load_matched_waveforms(pattern, clock_pattern, ...)` | 按大括号/正则模式批量加载信号。 |
| `eval(expr, clock, mode="single"|"zip")` | 对包含信号路径的表达式直接求值。 |
| `get_matched_signals(pattern)` | 解析模式为 `Signal` 对象，不加载数据。 |
| `top_scope_list()` | 返回层级树的根 `Scope` 节点。 |

**信号路径模式语法：** `{a,b}` 枚举、`{0..7}` 范围、`@([a-z]+)` 正则捕获。

### Waveform

`Waveform` 封装了三个平行的 NumPy 数组：`.value`、`.clock`、`.time`。

| 类别 | 操作 |
|:-----|:-----|
| **算术** | `+` `-` `*` `//` `%` `**` `/` `&` `|` `^` `~` `<<` `>>` `==` `!=` |
| **过滤** | `.mask(cond)`, `.filter(fn)`, `.drop_xz()` |
| **切片** | `.time_slice(t0, t1)`, `.cycle_slice(c0, c1)`, `.slice(i0, i1)`, `.take(indices)` |
| **边沿** | `.rising_edge()`, `.falling_edge()` (仅 1-bit) |
| **变换** | `.map(fn)`, `.unique_consecutive()`, `.compress()`, `.downsample(n, fn)` |
| **位操作** | `wave[7:0]` (位切片), `.split_bits(n)`, `Waveform.concatenate([a,b])` |
| **移位** | `.ahead(n)`, `.back(n)`, `.relative(offset)` |
| **4-state** | `.has_xz`, `.xz_cycles`, `.drop_xz()` |

### Pattern 模式匹配引擎

描述一段时序序列，NFA 引擎单次扫描找出所有匹配实例。

```python
from wavekit import Pattern

result = (
    Pattern()
    .wait(arvalid & arready)    # 等待 AR 握手
    .wait(rvalid & rready)      # 等待 R 握手
    .capture("rdata", rdata)    # 记录读数据
    .timeout(256)
    .match()
)

for m in result.filter_valid():
    print(f"延迟: {m.duration.value} 周期, 数据: {m.captures['rdata'].value}")
```

| 步骤 | 说明 |
|:-----|:-----|
| `.wait(cond)` | 阻塞等待条件为真。 |
| `.delay(n)` | 前进 n 个周期。 |
| `.capture(name, signal)` | 记录信号值。 |
| `.require(cond)` | 断言条件；失败标记为 `REQUIRE_VIOLATED`。 |
| `.loop(body, until=|when=)` | 循环执行直到/当条件满足。 |
| `.repeat(body, n)` | 重复执行 n 次。 |
| `.branch(cond, T, F)` | 条件分支。 |
| `.timeout(max)` | 未完成实例标记为 `TIMEOUT`。 |
| `.match()` | 运行引擎；返回 `MatchResult`，内含 `.start`、`.end`、`.duration`、`.captures`、`.filter_valid()`。 |

## 版本历史

| 版本 | 亮点 |
|:-----|:-----|
| `0.8.1` | 修复 xz_mask 在二元运算、relative、concatenate 中的传播 |
| `0.8.0` | 4-state x/z 掩码层 |
| `0.7.2` | 信号值变化缓存（单次扫描批量加载） |
| `0.7.1` | 代码卫生 + 全面测试套件 |
| `0.7.0` | 用 VCD_ANALYZER VCDParser 替换 vcdvcd |

完整更新日志：[CHANGELOG.md](CHANGELOG.md)

## 测试

```bash
PYTHONPATH=src python tests/run_tests.py
```

48 项测试覆盖 VCDParser、VcdReader、iverilog 生成 VCD、缓存层、xz_mask 及边界情况。无需 pytest。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

内嵌的 VCD 解析器 (`src/wavekit/readers/vcd/vcd_parser.py`)
改编自 [VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9，同为 MIT 许可。

[English](README.md)
