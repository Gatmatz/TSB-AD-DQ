"""Loads `.env` in this folder, the file docker-compose reads, into the environment."""

import os
from pathlib import Path


def load_env() -> None:
    """Sets the `KEY=VALUE` lines of `.env` that are not set yet (a variable set in the shell wins, as in
    docker-compose); a missing file is fine."""
    path = Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)
