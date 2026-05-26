"""Common clock edge detection logic shared across VCD/FST/FSDB readers."""

import numpy as np


def compute_clock_edge_mask(all_clock_changes, sample_on_posedge):
    """Detect real 0->1 or 1->0 transitions in clock value-change array.

    Returns a boolean mask of the same length as all_clock_changes,
    True for rows that represent an actual edge (not just a level match).
    """
    clock_values = all_clock_changes[:, 1]
    clock_prev = np.roll(clock_values, 1)
    if sample_on_posedge:
        mask = (clock_prev == 0) & (clock_values == 1)
    else:
        mask = (clock_prev == 1) & (clock_values == 0)
    mask[0] = False
    return mask
