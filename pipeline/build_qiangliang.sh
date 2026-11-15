#!/usr/bin/env bash
# Compatibility alias; the declared unified recipe is the only build path.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [[ $# -ne 0 ]]; then
  printf 'Usage: bash pipeline/build_qiangliang.sh\n' >&2
  exit 2
fi
exec bash "$ROOT/pipeline/build_beast.sh" qiangliang
