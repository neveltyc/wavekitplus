<p align="center">
  <h1 align="center">wavekit-plus</h1>
  <p align="center">
    把仿真波形变成 NumPy 数组。<br>
    测量延迟、检查协议、定位时序 bug &mdash; 用 Python 脚本，而不是在波形查看器里手动翻。
  </p>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.9.8-3366cc?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9+-3366cc?style=flat-square&logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-3366cc?style=flat-square">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-22aa55?style=flat-square">
</p>

<p align="center">
  <b>Fork 自 <a href="https://github.com/cxzzzz/wavekit">cxzzzz/wavekit</a></b> &mdash;
  用流式 IEEE 兼容 VCD 解析器替换了原有的 vcdvcd。
</p>

---

## 这是什么？

你用 Verilator / Icarus / QuestaSim / VCS 跑 RTL 仿真，生成了一个 `.vcd` 文件&mdash;&mdash;
里面记录了每个信号在每个时刻的值变化。通常你会打开 GTKWave 或 Verdi，缩放、肉眼读数、手动量时间。

**wavekit-plus** 把这个 `.vcd` 加载成 Python 里的 NumPy 数组，让你写脚本来回答这些问题：

- "`arvalid & arready` 到 `rvalid & rready` 的平均延迟是多少？"
- "这个 FIFO 有没有溢出过？列出所有 `w_ptr == r_ptr` 且 `wr_en` 为高的周期。"
- "在 100 ns 到 500 ns 之间，`state` 出现过几次 `x` 或 `z`？"
- "端口 A 和端口 B 的写数据有没有在同一周期发生过碰撞？"

也支持 FST 格式（Verilator 快照）和 FSDB 格式（Verdi），并内置了一个模式匹配引擎&mdash;&mdash;
描述一段时序序列（握手、突发、stall），引擎单次扫描就能找出所有匹配实例。

## 为什么 Fork？

