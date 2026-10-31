#!/usr/bin/env bash
# 把 Rodin 原始产物处理成运行时资源：标准化 → 按构型绑骨骼/动画 → 压缩
#
# 用法：
#   pipeline/build_beast.sh <beast-id> <body-job-id> [part:job-id[:length] ...]
#   例：pipeline/build_beast.sh jiuweihu jiuweihu-body-i2m tail:jiuweihu-tail-max:0.7
#   例：pipeline/build_beast.sh dijiang dijiang-body-max wing:dijiang-wing-max:0.65 leg:dijiang-leg-max:0.20
set -euo pipefail

BEAST=$1
BODY_JOB=$2
shift 2
PARTS=("$@")

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
WORK="$ROOT/raw/_build/$BEAST"
OUT="$ROOT/public/models/$BEAST"
mkdir -p "$WORK" "$OUT"

ARCHETYPE=$(node -e "
const fs = require('fs');
const p = '$ROOT/content/beasts/$BEAST.json';
console.log(fs.existsSync(p) ? (JSON.parse(fs.readFileSync(p, 'utf8')).archetype || 'quadruped') : 'quadruped');
")

blender() {
  "$BLENDER" --background --factory-startup --python "$ROOT/pipeline/blender/$1" -- "${@:2}" 2>&1 \
    | grep -E '^(CLEANUP|BBOX|TRIS|TEXTURE|SKIN|LANDMARKS|LEGS|SAC_BOUNDS|EXPORTED)|Error|Traceback' || true
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

echo "== body (archetype=$ARCHETYPE)"
TRIM_FLAG=()
BODY_LEN=1.0
if [[ "$ARCHETYPE" == "quadruped" && ${#PARTS[@]} -gt 0 ]]; then
  for spec in "${PARTS[@]}"; do
    [[ "$spec" == tail:* || "$spec" != *:* ]] && TRIM_FLAG=(--trim-tail)
  done
elif [[ "$ARCHETYPE" == "sac" ]]; then
  BODY_LEN=0.78
fi

blender normalize.py "$(pick_glb "$BODY_JOB")" "$WORK/body_norm.glb" --length "$BODY_LEN" ${TRIM_FLAG[@]+"${TRIM_FLAG[@]}"}
blender "rig_${ARCHETYPE}.py" "$WORK/body_norm.glb" "$WORK/body_rig.glb" --preview "$WORK/rig.png"
optimize "$WORK/body_rig.glb" "$OUT/body.glb" 2048

for spec in "${PARTS[@]}"; do
  if [[ "$spec" == *:* ]]; then
    IFS=':' read -r PNAME PJOB PLEN <<< "$spec"
    PLEN=${PLEN:-0.7}
  else
    PNAME="tail"
    PJOB="$spec"
    PLEN=0.7
  fi
  echo "== part:$PNAME ($PJOB len=$PLEN)"
  blender normalize.py "$(pick_glb "$PJOB")" "$WORK/${PNAME}_norm.glb" --length "$PLEN"
  optimize "$WORK/${PNAME}_norm.glb" "$OUT/${PNAME}.glb" 1024
done
