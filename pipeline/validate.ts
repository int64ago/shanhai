/**
 * 仓库与构建前校验脚本（CI 与本地通用）：
 * 1. 检查 public/models/ 下的 .glb 是否为真实的二进制 GLB（防止 CI 漏拉 Git LFS 只拿到指针文本）
 * 2. 检查 src/app/beasts.ts 中标记 ready: true 的神兽是否具备完整的设定 JSON 与运行时模型
 * 3. 检查单只神兽的模型总大小是否 ≤ 15MB
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BEASTS } from '../src/app/beasts.ts'

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

function main() {
  checkGlbFile(join(ROOT, 'public/models/_placeholder/fox.glb'))

  const seen = new Set<string>()
  for (const beast of BEASTS) {
    if (seen.has(beast.id)) throw new Error(`重复的神兽 id: ${beast.id}`)
    seen.add(beast.id)
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

  const readyBeasts = BEASTS.filter((b) => b.ready)
  for (const beast of readyBeasts) {
    const contentPath = join(ROOT, 'content/beasts', `${beast.id}.json`)
    if (!existsSync(contentPath)) {
      throw new Error(`[${beast.id}] ready=true 但缺少设定文件: ${contentPath}`)
    }
    const meta = JSON.parse(readFileSync(contentPath, 'utf8')) as {
      id: string
      archetype?: string
      source?: unknown[]
      inferred?: unknown[]
    }
    if (meta.id !== beast.id) throw new Error(`[${beast.id}] 设定文件 id 不匹配: ${meta.id}`)
    if (!meta.archetype || !VALID_ARCHETYPES.has(meta.archetype)) {
      throw new Error(`[${beast.id}] 设定文件缺少合法的 archetype: ${String(meta.archetype)}`)
    }
    if (!Array.isArray(meta.source) || meta.source.length === 0) {
      throw new Error(`[${beast.id}] 设定文件缺少原文 source`)
    }
    if (!Array.isArray(meta.inferred) || meta.inferred.length === 0) {
      throw new Error(`[${beast.id}] 设定文件缺少设计推断 inferred`)
    }

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
