#!/usr/bin/env bash
# Downloads TSB-AD-U (~73 MB, 870 CSVs) and extracts it to <dest>/TSB-AD-U/.
#   bash TSB_AD/quality/experiments/utils/download_datasets.sh [dest]
# `dest` defaults to `experiments/data`, where settings.py (DATA_DIR) expects the series. Existing files are overwritten.
set -euo pipefail

URL="https://www.thedatum.org/datasets/TSB-AD-U.zip"
EXPERIMENTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$EXPERIMENTS/data}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
zip="$tmp/TSB-AD-U.zip"

echo "Downloading $URL"
if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --progress-bar -o "$zip" "$URL"
elif command -v wget >/dev/null 2>&1; then
    wget -q --show-progress -O "$zip" "$URL"
else
    echo "error: curl or wget is required" >&2
    exit 1
fi

command -v unzip >/dev/null 2>&1 || { echo "error: unzip is required" >&2; exit 1; }
unzip -tq "$zip" >/dev/null || { echo "error: the downloaded file is not a valid zip" >&2; exit 1; }

mkdir -p "$DEST"
unzip -q -o "$zip" -d "$DEST"

count="$(find "$DEST/TSB-AD-U" -maxdepth 1 -name '*.csv' | wc -l)"
echo "Extracted $count series to $DEST/TSB-AD-U"
