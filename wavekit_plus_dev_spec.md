# wavekit-plus 开发文档

## 目标

Fork wavekit，用 VCD_ANALYZER 的 `VCDParser` 替换 vcdvcd 依赖，获得流式解析、Extended VCD 支持、bit-explosion 自动重组、输入防御。上层的 Waveform 类和 Pattern 引擎不动。

## 前置条件

```bash
# 源码
git clone https://github.com/cxzzzz/wavekit.git
curl -fsSL https://raw.githubusercontent.com/neveltyc/VCD_ANALYZER/v1.3.9/vcd_analyzer.py -o vcd_analyzer.py

# 理解两个项目
# wavekit 源码：wavekit/src/wavekit/
# VCD_ANALYZER 源码：vcd_analyzer.py（单文件）
```

---

## 架构理解：数据流

```
当前 wavekit 的数据流：

VCD 文件
  → vcdvcd.VCDVCD(file)          全量解析到内存，得到 signal.tv = [(time, value_str), ...]
  → re.sub(r'[xXzZ]', '0', v)    x/z 替换成整数
  → np.array([(t, int(v, 2))])    转成 Numpy (time, int_value) 二维数组
  → value_change_to_value_array() Cython 函数，按时钟边沿重采样
  → Waveform(value, clock, time)  上层所有操作基于此对象

替换后的数据流：

VCD 文件
  → VCDParser(file)               流式 header 解析，得到 signals dict
  → iter_events(sids={target})     流式产出 (time, sig_id, value_str)，只遍历所需信号
  → 收集 per-signal (time, value_str) 列表
  → x/z 替换 + int 转换            与当前逻辑相同
  → np.array([(t, int_value)])     与当前逻辑相同
  → value_change_to_value_array()  不变
  → Waveform(value, clock, time)   不变
```

**关键改进点：** 当前 vcdvcd 全量解析所有信号到内存；替换后 `iter_events(sids=...)` 只遍历所需信号，内存占用降低一个数量级。

---

## 需要改的文件（3 个）

### 1. `src/wavekit/readers/vcd/reader.py`（重写，约 250 行）

这是唯一的核心改动文件。当前 204 行，重写后预计 250 行左右。

#### 1.1 删除 vcdvcd 依赖

```python
# 删除这两行：
from vcdvcd import VCDVCD
from vcdvcd import Scope as VcdVcdScope

# 替换为：
from .vcd_parser import VCDParser  # 从 vcd_analyzer.py 提取的解析器
```

#### 1.2 重写 VcdScope 类

当前 VcdScope 包装 vcdvcd 的 `VcdVcdScope` 对象。替换后需要从 `VCDParser.signals` 重建 scope 树。

VCDParser 的 signals 字典结构：
```python
parser.signals = {
    'sig_id': {
        'path': 'tb.dut.data[7:0]',    # 完整路径
        'width': 8,                      # 位宽
        'type': 'wire',                  # 类型
        'scope': 'tb.dut',              # 声明时的 scope
        'scopes': ['tb.dut'],           # 所有 scope（含 alias）
        'aliases': ['tb.dut.data[7:0]'], # 所有路径别名
        'synthesized': False,            # 是否 bit-explosion 重组
    }
}
```

需要从 `scope` 字段重建树结构。实现方式：

```python
class VcdScope(Scope):
    def __init__(self, name: str, full_path: str, parser: VCDParser, reader: 'VcdReader'):
        super().__init__(name=name)
        self._full_path = full_path
        self._parser = parser
        self._reader = reader

    @cached_property
    def signal_list(self) -> Sequence[Signal]:
        signals = []
        for sid, info in self._parser.signals.items():
            if info.get('scope') == self._full_path:
                # 从 path 提取本地名称
                local_name = info['path'].split('.')[-1]
                signals.append(Signal(
                    name=local_name,
                    full_name=info['path'],
                    width=info['width'],
                    range=None,
                    signed=False,
                ))
        return signals

    @cached_property
    def child_scope_list(self) -> Sequence[Scope]:
        # 找所有直接子 scope
        prefix = self._full_path + '.'
        children = set()
        for sid, info in self._parser.signals.items():
            scope = info.get('scope', '')
            if scope.startswith(prefix):
                # 取下一级 scope 名
                remainder = scope[len(prefix):]
                child_name = remainder.split('.')[0]
                children.add(child_name)
        return [
            VcdScope(name=c, full_path=f'{self._full_path}.{c}',
                     parser=self._parser, reader=self._reader)
            for c in sorted(children)
        ]
```

