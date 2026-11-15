/**
 * 统一异兽登记与制作配方解析器：
 * 将 src/app/beasts.ts（总目登记）、content/beasts/<id>.json（考据与部件配方）、
 * src/beasts/<id>/<Name>.tsx（运行时组件）、pipeline/blender/*（预处理与绑骨脚本）
 * 以及 scripts/qa-*.mjs（浏览器 QA）收口到同一解析模型。
 *
 * 用法：
 *   pnpm beast:recipe <beast-id>
 *   pnpm beast:recipe --pending
 *   pnpm beast:recipe --all
 *   pnpm exec tsx pipeline/recipe.ts --build-plan <beast-id>
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BEASTS, type BeastArchetype, type BeastEntry } from '../src/app/beasts.ts'
import { toBeastComponentName, type BeastContentSpec } from '../src/app/beastSpec.ts'
import { resolveCompressionArgs } from './compression.ts'

export const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)))

export interface ResolvedPart {
  name: string
  jobPath: string | null
  jobId: string | null
  instances: number
  length: number
  texSize: number
}

export interface ResolvedBuildPlan {
  id: string
  archetype: BeastArchetype
  bodyLength: number
  trimTail: boolean
  prepareScript: string | null
  prepareArgs: string[] | null
  compressionArgs: string[]
  rigScript: string | null
  bodyJobId: string | null
  parts: ResolvedPart[]
}

export interface ResolvedBeastRecipe {
  entry: BeastEntry
  contentPath: string
  contentExists: boolean
  content: BeastContentSpec | null
  componentPath: string
  componentExists: boolean
  narrationPath: string
  narrationExists: boolean
  modelDir: string
  modelFiles: string[]
  prepareScript: string | null
  rigScript: string | null
  qaScript: string | null
  buildPlan: ResolvedBuildPlan
}

function defaultBodyLength(id: string, archetype: BeastArchetype): number {
  if (id === 'jingwei') return 1.5
  if (archetype === 'sac') return 0.78
  if (archetype === 'avian') return 1.22
  return 1.0
}

function resolveBlenderScript(specPath: string | undefined, fallbackRel: string): string | null {
  if (specPath) {
    const normalized = specPath.startsWith('pipeline/') ? specPath : `pipeline/blender/${specPath}`
    return normalized
  }
  return existsSync(join(ROOT, fallbackRel)) ? fallbackRel : null
}

function resolveJobId(jobPath: string | undefined, explicitJobId: string | undefined): string | null {
  if (explicitJobId) return explicitJobId
  if (!jobPath) return null
  const abs = join(ROOT, jobPath)
  if (!existsSync(abs)) return null
  try {
    const parsed = JSON.parse(readFileSync(abs, 'utf8')) as { id?: string }
    return parsed.id || null
  } catch {
    return null
  }
}

export function resolveBeastRecipe(id: string): ResolvedBeastRecipe {
  const entry = BEASTS.find((b) => b.id === id)
  if (!entry) throw new Error(`未知神兽 id: ${id}`)

  const contentRel = `content/beasts/${id}.json`
  const contentAbs = join(ROOT, contentRel)
  const contentExists = existsSync(contentAbs)
  const content = contentExists ? (JSON.parse(readFileSync(contentAbs, 'utf8')) as BeastContentSpec) : null

  const componentRel = `src/beasts/${id}/${toBeastComponentName(id)}.tsx`
  const componentExists = existsSync(join(ROOT, componentRel))

  const narrationRel = `public/audio/narration/${id}.mp3`
  const narrationExists = existsSync(join(ROOT, narrationRel))

  const modelRel = `public/models/${id}`
  const modelAbs = join(ROOT, modelRel)
  const modelFiles = existsSync(modelAbs)
    ? readdirSync(modelAbs)
        .filter((f) => f.endsWith('.glb'))
        .sort()
    : []

  const recipe = content?.recipe
  const prepareScript = resolveBlenderScript(recipe?.prepareScript, `pipeline/blender/prepare_${id}.py`)
  const defaultRigRel = existsSync(join(ROOT, `pipeline/blender/rig_${id}.py`))
    ? `pipeline/blender/rig_${id}.py`
    : `pipeline/blender/rig_${entry.archetype}.py`
  const rigScript = resolveBlenderScript(recipe?.rigScript, defaultRigRel)

  const defaultQaRel = `scripts/qa-${id.replaceAll('_', '-')}.mjs`
  const qaScript = recipe?.qaScript ?? (existsSync(join(ROOT, defaultQaRel)) ? defaultQaRel : null)

  const partsSpec = content?.parts ?? []
  const bodyPart = partsSpec.find((p) => p.id === 'body')
  const extraParts: ResolvedPart[] = partsSpec
    .filter((p) => p.id !== 'body')
    .map((p) => ({
      name: p.id,
      jobPath: p.job ?? null,
      jobId: resolveJobId(p.job, p.jobId),
      instances: p.instances ?? 1,
      length: p.length ?? 0.7,
      texSize: p.texSize ?? 1024,
    }))

  const hasTailPart = extraParts.some((p) => p.name === 'tail')
  const trimTail = recipe?.trimTail ?? (entry.archetype === 'quadruped' && hasTailPart)
  const bodyLength = recipe?.bodyLength ?? bodyPart?.length ?? defaultBodyLength(id, entry.archetype)
  const bodyJobId = resolveJobId(bodyPart?.job, bodyPart?.jobId)

  return {
    entry,
    contentPath: contentRel,
    contentExists,
    content,
    componentPath: componentRel,
    componentExists,
    narrationPath: narrationRel,
    narrationExists,
    modelDir: modelRel,
    modelFiles,
    prepareScript,
    rigScript,
    qaScript,
    buildPlan: {
      id,
      archetype: entry.archetype,
      bodyLength,
      trimTail,
      // Discovered legacy scripts have different CLIs; execution requires an explicit recipe.
      prepareScript: recipe?.prepareScript ? prepareScript : null,
      prepareArgs: recipe?.prepareScript ? (recipe.prepareArgs ?? ['{body.raw}', '{body.out}']) : null,
      compressionArgs: resolveCompressionArgs(recipe?.compression),
      rigScript,
      bodyJobId,
      parts: extraParts,
    },
  }
}

function printSummary(recipes: ResolvedBeastRecipe[]) {
  for (const r of recipes) {
    const status = r.entry.ready ? 'READY  ' : 'PENDING'
    const marks = [
      r.contentExists ? 'json' : '-json',
      r.componentExists ? 'tsx' : '-tsx',
      r.modelFiles.includes('body.glb') ? `glb(${r.modelFiles.length})` : '-glb',
      r.narrationExists ? 'mp3' : '-mp3',
      r.rigScript ? r.rigScript.replace('pipeline/blender/', '') : '-rig',
    ].join(' | ')
    console.log(`${status} ${r.entry.id.padEnd(13)} ${r.entry.name.padEnd(5)} [${r.entry.archetype.padEnd(10)}] ${marks}`)
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2)
  if (args[0] === '--build-plan') {
    const id = args[1]
    if (!id) {
      console.error('用法: tsx pipeline/recipe.ts --build-plan <beast-id>')
      process.exit(2)
    }
    const resolved = resolveBeastRecipe(id)
    console.log(JSON.stringify(resolved.buildPlan, null, 2))
  } else if (args[0] === '--pending') {
    printSummary(BEASTS.filter((b) => !b.ready).map((b) => resolveBeastRecipe(b.id)))
  } else if (args[0] === '--all' || args.length === 0) {
    printSummary(BEASTS.map((b) => resolveBeastRecipe(b.id)))
  } else {
    const resolved = resolveBeastRecipe(args[0])
    console.log(JSON.stringify(resolved, null, 2))
  }
}
