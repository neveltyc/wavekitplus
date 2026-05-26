from __future__ import annotations

"""Common clock edge detection logic shared across VCD/FST/FSDB readers."""

import numpy as np


def select_clock_edges(
    all_clock_changes,
    *,
    sample_on_posedge: bool,
    clock_width: int,
    clock_xz_mask: np.ndarray | None = None,
    clock_name: str = 'clock',
):
    if clock_width != 1:
        raise ValueError(
            f"clock signal '{clock_name}' has width {clock_width}; "
            'only 1-bit clocks are supported'
        )
    values = all_clock_changes[:, 1]
    prev = np.roll(values, 1)
    if sample_on_posedge:
        edge_mask = (prev == 0) & (values == 1)
    else:
        edge_mask = (prev == 1) & (values == 0)
    edge_mask[0] = False
    if clock_xz_mask is not None:
        prev_xz = np.roll(clock_xz_mask, 1)
        prev_xz[0] = True
        edge_mask &= ~clock_xz_mask & ~prev_xz
    edge_times = all_clock_changes[edge_mask, 0]
    if len(edge_times) == 0:
        edge_label = 'rising' if sample_on_posedge else 'falling'
        raise ValueError(
            f"clock signal '{clock_name}' has no valid {edge_label} edges"
        )
    return edge_mask, edge_times
