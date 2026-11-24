"""Detector settings that differ from TSB-AD's tuned hyperparameters."""

# TSB-AD's tuned dict leaves IForest's window at the wrapper default (100); the leaderboard's IForest uses 1.
DETECTOR_PARAMS = {"IForest": {"slidingWindow": 1}}

# The detectors with an internal metric (`internal.py`), LOF's k for the k-distance and the share of variance of
# the PCA components a window is rebuilt from.
INTERNAL_DETECTORS = ("IForest", "LOF", "MatrixProfile", "PCA", "Sub_PCA")
INTERNAL_K = 20
INTERNAL_PCA_VARIANCE = 0.95
