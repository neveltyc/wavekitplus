# wavekitplus 功能增强开发文档

## 概述

在 v0.7.0（替换 vcdvcd 后端）基础上，分两个阶段增强 wavekitplus 的能力。所有改动必须保持与 wavekit-mcp 的兼容性——wavekit-mcp 通过 `import wavekit` 使用本库，不能破坏任何现有的公开接口。

## 兼容性约束（贯穿所有阶段）

wavekit-mcp 的依赖面：

```python
# session.py — 注入到沙箱的类名（不能改名、不能删除）
wavekit.VcdReader
wavekit.FstReader
wavekit.FsdbReader
wavekit.Pattern
wavekit.Channel
wavekit.Waveform
wavekit.MatchResult
wavekit.MatchStatus

# serializer.py — 直接访问的 Waveform 属性（不能改类型或删除）
wave.value           # ndarray
wave.signal.full_name
wave.signal.name
wave.width           # int | None
wave.signed          # bool
wave.clock           # ndarray
wave.time            # ndarray

# base.py — 抽象方法签名
Reader.load_waveform(signal, clock, xz_value=0, signed=False, ...)
Reader.load_matched_waveforms(pattern, clock_pattern, ...)
Reader.top_scope_list()
Reader.close()
Reader.eval(expr, clock, ...)
```

**规则：所有新功能必须是可选参数或新类型。现有代码不传新参数时，行为必须与 v0.7.x 完全一致。**

---

# Phase 1：信号缓存层（v0.7.2）

## 问题

当前每次 `load_waveform` 都触发一次 `iter_events` 全文件扫描。加载 N 个信号扫 N 遍文件。`load_matched_waveforms` 加载 20 个信号就扫 20 遍——因为 `base.py` 的默认实现是循环调用 `load_waveform`。

## 目标

同一个 VcdReader 实例内，每个信号的 value-change 列表只从文件读取一次。多信号加载时合并为单次扫描。

## 改动范围

只改一个文件：`src/wavekit/readers/vcd/reader.py`

不改的文件：vcd_parser.py、base.py、waveform.py、pattern/\*、\_\_init\_\_.py

## 实现设计

### 1. 缓存结构

在 VcdReader 上添加：

```python
class VcdReader(Reader):
    def __init__(self, file: str):
        super().__init__()
        self.file = file
        self._parser = VCDParser(file)
        self._time_range = self._parser.scan_time_range()
        # 新增：信号 value-change 缓存
        self._tv_cache: dict[str, list[tuple[int, str]]] = {}
        # ... 以下不变 ...
```

`_tv_cache` 的 key 是 VCDParser 的 sig_id（identifier_code），value 是 `[(tick, value_str), ...]` 列表。

### 2. 缓存填充方法

```python
def _ensure_cached(self, sids: set[str]) -> None:
    """确保 sids 中所有信号的 tv list 都在缓存中。
    
    对缺失的信号做一次 iter_events 批量扫描。
    已缓存的信号不会重复扫描。
    """
    missing = sids - self._tv_cache.keys()
    if not missing:
        return
    for t, sid, val in self._parser.iter_events(sids=missing):
        self._tv_cache.setdefault(sid, []).append((t, val))
    # 确保没有事件的信号也有空列表，避免重复扫描
    for sid in missing:
        self._tv_cache.setdefault(sid, [])
```

### 3. 改造 load_waveform

当前 load_waveform 的数据收集部分是：

```python
# 当前实现
signal_tv: list[tuple[int, str]] = []
clock_tv: list[tuple[int, str]] = []
needed_sids = {signal_sid, clock_sid}
for t, sid, val in self._parser.iter_events(sids=needed_sids):
    if sid == clock_sid:
        clock_tv.append((t, val))
    elif sid == signal_sid:
        signal_tv.append((t, val))
```

改为：

```python
# 新实现
self._ensure_cached({signal_sid, clock_sid})
signal_tv = self._tv_cache[signal_sid]
clock_tv = self._tv_cache[clock_sid]
```

其余代码（numpy 转换、时钟重采样、range slice）完全不变。

### 4. 覆盖 load_matched_waveforms（可选优化）

base.py 的默认 `load_matched_waveforms` 是循环调用 `load_waveform`。有了缓存之后这已经不会重复扫描了——第一次 `load_waveform` 缓存了 clock，后续 19 次直接命中。

但如果想进一步优化（一次扫描收集所有信号），可以在 VcdReader 里覆盖：

