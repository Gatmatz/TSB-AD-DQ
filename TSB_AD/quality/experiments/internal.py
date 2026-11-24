"""Internal metric: how well a detector's own quantity q_i separates the anomalous windows (A, at least one point
labeled 1) from the normal ones (N), on the windows the detector itself uses:

    internal_gap = mean(q_i in A) - mean(q_i in N)

    IForest        separation_gap  negated isolation score (`score_samples`) of the run's own forest
    LOF            kdist_gap       distance to the k-th nearest neighbor, k = min(INTERNAL_K, M - 1)
    MatrixProfile  nn_dist_gap     z-normalized nearest-neighbor distance / (2 * sqrt(m)), so 0-1 for any m
    (Sub_)PCA      recon_gap       squared error of the window rebuilt from the components explaining
                                   INTERNAL_PCA_VARIANCE of the variance (at least one left out), per point
                                   (SPE / Q statistic)

q_i is read from the fitted TSB-AD model, so it describes the model that produced the scores. TSB-AD z-scores the
IForest/LOF/PCA windows, so all four are scale-free. Compare a gap only within one detector.
"""

import inspect

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from TSB_AD.quality.experiments.enums.detectors import INTERNAL_K, INTERNAL_PCA_VARIANCE


def fit(detector: str, data: np.ndarray, params: dict):
    """`(scores, clf)`: the TSB-AD model of `detector` fitted on `data` as its wrapper in `TSB_AD.model_wrapper`
    does (which keeps only the scores), so its internals can be read."""
    from TSB_AD import model_wrapper
    from TSB_AD.models.IForest import IForest
    from TSB_AD.models.LOF import LOF
    from TSB_AD.models.MatrixProfile import MatrixProfile
    from TSB_AD.models.PCA import PCA
    from TSB_AD.utils.slidingWindows import find_length_rank

    wrapper = inspect.signature(getattr(model_wrapper, f"run_{detector}")).parameters
    args = {**{name: p.default for name, p in wrapper.items() if name != "data"}, **params}
    if detector == "IForest":
        clf = IForest(slidingWindow=args["slidingWindow"], n_estimators=args["n_estimators"],
                      max_features=args["max_features"], n_jobs=args["n_jobs"])
    elif detector == "LOF":
        clf = LOF(slidingWindow=args["slidingWindow"], n_neighbors=args["n_neighbors"], metric=args["metric"],
                  n_jobs=args["n_jobs"])
    elif detector == "PCA":
        clf = PCA(slidingWindow=args["slidingWindow"], n_components=args["n_components"])
    elif detector == "Sub_PCA":  # PCA with the window of the series' period
        clf = PCA(slidingWindow=find_length_rank(data, rank=args["periodicity"]), n_components=args["n_components"])
    else:
        clf = MatrixProfile(window=find_length_rank(data, rank=args["periodicity"]))
    clf.fit(data)
    return clf.decision_scores_.ravel(), clf


def internal_gap(detector: str, clf, data: np.ndarray, label: np.ndarray) -> float | None:
    """`mean(q_A) - mean(q_N)` of the fitted model `clf` (from `fit`); None if A or N is empty."""
    from TSB_AD.models.feature import Window
    from TSB_AD.utils.utility import zscore

    if detector in ("IForest", "PCA", "Sub_PCA"):  # rebuild the input the model was fitted on, as its `fit` does
        x = Window(window=clf.slidingWindow).convert(data)
        if clf.normalize:
            x = zscore(x, axis=0, ddof=0)
    if detector == "IForest":
        q, w = -clf.detector_.score_samples(x), clf.slidingWindow
    elif detector in ("PCA", "Sub_PCA"):
        if clf.standardization:
            x = clf.scaler_.transform(x)
        if clf.zero_pruning:
            x = x[:, np.any(x != 0, axis=0)]
        pca = clf.detector_
        kept = int(np.searchsorted(np.cumsum(pca.explained_variance_ratio_), INTERNAL_PCA_VARIANCE)) + 1
        kept = min(kept, len(pca.components_) - 1)  # a small noisy window can need all components for the cutoff
        centered = x - pca.mean_
        rebuilt = centered @ pca.components_[:kept].T @ pca.components_[:kept]
        q, w = ((centered - rebuilt) ** 2).mean(axis=1), clf.slidingWindow
    elif detector == "LOF":
        distances = clf.detector_._distances_fit_X_  # sorted, self excluded, n_neighbors columns
        q, w = distances[:, min(INTERNAL_K, distances.shape[1]) - 1], clf.slidingWindow
    else:
        q, w = clf.profile[:, 0].astype(float) / (2 * np.sqrt(clf.window)), clf.window
    anomalous = sliding_window_view(np.asarray(label), w).max(axis=1) > 0
    if anomalous.all() or not anomalous.any():
        return None
    return float(q[anomalous].mean() - q[~anomalous].mean())
