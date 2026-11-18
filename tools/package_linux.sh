#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output_dir=${1:-"$root/work/linux-release"}
mkdir -p -- "$output_dir"
output_dir=$(realpath -- "$output_dir")

image=$(docker build --quiet --platform linux/amd64 "$root/tools/packaging")
docker run --rm --platform linux/amd64 --network none --user "$(id -u):$(id -g)" \
  --env PYTHONDONTWRITEBYTECODE=1 --env PYINSTALLER_CONFIG_DIR=/tmp/pyinstaller-cache \
  --mount "type=bind,source=$root,target=/source,readonly" \
  --mount "type=bind,source=$output_dir,target=/output" \
  --workdir /source "$image" python3 tools/packaging/bundle.py /output
