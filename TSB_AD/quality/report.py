"""What a pollution was asked to do (`desired`) versus what it did (`actual`).

    polluted, report = pollute(series, "point_swap", fraction=0.1, return_report=True)
    report["desired"]   # {"affected": 402, "swaps": 201}
    report["actual"]    # {"affected": 402, "swaps": 201}

Both have the same keys. `affected` is the number of points changed (made missing, shifted, frozen or moved); the
other keys depend on the type:

    point_missing    fraction
    burst_missing    bursts, burst_length, longest_burst, fraction
    gilbert_elliott  fraction, runs, mean_run_length
    white_noise      snr_db
    spikes           multiplier
    stuck            blocks, block_length
    point_swap       swaps
    segment_swap     swaps, segment_length
    permutation_swap segments
    late_arrival     late, batches / delay

`desired` is what a perfect run gives (for example `int(n * fraction / 2)` swaps); the Icewafl-based types decide
each point independently, so their `actual` varies around it. `actual` is measured on the polluted series; the
JENGA-based types also report the exact bursts, blocks, swaps or segments they made.
"""

from __future__ import annotations

import numpy as np


def _runs(mask) -> list[int]:
    """Lengths of the runs of consecutive True values."""
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return []
    edges = np.flatnonzero(np.diff(np.concatenate([[0], mask.view(np.int8), [0]])))
    return (edges[1::2] - edges[0::2]).tolist()


def _round(value, digits=4):
    return round(float(value), digits)


def describe(kind: str, params: dict, original, polluted, extra: dict | None = None) -> dict:
    """`{"desired": {...}, "actual": {...}}` for one pollution of the applicable points (`original`); `extra` is the
    backend's own report."""
    extra = extra or {}
    x = np.asarray(original, dtype=float)
    y = np.asarray(polluted, dtype=float)
    n = len(x)
    changed = ~((x == y) | (np.isnan(x) & np.isnan(y)))
    new_missing = np.isnan(y) & ~np.isnan(x)
    n_changed = int(changed.sum())
    n_new_missing = int(new_missing.sum())
    desired: dict = {}
    actual: dict = {"affected": n_changed}

    if kind == "point_missing":
        desired = {"affected": int(n * params["fraction"]), "fraction": params["fraction"]}
        actual = {"affected": n_new_missing, "fraction": _round(n_new_missing / n)}

    elif kind in ("burst_missing", "gilbert_elliott"):
        runs = _runs(new_missing)
        if kind == "burst_missing":
            length = max(1, int(n * params["fraction"]) // params["num_bursts"])
            desired = {"affected": params["num_bursts"] * length, "bursts": params["num_bursts"],
                       "burst_length": length, "fraction": _round(params["num_bursts"] * length / n)}
            actual = {"affected": n_new_missing, "bursts": len(runs),
                      "burst_length": _round(np.mean(runs)) if runs else 0,
                      "longest_burst": max(runs, default=0), "fraction": _round(n_new_missing / n)}
        else:
            rate = params["a"] / (params["a"] + params["b"])
            desired = {"affected": int(round(n * rate)), "fraction": _round(rate), "mean_run_length": _round(1 / params["b"])}
            actual = {"affected": n_new_missing, "fraction": _round(n_new_missing / n), "runs": len(runs),
                      "mean_run_length": _round(np.mean(runs)) if runs else 0}

    elif kind == "white_noise":
        both = ~np.isnan(x) & ~np.isnan(y)
        noise_power = float(np.mean((y[both] - x[both]) ** 2)) if both.any() else 0.0
        signal_power = float(np.mean(x[both] ** 2)) if both.any() else 0.0
        snr = 10 * np.log10(signal_power / noise_power) if noise_power > 0 and signal_power > 0 else None
        desired = {"affected": int((~np.isnan(x)).sum()), "snr_db": params["snr_db"]}
        actual = {"affected": n_changed, "snr_db": None if snr is None else _round(snr, 3)}

    elif kind == "spikes":
        std = np.nanstd(x, ddof=1) if n > 1 else 0.0
        std = 1.0 if std == 0 or np.isnan(std) else std
        # a point hit by both a +k*std and a -k*std spike ends up equal to the original up to rounding
        spiked = np.abs(y - x) > 1e-9 * std
        desired = {"affected": int(n * params["fraction"]), "multiplier": params["multiplier"]}
        actual = {"affected": int(spiked.sum()),
                  "multiplier": _round(np.mean(np.abs(y[spiked] - x[spiked])) / std) if spiked.any() else 0}

    elif kind == "stuck":
        length = max(1, int(n * params["fraction"]) // params["stuck_blocks"])
        desired = {"affected": params["stuck_blocks"] * length, "blocks": params["stuck_blocks"], "block_length": length}
        actual = {"affected": n_changed, "blocks": extra.get("blocks", len(_runs(changed))),
                  "block_length": extra.get("block_length", length)}

    elif kind == "point_swap":
        swaps = max(1, int(params["fraction"] * n / 2))
        desired = {"affected": 2 * swaps, "swaps": swaps}
        actual = {"affected": n_changed, "swaps": extra.get("swaps", n_changed // 2)}

    elif kind == "segment_swap":
        length = max(1, int(params["fraction"] * n / (2 * params["num_swaps"])))
        desired = {"affected": 2 * params["num_swaps"] * length, "swaps": params["num_swaps"], "segment_length": length}
        actual = {"affected": n_changed, "swaps": extra.get("swaps", n_changed // (2 * length)),
                  "segment_length": extra.get("segment_length", length)}

    elif kind == "late_arrival":
        batches = round(n * params["fraction"] / params["batch_size"])
        desired = {"late": batches * params["batch_size"], "batches": batches, "delay": params["delay"]}
        actual = {"affected": n_changed, "late": extra.get("late"), "delay": extra.get("max_delay")}

    elif kind == "permutation_swap":
        desired = {"affected": n, "segments": params["num_permutations"]}
        actual = {"affected": n_changed, "segments": extra.get("segments", params["num_permutations"])}

    return {"desired": desired, "actual": actual}
