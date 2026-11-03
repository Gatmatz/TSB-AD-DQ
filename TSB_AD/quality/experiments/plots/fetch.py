"""Read-only Postgres accessors for the `plots` package.

The connection is opened read-only (`readonly=True`), so nothing in this module can write to the database.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def fetch_experiments(
    dataset: str | None = None,
    detector: str | None = None,
    pollution: str | None = None,
    applicability: str | None = None,
    imputation: str | None = None,
) -> "pd.DataFrame":
    """Fetches rows from the `experiments` table, optionally filtered; `None` (the default) skips a filter, so no
    arguments return every row. The pollution parameters (`params` JSON) are added as columns of their own
    (`snr_db`, `fraction`, `multiplier`, ...)."""
    import pandas as pd

    from TSB_AD.quality.experiments.database import connect

    filters = {"dataset": dataset, "detector": detector, "pollution": pollution, "applicability": applicability,
               "imputation": imputation}
    filters = {column: value for column, value in filters.items() if value is not None}
    where = ("WHERE " + " AND ".join(f"{column} = %({column})s" for column in filters)) if filters else ""

    conn = connect()
    conn.set_session(readonly=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM experiments {where}", filters)
            df = pd.DataFrame(cur.fetchall(), columns=[column.name for column in cur.description])
    finally:
        conn.close()
    params = pd.DataFrame(df["params"].tolist(), index=df.index) if len(df) else pd.DataFrame(index=df.index)
    return df.join(params)
