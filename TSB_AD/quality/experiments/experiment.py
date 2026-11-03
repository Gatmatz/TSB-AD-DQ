"""One experiment: pollute a series (or not, for the clean baseline), impute its missing points, run a TSB-AD
detector, score it with TSB-AD's metrics and store the result in Postgres (`experiments`, or `errors` if it fails).

    series = load_dataset("001_NAB_id_1_Facility_tr_1007_1st_2014")
    run_clean(store, series, "IForest", seed=2024)
    run_polluted(store, PollutedSeries(series, "point_missing", {"fraction": 0.1, "mechanism": "MCAR"}, 2024),
                 "IForest", "saits")
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

import numpy as np

from TSB_AD.quality import pollute
from TSB_AD.quality.enums import APPLICABILITY, LABEL_COL, POLLUTION_TYPES, VALUE_COL
from TSB_AD.quality.experiments import database
from TSB_AD.quality.experiments.cleaning import impute_missing
from TSB_AD.quality.experiments.database import minio
from TSB_AD.quality.experiments.enums.detectors import DETECTOR_PARAMS
from TSB_AD.quality.experiments.enums.metrics import METRIC_COLUMNS


def seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    # deterministic GPU runs, as in TSB_AD/main.py
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def run_detector(values, label, detector: str, train_size: int, window: int, seed: int) -> dict:
    """The `experiments` columns of TSB-AD's `get_metrics` for `detector` (tuned hyperparameters plus
    `DETECTOR_PARAMS`) on `values`, plus `execution_time`, the seconds of the detector alone. `window` is the
    metrics' window; detectors that estimate their own window do it on `values`, as in TSB-AD."""
    from sklearn.preprocessing import MinMaxScaler

    from TSB_AD.evaluation.metrics import get_metrics
    from TSB_AD.HP_list import Optimal_Uni_algo_HP_dict
    from TSB_AD.model_wrapper import (
        Semisupervise_AD_Pool,
        Unsupervise_AD_Pool,
        run_Semisupervise_AD,
        run_Unsupervise_AD,
    )

    params = {**Optimal_Uni_algo_HP_dict.get(detector, {}), **DETECTOR_PARAMS.get(detector, {})}
    data = np.asarray(values, dtype=float).reshape(-1, 1)
    seed_everything(seed)
    start = time.perf_counter()
    if detector in Semisupervise_AD_Pool:
        output = run_Semisupervise_AD(detector, data[:train_size], data, **params)
    elif detector in Unsupervise_AD_Pool:
        output = run_Unsupervise_AD(detector, data, **params)
    else:
        raise ValueError(f"unknown detector {detector!r}")
    seconds = time.perf_counter() - start
    if not isinstance(output, np.ndarray):  # the wrappers return an error message string
        raise RuntimeError(f"{detector} failed: {output}")
    score = MinMaxScaler().fit_transform(output.reshape(-1, 1)).ravel()
    pred = score > np.mean(score) + 3 * np.std(score)  # threshold as in TSB_AD/main.py
    metrics = get_metrics(score, label, slidingWindow=window, pred=pred)
    return {**{column: float(metrics[name]) for name, column in METRIC_COLUMNS.items()},
            "execution_time": seconds}


@dataclass
class Series:
    name: str
    values: np.ndarray
    label: np.ndarray
    train_size: int  # from the file name (`_tr_1007_`)
    window: int  # the metrics' window, on the original series as in TSB_AD/main.py


def load_dataset(name: str) -> Series:
    """The series `name` (a file stem, e.g. `001_NAB_id_1_...`), read from MinIO."""
    from TSB_AD.utils.slidingWindows import find_length_rank

    frame = minio.read_series(name)
    values = frame[VALUE_COL].to_numpy(dtype=float)
    return Series(name, values, frame[LABEL_COL].to_numpy(dtype=int), int(re.search(r"_tr_(\d+)_", name).group(1)),
                  int(find_length_rank(values.reshape(-1, 1), rank=1)))


class PollutedSeries:
    """One series polluted with one setting, shared by its detectors and imputers. It is polluted (and imputed) on
    first use, so a setting whose runs are all stored is never polluted."""

    def __init__(self, series: Series, kind: str, params: dict, seed: int):
        self.series, self.kind, self.params, self.seed = series, kind, params, seed
        self._cache = {}

    def get(self, imputation: str = "none"):
        """`(values, report, imputation_rmse)`: the polluted series with its missing points filled by `imputation`
        ("none": left as they are), the pollution report, and the RMSE of the filled points against the original
        series (None without imputation)."""
        if imputation not in self._cache:
            if imputation == "none":
                values, report = pollute(self.series.values, self.kind, labels=self.series.label, seed=self.seed,
                                         return_report=True, **self.params)
                self._cache[imputation] = (values, report, None)
            else:
                values, report, _ = self.get()
                missing = np.isnan(values)
                seed_everything(self.seed)
                filled = impute_missing(values, imputation)
                errors = (filled - self.series.values)[missing]
                self._cache[imputation] = (filled, report, float(np.sqrt(np.mean(errors ** 2))) if missing.any() else None)
        return self._cache[imputation]


def run_clean(store, series: Series, detector: str, seed: int) -> None:
    """The clean baseline: `detector` on the unpolluted series, stored with `pollution = 'clean'`."""
    row = {"pollution": "clean", "params": {}, "imputation": "none", "applicability": "none"}
    _run(store, series, detector, seed, row, lambda: (series.values, None, None))


def run_polluted(store, polluted: PollutedSeries, detector: str, imputation: str = "none") -> None:
    """`detector` on the polluted series, its missing points filled by the PyPOTS imputer `imputation` ("none" for
    the pollutions that create none). `applicability` in the params is stored in its own column (the type's default
    if not given)."""
    params = polluted.params
    row = {"pollution": polluted.kind, "params": {k: v for k, v in params.items() if k != "applicability"},
           "imputation": imputation,
           "applicability": str(params.get("applicability") or APPLICABILITY[POLLUTION_TYPES[polluted.kind]])}
    _run(store, polluted.series, detector, polluted.seed, row, lambda: polluted.get(imputation))


def _run(store, series: Series, detector: str, seed: int, row: dict, get_values) -> None:
    row = {**row, "dataset": series.name, "detector": detector, "seed": seed, "window_length": series.window,
           "execution_profile": database.execution_profile()}
    if store.is_done(row):
        return
    try:
        values, report, rmse = get_values()
        row.update(run_detector(values, series.label, detector, series.train_size, series.window, seed),
                   imputation_rmse=rmse, desired=report and report["desired"], actual=report and report["actual"])
    except Exception as e:  # keep the experiment going; the failure is stored in errors
        store.save_error(row, f"{type(e).__name__}: {e}"[:2000])
        status = "error"
    else:
        store.save(row)
        status = "ok"
    imputation = "" if row["imputation"] == "none" else f" {row['imputation']}"
    print(f"[{status}] {series.name} {detector} {row['pollution']} {row['params']} {row['applicability']}{imputation}",
          flush=True)  # flushed, so the lines appear at once even through `tee`