```python
def load_matched_waveforms(self, pattern, clock_pattern, **kwargs):
    # 先解析所有 pattern 得到 sid 集合
    matched_signals = self.get_matched_signals(pattern, ...)
    matched_clocks = self.get_matched_signals(clock_pattern, ...)
    all_sids = {self._resolve_signal_path(sig.full_name) 
                for sig in matched_signals.values()}
    all_sids |= {self._resolve_signal_path(clk.full_name) 
                 for clk in matched_clocks.values()}
    # 一次性预缓存
    self._ensure_cached(all_sids)
    # 然后走默认的循环调用（每次都命中缓存）
    return super().load_matched_waveforms(pattern, clock_pattern, **kwargs)
```

这个覆盖是可选的——不做也不影响正确性，只影响性能。第一版可以不做，看测试通过后再加。

### 5. 缓存失效

不做缓存失效。VcdReader 是只读的，VCD 文件在 reader 生命周期内不会变。缓存和 reader 同生共死。

如果用户需要重新读取（文件被覆盖了），关掉 reader 重新开一个。

### 测试

在 `tests/run_tests.py` 中新增：

```python
def _test_cache_consistency():
    """多次加载同一信号结果一致（验证缓存不引入差异）"""
    r = VcdReader(str(JTAG))
    w1 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w2 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    assert np.array_equal(w1.value, w2.value)
    assert np.array_equal(w1.time, w2.time)

def _test_cache_shared_clock():
    """加载多个信号共享时钟时，文件只扫描一次（通过缓存）"""
    r = VcdReader(str(JTAG))
    w1 = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w2 = r.load_waveform('tb.u0.J_next[3:0]', clock='tb.tck')
    # 两个信号的 clock 数组应该一致（来自同一份缓存的 tck 数据）
    assert np.array_equal(w1.clock, w2.clock)

def _test_cache_empty_signal():
    """没有 value change 的信号不会导致重复扫描"""
    # 构造一个只有 header 没有数据变化的信号的 VCD
    # 第一次 _ensure_cached 后 _tv_cache[sid] = []
    # 第二次 _ensure_cached 不应该再次扫描
```

同时确保 pytest 原有 31 个测试全部通过。

---

# Phase 2：4-state mask 层（v0.8.0）

## 问题

当前 `load_waveform` 用 `re.sub(r'[xXzZ]', str(xz_value), v)` 把 x/z 替换成整数。替换后无法区分 "信号被驱动为 0" 和 "信号是 x 但被替换成了 0"。

## 目标

`load_waveform` 新增可选参数 `xz_mask=False`。当 `xz_mask=True` 时，返回的 Waveform 携带一个 `xz_mask` 属性（ndarray[bool]），标记哪些采样点的原始值含有 x 或 z。

## 改动范围

两个文件：

1. `src/wavekit/waveform.py` — Waveform 类增加 xz_mask 属性和传播逻辑
2. `src/wavekit/readers/vcd/reader.py` — load_waveform 增加 xz_mask 参数

不改的文件：base.py（抽象方法签名加 xz_mask=False 默认参数）、pattern/\*、serializer（兼容）

## 实现设计

### 1. Waveform 类修改

```python
class Waveform:
    def __init__(
        self,
        value: npt.NDArray[Any],
        clock: npt.NDArray[np.number],
        time: npt.NDArray[np.number],
        signal: Signal | None = None,
        xz_mask: npt.NDArray[np.bool_] | None = None,  # 新增
    ):
        self.clock = clock
        self.time = time
        self.signal = signal if signal is not None else Signal('', '', None, None)
        self.xz_mask = xz_mask  # None = 没有 x/z 信息（向后兼容）

        # ... 现有的 value dtype 处理不变 ...
```

### 2. xz_mask 在运算中的传播规则

核心原则：**任一操作数含 x/z → 结果含 x/z**

在算术运算（`__add__`, `__sub__`, `__mul__` 等）中：

```python
def __add__(self, other):
    # ... 现有的 value 计算逻辑不变 ...
    result = Waveform(value=result_value, clock=self.clock, time=self.time, ...)
    # 新增：传播 xz_mask
    result.xz_mask = _merge_xz_masks(self, other)
    return result
```

辅助函数：

```python
def _merge_xz_masks(a: Waveform, b) -> np.ndarray | None:
    """合并两个操作数的 xz_mask。"""
    a_mask = a.xz_mask
    b_mask = b.xz_mask if isinstance(b, Waveform) else None
    if a_mask is None and b_mask is None:
        return None
    if a_mask is None:
        return b_mask.copy()
    if b_mask is None:
        return a_mask.copy()
    return a_mask | b_mask  # 任一为 True 则结果为 True
```

### 3. xz_mask 在过滤 / 切片中的传播

`mask()`, `filter()`, `time_slice()`, `cycle_slice()`, `__getitem__()` 等方法在截取 value 数组的同时，必须同步截取 xz_mask：

