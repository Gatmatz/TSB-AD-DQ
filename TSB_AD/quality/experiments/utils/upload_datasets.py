"""Uploads the series in `experiments/data/TSB-AD-U` to the folder `PERF` of the bucket `data` in MinIO.

    python TSB_AD/quality/experiments/utils/upload_datasets.py

Objects are stored as `data/PERF/<series>.csv`; a series already there with the same size is skipped. The bucket
name must be lowercase (S3 rule), a folder name may not. Settings come from `experiments/database/.env`:
MINIO_ENDPOINT (localhost:9100), MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, MINIO_SECURE (1 for https).
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from TSB_AD.quality.experiments.database.minio import BUCKET, PREFIX, client

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "TSB-AD-U"


def upload_datasets(data_dir=DATA_DIR, bucket: str = BUCKET, prefix: str = PREFIX, workers: int = 8, log=print) -> dict:
    """Uploads every `*.csv` in `data_dir` to `<bucket>/<prefix>/`; returns `{"uploaded", "skipped", "failed"}`."""
    from minio.error import S3Error

    files = sorted(Path(data_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(
            f"no CSV files in {data_dir}; run TSB_AD/quality/experiments/utils/download_datasets.sh first"
        )
    minio = client()
    if not minio.bucket_exists(bucket):
        minio.make_bucket(bucket)
        log(f"created bucket {bucket!r}")

    def upload(path: Path) -> str:
        key = f"{prefix}/{path.name}"
        try:
            if minio.stat_object(bucket, key).size == path.stat().st_size:
                return "skipped"
        except S3Error as e:
            if e.code != "NoSuchKey":
                raise
        minio.fput_object(bucket, key, str(path), content_type="text/csv")
        return "uploaded"

    counts = {"uploaded": 0, "skipped": 0, "failed": 0}

    def run(path: Path) -> None:
        try:
            counts[upload(path)] += 1
        except Exception as e:  # keep going; report the failures at the end
            counts["failed"] += 1
            log(f"[failed] {path.name}: {type(e).__name__}: {e}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(run, files))
    log(f"{len(files)} files -> {bucket}/{prefix}/: {counts}")
    return counts


if __name__ == "__main__":
    sys.exit(1 if upload_datasets()["failed"] else 0)
