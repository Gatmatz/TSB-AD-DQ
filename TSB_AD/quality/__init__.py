"""Time-series pollution for TSB-AD.

    from TSB_AD.quality import pollute

    polluted = pollute(series, "white_noise", snr_db=10, seed=0)
    polluted = pollute(series, "spikes", labels=labels, fraction=0.05, multiplier=5)
    polluted = pollute(series, "white_noise", labels=labels, snr_db=10, applicability="anomalies_only")

`series` is a 1-D array/Series or a TSB-AD DataFrame (`Data`, `Label`); the result has the same type (NaN marks
missing values). The caller names only the pollution; Icewafl or JENGA implements it (see `implementations()`), in
a private environment built on first use (see `runtime.py`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from TSB_AD.quality.backends import BACKENDS
from TSB_AD.quality.enums import (
    APPLICABILITY,
    COUNT_PARAMS,
    LABEL_COL,
    MECHANISMS,
    PARAMS,
    POLLUTION_TYPES,
    VALUE_COL,
    Applicability,
    CorruptionType,
)
from TSB_AD.quality.report import describe

__all__ = [
    "APPLICABILITY",
    "Applicability",
    "BACKENDS",
    "CorruptionType",
    "POLLUTION_TYPES",
    "list_pollutions",
    "implementations",
    "pollute",
]


def _check_params(kind: str, params: dict) -> None:
    """Raises a `ValueError` naming the problem if `params` do not fit the pollution `kind`."""
    required, optional = PARAMS[kind]
    missing = [p for p in required if p not in params]
    if missing:
        raise ValueError(f"{kind}: missing parameter(s) {missing}; expected {list(required + optional)}")
    unknown = [p for p in params if p not in required + optional]
    if unknown:
        raise ValueError(f"{kind}: unknown parameter(s) {unknown}; expected {list(required + optional)}")

    def number(name):
        try:
            return float(params[name])
        except (TypeError, ValueError):
            raise ValueError(f"{kind}: {name} must be a number, got {params[name]!r}") from None

    for name in params:
        if name == "mechanism":
            if params[name] not in MECHANISMS:
                raise ValueError(f"{kind}: mechanism must be one of {list(MECHANISMS)}, got {params[name]!r}")
        elif name in COUNT_PARAMS:
            value = number(name)
            if not value.is_integer() or value < 1:
                raise ValueError(f"{kind}: {name} must be an integer >= 1, got {params[name]!r}")
        elif name == "fraction":
            if not 0 <= number(name) <= 1:
                raise ValueError(f"{kind}: fraction must be between 0 and 1, got {params[name]!r}")
        elif name in ("a", "b"):
            if not 0 < number(name) <= 1:
                raise ValueError(f"{kind}: {name} must be in (0, 1], got {params[name]!r}")
        else:
            number(name)  # snr_db, multiplier


def list_pollutions() -> list[str]:
    """Names accepted by `pollute`."""
    return list(POLLUTION_TYPES)


def implementations() -> dict[str, dict[str, str]]:
    """How each pollution type is implemented: Icewafl where it has an equivalent, otherwise a JENGA subclass
    written for this package."""
    sub = "TabularCorruption subclass"
    return {
        "point_missing": {
            "icewafl": "ReplaceValue(None) + ProbabilityCondition (MCAR, binomial count); "
            "ReplaceValue(None) + FunctionCondition with tail-weighted probabilities (MNAR_*)",
        },
        "burst_missing": {
            "icewafl": "DurationPolluterBatch(ReplaceValue(None)) + ProbabilityCondition (mechanism='MCAR'; random number of bursts)",
            "jenga": f"BurstMissingValues ({sub}) for the MNAR mechanisms",
        },
        "gilbert_elliott": {
            "icewafl": "DurationPolluterBatch(ReplaceValue(None)) + ProbabilityCondition (fixed-length runs)",
        },
        "white_noise": {"icewafl": "GaussianNoise with sigma derived from snr_db"},
        "spikes": {"icewafl": "2 x GaussianNoise(mu=+-k*std, sigma=0) + ProbabilityCondition"},
        "stuck": {"jenga": f"StuckValues ({sub})"},
        "point_swap": {"jenga": f"SwappedPoints ({sub})"},
        "segment_swap": {"jenga": f"SwappedPoints ({sub})"},
        "permutation_swap": {"jenga": f"PermutedSegments ({sub})"},
        "late_arrival": {"icewafl": "DelayTupleBatch(delay) + FunctionCondition (the late batches, chosen with the seed)"},
    }


def _applicable_rows(labels, applicability: Applicability) -> np.ndarray:
    """Positions of the points a pollution may change."""
    if applicability == Applicability.NORMAL_ONLY:
        return np.flatnonzero(labels == 0)
    if applicability == Applicability.ANOMALIES_ONLY:
        return np.flatnonzero(labels != 0)
    return np.arange(len(labels))


def pollute(series, kind: str, *, labels=None, applicability=None, seed: int = 42, return_report: bool = False,
            **params):
    """Pollutes `series` with one pollution.

    Only the points that `applicability` allows are polluted: they are taken out as one shorter series, polluted, and
    put back in their places, so the parameters refer to those points (`fraction=0.1` is 10% of them, the noise
    level and spike size come from their values) and swaps stay among them. The labels never change.

    Args:
        series: 1-D values, or a DataFrame with `Data` (and `Label`).
        kind: a name from `list_pollutions()`, e.g. "white_noise".
        labels: anomaly labels, used by `applicability`; ignored for a DataFrame, all-normal if omitted.
        applicability: an `Applicability` or its value ("global", "normal_only", "anomalies_only"); default
            `APPLICABILITY` of the type (`normal_only` for spikes, `global` for the rest).
        seed: the same seed gives the same result.
        return_report: also return `{"desired": ..., "actual": ...}` (see `report.py`), as `(polluted, report)`.
        **params: the pollution's parameters, e.g. `snr_db=10` or `fraction=0.1`.
    """
    if not isinstance(kind, str) or kind not in POLLUTION_TYPES:
        raise ValueError(f"unknown pollution {kind!r}; expected one pollution name, one of {list_pollutions()}")
    _check_params(kind, params)
    corruption_type = POLLUTION_TYPES[kind]
    if applicability is None:
        applicability = APPLICABILITY[corruption_type]
    elif not isinstance(applicability, Applicability):
        try:
            applicability = Applicability(applicability)
        except ValueError:
            raise ValueError(f"unknown applicability {applicability!r}; expected one of "
                             f"{[a.value for a in Applicability]}") from None
    user_params = dict(params)  # `params` is replaced by the backend's own parameters below

    if isinstance(series, pd.DataFrame):
        df = series.copy()
        if LABEL_COL not in df:
            df[LABEL_COL] = 0
    else:
        values = np.asarray(series, dtype=float).ravel()
        lab = np.zeros(len(values), dtype=int) if labels is None else np.asarray(labels).ravel()
        df = pd.DataFrame({VALUE_COL: values, LABEL_COL: lab})

    from TSB_AD.quality.backends import icewafl, jenga

    rows = _applicable_rows(df[LABEL_COL].to_numpy(), applicability)
    part = df.iloc[rows].reset_index(drop=True)
    polluted = df.copy()
    report = {"desired": {"affected": 0}, "actual": {"affected": 0}}  # no applicable points: nothing changes
    if len(part):
        # Icewafl wherever it has an equivalent, JENGA for the rest
        try:
            backend, (backend_kind, params) = "icewafl", icewafl.translate(corruption_type, params, part)
        except NotImplementedError:
            backend, (backend_kind, params) = "jenga", jenga.translate(corruption_type, params)
        polluted_part, extra = BACKENDS[backend].pollute(part, backend_kind, params, seed)
        polluted.iloc[rows, polluted.columns.get_loc(VALUE_COL)] = polluted_part[VALUE_COL].to_numpy()
        if return_report:
            report = describe(kind, user_params, part[VALUE_COL].to_numpy(), polluted_part[VALUE_COL].to_numpy(), extra)

    result = polluted if isinstance(series, pd.DataFrame) else polluted[VALUE_COL].to_numpy()
    return (result, report) if return_report else result
