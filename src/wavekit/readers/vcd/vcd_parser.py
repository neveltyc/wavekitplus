# VCD parser extracted from VCD_ANALYZER v1.3.9
# Original: https://github.com/neveltyc/VCD_ANALYZER
# License: MIT (c) 2026 neveltyc
#
# Modifications for wavekit integration:
# - Extracted VCDParser class and dependencies only
# - Removed CLI commands, formatters, condition engine

import os
import re
from collections import defaultdict

_UNITS = {'fs': 1e-15, 'ps': 1e-12, 'ns': 1e-9, 'us': 1e-6, 'ms': 1e-3, 's': 1.0}


# Resource limits -- generous defaults that never trip on real engineering
# files but reject pathological/malicious inputs cleanly.
# Override per-process via environment variables, e.g.:
#   VCD_ANALYZER_MAX_VARS=2000000 vcd_analyzer info big.vcd


def _env_int(name, default):
    """Read a positive integer resource limit from the environment."""
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


MAX_VARS = _env_int('VCD_ANALYZER_MAX_VARS', 1_000_000)
MAX_REASSEMBLE_BITS = _env_int('VCD_ANALYZER_MAX_REASSEMBLE_BITS', 65536)
MAX_TIME_ARG_LEN = 100  # CLI/programmatic time string length cap
MAX_TIME_TICKS = (1 << 63) - 1  # int64 max -- keeps downstream arithmetic safe
MAX_FILTER_PATTERN_LEN = 256
MAX_FILTER_WILDCARDS = 16

