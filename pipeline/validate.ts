/**
 * 仓库与构建前统一校验脚本（CI 与本地通用）：
 * 1. 检查 public/models/ 下的 .glb 与 public/audio/narration/ 下的 .mp3 是否为真实二进制（防 Git LFS 指针未拉取）
 * 2. 校验统一神兽登记一致性：src/app/beasts.ts ↔ content/beasts/<id>.json ↔ src/beasts/<id>/<Name>.tsx
 * 3. 校验 content/beasts/*.json 制作配方引用（parts[].job、recipe.prepareScript/rigScript/qaScript）
 * 4. 检查单只神兽模型总大小 ≤ 15 MB
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BEASTS } from '../src/app/beasts.ts'
import { toBeastComponentName, type BeastContentSpec } from '../src/app/beastSpec.ts'
import { resolveCompressionArgs } from './compression.ts'

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)))
const MAX_BEAST_BYTES = 15 * 1024 * 1024
const VALID_ARCHETYPES = new Set(['sac', 'avian', 'serpentine', 'quadruped', 'biped'])

function checkGlbFile(path: string): number {
  if (!existsSync(path)) throw new Error(`缺少模型文件: ${path}`)
  const size = statSync(path).size
  const head = readFileSync(path).subarray(0, 16)
  const magic = head.toString('ascii', 0, 4)
  if (magic === 'vers') {
    throw new Error(`文件是未拉取的 Git LFS 指针，请先运行 git lfs pull: ${path}`)
  }
  if (magic !== 'glTF') {
    throw new Error(`文件不是合法的二进制 GLB (magic=${JSON.stringify(magic)}): ${path}`)
  }
  return size
}

function resolveRecipePath(path: string, kind: 'blender' | 'repo'): string {
  if (kind === 'blender' && !path.startsWith('pipeline/')) {
    return join(ROOT, 'pipeline/blender', path)
  }
  return join(ROOT, path)
}

function validateContentSpec(id: string, expectedName: string, expectedArchetype: string, contentPath: string) {
  const meta = JSON.parse(readFileSync(contentPath, 'utf8')) as Partial<BeastContentSpec>
  if (meta.id !== id) throw new Error(`[${id}] 设定文件 id 不匹配: ${String(meta.id)}`)
  if (meta.name !== expectedName) throw new Error(`[${id}] 设定文件 name 不匹配: ${String(meta.name)} !== ${expectedName}`)
  if (!meta.archetype || !VALID_ARCHETYPES.has(meta.archetype)) {
    throw new Error(`[${id}] 设定文件缺少合法的 archetype: ${String(meta.archetype)}`)
  }
  if (meta.archetype !== expectedArchetype) {
    throw new Error(`[${id}] 设定文件 archetype (${meta.archetype}) 与 beasts.ts (${expectedArchetype}) 不一致`)
  }
  if (!Array.isArray(meta.source) || meta.source.length === 0) {
    throw new Error(`[${id}] 设定文件缺少原文 source`)
  }
  if (!Array.isArray(meta.inferred) || meta.inferred.length === 0) {
    throw new Error(`[${id}] 设定文件缺少设计推断 inferred`)
  }
  if (meta.parts) {
    for (const part of meta.parts) {
      if (!part.id) throw new Error(`[${id}] parts 条目缺少 id`)
      if (part.job && !existsSync(join(ROOT, part.job))) {
        throw new Error(`[${id}] parts[${part.id}] 引用的 Rodin 任务不存在: ${part.job}`)
      }
    }
  }
  if (meta.recipe) {
    resolveCompressionArgs(meta.recipe.compression)
    if (meta.recipe.prepareArgs !== undefined) {
      if (!meta.recipe.prepareScript) throw new Error(`[${id}] recipe.prepareArgs 需要显式 prepareScript`)
      if (!Array.isArray(meta.recipe.prepareArgs) || meta.recipe.prepareArgs.some(arg => typeof arg !== 'string' || arg.includes('\0'))) {
        throw new Error(`[${id}] recipe.prepareArgs 必须为无 NUL 的字符串数组`)
      }
      const placeholders = new Set(['body.raw', 'body.out', 'body.length', 'outDir'])
      for (const part of meta.parts ?? []) {
        for (const field of ['raw', 'out', 'length']) placeholders.add(`${part.id}.${field}`)
      }
      for (const arg of meta.recipe.prepareArgs) {
        for (const match of arg.matchAll(/\{([^{}]+)\}/g)) {
          if (!placeholders.has(match[1])) throw new Error(`[${id}] 未知预处理占位符: {${match[1]}}`)
        }
      }
    }
    if (meta.recipe.prepareScript && !existsSync(resolveRecipePath(meta.recipe.prepareScript, 'blender'))) {
      throw new Error(`[${id}] recipe.prepareScript 不存在: ${meta.recipe.prepareScript}`)
    }
    if (meta.recipe.rigScript && !existsSync(resolveRecipePath(meta.recipe.rigScript, 'blender'))) {
      throw new Error(`[${id}] recipe.rigScript 不存在: ${meta.recipe.rigScript}`)
    }
    if (meta.recipe.qaScript && !existsSync(resolveRecipePath(meta.recipe.qaScript, 'repo'))) {
      throw new Error(`[${id}] recipe.qaScript 不存在: ${meta.recipe.qaScript}`)
    }
  }
  return meta as BeastContentSpec
}

function main() {
  checkGlbFile(join(ROOT, 'public/models/_placeholder/fox.glb'))

  const beastById = new Map<string, (typeof BEASTS)[number]>()
  for (const beast of BEASTS) {
    if (beastById.has(beast.id)) throw new Error(`重复的神兽 id: ${beast.id}`)
    beastById.set(beast.id, beast)
    if (!VALID_ARCHETYPES.has(beast.archetype)) {
      throw new Error(`[${beast.id}] 非法 archetype: ${beast.archetype}`)
    }
    if (!beast.quote || !beast.anatomy || !beast.story) {
      throw new Error(`[${beast.id}] 缺少 quote / anatomy / story 考据字段`)
    }
    const mp3Path = join(ROOT, 'public/audio/narration', `${beast.id}.mp3`)
    if (!existsSync(mp3Path)) {
      throw new Error(`[${beast.id}] 缺少评书人语音文件: ${mp3Path}（请运行 pnpm tts ${beast.id}）`)
    }
    const mp3Head = readFileSync(mp3Path).subarray(0, 16).toString('ascii', 0, 4)
    if (mp3Head === 'vers') {
      throw new Error(`语音文件是未拉取的 Git LFS 指针: ${mp3Path}`)
    }
  }
  console.log(`✔ 全卷图鉴校验通过: ${BEASTS.length} 尊神兽考据、造型参考与评书语音齐全`)

  // 检查 src/beasts/<id>/ 与 content/beasts/<id>.json 没有孤儿文件
  for (const entry of readdirSync(join(ROOT, 'src/beasts'), { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const beast = beastById.get(entry.name)
    if (!beast) throw new Error(`存在未在 beasts.ts 登记的组件目录: src/beasts/${entry.name}`)
    if (!beast.ready) {
      throw new Error(`[${beast.id}] 已有组件目录 src/beasts/${entry.name}，但 beasts.ts 中 ready 仍为 false`)
    }
  }

  for (const file of readdirSync(join(ROOT, 'content/beasts'))) {
    if (!file.endsWith('.json')) continue
    const id = file.replace(/\.json$/, '')
    const beast = beastById.get(id)
    if (!beast) throw new Error(`存在未在 beasts.ts 登记的设定文件: content/beasts/${file}`)
    validateContentSpec(id, beast.name, beast.archetype, join(ROOT, 'content/beasts', file))
  }

  const readyBeasts = BEASTS.filter((b) => b.ready)
  for (const beast of readyBeasts) {
    const componentRel = `src/beasts/${beast.id}/${toBeastComponentName(beast.id)}.tsx`
    if (!existsSync(join(ROOT, componentRel))) {
      throw new Error(`[${beast.id}] ready=true 但缺少运行时组件: ${componentRel}`)
    }

    const contentPath = join(ROOT, 'content/beasts', `${beast.id}.json`)
    if (!existsSync(contentPath)) {
      throw new Error(`[${beast.id}] ready=true 但缺少设定文件: ${contentPath}`)
    }
    const meta = validateContentSpec(beast.id, beast.name, beast.archetype, contentPath)

    const modelDir = join(ROOT, 'public/models', beast.id)
    if (!existsSync(modelDir)) throw new Error(`[${beast.id}] 缺少模型目录: ${modelDir}`)
    const glbs = readdirSync(modelDir).filter((f) => f.endsWith('.glb'))
    if (!glbs.includes('body.glb')) throw new Error(`[${beast.id}] 缺少主模型 body.glb`)

    let totalBytes = 0
    for (const f of glbs) totalBytes += checkGlbFile(join(modelDir, f))
    const mb = (totalBytes / (1024 * 1024)).toFixed(2)
    if (totalBytes > MAX_BEAST_BYTES) {
      throw new Error(`[${beast.id}] 模型总体积超标: ${mb} MB > 15 MB`)
    }
    console.log(`✔ ${beast.id} (${beast.name}, archetype=${meta.archetype}): ${glbs.length} GLBs, ${mb} MB`)
  }
}

main()