原始 wavekit 使用 [vcdvcd](https://github.com/zylin/Verilog_VCD)，它必须把整个 VCD 文件加载到内存
才能访问任何信号，而且引入了 Artistic 1.0 / GPL v1 许可证。

**本 Fork** 用 [VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9 的流式解析器替换了它，外加：

- **信号缓存** &mdash; 每个信号只从文件读一次，重复使用
- **4-state 掩码** &mdash; `xz_mask=True` 标记每个周期是否有 x 或 z
- **输入防御** &mdash; 16 项资源上限抵御恶意/畸形 VCD
- **许可证澄清** &mdash; MIT + BSD (NumPy)，没有 GPL 或 Artistic 条款

核心 wavekit 使用流程保持向后兼容；本 fork 的新增能力通过可选参数和辅助方法提供。

## 安装

```bash
git clone --recurse-submodules https://github.com/neveltyc/wavekitplus.git
cd wavekitplus
pip install numpy

export PYTHONPATH="$PWD/src:$PYTHONPATH"    # Linux / macOS
$env:PYTHONPATH = "$PWD\src"               # PowerShell
```

无需 C 编译器。可选：`pylibfst` 读 FST，`Cython` 编译加速，Verdi 运行时读 FSDB。

## 快速上手

```python
from wavekit import VcdReader

with VcdReader("sim.vcd") as r:
    # 加载信号，按时钟边沿采样
    addr = r.load_waveform("tb.dut.addr[31:0]", clock="tb.clk")

    # 大括号展开批量加载
    waves = r.load_matched_waveforms(
        "tb.dut.J_{state,next}[3:0]", clock_pattern="tb.tck"
    )

    # 表达式直接求值
    fifo_used = r.eval(
        "tb.dut.w_ptr[2:0] - tb.dut.r_ptr[2:0]", clock="tb.clk"
    )

    # 检测 x/z
    state = r.load_waveform("tb.state[2:0]", clock="tb.clk", xz_mask=True)
    clean = state.drop_xz()
```

### 实例：测量 AXI 读延迟

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
        .wait(arvalid & arready)   # AR 握手
        .wait(rvalid & rready)     # R 握手
        .capture("rdata", rdata)
        .match()
    )

    ok = result.filter_ok()
    print(f"延迟（周期）: {ok.duration.value}")
    print(f"读数据: {ok.captures['rdata'].value}")
```

## 核心 API

### Reader

| 方法 | 说明 |
|:-----|:-----|
| `VcdReader(file)` | 打开 VCD 文件 |
| `load_waveform(signal, clock, ...)` | 加载单个信号 &rarr; `Waveform` |
| `load_matched_waveforms(pattern, clock_pattern, ...)` | 按大括号/正则批量加载 |
| `eval(expr, clock)` | 对包含信号路径的表达式求值 |
| `get_matched_signals(pattern)` | 解析模式为 `Signal` 对象 |

**信号路径模式：** `{a,b}` 枚举、`{0..7}` 范围、`@([a-z]+)` 正则捕获。

### Waveform

`Waveform` 封装三个 NumPy 数组：`.value`、`.clock`、`.time`。

| 类别 | 操作 |
|:-----|:-----|
| 算术 | `+` `-` `*` `//` `%` `**` `/` `&` `|` `^` `~` `<<` `>>` `==` `!=` |
| 过滤 | `.mask(cond)`, `.filter(fn)`, `.drop_xz()` |
| 切片 | `.time_slice(t0, t1)`, `.cycle_slice(c0, c1)`, `.take(indices)` |
| 边沿 | `.rising_edge()`, `.falling_edge()` |
| 变换 | `.map(fn)`, `.unique_consecutive()`, `.compress()`, `.downsample(n, fn)` |
| 位操作 | `wave[7:0]`, `.split_bits(n)`, `Waveform.concatenate([a,b])` |
| 移位 | `.ahead(n)`, `.back(n)`, `.relative(offset)` |
| 4-state | `.has_xz`, `.xz_cycles`, `.drop_xz()` |

### Pattern 模式匹配

描述一段时序序列，引擎单次扫描找出所有匹配。
两种写法共享同一个运行时：

- **声明式** &mdash; 链式调用 `.wait()`、`.consume()`、`.capture()`、`.loop()` 等步骤，适合固定形态的事务流。
- **可编程式** &mdash; 向 `Pattern(handler)` 传入 async 处理函数，适合动态分支、按 ID 路由等复杂流程。

| 步骤 | 说明 |
|:-----|:-----|
| `.wait(cond)` | 观察等待条件为真（非消费型） |
| `.consume(cond, channel)` | 等待并原子消费一个通道事件（FIFO 仲裁） |
| `.delay(n)` | 前进 n 个周期 |
| `.capture(name, signal)` | 记录信号值 |
| `.require(cond)` | 断言条件（失败 &rarr; `REQUIRE_VIOLATED`） |
| `.loop(body, until=|when=)` | 循环直到/当条件满足 |
| `.repeat(body, n)` | 重复 n 次 |
| `.branch(cond, T, F)` | 条件分支 |
| `Pattern(timeout=max)` | 超时标记 `TIMEOUT`（`.timeout(max)` 已弃用） |
| `.match()` | 运行引擎 &rarr; `MatchResult`（`.start` `.end` `.duration` `.status` `.captures` `.filter_ok()` `.filter_failed()` `.filter_status(s)`） |
| `.collect()` | 仅可编程式：收集处理函数的非 `None` 返回值为列表 |

**可编程式示例** &mdash; 按 ID 匹配乱序响应：

```python
arfire = arvalid & arready   # 固定表达式在处理函数外预计算
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

## 版本历史

| 版本 | 亮点 |
|:-----|:-----|
| `0.9.6` | root_scope 信号匹配、VCD subrange metadata、严格 bit 选择 |
| `0.9.1` | root_scope 相对匹配辅助函数和 scoped path 清理 |
| `0.9.0` | 共享二元运算检查和三个 reader 后端的收尾逻辑 |
| `0.8.16` | Python 3.9 兼容, __getitem__ 边界检查, root_scope 嵌套路径 |
| `0.8.15` | signed+subrange 修复, mask 对齐, alias scope tree |
| `0.8.14` | select_clock_edges 公共函数, FST/FSDB 边沿检测 |
| `0.8.0` | 4-state x/z 掩码层 |
| `0.7.0` | 用 VCD_ANALYZER VCDParser 替换 vcdvcd |

完整更新日志：[CHANGELOG.md](CHANGELOG.md)

## 测试

```bash
PYTHONPATH=src python tests/run_tests.py
```

覆盖 VCDParser、VcdReader、iverilog 生成 VCD、缓存、xz_mask 及边界情况。
如果安装了开发依赖，`python -m pytest -q` 会运行更完整的 pytest 套件。

## 发布 tag

从已经准备好版本号和文档的工作树运行 PowerShell 发布脚本：

```powershell
.\release_tag.ps1 -Version v0.9.6 -CommitMessage "release: v0.9.6"
```

脚本会检查版本文档、运行 `tests/run_tests.py`、在可用时运行 pytest、保护 Iverilog
测试会改写日期的已跟踪 VCD fixture、提交发布改动，并创建 annotated Git tag。之后推送：

```bash
git push origin main --follow-tags
```

## 许可证

MIT &mdash; 详见 [LICENSE](LICENSE)。

内嵌的 VCD 解析器 (`src/wavekit/readers/vcd/vcd_parser.py`) 改编自
[VCD_ANALYZER](https://github.com/neveltyc/VCD_ANALYZER) v1.3.9，同为 MIT 许可。

[English](README.md)
