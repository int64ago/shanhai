#!/usr/bin/env bash
# 把 Rodin 原始产物处理成运行时资源：标准化 → 绑骨骼/动画 → 压缩
#
# 用法：pipeline/build_beast.sh jiuweihu <body-job-id> <tail-job-id>
#   例：pipeline/build_beast.sh jiuweihu jiuweihu-body-max jiuweihu-tail-max
set -euo pipefail

BEAST=$1
BODY_JOB=$2
TAIL_JOB=${3:-}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
WORK="$ROOT/raw/_build/$BEAST"
OUT="$ROOT/public/models/$BEAST"
mkdir -p "$WORK" "$OUT"

blender() {
  "$BLENDER" --background --factory-startup --python "$ROOT/pipeline/blender/$1" -- "${@:2}" 2>&1 \
    | grep -E '^(CLEANUP|BBOX|TRIS|TEXTURE|SKIN|LANDMARKS|LEGS|EXPORTED)|Error|Traceback' || true
}

# 选带贴图的那个 GLB（base_*_pbr.glb）；Extreme-High 另给的 model_export_raw.glb 是千万面无贴图高模，留作烘焙
pick_glb() {
  local f
  f=$(ls "$ROOT/raw/$1"/base_*pbr*.glb 2>/dev/null | head -1)
  [[ -n "$f" ]] || { echo "raw/$1 里找不到 base_*_pbr.glb" >&2; exit 1; }
  echo "$f"
}

optimize() {
  # 不做自动减面（AI 网格减面后蒙皮容易坏），不合并、不扁平化（保留骨骼层级）
  pnpm -s exec gltf-transform optimize "$1" "$2" \
    --simplify false --flatten false --join false --instance false --palette false \
    --texture-compress webp --texture-size "$3" --compress meshopt
  ls -la "$2" | awk '{print "SIZE", $5, $NF}'
}

echo "== body"
TRIM_FLAG=()
[[ -n "$TAIL_JOB" ]] && TRIM_FLAG=(--trim-tail)
blender normalize.py "$(pick_glb "$BODY_JOB")" "$WORK/body_norm.glb" --length 1.0 "${TRIM_FLAG[@]}"
blender rig_quadruped.py "$WORK/body_norm.glb" "$WORK/body_rig.glb" --preview "$WORK/rig.png"
optimize "$WORK/body_rig.glb" "$OUT/body.glb" 2048

if [[ -n "$TAIL_JOB" ]]; then
  echo "== tail"
  blender normalize.py "$(pick_glb "$TAIL_JOB")" "$WORK/tail_norm.glb" --length 0.7
  optimize "$WORK/tail_norm.glb" "$OUT/tail.glb" 1024
fi
