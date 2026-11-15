#!/usr/bin/env bash
# 把 Rodin 原始产物处理成运行时资源：标准化 → 按构型绑骨骼/动画 → 压缩
#
# 用法：
#   pipeline/build_beast.sh <beast-id>                                  # 按 content/beasts/<id>.json 统一配方构建
#   pipeline/build_beast.sh <beast-id> <body-job-id> [part:job[:len]...] # 显式指定任务构建
#   例：pipeline/build_beast.sh jiuweihu
#   例：pipeline/build_beast.sh dijiang dijiang-body-max wing:dijiang-wing-max:0.65 leg:dijiang-leg-max:0.20
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "用法: $0 <beast-id> [body-job-id [part:job-id[:length] ...]]" >&2
  exit 2
fi

BEAST=$1
shift 1

if [[ -z "$BEAST" || "$BEAST" == *"/"* || "$BEAST" == *".."* ]]; then
  echo "非法 beast-id: $BEAST" >&2
  exit 2
fi

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
if ! command -v "$BLENDER" >/dev/null 2>&1 && [[ ! -x "$BLENDER" ]]; then
  echo "找不到可执行的 Blender: $BLENDER（可通过 BLENDER=... 指定）" >&2
  exit 1
fi

BUILD_PLAN=$(pnpm -s exec tsx "$ROOT/pipeline/recipe.ts" --build-plan "$BEAST")

