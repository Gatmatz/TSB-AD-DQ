"""Detector settings that differ from TSB-AD's tuned hyperparameters."""

# TSB-AD's tuned dict leaves IForest's window at the wrapper default (100); the leaderboard's IForest uses 1.
DETECTOR_PARAMS = {"IForest": {"slidingWindow": 1}}
