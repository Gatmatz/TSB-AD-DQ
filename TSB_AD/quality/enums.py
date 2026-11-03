"""Constants: column names of a TSB-AD series, the corruption types, and what each pollution accepts."""

from enum import Enum

# Column names of a TSB-AD series: values and anomaly labels.
VALUE_COL = "Data"
LABEL_COL = "Label"


class EasilyStringifyableEnum(Enum):
    """`str(member)` gives `member.value`."""

    def __str__(self):
        return self.value


class CorruptionType(EasilyStringifyableEnum):
    # Missing
    POINT_MISSING = "PMIS"
    BURST_MISSING = "BMS"
    GILBERT_ELLIOTT = "GE"

    # White Noise
    NOISE_SNR = "SNR"

    # Spikes
    SPIKE = "SPK"

    # Sensor Freeze
    STUCK = "STK"

    # Swap
    POINT_SWAP = "PSW"
    SEGMENT_SWAP = "SSW"
    PERMUTATION_SWAP = "PMS"

    # Out of order
    LATE_ARRIVAL = "LAR"


class Applicability(EasilyStringifyableEnum):
    """Which points of a series a pollution changes (`pollute(..., applicability=...)`). The labels never change."""

    GLOBAL = "global"  # any point: normal, anomalous and the training part
    NORMAL_ONLY = "normal_only"  # only points with label 0
    ANOMALIES_ONLY = "anomalies_only"  # only points with label 1


# The default applicability of each type; `pollute(..., applicability=...)` overrides it.
APPLICABILITY: dict[CorruptionType, Applicability] = {
    CorruptionType.POINT_MISSING: Applicability.GLOBAL,
    CorruptionType.BURST_MISSING: Applicability.GLOBAL,
    CorruptionType.GILBERT_ELLIOTT: Applicability.GLOBAL,
    CorruptionType.NOISE_SNR: Applicability.GLOBAL,
    CorruptionType.SPIKE: Applicability.NORMAL_ONLY,
    CorruptionType.STUCK: Applicability.GLOBAL,
    CorruptionType.POINT_SWAP: Applicability.GLOBAL,
    CorruptionType.SEGMENT_SWAP: Applicability.GLOBAL,
    CorruptionType.PERMUTATION_SWAP: Applicability.GLOBAL,
    CorruptionType.LATE_ARRIVAL: Applicability.GLOBAL,
}


# The names `pollute` accepts, mapped to their corruption type.
POLLUTION_TYPES: dict[str, CorruptionType] = {
    "point_missing": CorruptionType.POINT_MISSING,
    "burst_missing": CorruptionType.BURST_MISSING,
    "gilbert_elliott": CorruptionType.GILBERT_ELLIOTT,
    "white_noise": CorruptionType.NOISE_SNR,
    "spikes": CorruptionType.SPIKE,
    "stuck": CorruptionType.STUCK,
    "point_swap": CorruptionType.POINT_SWAP,
    "segment_swap": CorruptionType.SEGMENT_SWAP,
    "permutation_swap": CorruptionType.PERMUTATION_SWAP,
    "late_arrival": CorruptionType.LATE_ARRIVAL,
}

MECHANISMS = ("MCAR", "MNAR_extreme", "MNAR_high")

# kind -> (required parameters, optional parameters)
PARAMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "point_missing": (("fraction", "mechanism"), ()),
    "burst_missing": (("fraction", "num_bursts"), ("mechanism",)),
    "gilbert_elliott": (("a", "b"), ()),
    "white_noise": (("snr_db",), ()),
    "spikes": (("fraction", "multiplier"), ()),
    "stuck": (("fraction", "stuck_blocks"), ()),
    "point_swap": (("fraction",), ()),
    "segment_swap": (("fraction", "num_swaps"), ()),
    "permutation_swap": (("num_permutations",), ()),
    "late_arrival": (("fraction", "batch_size", "delay"), ()),
}
COUNT_PARAMS = ("num_bursts", "stuck_blocks", "num_swaps", "num_permutations", "batch_size", "delay")  # integers >= 1
