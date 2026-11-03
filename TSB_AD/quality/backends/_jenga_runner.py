"""Runs one JENGA corruption inside the isolated environment: `python -I _jenga_runner.py config.json`.

`-I` keeps this directory off `sys.path`, where `backends/jenga.py` would shadow the real `jenga`.
"""

import importlib.util
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

cfg = json.loads(Path(sys.argv[1]).read_text())
spec = importlib.util.spec_from_file_location("jenga_corruptions", cfg["corruptions_file"])
jc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jc)

CLASSES = {
    "burst_missing": jc.BurstMissingValues,
    "stuck": jc.StuckValues,
    "swap": jc.SwappedPoints,
    "permutation": jc.PermutedSegments,
}

col = cfg["value_col"]
df = pd.read_csv(cfg["input"], float_precision="round_trip")
df[col] = df[col].astype(float)
# JENGA draws from the global `random` / `np.random` state.
random.seed(cfg["seed"])
np.random.seed(cfg["seed"])
corruption = CLASSES[cfg["kind"]](column=col, **cfg["params"])
out = corruption.transform(df)
out.to_csv(cfg["output"], index=False, na_rep="nan")
Path(cfg["report"]).write_text(json.dumps(getattr(corruption, "report", {})))
