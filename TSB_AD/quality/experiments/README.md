# Experiments

Pollute every TSB-AD-U series with every setting, run TSB-AD detectors on it, score them with TSB-AD's metrics,
and store every result in Postgres. Built on `TSB_AD.quality` (the `pollute` function); nothing here is part of the
published package.

## Run

Once, on the machine that hosts the services: start Postgres, MinIO and Adminer, and put the series in MinIO:

```bash
docker compose -f TSB_AD/quality/experiments/database/docker-compose.yml up -d
bash TSB_AD/quality/experiments/utils/download_datasets.sh        # TSB-AD-U to data/TSB-AD-U (870 CSVs)
uv run python TSB_AD/quality/experiments/utils/upload_datasets.py # to MinIO, data/PERF/<name>.csv
```

On every machine that runs experiments (also Kaggle, `notebooks/tsbad_quality_notebook.ipynb`), with
`database/.env` pointing at those services (safe to run again, each step is skipped when already done):

```bash
bash TSB_AD/quality/experiments/utils/setup_environment.sh
```

1. `.venv` with the experiment extras (psycopg2, minio, pypots)
2. `database/.env` from `.env.example`, if missing
3. the Icewafl/JENGA runtime built in `~/.cache/tsbad` (about a minute the first time) and the tables created
4. old Flink leftovers removed from `/tmp`

Then run the experiments of `settings.py` in tmux, so it keeps running, with the output also in `experiment.log`:

```bash
tmux new -s experiments "uv run python -m TSB_AD.quality.experiments.run_experiment --workers 12 2>&1 | tee -a experiment.log"
```

- `--workers N`: N processes; each dataset goes to exactly one of them, so no two run the same experiment. Each
  worker needs about 1.7 GB of RAM (one JVM per Icewafl job), so pick N from the free RAM, not the cores.

Leave it running with Ctrl+b then d, come back with `tmux attach -t experiments`. A rerun skips every run already stored.
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
| `CORRUPTION_SETTINGS` | 23 settings over white_noise, spikes, stuck (the other 6 types commented out) | the types to run and their parameter grids; every parameter has at least 3 values. `applicability` (`global`, `normal_only`, `anomalies_only`: which points are polluted) is swept like a parameter; without it a type uses its default (spikes `normal_only`, the rest `global`) |
| `IMPUTATIONS` | `saits` | the PyPOTS imputers of the missing points (`pypots.imputation` class names in lower case: saits, brits, lerp, locf, mean, median, ...), each with its default settings and a separate run; only after `point_missing`, `burst_missing`, `gilbert_elliott` |

`settings()` returns all of this as one dict; edit it (as in the small run above) to run a subset.

## What one experiment does

For each seed, dataset and detector, `run_experiment.py` runs first the clean baseline, then every pollution setting:

1. **Load** the series (`Data`, `Label`) from MinIO and its training size from the file name (`_tr_1007_`).
2. **Pollute** it with one setting (`pollute`, Icewafl or JENGA). Each setting is polluted once per seed and shared
   by the detectors. The clean baseline is not polluted.
3. **Impute** missing points with every imputer of `IMPUTATIONS` (PyPOTS, default settings), only after the
   pollutions that create them (`cleaning.py`). A learned imputer is trained on the polluted series itself, in
   windows of 96 points for 20 epochs (`enums/imputations.py`) and seeded; SAITS takes about 3 s on a 4k-point series. The pollution is
   shared by the imputers.
4. **Detect** with the detector's tuned hyperparameters (`Optimal_Uni_algo_HP_dict`, plus `DETECTOR_PARAMS` in
   `enums/detectors.py`).
   Detectors that estimate their window from the series (`Sub_*`, `MatrixProfile`, ...) do it on the series they
   get, polluted or not, as in TSB-AD.
5. **Score** with TSB-AD's `get_metrics` and store one row in `experiments`, or one in `errors` if anything failed.

## Database

| Table | One row per | Holds |
|---|---|---|
| `experiments` | successful run | dataset, detector, pollution (`clean` for the baseline), params (JSON), seed, imputation, applicability (`none` for the baseline), execution_profile, the 9 metrics, `execution_time`, `imputation_rmse`, `internal_gap`, `desired` / `actual` (JSON) |
| `errors` | failed run | the same key columns and the error message; removed when the run later succeeds |