#### 1.3 重写 VcdReader 类

```python
class VcdReader(Reader):
    def __init__(self, file: str):
        super().__init__()
        self.file = file
        self._parser = VCDParser(file)
        # 提取顶层 scope
        top_scopes = set()
        for sid, info in self._parser.signals.items():
            scope = info.get('scope', '')
            if scope:
                top_scopes.add(scope.split('.')[0])
        self._top_scope_list = [
            VcdScope(name=s, full_path=s, parser=self._parser, reader=self)
            for s in sorted(top_scopes)
        ]

    def top_scope_list(self) -> Sequence[Scope]:
        return self._top_scope_list

    @property
    def begin_time(self) -> int:
        t_min, _ = self._parser.scan_time_range()
        return t_min if t_min is not None else 0

    @property
    def end_time(self) -> int:
        _, t_max = self._parser.scan_time_range()
        return t_max if t_max is not None else 0
```

注意：`scan_time_range()` 每次调用会扫全文件。应该在 `__init__` 里缓存结果：

```python
    def __init__(self, file: str):
        ...
        self._time_range = self._parser.scan_time_range()

    @property
    def begin_time(self) -> int:
        return self._time_range[0] if self._time_range[0] is not None else 0

    @property
    def end_time(self) -> int:
        return self._time_range[1] if self._time_range[1] is not None else 0
```

#### 1.4 重写 load_waveform 方法

这是最关键的方法。当前实现从 vcdvcd 的 `signal.tv` 列表读取数据。替换后从 `iter_events()` 收集。

核心转换逻辑：

```python
def load_waveform(self, signal, clock, xz_value=0, signed=False,
                  sample_on_posedge=False, begin_time=None, end_time=None,
                  begin_cycle=None, end_cycle=None) -> Waveform:
    # ... 参数校验（与当前相同）...

    signal_path = signal.full_name if isinstance(signal, Signal) else signal
    clock_path = clock.full_name if isinstance(clock, Signal) else clock

    # 解析 range suffix
    bare_signal_path, range_suffix = split_by_range_expr(signal_path)

    # 找到 signal id 和 clock id
    signal_sid = self._resolve_signal_path(bare_signal_path)
    clock_sid = self._resolve_signal_path(clock_path)
    signal_info = self._parser.signals[signal_sid]
    width = signal_info['width']

    # 从 iter_events 收集 value changes
    # 只请求这两个信号，避免遍历无关信号
    needed_sids = {signal_sid, clock_sid}
    signal_tv = []  # [(time, value_str), ...]
    clock_tv = []

    for t, sid, val in self._parser.iter_events(sids=needed_sids):
        if sid == signal_sid:
            signal_tv.append((t, val))
        elif sid == clock_sid:
            clock_tv.append((t, val))

    # 转成 Numpy 数组（与当前 wavekit 逻辑相同）
    clock_changes = np.array(
        [(t, int(re.sub(r'[xXzZ]', '0', v), 2)) for t, v in clock_tv],
        dtype=np.uint64,
    )

    signal_value_change = np.array(
        [(t, int(re.sub(r'[xXzZ]', str(xz_value), v), 2)) for t, v in signal_tv],
        dtype=np.object_ if width > 64 else np.uint64,
    )

    # 以下与当前 wavekit 完全相同
    # ... clock edge 计算、begin_cycle/end_cycle 转换、value_change_to_waveform ...
```

#### 1.5 辅助方法 _resolve_signal_path

```python
def _resolve_signal_path(self, path: str) -> str:
    """从信号路径解析到 VCDParser 的 sig_id。"""
    # 精确匹配
    for sid, info in self._parser.signals.items():
        if path in info['aliases']:
            return sid
    # 带 range suffix 的模糊匹配
    pattern = re.compile(rf'^{re.escape(path)}\[\d+(?::\d+)?\]$')
    matches = []
    for sid, info in self._parser.signals.items():
        for alias in info['aliases']:
            if pattern.fullmatch(alias):
                matches.append(sid)
                break
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f'path {path!r} matches multiple signals')
    raise ValueError(f'signal {path!r} not found')

def close(self):
    pass
```

