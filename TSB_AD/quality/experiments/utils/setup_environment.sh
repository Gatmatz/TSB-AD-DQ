#!/usr/bin/env bash
# Sets up the Python side of the experiments; each step is skipped when it is already done, so it can be run again.
#   bash TSB_AD/quality/experiments/utils/setup_environment.sh
#   PYTHON=python bash TSB_AD/quality/experiments/utils/setup_environment.sh   # into that Python, no .venv (Kaggle:
#                                                                               # torch etc. are already installed there)
# Postgres and MinIO (with the series in data/PERF/) must already run where database/.env points. It does not run any
# experiment; the last lines it prints say how to.
set -euo pipefail

EXPERIMENTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$EXPERIMENTS/../../.." && pwd)"
DB="$EXPERIMENTS/database"
cd "$ROOT"

step() { echo; echo "== $*"; }

step "1/4 Python environment with the experiment extras"
command -v uv >/dev/null 2>&1 || { echo "error: uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
if [ -n "${PYTHON:-}" ]; then
    PY="$(command -v "$PYTHON")"
else
    [ -d .venv ] || uv venv
    PY="$ROOT/.venv/bin/python"
fi
echo "using $PY"
# --python: without it, uv installs into the system or conda Python when UV_SYSTEM_PYTHON or CONDA_PREFIX is set (Kaggle)
uv pip install --python "$PY" -e ".[quality-experiments]"

step "2/4 credentials (database/.env)"
if [ -f "$DB/.env" ]; then
    echo "exists"
else
    cp "$DB/.env.example" "$DB/.env"
    echo "created from .env.example; change the secrets before sharing the stack"
fi

step "3/4 Icewafl/JENGA runtime (~/.cache/tsbad; the first time takes about a minute) and the database tables"
"$PY" -c "from TSB_AD.quality import runtime; print(runtime.setup())"
"$PY" -c "from TSB_AD.quality.experiments.database import ResultStore; ResultStore().close(); print('tables ready')"

step "4/4 old Flink leftovers in /tmp"
if pgrep -f _icewafl_runner.py >/dev/null 2>&1; then
    echo "skipped: an Icewafl job is running"
else
    leftovers="$(find /tmp -maxdepth 1 \( -name 'flink-rpc-akka_*.jar' -o -name 'minicluster_*' \) 2>/dev/null | wc -l)"
    find /tmp -maxdepth 1 \( -name 'flink-rpc-akka_*.jar' -o -name 'minicluster_*' \) -exec rm -rf {} + 2>/dev/null || true
    echo "removed $leftovers"
fi

echo
echo "Ready. Run the experiments of settings.py with:"
echo "  tmux new -s experiments \"uv run python -m TSB_AD.quality.experiments.run_experiment --workers 12 2>&1 | tee -a experiment.log\""