# Additional header-section caps. Defaults are far above any legitimate
# engineering VCD but cleanly refuse pathological/malicious construction.
#
# Two failure modes are used:
#  - fail-fast (raise _VCDResourceError): for caps whose violation would
#    corrupt data correctness (lost value_changes, lost $var declarations,
#    deep scope that breaks path reconstruction).
#  - silent drop (truncate retained list): for metadata-only caps whose
#    violation only affects the cosmetic output of `info --verbose`. These
#    are noted inline where they apply.
MAX_INT_DIGITS = 100  # any int-from-string in header (width, bit idx, msb/lsb)
MAX_SIGNAL_WIDTH = MAX_REASSEMBLE_BITS  # max bits per single $var declaration
MAX_VALUE_ARG_LEN = MAX_SIGNAL_WIDTH + 2  # target value string, allows b<MAX_SIGNAL_WIDTH bits>
MAX_DECIMAL_VALUE_DIGITS = 100  # avoid Python 3.9 int() CPU DoS on --value decimal
MAX_HEX_VALUE_DIGITS = max(1, (MAX_SIGNAL_WIDTH + 3) // 4)
MAX_HEADER_BODY_TOKENS = 131072  # any $<kw>...$end section body length (metadata-only effect:
# truncates $comment / $date / $version bodies; $var bodies
# are never long enough to be affected in practice)
MAX_COMMENTS = 1024  # number of $comment sections retained (metadata-only)
MAX_SCOPE_DEPTH = 256  # $scope nesting depth (fail-fast: lost scope breaks path)
MAX_INITIAL_TOKENS = 131072  # tokens buffered from same line as $enddefinitions $end
# (fail-fast: these are data tokens, dropping them
# would silently corrupt waveforms)


# IEEE 1364-2005 18.2.2 real value_change is 'r' + real_number where
# real_number follows C99 printf("%g") shape: optional sign, integer and/or
# fractional digits, optional exponent. Used to reject garbage tokens like
# 'reset' that start with 'r' but aren't a numeric value_change.
#
# Pattern written to avoid backtracking (no alternation overlap):
#   sign?  ( digits  ( '.' digits? )?  |  '.' digits )  exponent?
# The two top-level alternatives are disjoint (start with digit vs '.'),
# so the engine never has to backtrack between them. Inputs are also
# length-bounded below; real_number tokens in VCD value_changes shouldn't
# exceed reasonable %g output width.

_REAL_RE = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
_REAL_MAX_LEN = 64  # Defensive cap: %.16g + sign + exponent fits well under this

# Extended VCD port state character → 4-state mapping (IEEE 1364-2005 18.4.3.1).
# Strengths (driver levels 0-7) are not exposed; for RTL debug the 4-state value
# is what matters. Conflict states (d/u/l/h) collapse to their logical level.
_PORT_STATE = {
    # Input (testfixture)
    'D': '0',
    'U': '1',
    'N': 'x',
    'Z': 'z',
    'd': '0',
    'u': '1',
    # Output (DUT)
    'L': '0',
    'H': '1',
    'X': 'x',
    'T': 'z',
    'l': '0',
    'h': '1',
    # Unknown direction (both input and output active)
    '0': '0',
    '1': '1',
    '?': 'x',
    'F': 'z',
    'A': 'x',
    'a': 'x',
    'B': 'x',
    'b': 'x',
    'C': 'x',
    'c': 'x',
    'f': 'z',
}


def _parse_timescale(text):
    """Extract base time unit in seconds from $timescale line.

    IEEE 1364-2005 18.2.3.8 only allows 1, 10, or 100 as the number, but
    we accept any positive integer for lenience. A zero, missing, or
    pathologically long number falls back to 1e-12 (1 ps) -- the standard's
    default -- to avoid downstream division-by-zero in time parsing and CPU
    DoS from int() on huge digit strings (Python 3.9 is O(n^2)).
    """
    m = re.search(r'(\d+)\s*(fs|ps|ns|us|ms|s)', text)
    if not m:
        return 1e-12
    digits = m.group(1)
    # Length cap matches MAX_TIME_ARG_LEN. The standard allows
    # only 1/10/100 (<=3 digits), so anything multi-line absurd is corruption.
    if len(digits) > MAX_TIME_ARG_LEN:
        return 1e-12
    n = int(digits)
    if n <= 0:
        return 1e-12
    return n * _UNITS[m.group(2)]


class _VCDResourceError(RuntimeError):
    """Raised when a VCD input exceeds configured resource limits.
    Surfaced in main() as a CLI error, no Python traceback."""


def _parse_vcd_timestamp_token(tok):
    """Parse a VCD '#<digits>' simulation_time token into an int.

    Returns int on success, None for malformed input (e.g. '#1.5' -- digit
    prefix passed the isdigit() pre-check but int() rejects it). The
    None-path preserves the round-7 "tolerant reader" behavior: malformed
    timestamps are silently skipped, the rest of the stream continues.

    Raises _VCDResourceError for inputs that would cause CPU/memory DoS or
    exceed int64. Python 3.11+ has PEP 678 (int_max_str_digits) baked in,
    but we target 3.9 where int(s) is O(n^2) for huge n; even on 3.11+
    the PEP 678 ValueError would otherwise become an unhandled traceback.
    """
    digits = tok[1:]
    if len(digits) > MAX_TIME_ARG_LEN:
        raise _VCDResourceError(
            f'VCD timestamp token too long: {len(digits)} digits (max {MAX_TIME_ARG_LEN}); '
            'file may be corrupt or malicious'
        )
    try:
        v = int(digits)
    except ValueError:
        return None  # tolerated malformed (e.g. '#1.5')
    if v > MAX_TIME_TICKS:
        raise _VCDResourceError(f'VCD timestamp too large: got {v}, max ticks is {MAX_TIME_TICKS}')
    return v


def _safe_int_digits(s):
    """Parse a digit string from VCD header to int with bounded cost.

    Used wherever the header declares an integer in user-controlled
    position: $var width, [msb:lsb] range, [N] bit index. Returns int
    on success, None for empty / malformed / oversized inputs. Never
    raises -- caller decides whether to skip the declaration or raise
    _VCDResourceError with richer context.

    Length cap MAX_INT_DIGITS=100 defends against the same Python 3.9
    O(n^2) decimal-int and Python 3.11+ PEP 678 ValueError issues as
    _parse_vcd_timestamp_token. 100 digits is far beyond any legitimate
    bit width or index (which fit in 4 digits comfortably).
    """
    if not s or len(s) > MAX_INT_DIGITS:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _clamp_overwide_logic_value(value, info):
    """Preserve clean 4-state state while rejecting malformed over-wide dumps.

    Legal VCD writers may omit redundant MSB bits; value formatting and condition
    matching already left-extend short values. A value longer than the
    declared width is malformed. Do not truncate it to the LSBs: that would
    turn corrupt input into a plausible-looking numeric value. Instead,
    degrade to all-x at the declared width so downstream dump/snapshot/search
    sees an explicit unknown.
    """
    vtype = info.get('type', 'wire')
    if vtype in ('real', 'realtime', 'event'):
        return value
    width = info.get('width')
    if width is None:
        return value
    if _is_4state_bits(value) and len(value) > width:
        return 'x' * width
    return value


_DECL_KEYWORDS = {
    '$timescale',
    '$scope',
    '$upscope',
    '$var',
    '$comment',
    '$date',
    '$version',
    '$enddefinitions',
}

# Simulation keywords that wrap value_changes until $end. The keyword and $end
# are pure markers -- the wrapped value_changes are parsed normally.
# Four-state VCD (18.2.3.9-12) + extended VCD (18.4.1 BNF).
_SIM_KEYWORDS = {
    '$dumpall',
    '$dumpoff',
    '$dumpon',
    '$dumpvars',
    '$dumpports',
    '$dumpportsoff',
    '$dumpportson',
    '$dumpportsall',
}

# Sections that can appear in the data area whose body is NOT value_changes
# and must be skipped wholesale until $end. $comment (18.2.3.1) is in both
# header and data; $vcdclose (18.3.6.1) wraps a final simulation time token.
_DATA_SKIP_SECTIONS = {'$comment', '$vcdclose'}


class VCDParser:
    """Streaming VCD parser. Token-based: handles single-line and multi-line
    sections, inline simulation keyword blocks, and multi-line port values
    per IEEE 1364-2005 Section 18.

    Auto-reassembles bit-exploded signals (QuestaSim writes 512-bit signals
    as 512 individual 1-bit $var entries with [N] suffix).

    Extended VCD ($dumpports) support level: port_state characters are
    lowered to 4-state values (0/1/x/z) for RTL debug. The strength0 and
    strength1 components are parsed but discarded -- preserving them would
    rarely benefit RTL-level analysis and clutters the value display.
    """

    def __init__(self, path):
        self.path = path
        self.ts_str = ''
        self.ts_sec = 1e-12  # timescale in seconds
        self.signals = {}  # sig_id -> {path, width, type, aliases}
        self._data_offset = 0
        # Header metadata per IEEE 1364-2005 18.2.3:
        #   $date    - simulation date string (18.2.3.2)
        #   $version - simulator vendor/version (18.2.3.3)
        #   $comment - free-form, may appear multiple times (18.2.3.1)
        # Captured verbatim for provenance display; an agent inspecting an
        # unknown VCD benefits from knowing which simulator produced it
        # (QuestaSim 2023.1 vs Icarus Verilog vs VCS) and when, since
        # downstream debug heuristics may depend on simulator quirks.
        self.date = ''
        self.version = ''
        self.comments = []
        # If $enddefinitions $end is followed by data tokens on the same
        # line(s) buffered by readline, those tokens replay first in data.
        self._initial_tokens = []
        self._bit_map = {}  # sym -> (sig_id, bit_index)
        self._bit_state_template = {}  # sig_id -> initial bit list for replay-local reassembly
        self._parse_header()

    def _parse_header(self):
        """Token-based header parse. Sections may span multiple lines;
        $end is the only terminator (IEEE 1364-2005 18.2.1)."""
        scope = []
        raw_vars = []  # (sym, name, width, bit_idx_str, scope_path, vtype)
        current_kw = None
        body = []
        done = False

        with open(self.path, encoding='utf-8', errors='replace') as f:
            while not done:
                line = f.readline()
                if not line:
                    break
                for tok in line.split():
                    if done:
                        # Buffer tokens that share the same line as
                        # `$enddefinitions $end`. These are data tokens
                        # (value_changes, timestamps), so they MUST NOT
                        # be silently dropped -- that would corrupt the
                        # waveform without the user noticing. Fail-fast.
                        # Normal VCDs have at most a handful of tokens
                        # on this line; 131072 is comfortably above any
                        # legitimate use.
                        if len(self._initial_tokens) >= MAX_INITIAL_TOKENS:
                            raise _VCDResourceError(
                                'too many data tokens on the same line as '
                                f'$enddefinitions $end (>{MAX_INITIAL_TOKENS}); file may be '
                                'corrupt or malicious'
                            )
                        self._initial_tokens.append(tok)
                        continue
                    if current_kw is None:
                        if tok in _DECL_KEYWORDS:
                            current_kw = tok
                            body = []
                        # else: stray token, ignore
                    elif tok == '$end':
                        # Section complete
                        if current_kw == '$timescale':
                            ts_body = ' '.join(body)
                            self.ts_str = '$timescale ' + ts_body + ' $end'
                            self.ts_sec = _parse_timescale(ts_body)
                        elif current_kw == '$scope' and len(body) >= 2:
                            # Cap nesting depth to defend against
                            # 1M-level $scope-without-$upscope construction.
                            if len(scope) >= MAX_SCOPE_DEPTH:
                                raise _VCDResourceError(
                                    f'$scope nesting depth exceeds {MAX_SCOPE_DEPTH}; '
                                    'file may be corrupt or malicious'
                                )
                            scope.append(body[1])
                        elif current_kw == '$upscope':
                            if scope:
                                scope.pop()
                        elif current_kw == '$var' and len(body) >= 4:
                            vtype = body[0]

                            def _collect_bracket(tokens, i):
                                if i >= len(tokens) or not tokens[i].startswith('['):
                                    return None, i
                                parts = []
                                while i < len(tokens):
                                    parts.append(tokens[i])
                                    if ']' in tokens[i]:
                                        return ''.join(parts), i + 1
                                    i += 1
                                return None, i

                            size_expr, idx_after_size = _collect_bracket(body, 1)
                            if size_expr is not None:
                                m = re.match(r'\[(\d+):(\d+)\]$', size_expr)
                                if not m:
                                    current_kw = None
                                    continue
                                msb = _safe_int_digits(m.group(1))
                                lsb = _safe_int_digits(m.group(2))
                                if msb is None or lsb is None:
                                    # Overlong or malformed digits -- skip
                                    # this $var rather than abort, since
                                    # the rest of the header may still be
                                    # useful.
                                    current_kw = None
                                    continue
                                w = abs(msb - lsb) + 1
                                idx = idx_after_size
                            else:
                                w = _safe_int_digits(body[1])
                                if w is None:
                                    current_kw = None
                                    continue
                                idx = 2
                            # Hazard 1 mitigation: refuse pathological widths
                            # before they reach value formatting (which would try to
                            # allocate `pad * (width - len(value))` bytes).
                            # Real signals never approach MAX_SIGNAL_WIDTH.
                            if w <= 0 or w > MAX_SIGNAL_WIDTH:
                                raise _VCDResourceError(
                                    f'$var width {w} exceeds max {MAX_SIGNAL_WIDTH}; '
                                    'file may be corrupt or malicious'
                                )
                            if len(body) <= idx + 1:
                                current_kw = None
                                continue
                            sym, name = body[idx], body[idx + 1]

                            # Per IEEE 1364 free-format, the bracket reference
                            # range can be split into several tokens, e.g.
                            # 'data [7 : 0]' → ['data', '[7', ':', '0]'].
                            bit_str, _idx_after_ref = _collect_bracket(body, idx + 2)
                            # Per IEEE 1364-2005 18.2.3.7 reference syntax:
                            #   identifier [bit_select_index]      → single bit
                            #   identifier [msb_index : lsb_index] → range
                            # For multi-bit refs with a range, fold it into
                            # the name so the displayed path is 'data[7:0]'.
                            # For w==1 with [N], keep bit_str separate for
                            # the bit-explosion heuristic below.
                            if bit_str is not None and w > 1:
                                name = name + bit_str
                                bit_str = None
                            # Resource cap: refuse to allocate unbounded memory
                            # for malicious VCDs declaring millions of $var.
                            # Default 500k is ~25x larger than typical QuestaSim
                            # files; tune via VCD_ANALYZER_MAX_VARS env var.
                            if len(raw_vars) >= MAX_VARS:
                                raise _VCDResourceError(
                                    f'too many $var declarations: more than {MAX_VARS}. '
                                    'Set VCD_ANALYZER_MAX_VARS to raise the limit.'
                                )
                            raw_vars.append((sym, name, w, bit_str, '.'.join(scope), vtype))
                        elif current_kw == '$enddefinitions':
                            done = True
                        elif current_kw == '$date':
                            # Tokens collapsed to single-spaced string;
                            # original used \t / multi-line for readability.
                            self.date = ' '.join(body)
                        elif current_kw == '$version':
                            self.version = ' '.join(body)
                        elif current_kw == '$comment':
                            # Per 18.2.3.1, $comment may appear multiple
                            # times. Silent drop after the cap is safe:
                            # comments are metadata, not data -- losing
                            # the 1025th comment only affects what
                            # `info --verbose` prints, never the waveform.
                            if len(self.comments) < MAX_COMMENTS:
                                self.comments.append(' '.join(body))
                        current_kw = None
                    else:
                        # Bound section body. In practice this only
                        # truncates oversized $comment / $date / $version
                        # bodies -- metadata. $var bodies are 4-8 tokens,
                        # $scope is 2, $timescale is 2; none come close
                        # to the cap. Silent drop is safe because:
                        #   - the $end token still closes the section
                        #     correctly (we still see it in the outer
                        #     loop, we just stop appending to body)
                        #   - dropped tokens never become part of any
                        #     value_change interpretation
                        if len(body) < MAX_HEADER_BODY_TOKENS:
                            body.append(tok)
            self._data_offset = f.tell()

        # Phase 2: detect and reassemble bit-exploded signals.
        # Bit-exploded heuristic per QuestaSim convention: each bit is a
        # 1-bit $var with [N] suffix. We auto-reassemble ONLY when the bit
        # indices form a complete 0..max_bit contiguous set. Standard-legal
        # partial dumps (e.g. only $var ... bus[4] ... emitted) must NOT be
        # synthesized as a bus[4:0] with phantom lower bits -- they are kept
        # as individual bit-select references.
        bit_groups = defaultdict(dict)  # (scope, base_name) -> {bit_idx: sym}
        bit_types = {}  # (scope, base_name) -> vtype
        duplicate_bit_groups = set()  # groups with duplicate bit indices; never reassemble
        standalone = []
        bit_select_singletons = []  # (sym, name, idx, sc, vtype)

        for sym, name, w, bit_str, sc, vtype in raw_vars:
            if w == 1 and bit_str is not None:
                m = re.match(r'\[(\d+)\]', bit_str)
                if m:
                    idx = _safe_int_digits(m.group(1))
                    if idx is None:
                        # Overlong/malformed bit index -- treat the $var as
                        # a standalone signal (its bit_str folded back).
                        standalone.append((sym, name + bit_str, 1, sc, vtype))
                        continue
                    group_key = (sc, name)
                    group = bit_groups[group_key]
                    if idx in group:
                        # Illegal VCD: duplicate bit-select declaration for the
                        # same reconstructed bus bit.  Do not silently let the
                        # later symbol overwrite the earlier one; mark the group
                        # non-reassemblable so all raw bit-select declarations
                        # remain visible as standalone signals.
                        duplicate_bit_groups.add(group_key)
                    else:
                        group[idx] = sym
                    # Resource cap: refuse to allocate gigantic synthesized
                    # buses (per-call template copy cost scales linearly).
                    # Default 65536 is 128x typical QuestaSim bit-bus size;
                    # tune via VCD_ANALYZER_MAX_REASSEMBLE_BITS env var.
                    if len(group) > MAX_REASSEMBLE_BITS:
                        raise _VCDResourceError(
                            'bit-exploded group {}.{} has more than {} bits. '
                            'Set VCD_ANALYZER_MAX_REASSEMBLE_BITS to raise the limit.'.format(
                                sc or '<root>', name, MAX_REASSEMBLE_BITS
                            )
                        )
                    bit_types[(sc, name)] = vtype
                    bit_select_singletons.append((sym, name, idx, sc, vtype))
                    continue
                # A 1-bit reference written as a range (for example
                # data[0:0]) is not a bit-exploded bus bit. Preserve the
                # reference suffix in the displayed path instead of silently
                # dropping it. Some simulators emit this non-canonical form.
                standalone.append((sym, name + bit_str, 1, sc, vtype))
                continue
            standalone.append((sym, name, w, sc, vtype))

        # Partition bit_groups: contiguous-from-0 with >=2 bits → reassemble;
        # everything else → individual bit-select references. A single
        # '[0]' declaration alone is NOT a bus -- it's a partial dump that
        # happens to use bit 0; synthesizing it as 'data[0:0]' would lie
        # about the file structure.
        #
        # DoS guard: do NOT compute set(range(max+1)) -- a malicious VCD with
        # 'bus[0]' + 'bus[1000000000]' would force materialization of a
        # billion-element set (gigabytes of RAM). Indices [0..max] form a
        # contiguous run iff: count == max+1 AND 0 is present. Both checks
        # are O(1) on dict_keys.
        non_contiguous = set(duplicate_bit_groups)
        for key, bits in bit_groups.items():
            if key in non_contiguous:
                continue
            indices = bits.keys()
            n = len(indices)
            if n < 2:
                non_contiguous.add(key)
                continue
            max_idx = max(indices)
            if max_idx + 1 != n or 0 not in indices:
                non_contiguous.add(key)

        # Each non-contiguous bit-select becomes a standalone 'name[idx]' signal
        for sym, name, idx, sc, vtype in bit_select_singletons:
            if (sc, name) in non_contiguous:
                standalone.append((sym, f'{name}[{idx}]', 1, sc, vtype))

        # Register standalone signals. Per IEEE 1364-2005 18.2.3.7, the same
        # identifier_code can be referenced under multiple paths. First seen
        # type wins when aliases have different var_types.
        for sym, name, w, sc, vtype in standalone:
            path = f'{sc}.{name}' if sc else name
            if sym in self.signals:
                self.signals[sym]['aliases'].append(path)
                if sc and sc not in self.signals[sym].setdefault('scopes', []):
                    self.signals[sym]['scopes'].append(sc)
            else:
                self.signals[sym] = {
                    'path': path,
                    'width': w,
                    'type': vtype,
                    'aliases': [path],
                    'scope': sc,
                    'scopes': [sc] if sc else [],
                }

        for (sc, name), bits in bit_groups.items():
            if not bits or (sc, name) in non_contiguous:
                continue
            max_bit = max(bits.keys())
            width = max_bit + 1
            path = f'{sc}.{name}[{max_bit}:0]' if sc else f'{name}[{max_bit}:0]'
            sig_id = f'__grp__{sc}__{name}'
            self.signals[sig_id] = {
                'path': path,
                'width': width,
                'type': bit_types.get((sc, name), 'wire'),
                'aliases': [path],
                'scope': sc,
                'scopes': [sc] if sc else [],
                'synthesized': True,  # bit-exploded reassembled bus
                'raw_bits': len(bits),  # number of $var declarations consumed
            }
            self._bit_state_template[sig_id] = ['x'] * width
            # Per IEEE 1364-2005 18.2.3.7, the same identifier_code can be
            # referenced under multiple paths. When two bit-exploded buses
            # share per-bit identifier codes (e.g. bus[0]/aliasbus[0] both
            # use '!'), each is a separate synthesized signal that must
            # update independently. _bit_map is therefore 1-to-many.
            for idx, sym in bits.items():
                self._bit_map.setdefault(sym, []).append((sig_id, idx))

        # Raw $var counts (transparent to IEEE 1364 spec) so 'info' can
        # report accurate metadata even when reassembly collapses many
        # declarations into a single synthesized bus. Distinct from
        # `signal_count` (post-reassembly view used by agent commands).
        self.raw_var_count = len(raw_vars)
        self.raw_type_counts = defaultdict(int)
        for _sym, _name, _w, _bit_str, _sc, vtype in raw_vars:
            self.raw_type_counts[vtype] += 1

    def _data_tokens(self):
        """Generator yielding all tokens from the data section."""
        for t in self._initial_tokens:
            yield t
        with open(self.path, encoding='utf-8', errors='replace') as f:
            f.seek(self._data_offset)
            for line in f:
                for t in line.split():
                    yield t

    def _is_structural_token(self, tok):
        """Return True when tok is structural rather than an identifier_code.

        Only #<digits> has positional ambiguity: it can be a timestamp at
        top level, or a legal identifier_code after b/r/p. If such a token is
        declared as a normal signal or bit-exploded bit, it is the symbol;
        otherwise it is structural and must be pushed back so the outer loop
        can process it as a timestamp.
        """
        if tok is None:
            return True
        if tok.startswith('#') and len(tok) > 1 and tok[1].isdigit():
            return tok not in self.signals and tok not in self._bit_map
        return False

    def _consume_value_change(self, tok, next_token, pushback):
        """Parse one VCD value_change token sequence.

        Returns (identifier_code, value_str) on a valid value_change, or None
        when tok is malformed / not a value_change. This is the single shared
        validation path used by iter_events() and scan_time_range(), so info's
        reported time range stays aligned with dump/search parsing behavior.

        next_token is a zero-arg function over the same pushback-capable token
        stream as the caller. If a token consumed while validating b/r/p turns
        out to be structural, it is pushed back in the same order used by the
        old local parsers.
        """
        if not tok:
            return None
        first = tok[0]

        if first in '01xXzZ':
            sym = tok[1:]
            if not sym:
                return None
            return sym, first.lower()

        if first in 'bB':
            bits = tok[1:]
            if not bits or any(c not in '01xXzZ' for c in bits):
                return None
            sym = next_token()
            if self._is_structural_token(sym):
                if sym is not None:
                    pushback.append(sym)
                return None
            return sym, bits.lower()

        if first in 'rR':
            body = tok[1:]
            if len(body) > _REAL_MAX_LEN or not _REAL_RE.match(body):
                return None
            sym = next_token()
            if self._is_structural_token(sym):
                if sym is not None:
                    pushback.append(sym)
                return None
            return sym, body

        if first == 'p':
            # Extended VCD (18.4.3.1): p<state> <s0> <s1> <id>.
            # Keep this validation in one place so malformed port events are
            # treated identically by iter_events() and scan_time_range().
            state = tok[1:] if len(tok) > 1 else ''
            if not state or any(c not in _PORT_STATE for c in state):
                return None

            s0 = next_token()
            if s0 is None or len(s0) != 1 or s0 not in '01234567':
                if s0 is not None:
                    pushback.append(s0)
                return None

            s1 = next_token()
            if s1 is None or len(s1) != 1 or s1 not in '01234567':
                if s1 is not None:
                    pushback.append(s1)
                pushback.append(s0)
                return None

            sym = next_token()
            if self._is_structural_token(sym):
                if sym is not None:
                    pushback.append(sym)
                pushback.append(s1)
                pushback.append(s0)
                return None
            return sym, ''.join(_PORT_STATE[c] for c in state)

        return None

    def iter_events(self, t0=0, t1=None, sids=None):
        """Yield (time, sig_id, value_str) with bit reassembly.

        Token-based, context-sensitive. Section keywords ($comment/$vcdclose/
        $dumpvars/$dumpoff/$dumpon/$dumpall/$dumpports*) are only recognized
        when the parser is at a top-level position (expecting either a
        timestamp or a value_change opener). After 'b<bits>', 'r<num>', or
        'p<state> <s0> <s1>' the NEXT token is consumed as identifier_code
        even if it happens to be the string '$comment' (legal per
        IEEE 1364-2005 18.2.1: identifier_code is any printable ASCII).

        Initial value changes appearing before any '#T' timestamp are
        emitted at logical t=0 (typical case: $dumpvars block directly
        after $enddefinitions without a leading #0).
        """
        cur_t = 0
        pending = {}

        def _flush():
            if not pending:
                return []
            items = list(pending.items())
            pending.clear()
            return items

        # Pushback-capable token stream. Lets us peek the next token in
        # b/r value_change branches and refuse it if it looks structural
        # (timestamp or section keyword) -- otherwise malformed inputs
        # like 'b1010\n#10\n1!' would silently consume #10 as the
        # identifier_code and corrupt the timeline.
        raw = self._data_tokens()
        pushback = []
        # Replay-local bit state. iter_events() must be pure with respect
        # to parser metadata: compare/search/summary/snapshot may replay
        # the same VCDParser multiple times and in non-monotonic order.
        # Object-level mutable state would leak future bit values into
        # earlier snapshots for bit-exploded buses.
        #
        # Laziness: when the caller selected a subset of signals (sids),
        # maintain only the synthesized bit-buses that can be emitted for
        # this query. This avoids touching large unrelated bit-exploded
        # buses during catch-up scans, while preserving exact behavior for
        # selected buses and for no-filter calls.
        if sids is None:
            bit_map = self._bit_map
            bit_state = {gid: bits[:] for gid, bits in self._bit_state_template.items()}
        else:
            bit_map = {}
            needed_gids = set()
            for sym0, refs in self._bit_map.items():
                kept = [(gid, idx) for gid, idx in refs if gid in sids]
                if kept:
                    bit_map[sym0] = kept
                    for gid, _idx in kept:
                        needed_gids.add(gid)
            bit_state = {gid: self._bit_state_template[gid][:] for gid in needed_gids}

        def _next():
            return pushback.pop() if pushback else next(raw, None)

        try:
            while True:
                tok = _next()
                if tok is None:
                    break
                # Top-level: any unknown $keyword starts a section ending at
                # $end. This is safer than passing the body through as value
                # changes -- '$bogus 1! $end' must not pollute the waveform.
                # Known wrappers ($dumpvars etc) are pass-through (their body
                # IS value_changes per 18.2.3.9-12).
                if tok == '$end':
                    continue
                if tok in _SIM_KEYWORDS:
                    continue
                if tok.startswith('$'):
                    # $comment, $vcdclose, $bogus, ...: drop body to $end
                    for t in raw:
                        if t == '$end':
                            break
                    continue

                if tok.startswith('#') and len(tok) > 1 and tok[1].isdigit():
                    new_t = _parse_vcd_timestamp_token(tok)
                    if new_t is None:
                        # Malformed (e.g. '#1.5'); silently skip per round-7 policy.
                        continue
                    if cur_t >= t0:
                        for sid, val in _flush():
                            yield cur_t, sid, val
                    cur_t = new_t
                    if t1 is not None and cur_t > t1:
                        return
                    continue

                # Shared value_change parser. Keeping b/r/p validation in one
                # helper prevents scan_time_range() and iter_events() from
                # drifting apart when malformed-token rules are adjusted.
                parsed = self._consume_value_change(tok, _next, pushback)
                if parsed is None:
                    continue
                sym, val = parsed

                # Catch-up before t0: update bit_state only, don't emit.
                # Standalone state is owned by callers (e.g. downstream consumers
                # accumulates it from yielded events), so nothing to do here
                # for the standalone case -- the continue is correct.
                if cur_t < t0:
                    if sym in bit_map:
                        bit_val = val if _is_4state_bits(val) and len(val) == 1 else 'x'
                        for gid, idx in bit_map[sym]:
                            bit_state[gid][idx] = bit_val
                    continue

                # Bit-exploded signal: aggregate into virtual bus value(s).
                # If the same identifier_code drives multiple synthesized buses
                # (via aliased parent declarations), each gets its own event.
                #
                # IMPORTANT: do NOT continue after this branch. Per IEEE 1364-2005
                # 18.2.3.7, the same identifier_code can be referenced by both a
                # standalone $var (e.g. clk) AND a bit-select $var (e.g.
                # data_bus[0]) when RTL assigns one to the other. If we continued,
                # the standalone alias would silently never emit events and the
                # agent would see clk as a flat line. Fall through to the
                # standalone block so both signals update on the same value_change.
                if sym in bit_map:
                    bit_val = val if _is_4state_bits(val) and len(val) == 1 else 'x'
                    for gid, idx in bit_map[sym]:
                        bit_state[gid][idx] = bit_val
                        if sids is None or gid in sids:
                            pending[gid] = ''.join(reversed(bit_state[gid]))

                # Standalone signal (may run after the bit-bus branch above when
                # the sym serves both roles).
                if sym not in self.signals:
                    continue
                if sids is not None and sym not in sids:
                    continue
                pending[sym] = _clamp_overwide_logic_value(val, self.signals[sym])

            # Final flush
            if cur_t >= t0:
                for sid, val in _flush():
                    yield cur_t, sid, val
        finally:
            close = getattr(raw, 'close', None)
            if close is not None:
                close()

    def scan_time_range(self):
        """Min/max timestamps in the file.

        If any value_change occurs before the first #T (an initial $dumpvars
        block), t_min is 0. Time is observed-max (never less than the largest
        seen), so malformed VCDs with timestamps going backwards do not produce
        negative duration. Value-change body validation uses the same shared token consumer as
        iter_events(), so info/dump agree on malformed b/r/p bodies.

        The underlying token generator owns an open file. Close it explicitly
        on all paths instead of relying on garbage collection if a resource
        error is raised while scanning a corrupt file.
        """
        t_min = t_max = None
        saw_initial_data = False
        raw = self._data_tokens()
        pushback = []

        def _next():
            return pushback.pop() if pushback else next(raw, None)

        try:
            while True:
                tok = _next()
                if tok is None:
                    break
                if tok == '$end' or tok in _SIM_KEYWORDS:
                    continue
                if tok.startswith('$'):
                    for t in raw:
                        if t == '$end':
                            break
                    continue
                if tok.startswith('#') and len(tok) > 1 and tok[1].isdigit():
                    t = _parse_vcd_timestamp_token(tok)
                    if t is None:
                        continue
                    if t_min is None:
                        t_min = 0 if saw_initial_data else t
                    t_max = t if t_max is None else max(t_max, t)
                    continue

                # Shared value_change validation. We do not need the
                # parsed sym/value here; the goal is only to know whether a
                # legitimate value_change appears before the first timestamp.
                if self._consume_value_change(tok, _next, pushback) is not None:
                    if t_min is None:
                        saw_initial_data = True
        finally:
            close = getattr(raw, 'close', None)
            if close is not None:
                close()

        if t_min is None and saw_initial_data:
            t_min = t_max = 0
        return t_min, t_max


# -- Subcommands -------------------------------------------------------------


def _is_4state_bits(text):
    return text is not None and text != '' and all(c in '01xz' for c in text)
