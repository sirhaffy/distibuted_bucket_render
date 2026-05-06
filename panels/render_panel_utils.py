"""Utility functions for the render panel"""
import math


def calc_bucket_grid(target_buckets, res_x, res_y):
    """Calculate optimal cols x rows for near-square tiles based on resolution aspect ratio"""
    aspect = res_x / res_y if res_y > 0 else 1.0

    # cols/rows such that cols*rows ~ target and (res_x/cols) ~ (res_y/rows)
    cols = max(1, round(math.sqrt(target_buckets * aspect)))
    rows = max(1, round(target_buckets / cols))

    # Ensure we have at least target_buckets
    if cols * rows < target_buckets:
        if cols <= rows:
            cols += 1
        else:
            rows += 1

    return cols, rows
