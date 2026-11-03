"""Postgres access for the experiments. Settings come from `.env` in this folder (see `env.py`); the defaults match
`docker-compose.yml`: POSTGRES_HOST (localhost), POSTGRES_PORT (5433), POSTGRES_USER (tsbad), POSTGRES_PASSWORD
(tsbad), POSTGRES_DB (tsbad_quality), EXECUTION_PROFILE (a name for this setup).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from TSB_AD.quality.experiments.database.env import load_env
from TSB_AD.quality.experiments.enums.metrics import METRIC_COLUMNS

_KEY = ("dataset", "detector", "pollution", "params", "seed", "imputation", "applicability")
_COLUMNS = (*_KEY, "execution_profile", "window_length", *METRIC_COLUMNS.values(), "execution_time",
            "imputation_rmse", "desired", "actual")
_KEY_MATCH = " AND ".join(f"{c} = %({c})s" for c in _KEY)


def execution_profile() -> str | None:
    """`EXECUTION_PROFILE` from `.env`, stored with every result."""
    load_env()
    return os.environ.get("EXECUTION_PROFILE") or None


def connect():
    import psycopg2

    load_env()
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5433")),
        user=os.environ.get("POSTGRES_USER", "tsbad"),
        password=os.environ.get("POSTGRES_PASSWORD", "tsbad"),
        dbname=os.environ.get("POSTGRES_DB", "tsbad_quality"),
        connect_timeout=10,  # an unreachable host fails after 10 s instead of hanging
    )


def _params(params: dict) -> dict:
    """10.0 -> 10: Postgres treats the two as the same JSON value, so the Python key must too."""
    return {k: int(v) if isinstance(v, float) and v.is_integer() else v for k, v in params.items()}


def _key(row: dict) -> tuple:
    return tuple(json.dumps(_params(row[c]), sort_keys=True) if c == "params" else row[c] for c in _KEY)


class ResultStore:
    """The stored results (so reruns skip them) and errors; creates the tables if they are missing."""

    def __init__(self):
        self.conn = connect()
        # parallel processes would race on CREATE TABLE IF NOT EXISTS; the lock lets one create, the rest wait
        self._execute(["SELECT pg_advisory_xact_lock(4286)", Path(__file__).with_name("schema.sql").read_text()], {})
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(_KEY)} FROM experiments")
            self._done = {_key(dict(zip(_KEY, values))) for values in cur.fetchall()}

    def is_done(self, row: dict) -> bool:
        return _key(row) in self._done

    def save(self, row: dict) -> None:
        """Inserts or replaces the result of a run and clears its stored error."""
        from psycopg2.extras import Json

        values = {c: row.get(c) for c in _COLUMNS}
        values.update({c: Json(row[c]) for c in ("desired", "actual") if row.get(c) is not None},
                      params=Json(_params(row["params"])))
        update = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS if c not in _KEY)
        self._execute([
            f"INSERT INTO experiments ({', '.join(_COLUMNS)}) VALUES ({', '.join(f'%({c})s' for c in _COLUMNS)}) "
            f"ON CONFLICT ON CONSTRAINT experiments_run_key DO UPDATE SET {update}, created_at = now()",
            f"DELETE FROM errors WHERE {_KEY_MATCH}",
        ], values)
        self._done.add(_key(row))

    def save_error(self, row: dict, error: str) -> None:
        """Stores a failed run, replacing an earlier error of the same run."""
        from psycopg2.extras import Json

        values = {**{c: row[c] for c in _KEY}, "params": Json(_params(row["params"])), "error": error}
        self._execute([
            f"INSERT INTO errors ({', '.join(_KEY)}, error) VALUES ({', '.join(f'%({c})s' for c in _KEY)}, %(error)s) "
            "ON CONFLICT ON CONSTRAINT errors_run_key DO UPDATE SET error = EXCLUDED.error, created_at = now()",
        ], values)

    def _execute(self, statements: list, values: dict) -> None:
        try:
            with self.conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement, values or None)
            self.conn.commit()
        except Exception:
            self.conn.rollback()  # a failed statement leaves the transaction aborted; later saves would all fail
            raise

    def close(self) -> None:
        self.conn.close()
