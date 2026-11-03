"""Filling the missing points that some pollutions create, with PyPOTS."""

import contextlib
import inspect
import os

import numpy as np

from TSB_AD.quality.experiments.enums.imputations import EPOCHS, REQUIRED_PARAMS, WINDOW


def impute_missing(values: np.ndarray, how: str) -> np.ndarray:
    """`values` with its NaN filled by the PyPOTS imputer `how` (a `pypots.imputation` class name in lower case); the
    observed points are kept. A learned imputer is trained on the series itself for `EPOCHS`, in windows of `WINDOW`
    points; seed before calling for a reproducible result."""
    missing = np.isnan(values)
    if not missing.any():
        return values
    with open(os.devnull, "w", encoding="utf-8") as devnull, contextlib.redirect_stdout(devnull):  # import banner
        from pypots import imputation
    cls = {name.lower(): getattr(imputation, name) for name in imputation.__all__}[how]
    accepted = inspect.signature(cls).parameters
    learned = "n_steps" in accepted
    params = dict(REQUIRED_PARAMS.get(how, {}))
    if learned:
        params.update(n_steps=WINDOW, n_features=1, epochs=EPOCHS)
    if "verbose" in accepted:
        params["verbose"] = False
    imputer = cls(**params)

    mean, std = np.nanmean(values), np.nanstd(values) or 1.0
    n_steps = WINDOW if learned else len(values)
    x = np.append((values - mean) / std, np.full(-len(values) % n_steps, np.nan)).reshape(-1, n_steps, 1)
    if learned:
        imputer.fit({"X": x})
    filled = imputer.impute({"X": x}).ravel()[:len(values)] * std + mean
    return np.where(missing, filled, values)
