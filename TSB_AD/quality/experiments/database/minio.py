"""The series in MinIO, stored as `<BUCKET>/<PREFIX>/<name>.csv` by `utils/upload_datasets.py`. Settings come from
`.env` in this folder (see `env.py`): MINIO_ENDPOINT (localhost:9100), MINIO_ROOT_USER (tsbad), MINIO_ROOT_PASSWORD
(tsbad-secret), MINIO_SECURE (1 for https).
"""

import io
import os
from functools import cache

from TSB_AD.quality.experiments.database.env import load_env

BUCKET = "data"  # bucket names must be lowercase; PERF is a folder in it
PREFIX = "PERF"


@cache
def client():
    from minio import Minio

    load_env()
    return Minio(
        os.environ.get("MINIO_ENDPOINT", "localhost:9100"),
        access_key=os.environ.get("MINIO_ROOT_USER", "tsbad"),
        secret_key=os.environ.get("MINIO_ROOT_PASSWORD", "tsbad-secret"),
        secure=os.environ.get("MINIO_SECURE", "0") == "1",
    )


def read_series(name: str):
    """The series `name` (a file stem, e.g. `001_NAB_id_1_...`) as a DataFrame with `Data` and `Label`."""
    import pandas as pd

    response = client().get_object(BUCKET, f"{PREFIX}/{name}.csv")
    try:
        return pd.read_csv(io.BytesIO(response.read()))
    finally:
        response.close()
        response.release_conn()