- **Credentials and ports:** `database/.env` (template: `.env.example`), read by docker-compose and the Python code.
  Postgres on `localhost:5433`, MinIO on `:9100` (console `:9101`), Adminer on `:8082` (the defaults; on panther the
  MinIO ports are swapped in `.env`, API on `:9101`, because only 9101 is open to the outside).
- **`execution_profile`:** the `EXECUTION_PROFILE` name in `.env` (machine or setup), stored with every row.
- **`desired` / `actual`:** what the setting asked for versus what the pollution did, for example
  `desired->>'swaps'` next to `actual->>'swaps'`.
- **`execution_time`:** seconds the detector took, without the pollution or the metrics.
- **`imputation_rmse`:** RMSE of the imputed points against the original series, in the series' units; only for
  the pollutions that create missing points, empty (NULL) for the rest.
- **`internal_gap`:** how well the detector's own quantity separates anomalous windows (at least one point labeled 1)
  from normal ones: `mean(q_A) - mean(q_N)` on the windows the detector uses (`internal.py`). IForest: negated
  isolation score; LOF: distance to the 20th nearest neighbor; MatrixProfile: nearest-neighbor distance / 2√m;
  PCA and Sub_PCA: squared error of the window rebuilt from the components explaining 95 % of the variance, per point.
  Scale-free, but compare it only within one detector; NULL for the other detectors. The change against the clean
  run is computed when analysing (skip clean gaps near 0 and summarise with the median):

  ```sql
  SELECT p.dataset, p.detector, p.pollution, p.params,
         (p.internal_gap - c.internal_gap) / abs(c.internal_gap) * 100 AS internal_gap_change
  FROM experiments p JOIN experiments c
    ON c.dataset = p.dataset AND c.detector = p.detector AND c.seed = p.seed AND c.pollution = 'clean'
  WHERE p.pollution <> 'clean' AND abs(c.internal_gap) > 1e-6;
  ```
- **Schema:** `database/schema.sql`, applied on the first container start and on every connection (it only creates
  what is missing).

## Files

| Path | What |
|---|---|
| `run_experiment.py` | the script: the loops over seeds, datasets and detectors |
| `experiment.py` | one experiment: `run_detector` (detect and score), `PollutedSeries` (pollute and impute once), `run_clean` / `run_polluted` (stored) |
| `settings.py` | what to run |
| `cleaning.py` | imputation (PyPOTS) |
| `enums/` | constants: detector overrides, imputer settings, metric columns, plot styles, missing-value pollutions |
| `plots/` | figures from the `experiments` table (`python -m TSB_AD.quality.experiments.plots.WhiteNoiseLineplot`) |
| `database/` | schema, docker-compose, `.env`, Postgres access (`ResultStore`), MinIO access (`minio.py`) |
| `lists/` | the evaluation list |
| `data/` | the downloaded series, the source of the upload to MinIO (git-ignored) |
| `utils/setup_environment.sh` | sets everything up (does not run experiments) |
| `utils/download_datasets.sh` | downloads and extracts TSB-AD-U |
| `utils/upload_datasets.py` | uploads `data/TSB-AD-U` to MinIO (`data/PERF/`) |

## Things to know

- **IForest uses window 1** (`enums/detectors.py`): TSB-AD's tuned dict leaves it at 100, but the TSB-AD leaderboard's
  IForest uses 1. With it, the clean baseline reproduces the leaderboard (IForest VUS-PR 0.1354 on the first NAB series).
- **Windows:** the metrics' window (`window_length`) is computed once on the original series (`find_length_rank`,
  rank 1, as in `TSB_AD/main.py`), so all runs of a series are scored alike. Detectors that estimate their own
  window do it on the polluted series, so pollution can change it.
- **F1-type metrics** use the `mean + 3 std` threshold of `TSB_AD/main.py`; the leaderboard uses the best threshold
  instead, so only the threshold-free metrics (AUC-PR, AUC-ROC, VUS-PR, VUS-ROC) compare with it directly.
- **The clean baseline is repeated for every seed.** IForest and LOF are deterministic here, so their clean rows are
  the same for all seeds.
- **Pollution seeding** comes only from the `seed` passed to `pollute`; the global seeds (`seed_everything`) affect
  the detectors, not the pollution.
- **Cost:** a setting polluted by Icewafl (white_noise, spikes, the missing types) takes about 4 s, JENGA (stuck,
  swaps) much less; each learned imputer adds its training (SAITS about 30 s on a 4k-point series).
- **A series missing in MinIO** is logged as `[error] <name>` and skipped; `upload_datasets.py` uploads all 870.