### 2. `src/wavekit/readers/vcd/vcd_parser.py`（新建）

从 `vcd_analyzer.py` 提取 `VCDParser` 类及其依赖。需要提取的部分：

- `VCDParser` 类（`_parse_header`、`iter_events`、`scan_time_range`、`match`、`_consume_value_change`、`_is_structural_token`、`_data_tokens`）
- 依赖的工具函数：`_parse_timescale`、`_safe_int_digits`、`_parse_vcd_timestamp_token`、`_is_4state_bits`、`_clamp_overwide_logic_value`
- 依赖的常量：所有 `MAX_*` 常量、`_env_int`、`_UNITS`、`_REAL_RE`、`_PORT_STATE`、`_DECL_KEYWORDS`、`_SIM_KEYWORDS`、`_DATA_SKIP_SECTIONS`
- 异常类：`_VCDResourceError`

**不需要**提取的部分：

- 所有 `cmd_*` 函数（命令实现）
- `main()` 和 argparse 代码
- `parse_time`、`fmt_time`、`fmt_val`（CLI 格式化工具）
- condition 相关代码（`_parse_conditions`、`_value_matches` 等）
- filter 相关代码（`_normalize_filter_patterns`、`_glob_lite_regex`）

提取后大约 700-800 行。文件头加上 license 声明：

```python
# VCD parser extracted from VCD_ANALYZER v1.3.9
# Original: https://github.com/neveltyc/VCD_ANALYZER
# License: MIT (c) 2026 neveltyc
#
# Modifications for wavekit integration:
# - Extracted VCDParser class and dependencies only
# - Removed CLI commands, formatters, condition engine
```

### 3. `pyproject.toml`（修改依赖）

```toml
[tool.poetry.dependencies]
python = "^3.9"
numpy = "^2.0.0"
# vcdvcd = "^2.3.5"    ← 删除
pylibfst = "^0.2.1"
pytest = "^8.2.2"
```

---

## 不需要改的文件

| 文件 | 行数 | 原因 |
|---|---|---|
| `src/wavekit/waveform.py` | 1449 | 只消费 Numpy 数组，不关心解析器 |
| `src/wavekit/pattern/*.py` | 940 | 只消费 Waveform 对象 |
| `src/wavekit/readers/base.py` | 537 | 抽象基类，接口不变 |
| `src/wavekit/readers/value_change.pyx` | 125 | Cython 重采样，输入是 Numpy 数组 |
| `src/wavekit/readers/fsdb/*` | 1026 | FSDB reader 独立，不受影响 |
| `src/wavekit/readers/fst/*` | 261 | FST reader 独立，不受影响 |
| `src/wavekit/scope.py` | 317 | 基类不变，VcdScope 子类在 reader.py 里 |
| `src/wavekit/signal.py` | 87 | 数据类不变 |
| `src/wavekit/__init__.py` | 71 | 导出不变（VcdReader 路径不变） |

---

## 测试策略

### 第一阶段：现有测试全部通过

```bash
poetry run pytest tests/test_vcdreader.py -v
poetry run pytest tests/test_readme_examples.py -v
poetry run pytest tests/test_examples.py -v
```

这些测试使用 `tests/testdata/jtag.vcd` 作为 fixture，验证 VcdReader 的所有公开接口。替换后这些测试必须全部通过且结果一致。

### 第二阶段：新增测试

针对 VCD_ANALYZER 解析器的独特能力：

```python
# test_vcdreader_plus.py

def test_bit_exploded_bus_reassembly():
    """QuestaSim 的 bit-explosion 应被自动重组为单个 bus 信号。"""
    # 构造一个包含 bus[0], bus[1], ..., bus[7] 的 VCD fixture
    # 验证 VcdReader 能加载 bus[7:0] 作为一个 8-bit 信号

def test_extended_vcd_port_state():
    """Extended VCD 的 p<state> 格式应被正确解析为 4-state 值。"""
    # 构造一个包含 $dumpports 的 VCD fixture

def test_malformed_vcd_does_not_crash():
    """畸形 VCD 不应导致未捕获异常。"""
    # 构造包含超长 timestamp、非法 $var 宽度、截断文件等 fixture

def test_large_signal_count_resource_limit():
    """超过 MAX_VARS 的 VCD 应报 _VCDResourceError 而非 OOM。"""

def test_streaming_memory_constant():
    """加载单个信号时，内存占用不应随文件中信号总数增长。"""
    # 生成一个 10000 信号的 VCD，只加载其中 1 个
    # 验证 peak memory 没有爆炸
```

