"""JENGA (https://github.com/schelterlabs/jenga) corruptions of the `Data` column, run in the isolated environment of
`TSB_AD.quality.runtime` (JENGA pins Python <3.10, so it is never imported here).

`kind` -> corruption class in `jenga_corruptions`; `params` are its constructor arguments without `column`.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

from TSB_AD.quality import runtime
from TSB_AD.quality.enums import LABEL_COL, VALUE_COL

KINDS = ("burst_missing", "stuck", "swap", "permutation")  # classes in `jenga_corruptions`


def translate(corruption_type, params):
    """Translates a `CorruptionType` and its params to a JENGA `(kind, params)`.

    Only the errors Icewafl cannot express are mapped: MNAR bursts, stuck values, swaps and permutations. JENGA has
    no temporal errors, so each is a JENGA-style subclass in `jenga_corruptions`; its own `MissingValues`,
    `GaussianNoise` and `Scaling` are not used.
    """
    from TSB_AD.quality.enums import CorruptionType as C

    simple = {
        C.BURST_MISSING: "burst_missing",
        C.STUCK: "stuck",
        C.POINT_SWAP: "swap",
        C.SEGMENT_SWAP: "swap",
        C.PERMUTATION_SWAP: "permutation",
    }
    if corruption_type in simple:
        return simple[corruption_type], dict(params)
    raise NotImplementedError(f"no JENGA equivalent of {corruption_type} with {params}")


_RUNNER = Path(__file__).with_name("_jenga_runner.py")
_CORRUPTIONS = Path(__file__).with_name("jenga_corruptions.py")


def pollute(df, kind, params, seed):
    """Returns `(polluted frame, report)`; the report holds what the corruption actually did."""
    if kind not in KINDS:
        raise ValueError(f"unknown JENGA corruption {kind!r}; expected one of {KINDS}")
    python = runtime.env_python("jenga")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        in_path, out_path, cfg_path = tmp / "in.csv", tmp / "out.csv", tmp / "config.json"
        report_path = tmp / "report.json"
        df[[VALUE_COL, LABEL_COL]].to_csv(in_path, index=False, na_rep="nan")
        cfg_path.write_text(
            json.dumps(
                {
                    "input": str(in_path),
                    "output": str(out_path),
                    "report": str(report_path),
                    "value_col": VALUE_COL,
                    "kind": kind,
                    "seed": seed,
                    "params": params,
                    "corruptions_file": str(_CORRUPTIONS),
                }
            )
        )
        run = subprocess.run([python, "-I", str(_RUNNER), str(cfg_path)], capture_output=True, text=True)
        if run.returncode != 0:
            raise RuntimeError(f"JENGA corruption {kind!r} failed:\n{run.stderr.strip()[-1500:]}")
        out = pd.read_csv(out_path, na_values=["nan"], float_precision="round_trip")
        report = json.loads(report_path.read_text())
    result = df.copy()
    result[VALUE_COL] = out[VALUE_COL].to_numpy()
    return result, report