```python
def mask(self, mask_cond):
    # ... 现有逻辑 ...
    result = Waveform(value=filtered_value, clock=filtered_clock, ...)
    if self.xz_mask is not None:
        result.xz_mask = self.xz_mask[mask_indices]
    return result
```

`__getitem__`（bit slice `waveform[7:4]`）中，xz_mask 直接透传（bit slice 不改变哪些周期含 x/z，只改变值）。

### 4. VcdReader.load_waveform 修改

在 base.py 的抽象签名中加默认参数：

```python
# base.py
@abstractmethod
def load_waveform(
    self, signal, clock, xz_value=0, signed=False,
    sample_on_posedge=False,
    begin_time=None, end_time=None,
    begin_cycle=None, end_cycle=None,
    xz_mask: bool = False,  # 新增
) -> Waveform:
```

在 VcdReader 中：

```python
def load_waveform(self, signal, clock, xz_value=0, signed=False,
                  sample_on_posedge=False,
                  begin_time=None, end_time=None,
                  begin_cycle=None, end_cycle=None,
                  xz_mask: bool = False) -> Waveform:
    # ... 解析参数、缓存查找（Phase 1）...

    # 从缓存获取 tv list
    self._ensure_cached({signal_sid, clock_sid})
    signal_tv = self._tv_cache[signal_sid]
    clock_tv = self._tv_cache[clock_sid]

    # 构建 numpy 数组时，同时记录 x/z 位置
    if xz_mask:
        xz_flags = np.array(
            [bool(re.search(r'[xXzZ]', v[1])) for v in signal_tv],
            dtype=np.bool_,
        )
    
    # value 转换（与当前逻辑相同，x/z 仍然替换为 xz_value）
    signal_value_change = np.array(
        [(v[0], int(re.sub(r'[xXzZ]', str(xz_value), v[1]), 2)) for v in signal_tv],
        dtype=np.object_ if width > 64 else np.uint64,
    )
    
    # ... 时钟重采样（不变）...

    full_wave = self.value_change_to_waveform(
        signal_value_change, clock_value_change,
        width=width, signed=signed, ...)

    # 将 xz_flags 重采样到时钟域
    if xz_mask:
        # xz_flags 是 value-change 级别的，需要重采样到 clock cycle 级别
        # 复用 value_change_to_waveform 的逻辑：构造一个 (time, flag) 数组
        xz_vc = np.zeros((len(signal_tv), 2), dtype=np.uint64)
        xz_vc[:, 0] = np.array([v[0] for v in signal_tv], dtype=np.uint64)
        xz_vc[:, 1] = xz_flags.astype(np.uint64)
        xz_wave = self.value_change_to_waveform(
            xz_vc, clock_value_change,
            width=1, signed=False,
            sample_on_posedge=sample_on_posedge,
            signal='_xz_mask', clock_offset=clock_offset,
        )
        full_wave.xz_mask = xz_wave.value.astype(np.bool_)

    result = full_wave.time_slice(begin_time, end_time)
    # ... range slice（不变）...
    return result
```

### 5. 便捷方法

在 Waveform 上加两个常用方法：

```python
@property
def has_xz(self) -> bool:
    """这个波形是否携带了 4-state 信息。"""
    return self.xz_mask is not None

@property
def xz_cycles(self) -> np.ndarray:
    """返回所有含 x/z 的时钟周期编号。"""
    if self.xz_mask is None:
        return np.array([], dtype=np.uint64)
    return self.clock[self.xz_mask]

def drop_xz(self) -> 'Waveform':
    """返回去掉所有 x/z 周期的新 Waveform（等价于 self.mask(~self.xz_mask)）。"""
    if self.xz_mask is None or not np.any(self.xz_mask):
        return self.copy()
    return self.mask(~self.xz_mask)
```

### 6. wavekit-mcp 兼容性

serializer.py 访问 `wave.value`, `wave.width`, `wave.signed`, `wave.clock`, `wave.time`。`xz_mask` 是新属性，serializer 不访问它——所以不需要改 wavekit-mcp。

如果 Agent 在沙箱里写 `print(wave.xz_mask)`，serializer 的 ndarray 分支会自动序列化它。

### 测试

