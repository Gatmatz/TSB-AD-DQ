"""Time-series corruptions as JENGA `TabularCorruption`s, for the errors neither Icewafl nor JENGA ships.

JENGA has only tabular corruptions, so these use its extension API: JENGA's `(column, fraction, ...)` constructor and
`transform(df) -> corrupted copy`, with randomness from the global `np.random` like JENGA's own corruptions. All
target the whole series. After `transform`, `report` holds what was actually done (bursts, blocks, swaps or
segments), which `TSB_AD.quality.report` compares with what was asked for.
"""

import numpy as np
from jenga.basis import TabularCorruption


def _zscores(values):
    return (values - np.nanmean(values)) / (np.nanstd(values) + 1e-10)


class BurstMissingValues(TabularCorruption):
    """`num_bursts` runs of `max(1, int(n * fraction) // num_bursts)` consecutive missing values.
    Burst starts are uniform ('MCAR') or weighted by the mean |z| ('MNAR_extreme') / mean
    max(z, 0) + 0.01 ('MNAR_high') over the burst window."""

    def __init__(self, column, fraction, num_bursts, mechanism="MCAR"):
        super().__init__(column, fraction, sampling=mechanism)
        self.num_bursts = num_bursts
        self.mechanism = mechanism

    def transform(self, data):
        df = data.copy(deep=True)
        n = len(df)
        length = max(1, int(n * self.fraction) // self.num_bursts)
        starts = np.arange(0, n - length + 1)
        count = min(self.num_bursts, len(starts))
        if count == 0:
            return df
        p = None
        if self.mechanism != "MCAR":
            z = _zscores(df[self.column].to_numpy(dtype=float))
            score = np.nan_to_num(np.abs(z) if self.mechanism == "MNAR_extreme" else np.maximum(z, 0))
            cum = np.concatenate([[0.0], np.cumsum(score)])
            p = (cum[starts + length] - cum[starts]) / length
            if self.mechanism == "MNAR_high":
                p = p + 0.01
            if p.sum() > 0:
                p = p / p.sum()
                count = min(count, int((p > 0).sum()))  # choice(replace=False) needs enough non-zero weights
            else:  # no value stands out (e.g. a constant series): every start is equally likely
                p = None
        chosen = np.random.choice(starts, size=count, replace=False, p=p)
        self.report = {"bursts": int(len(chosen)), "burst_length": int(length)}
        rows = np.unique(np.concatenate([np.arange(s, s + length) for s in chosen]))
        df.iloc[rows, df.columns.get_loc(self.column)] = np.nan
        return df


class StuckValues(TabularCorruption):
    """`stuck_blocks` runs of `max(1, int(n * fraction) // stuck_blocks)` points frozen to the
    value at the start of the run (a frozen sensor)."""

    def __init__(self, column, fraction, stuck_blocks):
        super().__init__(column, fraction)
        self.stuck_blocks = stuck_blocks

    def transform(self, data):
        df = data.copy(deep=True)
        values = np.array(df[self.column], dtype=float)
        length = max(1, int(len(df) * self.fraction) // self.stuck_blocks)
        starts = np.random.choice(len(df), size=min(self.stuck_blocks, len(df)), replace=False)
        for s in starts:
            values[s : s + length] = values[s]
        self.report = {"blocks": int(len(starts)), "block_length": int(length)}
        df[self.column] = values
        return df


class SwappedPoints(TabularCorruption):
    """Swaps `num_swaps` pairs of equal-length segments of the series (single points when `num_swaps`
    is None, then `int(fraction * n / 2)` pairs). Segment length is
    `max(1, int(fraction * n / (2 * num_swaps)))`. Segments never overlap each other or an earlier
    swap; if the series runs out of free room, fewer swaps are made."""

    def __init__(self, column, fraction, num_swaps=None):
        super().__init__(column, fraction)
        self.num_swaps = num_swaps

    def transform(self, data):
        df = data.copy(deep=True)
        n = len(df)
        if self.num_swaps is None:
            length, swaps = 1, max(1, int(self.fraction * n / 2))
        else:
            length, swaps = max(1, int(self.fraction * n / (2 * self.num_swaps))), self.num_swaps
        values = np.array(df[self.column], dtype=float)

        if length == 1:
            # random pairing of distinct points: a uniform random matching, without a loop over the series
            chosen = np.random.choice(n, size=2 * min(swaps, n // 2), replace=False)
            first, second = chosen[0::2], chosen[1::2]
            values[first], values[second] = values[second].copy(), values[first].copy()
            made = len(first)
        else:
            used = np.zeros(n, dtype=bool)
            made = 0
            for _ in range(swaps):
                # a start is free when its whole segment [s, s + length) is unused
                taken = np.concatenate([[0], np.cumsum(used)])
                starts = np.flatnonzero(taken[length:] - taken[:-length] == 0)
                if len(starts) < 2:
                    break
                i = np.random.choice(starts)
                others = starts[np.abs(starts - i) >= length]
                if len(others) == 0:
                    continue
                j = np.random.choice(others)
                values[i : i + length], values[j : j + length] = (
                    values[j : j + length].copy(),
                    values[i : i + length].copy(),
                )
                used[i : i + length] = used[j : j + length] = True
                made += 1
        self.report = {"swaps": int(made), "segment_length": int(length)}
        df[self.column] = values
        return df


class PermutedSegments(TabularCorruption):
    """Cuts the series into `num_permutations` near-equal segments and reorders them with a
    derangement (no segment keeps its place). Labels are left where they are."""

    def __init__(self, column, num_permutations):
        super().__init__(column, fraction=1.0)
        self.num_permutations = num_permutations

    def transform(self, data):
        df = data.copy(deep=True)
        n, k = len(df), self.num_permutations
        if k < 2 or n < 2 * k:
            self.report = {"segments": 0}
            return df
        self.report = {"segments": int(k)}
        segments = np.array_split(np.arange(n), k)
        while True:
            perm = np.random.permutation(k)
            if not np.any(perm == np.arange(k)):
                break
        order = np.concatenate([segments[i] for i in perm])
        df[self.column] = df[self.column].to_numpy()[order]
        return df
