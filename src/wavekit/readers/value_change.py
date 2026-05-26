"""Pure Python fallback for the Cython value_change module.

Provides str_value_change_to_int_value_change_uint64,
value_change_to_value_array_uint64, value_change_to_value_array_object,
and value_change_to_value_array with identical signatures to the .pyx.
"""

import numpy as np


def str_value_change_to_int_value_change_uint64(int_str_list, xz_value):
    """Convert a list of (time, value_str) tuples to a uint64 (n, 2) array."""
    n = len(int_str_list)
    result = np.zeros((n, 2), dtype=np.uint64)
    for i, (t, s) in enumerate(int_str_list):
        new_value = 0
        for ch in s:
            if ch in 'zZxX':
                new_value = (new_value << 1) + xz_value
            else:
                new_value = (new_value << 1) + (ord(ch) - 48)
        result[i, 0] = t
        result[i, 1] = new_value
    return result


def value_change_to_value_array_uint64(value_change, clock_changes,
                                       sample_on_posedge, clock_offset=0):
    """Resample uint64 value changes to clock edges."""
    value_time = value_change[:, 0]
    value = value_change[:, 1]
    clock_time = clock_changes[:, 0]
    clock = clock_changes[:, 1]

    n_clock = clock.size
    value_res = np.zeros(n_clock, dtype=np.uint64)
    clock_res = np.zeros(n_clock, dtype=np.uint64)
    time_res = np.zeros(n_clock, dtype=np.uint64)

    sample_clock_value = 1 if sample_on_posedge else 0
    vidx = 0
    ccnt = 0
    vrange = value.size

    for cidx in range(n_clock):
        if clock[cidx] == sample_clock_value:
            ctime = clock_time[cidx]
            while vidx + 1 < vrange and value_time[vidx + 1] <= ctime:
                vidx += 1
            value_res[ccnt] = value[vidx]
            clock_res[ccnt] = clock_offset + ccnt
            time_res[ccnt] = ctime
            ccnt += 1

    return value_res[:ccnt], clock_res[:ccnt], time_res[:ccnt]


def value_change_to_value_array_object(value_change, clock_changes,
                                       sample_on_posedge, clock_offset=0):
    """Resample object-typed value changes to clock edges."""
    value_time = value_change[:, 0].astype(np.uint64)
    value = value_change[:, 1]
    clock_time = clock_changes[:, 0]
    clock = clock_changes[:, 1]

    n_clock = clock.size
    value_res = np.zeros(n_clock, dtype=np.object_)
    clock_res = np.zeros(n_clock, dtype=np.uint64)
    time_res = np.zeros(n_clock, dtype=np.uint64)

    sample_clock_value = 1 if sample_on_posedge else 0
    vidx = 0
    ccnt = 0
    vrange = value.size

    for cidx in range(n_clock):
        if clock[cidx] == sample_clock_value:
            ctime = clock_time[cidx]
            while vidx + 1 < vrange and value_time[vidx + 1] <= ctime:
                vidx += 1
            value_res[ccnt] = value[vidx]
            clock_res[ccnt] = clock_offset + ccnt
            time_res[ccnt] = ctime
            ccnt += 1

    return value_res[:ccnt], clock_res[:ccnt], time_res[:ccnt]


def value_change_to_value_array(value_change, clock_changes,
                                sample_on_posedge, clock_offset=0):
    """Dispatch to uint64 or object path based on value_change dtype."""
    if value_change.dtype == np.object_:
        return value_change_to_value_array_object(
            value_change, clock_changes, sample_on_posedge, clock_offset)
    else:
        return value_change_to_value_array_uint64(
            value_change, clock_changes, sample_on_posedge, clock_offset)