```python
def _test_xz_mask_basic():
    """xz_mask=True 时，含 x/z 的采样点被正确标记"""
    # 用 basic_trace.vcd 中 state 信号（初始值可能含 x）
    r = VcdReader(str(fixture_with_x))
    w = r.load_waveform('tb.state[2:0]', clock='tb.clk', xz_mask=True)
    assert w.xz_mask is not None
    assert w.xz_mask.dtype == np.bool_

def _test_xz_mask_default_off():
    """xz_mask 默认关闭，不影响现有行为"""
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    assert w.xz_mask is None  # 默认不携带

def _test_xz_mask_propagation():
    """算术运算正确传播 xz_mask"""
    r = VcdReader(str(fixture_with_x))
    a = r.load_waveform('tb.sig_a', clock='tb.clk', xz_mask=True)
    b = r.load_waveform('tb.sig_b', clock='tb.clk', xz_mask=True)
    c = a + b
    # 如果 a 或 b 任一含 x/z，c 的对应位置也应标记
    if a.xz_mask is not None and b.xz_mask is not None:
        expected = a.xz_mask | b.xz_mask
        assert np.array_equal(c.xz_mask, expected)

def _test_xz_mask_drop():
    """drop_xz 正确过滤含 x/z 的周期"""
    r = VcdReader(str(fixture_with_x))
    w = r.load_waveform('tb.state[2:0]', clock='tb.clk', xz_mask=True)
    clean = w.drop_xz()
    assert clean.xz_mask is None or not np.any(clean.xz_mask)
    assert len(clean.value) <= len(w.value)

def _test_xz_mask_no_xz():
    """纯 0/1 信号的 xz_mask 应全为 False"""
    r = VcdReader(str(JTAG))
    w = r.load_waveform('tb.tck', clock='tb.tck', xz_mask=True)
    assert w.xz_mask is not None
    assert not np.any(w.xz_mask)

def _test_backward_compat_with_xz_mask():
    """xz_mask=True 不影响 value 的数值（仍然按 xz_value 替换）"""
    r = VcdReader(str(JTAG))
    w_old = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck')
    w_new = r.load_waveform('tb.u0.J_state[3:0]', clock='tb.tck', xz_mask=True)
    assert np.array_equal(w_old.value, w_new.value)
    assert np.array_equal(w_old.clock, w_new.clock)
```

### 需要一个含 x/z 的测试 fixture

从 VCD_ANALYZER 的 `basic_trace.vcd` 或自建一个：

```vcd
$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 3 " state $end
$upscope $end
$enddefinitions $end
#0
0!
bxxx "
#5
1!
#10
0!
b001 "
#15
1!
#20
0!
b010 "
#25
1!
#30
0!
bx10 "
#35
1!
```

这个 fixture 中 state 在 tick 0 是 `xxx`，tick 10 变成 `001`，tick 30 变成 `x10`。xz_mask 在时钟重采样后应该在对应周期标记 True。

---

# Phase 3：EventTrace 异步事件层（v1.0，后续规划）

## 简述

在 Reader 上加 `load_event_trace(signal)` 方法，返回 `EventTrace` 对象。EventTrace 不做时钟重采样，保留原始 VCD 时间戳，用于中断、复位、跨时钟域信号的精确时间分析。

## 关键接口（预留设计）

```python
class EventTrace:
    times: np.ndarray       # VCD tick 时间戳
    values: np.ndarray      # 每次跳变的信号值
    width: int
    signal: Signal

    def posedge(self) -> np.ndarray:
        """返回所有上升沿的时间戳"""

    def negedge(self) -> np.ndarray:
        """返回所有下降沿的时间戳"""

    def at_time(self, t: int) -> int:
        """返回时刻 t 的信号值（二分查找）"""

    def to_waveform(self, clock: str, reader: Reader) -> Waveform:
        """按指定时钟重采样，转成 Waveform（桥接方法）"""
```

Phase 3 的详细设计等 Phase 1 和 Phase 2 稳定后再展开。

---

# 实施顺序

```
v0.7.2  Phase 1（信号缓存）
        1. VcdReader 加 _tv_cache 和 _ensure_cached
        2. load_waveform 改为从缓存读取
        3. 新增缓存相关测试
        4. 跑通全部 pytest + run_tests.py
        5. CHANGELOG 更新

v0.8.0  Phase 2（4-state mask）
        1. Waveform.__init__ 加 xz_mask 参数
        2. Waveform 算术/过滤/切片方法加 mask 传播
        3. 加 has_xz / xz_cycles / drop_xz 便捷方法
        4. base.py load_waveform 签名加 xz_mask=False
        5. VcdReader.load_waveform 实现 xz_mask 生成
        6. 创建含 x/z 的测试 fixture
        7. 新增 xz_mask 相关测试
        8. 跑通全部 pytest + run_tests.py（包括所有旧测试）
        9. CHANGELOG 更新
```

每个版本发布前的检查清单：

```
□ pytest tests/test_vcdreader.py        全部通过（31 个）
□ pytest tests/test_waveform.py         全部通过
□ pytest tests/test_readme_examples.py  全部通过
□ pytest tests/test_pattern.py          全部通过
□ python tests/run_tests.py             全部通过
□ wavekit-mcp 的 import wavekit 能正常工作
□ CHANGELOG 更新
```
