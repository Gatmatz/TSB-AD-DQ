"""Icewafl (https://github.com/chri-schi/Icewafl, EDBT 2025) polluters, run as a Flink batch job.

Icewafl is a PyFlink project (Java 11, Python <=3.10, `apache-flink==1.17.0`) that imports itself as `src.*`, so each
call writes the series to a TSV, runs `_icewafl_runner.py` in a subprocess from the Icewafl checkout and reads the
result back. `TSB_AD.quality.runtime` provisions everything on first use.

`kind` -> Icewafl polluters; a `probability` parameter (default 1.0) is the fraction of tuples polluted:
    gaussian_noise    GaussianNoise(mu=0, sigma=0.2)
    replace_value     ReplaceValue(replacement); None becomes NaN
    spikes            two GaussianNoise(mu=+-delta, sigma=0), each under ProbabilityCondition(probability / 2)
    mnar_missing      ReplaceValue(None) under FunctionCondition(random() < probabilities[id])
    duration_missing  DurationPolluterBatch(ReplaceValue(None), length) started by ProbabilityCondition(start_prob)
    missing_runs      ReplaceValue(None) on exactly `count` runs of `length` points, placed with the seed
    delay             DelayTupleBatch(delay) on the late points: batches of `batch_size` points, `fraction` of the
                      series, chosen with the seed; the output is read in the order Icewafl emits it

Seeding: Icewafl draws from Python's global `random` inside the Flink workers, which cannot be seeded from outside,
so the runner swaps in subclasses with their own `random.Random(seed)`. Reruns with the same seed match because the
job runs with parallelism 1 in batch mode.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from TSB_AD.quality import runtime
from TSB_AD.quality.enums import LABEL_COL, VALUE_COL

KINDS = ("gaussian_noise", "replace_value", "spikes", "mnar_missing", "duration_missing", "missing_runs", "delay")
_RUNNER = Path(__file__).with_name("_icewafl_runner.py")
_ID = "myId"


def translate(corruption_type, params, df=None):
    """Translates a `CorruptionType` and its params to an Icewafl `(kind, params)`; raises `NotImplementedError` if
    Icewafl has no equivalent.

    - White noise: `GaussianNoise` with the sigma that gives the SNR on the whole signal.
    - Point missing, MCAR: each tuple becomes missing with probability `fraction` (a binomial count, not exact).
    - Point missing, MNAR: per-point probability `min(1, count * w / sum(w))`, `w` = `|z|` or `max(z, 0) + 0.01`.
    - Spikes: `+-multiplier * std`, each point with probability `fraction`.
    - Burst missing, MCAR: exactly `num_bursts` runs of `n * fraction // num_bursts` points, placed at random with the
      seed and never touching each other.
    - Gilbert-Elliott: runs of `1 / b` points (rounded half up) started with probability `a`; fixed length instead
      of geometric.
    - Late arrival: `round(n * fraction / batch_size)` batches of `batch_size` consecutive points, each point held
      back by `delay` points (`DelayTupleBatch`).
    Stuck values, swaps, permutations and MNAR bursts have no Icewafl equivalent.
    """
    from TSB_AD.quality.enums import CorruptionType as C

    if df is None:
        raise NotImplementedError("the series is needed to parameterise Icewafl")
    n = len(df)
    values = df[VALUE_COL].to_numpy(dtype=float)

    if corruption_type == C.NOISE_SNR:
        signal = values[~np.isnan(values)]
        power = float(np.mean(signal**2)) or 1e-6
        return "gaussian_noise", {"mu": 0, "sigma": float(np.sqrt(power / 10 ** (params["snr_db"] / 10)))}

    if corruption_type == C.POINT_MISSING:
        if params.get("mechanism") == "MCAR":
            return "replace_value", {"replacement": None, "probability": params["fraction"]}
        if params.get("mechanism") in ("MNAR_extreme", "MNAR_high"):
            z = (values - np.nanmean(values)) / (np.nanstd(values) + 1e-10)
            w = np.abs(z) if params["mechanism"] == "MNAR_extreme" else np.maximum(z, 0) + 0.01
            w = np.nan_to_num(w, nan=0.0)
            count = int(n * params["fraction"])
            probabilities = np.minimum(1.0, count * w / w.sum()) if count and w.sum() > 0 else np.zeros(n)
            return "mnar_missing", {"probabilities": probabilities.tolist()}

    if corruption_type == C.SPIKE:
        std = float(np.nanstd(values, ddof=1)) if n > 1 else 1.0  # pandas std (ddof=1)
        if std == 0 or np.isnan(std):
            std = 1.0
        return "spikes", {"delta": params["multiplier"] * std, "probability": params["fraction"]}

    if corruption_type == C.BURST_MISSING and params.get("mechanism", "MCAR") == "MCAR":
        length = max(1, int(n * params["fraction"]) // params["num_bursts"])
        return "missing_runs", {"count": params["num_bursts"], "length": length}

    if corruption_type == C.LATE_ARRIVAL:
        return "delay", {k: params[k] for k in ("fraction", "batch_size", "delay")}

    if corruption_type == C.GILBERT_ELLIOTT:
        return "duration_missing", {"length": max(1, int(1 / params["b"] + 0.5)), "start_prob": params["a"]}

    raise NotImplementedError(f"no Icewafl equivalent of {corruption_type} with {params}")


def pollute(df, kind, params, seed):
    """Returns `(polluted frame, report)`; the report is empty for Icewafl, except for `delay`: `late` (points that
    arrive later than their place) and `max_delay` (the most places a point moved)."""
    if kind not in KINDS:
        raise ValueError(f"unknown Icewafl polluter {kind!r}; expected one of {KINDS}")
    python, java, home = runtime.env_python("icewafl"), runtime.java_home(), runtime.icewafl_home()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        in_path, out_dir, cfg_path = tmp / "in.tsv", tmp / "out", tmp / "config.json"
        frame = df[[VALUE_COL, LABEL_COL]].copy()
        frame["Time"] = (np.arange(len(frame)) + 1) * 1000  # event time in ms; must be > 0 for the duration polluter
        frame.to_csv(in_path, sep="\t", header=False, index=False, na_rep="nan")
        cfg_path.write_text(
            json.dumps(
                {
                    "input": str(in_path),
                    "output": str(out_dir),
                    "value_col": VALUE_COL,
                    "label_col": LABEL_COL,
                    "kind": kind,
                    "seed": seed,
                    "params": params,
                }
            )
        )
        # Flink's temporary files (a 36 MB jar and a mini-cluster folder per job) go into this job's folder, which is
        # deleted with it: the runner skips Flink's own cleanup (see the end of _icewafl_runner.py)
        flink_tmp = tmp / "flink"
        flink_tmp.mkdir()
        java_options = f"{os.environ.get('JAVA_TOOL_OPTIONS', '')} -Djava.io.tmpdir={flink_tmp}".strip()
        run = subprocess.run(
            [python, str(_RUNNER), str(cfg_path)],
            cwd=home,
            env={**os.environ, "PYTHONPATH": home, "JAVA_HOME": java, "PATH": os.path.join(java, "bin") + os.pathsep + os.environ["PATH"],
                 "TMPDIR": str(flink_tmp), "JAVA_TOOL_OPTIONS": java_options},
            capture_output=True,
            text=True,
        )
        if run.returncode != 0:
            raise RuntimeError(f"Icewafl pollution {kind!r} failed:\n{(run.stderr or run.stdout).strip()[-1500:]}")

        part_files = [p for p in out_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]
        out = pd.concat(
            [pd.read_csv(p, header=None, names=[_ID, VALUE_COL, LABEL_COL, "Time"], na_values=["None", "nan"], float_precision="round_trip") for p in part_files]
        )

    result = df.copy()
    if kind == "delay":  # the order of arrival is the pollution: the i-th value to arrive takes place i
        moved = np.arange(len(out)) - out[_ID].to_numpy()
        result[VALUE_COL] = out[VALUE_COL].to_numpy()
        return result, {"late": int((moved > 0).sum()), "max_delay": int(moved.max(initial=0))}
    # keep the original positions
    out = out.sort_values(_ID).set_index(_ID).reindex(range(len(df)))
    result[VALUE_COL] = out[VALUE_COL].to_numpy()
    return result, {}  # Icewafl reports nothing itself; `TSB_AD.quality.report` measures the output
