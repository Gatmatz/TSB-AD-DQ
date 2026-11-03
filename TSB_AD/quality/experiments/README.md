# Experiments

Pollute every TSB-AD-U series with every setting, run TSB-AD detectors on it, score them with TSB-AD's metrics,
and store every result in Postgres. Built on `TSB_AD.quality` (the `pollute` function); nothing here is part of the
published package.

## Run

From the repository root, set everything up (it does not run any experiment; safe to run again, each step is skipped
when already done):

```bash
bash TSB_AD/quality/experiments/utils/setup_environment.sh
```

1. `.venv` with the experiment extras (psycopg2, minio)
2. `database/.env` from `.env.example`
3. TSB-AD-U downloaded to `data/TSB-AD-U` (870 CSVs)
4. Postgres, MinIO and Adminer started (`database/docker-compose.yml`)
5. the series uploaded to MinIO (`data/PERF/<name>.csv`), where the experiments read them from
6. the Icewafl/JENGA runtime built in `~/.cache/tsbad` (about a minute the first time) and the tables created
7. old Flink leftovers removed from `/tmp`

Then run the experiments of `settings.py`, in a terminal multiplexer so it keeps running (`screen` is installed here,
tmux is not), with the output also in `experiment.log`:

```bash
screen -S experiments bash -c "uv run python -m TSB_AD.quality.experiments.run_experiment 2>&1 | tee -a experiment.log"
```

Leave it running with Ctrl+a then d, come back with `screen -r experiments`. A rerun skips every run already stored.
Progress:

```bash
docker exec tsbad-quality-postgres-1 psql -U tsbad -d tsbad_quality -c "SELECT count(*) FROM experiments"
```

A small run (3 datasets):

```bash
uv run python -c "
from TSB_AD.quality.experiments.settings import settings
from TSB_AD.quality.experiments.run_experiment import main
c = settings(); c['datasets'] = c['datasets'][:3]; main(c)"
```

## Configure: `settings.py`

| Setting | Now | Meaning |
|---|---|---|
| `EVA_LIST` | `lists/TSB-AD-U-Eva-Small.csv` (340 series) | the series to run: TSB-AD's evaluation list without its 10 largest series; read from MinIO (`data/PERF/<name>.csv`) |
| `DETECTORS` | IForest, LOF, MatrixProfile | names from TSB-AD's detector pools, run with their tuned hyperparameters |
| `SEEDS` | 4286, 48608, 72078 | every run is repeated once per seed |
| `CORRUPTION_SETTINGS` | 65 settings over the 9 pollution types | the parameter grid; every parameter has at least 3 values |
| `imputation` in `settings()` | `linear` | how missing points are filled; only for `point_missing`, `burst_missing`, `gilbert_elliott` |

`settings()` returns all of this as one dict; edit it (as in the small run above) to run a subset.

## What one experiment does

For each seed, dataset and detector, `run_experiment.py` runs first the clean baseline, then every pollution setting:

1. **Load** the series (`Data`, `Label`) from MinIO and its training size from the file name (`_tr_1007_`).
2. **Pollute** it with one setting (`pollute`, Icewafl or JENGA). Each setting is polluted once per seed and shared
   by the detectors. The clean baseline is not polluted.
3. **Impute** missing points, only after the pollutions that create them (`cleaning.py`).
4. **Detect** with the detector's tuned hyperparameters (`Optimal_Uni_algo_HP_dict`, plus `enums/detectors.py`) and
   its window from the `windows` table.
5. **Score** with TSB-AD's `get_metrics` and store one row in `experiments`, or one in `errors` if anything failed.

## Database

| Table | One row per | Holds |
|---|---|---|
| `experiments` | successful run | dataset, detector, pollution (`clean` for the baseline), params (JSON), seed, imputation, execution_profile, the 9 metrics, `execution_time`, `desired` / `actual` (JSON) |
| `errors` | failed run | the same key columns and the error message; removed when the run later succeeds |
| `windows` | dataset and detector | the detector's sliding window, computed once on the original series |

- **Credentials and ports:** `database/.env` (template: `.env.example`), read by docker-compose and the Python code.
  Postgres on `localhost:5433`, MinIO on `:9100` (console `:9101`), Adminer on `:8082`.
- **`execution_profile`:** the `EXECUTION_PROFILE` name in `.env` (machine or setup), stored with every row.
- **`desired` / `actual`:** what the setting asked for versus what the pollution did, for example
  `desired->>'swaps'` next to `actual->>'swaps'`.
- **`execution_time`:** seconds the detector took, without the pollution or the metrics.
- **Schema:** `database/schema.sql`, applied on the first container start and on every connection (it only creates
  what is missing).

## Files

| Path | What |
|---|---|
| `run_experiment.py` | the script: the loops over seeds, datasets and detectors |
| `experiment.py` | one experiment: `run_experiment` (in memory), `run_clean` / `run_polluted` (stored) |
| `settings.py` | what to run |
| `cleaning.py` | imputation |
| `utils.py` | seeding and the detector-window helpers |
| `enums/` | constants: detector overrides, imputations, missing-type pollutions |
| `database/` | schema, docker-compose, `.env`, Postgres access (`ResultStore`), MinIO access (`minio.py`) |
| `lists/` | the evaluation list |
| `data/` | the downloaded series, the source of the upload to MinIO (git-ignored) |
| `utils/setup_environment.sh` | sets everything up (does not run experiments) |
| `utils/download_datasets.sh` | downloads and extracts TSB-AD-U |
| `utils/upload_datasets.py` | uploads `data/TSB-AD-U` to MinIO (`data/PERF/`) |
| `utils/compute_windows.py` | fills the `windows` table from the series in MinIO (optional: the experiment fills it itself) |

## Things to know

- **IForest uses window 1** (`enums/detectors.py`): TSB-AD's tuned dict leaves it at 100, but the TSB-AD leaderboard's
  IForest uses 1. With it, the clean baseline reproduces the leaderboard (IForest VUS-PR 0.1354 on the first NAB series).
- **Detector windows are fixed.** Detectors that estimate their window from the series (`Sub_*`, `MatrixProfile`, ...)
  would re-estimate it on the polluted series; instead they get the window of the original series from `windows`.
  This does not reach models that compute a window inside their own code (Syntropic, CHARM). Do not run detectors in
  parallel threads: the window is fixed by temporarily replacing TSB-AD's estimator.
- **F1-type metrics** use the `mean + 3 std` threshold of `TSB_AD/main.py`; the leaderboard uses the best threshold
  instead, so only the threshold-free metrics (AUC-PR, AUC-ROC, VUS-PR, VUS-ROC) compare with it directly.
- **The clean baseline is repeated for every seed.** IForest and LOF are deterministic here, so their clean rows are
  the same for all seeds.
- **Pollution seeding** comes only from the `seed` passed to `pollute`; the global seeds (`seed_everything`) affect
  the detectors, not the pollution.
- **Cost:** 41 of the 65 settings run on Icewafl at about 4 s each, so pollution alone is about 46 hours for 340
  datasets and 3 seeds; detector time comes on top (MatrixProfile is the slowest of the three).
- **A series missing in MinIO stops the run** (`FileNotFoundError` naming it); `upload_datasets.py` uploads all 870.