ARCHETYPE=$(node -e "const p = JSON.parse(process.argv[1]); console.log(p.archetype)" "$BUILD_PLAN")
PLAN_BODY_LEN=$(node -e "const p = JSON.parse(process.argv[1]); console.log(p.bodyLength)" "$BUILD_PLAN")
PLAN_TRIM_TAIL=$(node -e "const p = JSON.parse(process.argv[1]); console.log(p.trimTail ? '1' : '0')" "$BUILD_PLAN")
PLAN_RIG=$(node -e "const p = JSON.parse(process.argv[1]); console.log(p.rigScript || '')" "$BUILD_PLAN")
PLAN_PREPARE=$(node -e "const p = JSON.parse(process.argv[1]); console.log(p.prepareScript || '')" "$BUILD_PLAN")
if [[ -n "$PLAN_PREPARE" && ! -f "$ROOT/$PLAN_PREPARE" ]]; then
  echo "找不到配方预处理脚本: $PLAN_PREPARE" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  BODY_JOB=$(node -e "const p = JSON.parse(process.argv[1]); console.log(p.bodyJobId || '')" "$BUILD_PLAN")
  if [[ -z "$BODY_JOB" ]]; then
    echo "神兽 $BEAST 的统一配方缺少 body 任务（请补充 content/beasts/$BEAST.json 的 parts[id=body]，或显式传入 <body-job-id>）" >&2
    exit 2
  fi
  PARTS=()
  PART_LINES=$(node -e "
    const p = JSON.parse(process.argv[1]);
    for (const part of p.parts || []) {
      if (!part.jobId) {
        console.error('神兽 ' + p.id + ' 的部件 ' + part.name + ' 缺少 jobId');
        process.exit(2);
      }
      console.log(part.name + ':' + part.jobId + ':' + part.length + ':' + (part.texSize || 1024));
    }
  " "$BUILD_PLAN")
  while IFS= read -r line; do
    [[ -n "$line" ]] && PARTS+=("$line")
  done <<< "$PART_LINES"
else
  BODY_JOB=$1
  shift 1
  PARTS=("$@")
fi

if [[ -z "$BODY_JOB" || "$BODY_JOB" == *"/"* || "$BODY_JOB" == *".."* ]]; then
  echo "非法 body-job-id: $BODY_JOB" >&2
  exit 2
fi

# 选带贴图的那个 GLB（base_*_pbr.glb）；Extreme-High 另给的 model_export_raw.glb 是千万面无贴图高模，留作烘焙
pick_glb() {
  local job_id=$1
  local had_nullglob=0
  local matches=()
  if [[ -z "$job_id" || "$job_id" == *"/"* || "$job_id" == *".."* ]]; then
    echo "非法 job-id: $job_id" >&2
    exit 2
  fi
  shopt -q nullglob && had_nullglob=1
  shopt -s nullglob
  matches=("$ROOT/raw/$job_id"/base_*pbr*.glb)
  ((had_nullglob)) || shopt -u nullglob
  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "raw/$job_id 里找不到 base_*pbr*.glb" >&2
    exit 1
  fi
  echo "${matches[0]}"
}

echo "== body ($BEAST, archetype=$ARCHETYPE)"
BODY_LEN="$PLAN_BODY_LEN"
TRIM_FLAG=()
if [[ "$PLAN_TRIM_TAIL" == "1" ]]; then
  TRIM_FLAG=(--trim-tail)
elif [[ "$ARCHETYPE" == "quadruped" && ${#PARTS[@]} -gt 0 ]]; then
  for spec in "${PARTS[@]}"; do
    [[ "$spec" == tail:* || "$spec" != *:* ]] && TRIM_FLAG=(--trim-tail)
  done
fi

if [[ -n "$PLAN_RIG" ]]; then
  RIG_PATH="$ROOT/$PLAN_RIG"
  RIG_NAME="${PLAN_RIG#pipeline/blender/}"
else
  RIG_NAME="rig_${ARCHETYPE}.py"
  RIG_PATH="$ROOT/pipeline/blender/$RIG_NAME"
fi

if [[ ! -f "$ROOT/pipeline/blender/normalize.py" ]]; then
  echo "找不到标准化脚本: pipeline/blender/normalize.py" >&2
  exit 1
fi
if [[ ! -f "$RIG_PATH" ]]; then
  echo "找不到构型绑骨脚本: $RIG_PATH (beast=$BEAST, archetype=$ARCHETYPE)" >&2
  exit 1
fi

BODY_RAW=$(pick_glb "$BODY_JOB")

PARSED_PARTS=()
if [[ ${#PARTS[@]} -gt 0 ]]; then
  for spec in "${PARTS[@]}"; do
    if [[ "$spec" == *:* ]]; then
      IFS=':' read -r PNAME PJOB PLEN PTEX extra <<< "$spec"
      if [[ -n "${extra:-}" ]]; then
        echo "非法部件参数（应为 part:job-id[:length[:texSize]]）: $spec" >&2
        exit 2
      fi
      PLEN=${PLEN:-0.7}
      PTEX=${PTEX:-1024}
    else
      PNAME="tail"
      PJOB="$spec"
      PLEN=0.7
      PTEX=1024
    fi
    if [[ -z "$PNAME" || "$PNAME" == *"/"* || "$PNAME" == *".."* ]]; then
      echo "非法部件名: $PNAME" >&2
      exit 2
    fi
    PART_RAW=$(pick_glb "$PJOB")
    PARSED_PARTS+=("$PNAME|$PJOB|$PLEN|$PTEX|$PART_RAW")
  done
fi

WORK="$ROOT/raw/_build/$BEAST"
OUT="$ROOT/public/models/$BEAST"
mkdir -p "$WORK"
RUN_DIR=$(mktemp -d "$WORK/.build.XXXXXX")
STAGE_OUT="$RUN_DIR/out"
mkdir -p "$STAGE_OUT"
cleanup() {
  rm -rf "$RUN_DIR"
}
trap cleanup EXIT

# The resolver emits only validated compression options. Keep argv boundaries.
node --input-type=module - "$BUILD_PLAN" >"$RUN_DIR/compression-args" <<'NODE'
const args = JSON.parse(process.argv[2]).compressionArgs ?? []
if (!Array.isArray(args) || args.some(arg => typeof arg !== 'string' || arg.includes('\0'))) {
  throw new Error('Invalid compression arguments')
}
for (const arg of args) process.stdout.write(arg + '\0')
NODE
COMPRESSION_ARGS=()
while IFS= read -r -d '' arg; do COMPRESSION_ARGS+=("$arg"); done <"$RUN_DIR/compression-args"

run_blender() {
  local script_path=$1
  local expected_out=$2
  shift 2
  local log_file
  log_file=$(mktemp "$RUN_DIR/blender.log.XXXXXX")

  if ! "$BLENDER" --background --factory-startup --disable-autoexec --python-exit-code 1 --python "$script_path" -- "$@" >"$log_file" 2>&1; then
    echo "Blender 执行失败: $script_path" >&2
    tail -n 40 "$log_file" >&2 || true
    return 1
  fi
  grep -E '^(CLEANUP|BBOX|TRIS|TEXTURE|SKIN|LANDMARKS|LEGS|SAC_BOUNDS|EXPORTED)|Error|Traceback' "$log_file" || true
  if [[ ! -s "$expected_out" ]]; then
    echo "Blender 未生成预期输出: $expected_out" >&2
    tail -n 40 "$log_file" >&2 || true
    return 1
  fi
}

optimize() {
  local in_glb=$1
  local out_glb=$2
  local tex_size=$3
  # 不做自动减面（AI 网格减面后蒙皮容易坏），不合并、不扁平化（保留骨骼层级）
  pnpm -s exec gltf-transform optimize "$in_glb" "$out_glb" \
    --simplify false --flatten false --join false --instance false --palette false \
    --texture-compress webp --texture-size "$tex_size" --compress meshopt ${COMPRESSION_ARGS[@]+"${COMPRESSION_ARGS[@]}"}
  if [[ ! -s "$out_glb" ]]; then
    echo "gltf-transform 未生成输出文件: $out_glb" >&2
    return 1
  fi
  local magic
  magic=$(LC_ALL=C head -c 4 "$out_glb")
  if [[ "$magic" != "glTF" ]]; then
    echo "输出文件不是合法的二进制 GLB: $out_glb" >&2
    return 1
  fi
  ls -la "$out_glb" | awk '{print "SIZE", $5, $NF}'
}

if [[ -n "$PLAN_PREPARE" ]]; then
  # Resolve placeholders as argv values, never as shell source. NUL framing
  # preserves whitespace and empty arguments in custom script interfaces.
  node --input-type=module - "$BUILD_PLAN" "$BODY_RAW" "$RUN_DIR" ${PARSED_PARTS[@]+"${PARSED_PARTS[@]}"} >"$RUN_DIR/prepare-args" <<'NODE'
const [planText, bodyRaw, outDir, ...parts] = process.argv.slice(2)
const plan = JSON.parse(planText)
const values = {
  'body.raw': bodyRaw,
  'body.out': `${outDir}/body_norm.glb`,
  'body.length': String(plan.bodyLength),
  outDir,
}
for (const entry of parts) {
  const [name, , length, , raw] = entry.split('|')
  values[`${name}.raw`] = raw
  values[`${name}.out`] = `${outDir}/${name}_norm.glb`
  values[`${name}.length`] = length
}
if (!Array.isArray(plan.prepareArgs) || plan.prepareArgs.some(arg => typeof arg !== 'string')) {
  throw new Error('recipe.prepareArgs must be an array of strings')
}
const args = plan.prepareArgs.map(arg => arg.replace(/\{([^{}]+)\}/g, (_, key) => {
  if (!Object.hasOwn(values, key)) throw new Error(`Unknown preparation placeholder: {${key}}`)
  return values[key]
}))
for (const arg of args) {
  if (arg.includes('\0')) throw new Error('Preparation arguments cannot contain NUL')
  process.stdout.write(arg + '\0')
}
NODE
  PREPARE_ARGS=()
  while IFS= read -r -d '' arg; do PREPARE_ARGS+=("$arg"); done <"$RUN_DIR/prepare-args"
  run_blender "$ROOT/$PLAN_PREPARE" "$RUN_DIR/body_norm.glb" ${PREPARE_ARGS[@]+"${PREPARE_ARGS[@]}"}
  for entry in ${PARSED_PARTS[@]+"${PARSED_PARTS[@]}"}; do
    IFS='|' read -r PNAME PJOB PLEN PTEX PART_RAW <<< "$entry"
    if [[ ! -s "$RUN_DIR/${PNAME}_norm.glb" ]]; then
      echo "配方预处理未生成部件: ${PNAME}_norm.glb" >&2
      exit 1
    fi
  done
else
  run_blender "$ROOT/pipeline/blender/normalize.py" "$RUN_DIR/body_norm.glb" "$BODY_RAW" "$RUN_DIR/body_norm.glb" --length "$BODY_LEN" ${TRIM_FLAG[@]+"${TRIM_FLAG[@]}"}
fi
run_blender "$RIG_PATH" "$RUN_DIR/body_rig.glb" "$RUN_DIR/body_norm.glb" "$RUN_DIR/body_rig.glb" --preview "$RUN_DIR/rig.png"
optimize "$RUN_DIR/body_rig.glb" "$STAGE_OUT/body.glb" 2048

if [[ ${#PARSED_PARTS[@]} -gt 0 ]]; then
  for entry in "${PARSED_PARTS[@]}"; do
    IFS='|' read -r PNAME PJOB PLEN PTEX PART_RAW <<< "$entry"
    echo "== part:$PNAME ($PJOB len=$PLEN tex=$PTEX)"
    if [[ -z "$PLAN_PREPARE" ]]; then
      run_blender "$ROOT/pipeline/blender/normalize.py" "$RUN_DIR/${PNAME}_norm.glb" "$PART_RAW" "$RUN_DIR/${PNAME}_norm.glb" --length "$PLEN"
    fi
    optimize "$RUN_DIR/${PNAME}_norm.glb" "$STAGE_OUT/${PNAME}.glb" "$PTEX"
  done
fi

if [[ -s "$RUN_DIR/rig.png" ]]; then
  mv -f "$RUN_DIR/rig.png" "$WORK/rig.png"
fi
mkdir -p "$OUT"
mv -f "$STAGE_OUT"/*.glb "$OUT/"
