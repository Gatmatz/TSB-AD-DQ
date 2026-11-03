"""Shared settings of the `plots` package: the detectors shown, the defaults, per-detector colors/markers/labels and
the font."""

DETECTORS = ("LOF", "IForest", "StreamVAE")  # the detectors a plot shows by default
DEFAULT_METRIC = "AUC-ROC"

# Paul Tol's colorblind-safe palette; no green
DETECTOR_COLORS = {
    "LOF": "#4477AA",
    "IForest": "#EE6677",
    "MatrixProfile": "#66CCEE",
    "StreamVAE": "#AA3377",
}
DETECTOR_MARKERS = {"LOF": "o", "IForest": "s", "MatrixProfile": "^", "StreamVAE": "D"}
DETECTOR_DISPLAY_NAMES = {
    "LOF": "Local Outlier Factor",
    "IForest": "Isolation Forest",
    "MatrixProfile": "Matrix Profile",
    "StreamVAE": "StreamVAE",
}

FONT_FAMILY = ["Liberation Sans", "DejaVu Sans"]  # Liberation Sans has Arial's metrics; DejaVu ships with matplotlib
