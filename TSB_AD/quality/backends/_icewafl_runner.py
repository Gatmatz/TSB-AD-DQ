"""Runs one Icewafl pollution pipeline as a subprocess of `icewafl.py`, from the Icewafl checkout (cwd and
PYTHONPATH), so that `src.*` resolves to Icewafl's modules.

Usage: python _icewafl_runner.py <config.json>
"""

import json
import os
import random
import sys
import tempfile
from pathlib import Path

from pyflink.datastream import RuntimeExecutionMode, StreamExecutionEnvironment

import numpy as np

from src.Builder.polluter_builder import PolluterBuilderComposite
from src.Conditions.function_condition import FunctionCondition
from src.Conditions.probability_condition import ProbabilityCondition
from src.Polluters.TabularPolluters.KeyedStreamPolluters.delay_tuple_batch_temporal_polluter import DelayTupleBatch
from src.Polluters.TabularPolluters.StreamPolluters.AttributePolluter.gaussian_noise_attribute_polluter import (
    GaussianNoise,
)
from src.Polluters.TabularPolluters.StreamPolluters.AttributePolluter.replace_value_attribute_polluter import (
    ReplaceValue,
)
from src.Polluters.TabularPolluters.StreamPolluters.duration_batch_polluter import DurationPolluterBatch
from src.ReadWrite.CSV.read_write_utils import TabularTimestampAssigner
from src.ReadWrite.CSV.reader_writer_csv import CsvReader, CsvWriter

ID = "myId"
TIME = "Time"  # event time in ms, 1000 per point; needed by the duration polluter
STEP_MS = 1000


class SeededProbabilityCondition(ProbabilityCondition):
    """`ProbabilityCondition` with its own `random.Random(seed)`, pickled into the job (parallelism 1, ordered
    input), so every run consumes the same stream."""

    def __init__(self, probability, seed):
        super().__init__(probability)
        self._rng = random.Random(seed)

    def condition(self, value) -> bool:
        return self._rng.random() < self._probability


class SeededGaussianNoise(GaussianNoise):
    """`GaussianNoise` drawing from its own `random.Random(seed)`."""

    def __init__(self, attribute, id_attribute, mu, sigma, seed):
        super().__init__(attribute, id_attribute, mu=mu, sigma=sigma)
        self._rng = random.Random(seed)

    def _transform(self, value):
        value[self._attribute] = value[self._attribute] + self._rng.gauss(self._mu, self._sigma)
        return value


def random_runs(n, count, length, gap, seed, end=0):
    """The ids of `count` runs of `length` consecutive points at random places, at least `gap` points apart and `end`
    points before the end of the series; fewer if the series is full."""
    rng = random.Random(seed)
    starts = list(range(n - length - end + 1))
    rng.shuffle(starts)
    used = np.zeros(n, dtype=bool)
    ids = set()
    for start in starts:
        if len(ids) >= count * length:
            break
        if not used[max(0, start - gap):start + length + gap].any():
            used[start:start + length] = True
            ids.update(range(start, start + length))
    return ids


def build_polluters(kind, col, params, seed, tuple_type=None, n=0):
    if kind == "gaussian_noise":
        return [SeededGaussianNoise(col, ID, params.get("mu", 0), params.get("sigma", 0.2), seed)]
    if kind == "replace_value":
        return [ReplaceValue(col, ID, params.get("replacement"))]
    if kind == "spikes":
        # +delta and -delta as two GaussianNoise(sigma=0) polluters, each on half of the probability
        up = GaussianNoise(col, ID, mu=params["delta"], sigma=0)
        down = GaussianNoise(col, ID, mu=-params["delta"], sigma=0)
        return [
            up.set_condition(SeededProbabilityCondition(params["probability"] / 2, seed)),
            down.set_condition(SeededProbabilityCondition(params["probability"] / 2, seed + 1)),
        ]
    if kind == "mnar_missing":
        rng = random.Random(seed)
        probabilities = np.asarray(params["probabilities"], dtype=float)
        return [
            ReplaceValue(col, ID, None).set_condition(
                FunctionCondition(lambda v: rng.random() < probabilities[int(v[ID])])
            )
        ]
    if kind == "duration_missing":
        # a run of `length` missing points starts with probability `start_prob` at every point outside a run
        run = DurationPolluterBatch(ReplaceValue(col, ID, None), (params["length"] - 1) * STEP_MS)
        return [run.set_condition(SeededProbabilityCondition(params["start_prob"], seed))]
    if kind == "missing_runs":
        rows = random_runs(n, params["count"], params["length"], 1, seed)  # 1 apart: two runs never merge
        return [ReplaceValue(col, ID, None).set_condition(FunctionCondition(lambda v: int(v[ID]) in rows))]
    if kind == "delay":
        # the late batches, apart and before the end by `delay` so each is overtaken by `delay` points; a held point
        # is released before the first point at least `delay_ms` later, so +1 makes it come after the next `delay`
        batches = round(n * params["fraction"] / params["batch_size"])
        late = random_runs(n, batches, params["batch_size"], params["delay"], seed, end=params["delay"])
        delayed = DelayTupleBatch(tuple_type, ID, (params["delay"] + 1) * STEP_MS)
        return [delayed.set_condition(FunctionCondition(lambda v: int(v[ID]) in late))]
    raise ValueError(kind)


def main(cfg):
    value_col, label_col = cfg["value_col"], cfg["label_col"]
    params = dict(cfg["params"])
    probability = params.get("probability", 1.0)

    with tempfile.TemporaryDirectory() as tmp:
        schema_path = Path(tmp) / "schema.json"
        schema_path.write_text(json.dumps({value_col: "float", label_col: "int", TIME: "int"}))

        env = StreamExecutionEnvironment.get_execution_environment()
        env.set_runtime_mode(RuntimeExecutionMode.BATCH)
        env.set_parallelism(1)
        # Flink starts its Python workers with the bare command `python`; pin it to this interpreter
        env.set_python_executable(sys.executable)

        reader = CsvReader(cfg["input"], str(schema_path), "\t").set_ts_assigner(TabularTimestampAssigner(TIME))
        ds = reader.get_stream(env, "source")

        n = sum(1 for _ in open(cfg["input"]))
        polluters = build_polluters(cfg["kind"], value_col, params, cfg["seed"], reader.tuple_type, n)
        if probability < 1.0 and cfg["kind"] != "spikes":  # spikes use `probability` themselves
            polluters[0].set_condition(SeededProbabilityCondition(probability, cfg["seed"] + 1))
        ds = PolluterBuilderComposite().set_polluters(polluters).build(ds)

        CsvWriter(cfg["output"], list(reader.attribute_names)).write(ds)
        env.execute()


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()))
    # PyFlink 1.17 intermittently segfaults while tearing down its JVM gateway at interpreter
    # exit, after the job has finished and the output is written; skip the teardown.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
