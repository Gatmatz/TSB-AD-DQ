"""Runs the experiments of `settings()` and stores the metrics in Postgres.

    python -m TSB_AD.quality.experiments.run_experiment --workers 8

First the clean baseline (`pollution = 'clean'`) of every dataset, then the pollutions, for every seed and detector.
N worker processes share the datasets: each dataset goes to exactly one process, so no two run the same experiment.
A run that fails is stored in `errors` and the next one starts; runs already stored are skipped, so an interrupted
run can be started again. To run a subset from Python, edit the dict:

    config = settings()
    config["datasets"] = config["datasets"][:5]
    main(config, workers=4)
"""

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat
from multiprocessing import get_context

from TSB_AD.quality.experiments.database import ResultStore
from TSB_AD.quality.experiments.enums.pollutions import MISSING_POLLUTIONS
from TSB_AD.quality.experiments.experiment import PollutedSeries, load_dataset, run_clean, run_polluted
from TSB_AD.quality.experiments.settings import settings

_store = None  # each worker process keeps one database connection


def _init_worker():
    global _store
    _store = ResultStore()


def _imputations(config, kind) -> list:
    return config["imputations"] if kind in MISSING_POLLUTIONS else ["none"]


def run_dataset(config, name, clean):
    """The clean baseline (`clean`) or the pollutions of one dataset, for every seed, detector and imputer; each
    setting is polluted once per seed."""
    try:
        series = load_dataset(name)
    except Exception as e:  # e.g. not in MinIO; the other datasets go on
        print(f"[error] {name}: {type(e).__name__}: {e}", flush=True)
        return
    for seed in config["seeds"]:
        if clean:
            for detector in config["detectors"]:
                run_clean(_store, series, detector, seed)
            continue
        for kind, grid in config["pollutions"].items():
            for params in grid:
                polluted = PollutedSeries(series, kind, params, seed)
                for imputation in _imputations(config, kind):
                    for detector in config["detectors"]:
                        run_polluted(_store, polluted, detector, imputation)


def main(config=None, workers=1):
    from TSB_AD.quality import runtime

    config = config or settings()
    settings_count = sum(len(grid) * len(_imputations(config, kind)) for kind, grid in config["pollutions"].items())
    runs = len(config["datasets"]) * len(config["seeds"]) * len(config["detectors"]) * (1 + settings_count)
    print(f"{len(config['datasets'])} datasets x {len(config['seeds'])} seeds x {config['detectors']} x "
          f"(clean + {settings_count} pollution settings) = {runs} runs, {workers} worker(s); "
          "one line per finished run, runs already stored are skipped silently", flush=True)

    runtime.setup()  # built once here, so the workers do not race to build it on first use
    ResultStore().close()  # tables created once here
    if workers > 1:  # one thread per process: N multi-threaded processes would oversubscribe the cores
        for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ.setdefault(variable, "1")
    names = config["datasets"]
    with ProcessPoolExecutor(workers, mp_context=get_context("spawn"), initializer=_init_worker) as pool:
        list(pool.map(run_dataset, repeat(config), names, repeat(True)))  # first the clean baselines
        list(pool.map(run_dataset, repeat(config), names, repeat(False)))  # then the pollutions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the experiments of settings.py and store them in Postgres.")
    parser.add_argument("--workers", type=int, default=1, help="parallel processes; each takes whole datasets (default 1)")
    main(workers=parser.parse_args().workers)