### 第三阶段：性能对比

```python
# benchmark_vcd_reader.py

def benchmark_load_single_signal():
    """对比替换前后加载单个信号的速度和内存。"""
    # 用 pyvcd 生成一个 1000 信号 × 100000 时钟周期的 VCD
    # 分别用 vcdvcd-based reader 和 VCDParser-based reader 加载 1 个信号
    # 记录时间和 peak RSS
```

---

## 边界情况处理

### iter_events 的 value 格式与 vcdvcd 的差异

vcdvcd 的 `signal.tv` 存储的 value 是原始 VCD 字符串：`'0'`、`'1'`、`'x'`、`'10110'` 等。

VCDParser 的 `iter_events` 产出的 value 也是同样格式的 4-state 字符串，但有几个细节差异：

1. **大小写**：VCDParser 统一 normalize 为小写 (`x` 不是 `X`，`z` 不是 `Z`)。vcdvcd 保留原始大小写。当前 wavekit 的 `re.sub(r'[xXzZ]', ...)` 已经处理了两种大小写，所以不影响。

2. **bit-explosion 重组**：VCDParser 对 QuestaSim 的 bit-exploded 信号会产出合成的 bus value（多位字符串），vcdvcd 不做这个。对 wavekit 来说这是增强——更宽的信号能被正确加载。

3. **Extended VCD port state**：VCDParser 把 `p<state>` 转成 4-state 字符串（如 `'01xz'`），vcdvcd 直接忽略。对 wavekit 来说这也是增强。

4. **overwide 值钳位**：VCDParser 的 `_clamp_overwide_logic_value` 会把超宽 dump 值退化为全 `x`。vcdvcd 不做检查。对 wavekit 来说，全 x 值经过 `re.sub` 后变成全 0，比 vcdvcd 的未定义行为（可能是截断、可能是异常）更安全。

### scan_time_range 的缓存

`VCDParser.scan_time_range()` 每次调用扫描完整数据段。wavekit 的 `begin_time`/`end_time` 是 `@property`，可能被多次访问。**必须在 `__init__` 中缓存结果**，否则每次访问都重新扫描文件。

### iter_events 的多次调用

`load_waveform` 每次调用都会触发一次 `iter_events` 遍历。如果用户加载 10 个信号，文件被扫描 10 次。这在 vcdvcd 模式下不存在（全量解析一次后全在内存里）。

对于交互式使用这是可接受的（每次扫描只处理所需信号子集，I/O 仍然是顺序的）。如果将来需要优化，可以加一个可选的"预加载"模式：一次 `iter_events(sids=all_needed)` 扫描收集所有信号的 tv 列表，缓存在 reader 中。但这不是第一版需要做的事。

---

## 实施步骤（建议顺序）

```
1. Fork wavekit，创建 wavekit-plus 分支
2. 把 vcd_analyzer.py 的解析器部分提取到 src/wavekit/readers/vcd/vcd_parser.py
3. 重写 src/wavekit/readers/vcd/reader.py（VcdScope + VcdReader）
4. pyproject.toml 删除 vcdvcd 依赖
5. 运行 tests/test_vcdreader.py，逐个修到全部通过
6. 运行 tests/test_readme_examples.py 和 tests/test_examples.py
7. 新增 bit-explosion、Extended VCD、malformed input 测试
8. 更新 README 和 LICENSE 声明
9. 可选：性能 benchmark 对比
```

---

## License 处理

wavekit 原始 license 是 MIT (Copyright Microsoft Corporation)。fork 后：

```
- 保留原始 MIT 声明（法律要求）
- vcd_parser.py 头部标注 VCD_ANALYZER 的 MIT license
- 删除 vcdvcd 依赖后，整个依赖链变成纯 MIT + BSD（numpy）
- 不再有 Artistic 1.0 / GPL v1 的 license 污染
```
