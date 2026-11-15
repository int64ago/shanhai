/**
 * 为待制作神兽生成统一的考据设定模板、制作配方（content/beasts/<id>.json）
 * 以及首批 Rodin 文生 3D 任务配置（pipeline/rodin/jobs/<id>-body-v1.json）。
 *
 * 用法：
 *   pnpm beast:scaffold <beast-id> [--force]
 */
import { existsSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { BEASTS } from '../src/app/beasts.ts'
import type { BeastContentSpec } from '../src/app/beastSpec.ts'
import { ROOT } from './recipe.ts'

function buildDefaultSpec(id: string): BeastContentSpec {
  const entry = BEASTS.find((b) => b.id === id)
  if (!entry) throw new Error(`BEASTS 总目中找不到神兽 id: ${id}`)

  const bodyJob = `pipeline/rodin/jobs/${id}-body-v1.json`
  return {
    id: entry.id,
    name: entry.name,
    archetype: entry.archetype,
    source: [
      {
        book: `山海经·${entry.source}`,
        text: entry.quote,
      },
    ],
    inferred: [
      {
        item: '造型与解剖补足',
        basis: `据原典与总目构型设计：${entry.anatomy}（非原文细部由艺术补足）`,
      },
      {
        item: '设色与气韵',
        basis: `据工笔水墨设色参考：${entry.palette}`,
      },
    ],
    parts: [
      {
        id: 'body',
        job: bodyJob,
        instances: 1,
      },
    ],
    recipe: {
      mode: entry.archetype === 'quadruped' || entry.archetype === 'sac' || entry.archetype === 'avian' ? 'archetype' : 'custom',
      rigScript: `rig_${entry.archetype}.py`,
    },
  }
}

function buildStarterJob(id: string) {
  const entry = BEASTS.find((b) => b.id === id)!
  const poseHint =
    entry.archetype === 'quadruped'
      ? 'standing tall on four straight legs, level back, neutral symmetrical pose'
      : entry.archetype === 'avian'
        ? 'avian creature standing upright in a clean symmetrical pose, clear silhouette'
        : entry.archetype === 'serpentine'
          ? 'elongated serpentine body in a gentle natural pose, clear silhouette'
          : entry.archetype === 'sac'
            ? 'rounded sac-like creature body in a clean symmetrical pose'
            : 'upright bipedal mythical figure standing in a clean symmetrical A-pose'

  return {
    id: `${id}-body-v1`,
    beast: id,
    tier: 'Gen-2.5-Medium',
    prompt: `an ancient Chinese mythical creature (${id}), ${poseHint}, rich organic anatomical surface, isolated full body on plain background`,
    params: {
      mesh_mode: 'Raw',
      geometry_file_format: 'glb',
      quality_override: 50000,
    },
  }
}

async function main() {
  const args = process.argv.slice(2)
  const force = args.includes('--force')
  const id = args.find((a) => !a.startsWith('--'))
  if (!id) {
    console.error('用法: pnpm beast:scaffold <beast-id> [--force]')
    process.exit(2)
  }

  const entry = BEASTS.find((b) => b.id === id)
  if (!entry) throw new Error(`未知神兽 id: ${id}`)

  await mkdir(join(ROOT, 'content/beasts'), { recursive: true })
  await mkdir(join(ROOT, 'pipeline/rodin/jobs'), { recursive: true })

  const contentPath = join(ROOT, 'content/beasts', `${id}.json`)
  if (!existsSync(contentPath) || force) {
    const spec = buildDefaultSpec(id)
    await writeFile(contentPath, `${JSON.stringify(spec, null, 2)}\n`)
    console.log(`✔ 生成设定与配方: content/beasts/${id}.json`)
  } else {
    console.log(`[skip] 已存在: content/beasts/${id}.json`)
  }

  const jobPath = join(ROOT, 'pipeline/rodin/jobs', `${id}-body-v1.json`)
  if (!existsSync(jobPath) || force) {
    const job = buildStarterJob(id)
    await writeFile(jobPath, `${JSON.stringify(job, null, 2)}\n`)
    console.log(`✔ 生成初版 Rodin 任务: pipeline/rodin/jobs/${id}-body-v1.json`)
  } else {
    console.log(`[skip] 已存在: pipeline/rodin/jobs/${id}-body-v1.json`)
  }

  console.log(`\n下一步 (${entry.name} / ${entry.id}, archetype=${entry.archetype}):`)
  console.log(`1. 逐字核对 content/beasts/${id}.json 中的 source 与 inferred`)
  console.log(`2. 完善 pipeline/rodin/jobs/${id}-body-v1.json（及独立异体部件 job），运行 pnpm rodin`)
  console.log(`3. 完成 Blender 预处理/绑骨后运行 pipeline/build_beast.sh ${id}`)
  console.log(`4. 新建 src/beasts/${id}/${id.split('_').map((s) => s[0].toUpperCase() + s.slice(1)).join('')}.tsx（beastRegistry.ts 会自动发现）`)
  console.log(`5. 将 src/app/beasts.ts 中 ${id} 的 ready 设为 true 并执行 pnpm typecheck && pnpm validate && pnpm build`)
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err)
  process.exit(1)
})
