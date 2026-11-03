"""Experiment settings: the pollution sweeps, the detectors, and the `settings()` dict that `run_experiment.py` runs."""

from itertools import product
from pathlib import Path

from TSB_AD.quality import POLLUTION_TYPES
from TSB_AD.quality.enums import Applicability, CorruptionType


# The types to run and their parameter grids; a type that is not here is not run. `applicability` (which points are
# polluted) is swept like the other parameters; without it, a type uses its default (`APPLICABILITY` in enums.py).
CORRUPTION_SETTINGS: dict[CorruptionType, dict[str, list]] = {
    CorruptionType.NOISE_SNR: {"snr_db": [30, 20, 10, 0, -10], "applicability": [Applicability.GLOBAL]},
    CorruptionType.SPIKE: {"multiplier": [3, 5, 10], "fraction": [0.01, 0.05, 0.2],
                           "applicability": [Applicability.NORMAL_ONLY]},
    CorruptionType.STUCK: {"fraction": [0.01, 0.05, 0.2], "stuck_blocks": [1, 5, 20],
                           "applicability": [Applicability.GLOBAL]},
    CorruptionType.POINT_MISSING: {
        "fraction": [0.05, 0.1, 0.2],
        "mechanism": ["MCAR", "MNAR_high", "MNAR_extreme"],
    },
    CorruptionType.BURST_MISSING: {"fraction": [0.05, 0.1, 0.2], "num_bursts": [1, 5, 10]},
    CorruptionType.GILBERT_ELLIOTT: {"a": [0.01, 0.05, 0.1], "b": [0.1, 0.25, 0.5]},
    # CorruptionType.POINT_SWAP: {"fraction": [0.01, 0.1, 0.4]},
    # CorruptionType.SEGMENT_SWAP: {"fraction": [0.05, 0.1, 0.2], "num_swaps": [1, 5, 20]},
    # CorruptionType.PERMUTATION_SWAP: {"num_permutations": [2, 8, 24]},
    # CorruptionType.LATE_ARRIVAL: {"fraction": [0.01, 0.05, 0.2], "batch_size": [1, 10, 50], "delay": [1, 5, 20]},
}

# The PyPOTS imputers that fill the missing points of point_missing, burst_missing and gilbert_elliott, each with its
# default settings (`cleaning.py`); each one is a separate run, the pollution is shared. Names: `pypots.imputation`
# classes in lower case, e.g. saits, lerp, locf, mean, median. A learned one that needs more than `n_steps` also needs
# its required parameters in `enums/imputations.py`.
IMPUTATIONS = ["saits"]

EVA_LIST = Path(__file__).resolve().parent / "lists" / "TSB-AD-U-Eva-Small.csv"  # the series to run (header + file names)
DETECTORS = ["IForest", "LOF"]  # names from TSB-AD's detector pools; each runs with its tuned hyperparameters

SEEDS = [4286, 48608, 72078]  # seeds for the pollution and the detectors; each run is repeated with every seed

def eva_dataset_list() -> list[str]:
    """Dataset names (file stems) in `EVA_LIST`, in file order."""
    with EVA_LIST.open() as f:
        return [Path(line.strip()).stem for line in f.readlines()[1:] if line.strip()]


def sweep(grid: dict[str, list]) -> list[dict]:
    """All parameter combinations of a grid."""
    return [dict(zip(grid, combo)) for combo in product(*grid.values())]


def settings() -> dict:
    """The dict `run_experiment.py` runs; edit it to run a subset.

    `datasets`: names of the series in `EVA_LIST`, read from MinIO (`data/PERF/<name>.csv`). `pollutions`: `{type: [parameters, ...]}` from
    `CORRUPTION_SETTINGS` (only its types). `seeds`: every run is repeated once per seed. `imputations`: `IMPUTATIONS`.
    """
    return {
        "datasets": eva_dataset_list(),
        "detectors": list(DETECTORS),
        "pollutions": {kind: sweep(CORRUPTION_SETTINGS[type_]) for kind, type_ in POLLUTION_TYPES.items()
                       if type_ in CORRUPTION_SETTINGS},
        "seeds": list(SEEDS),
        "imputations": list(IMPUTATIONS),
    }
