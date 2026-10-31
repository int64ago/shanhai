/**
 * Hyper3D Rodin Gen-2.5 生成脚本：提交 → 轮询 → 下载，带缓存、积分日志、单兽积分上限。
 *
 * 用法：
 *   pnpm rodin pipeline/rodin/jobs/<job>.json [--dry-run] [--force]
 *   pnpm rodin:balance
 *
 * 接口依据 https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5（2026-10-31 核实）
 */
import { createHash } from 'node:crypto'
import { appendFile, copyFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const API = 'https://api.hyper3d.com/api/v2'
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const CACHE_DIR = join(ROOT, 'pipeline/rodin/cache')
const RAW_DIR = join(ROOT, 'raw')
const CREDITS_LOG = join(ROOT, 'pipeline/rodin/credits.log')
const DEFAULT_BEAST_BUDGET = 20

const POLL_INITIAL_MS = 5_000
const POLL_MAX_MS = 30_000
const POLL_DEADLINE_MS = 60 * 60_000

interface Job {
  /** 产物目录名，如 jiuweihu-tail-preview */
  id: string
  /** 所属神兽，用于按兽统计积分 */
  beast: string
  /** 单兽积分上限，缺省用 DEFAULT_BEAST_BUDGET */
  budget?: number
  tier: string
  prompt?: string
  /** 相对仓库根目录的图片路径，1–5 张，第一张决定材质 */
  images?: string[]
  /** 其余表单字段原样提交，如 mesh_mode / quality / material / geometry_file_format / seed */
  params?: Record<string, string | number | boolean>
}

interface CacheMeta {
  job: Job
  hash: string
  uuid?: string
  subscriptionKey?: string
  consumed?: number
  status: 'submitted' | 'done' | 'failed'
  files?: string[]
}

interface CreditEntry {
  time: string
  beast: string
  job: string
  hash: string
  tier: string
  uuid: string
  consumed: number
}

function apiKey(): string {
  const envFile = join(ROOT, '.env.local')
  if (!process.env.HYPER3D_API_KEY && existsSync(envFile)) process.loadEnvFile(envFile)
  const key = process.env.HYPER3D_API_KEY
  if (!key) throw new Error('缺少 HYPER3D_API_KEY，请在 .env.local 中配置')
  return key
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function retryAfterMs(res: Response): number {
  const value = res.headers.get('retry-after')
  if (!value) return POLL_INITIAL_MS
  const seconds = Number(value)
  if (Number.isFinite(seconds)) return seconds * 1000
  const date = Date.parse(value)
  return Number.isNaN(date) ? POLL_INITIAL_MS : Math.max(0, date - Date.now())
}

/** 带 429 重试的请求，返回解析后的 JSON */
async function request<T>(path: string, init: RequestInit): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(`${API}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${apiKey()}`, ...init.headers },
    })
    if (res.status === 429 && attempt < 10) {
      const wait = retryAfterMs(res)
      console.warn(`  429 限流，${Math.round(wait / 1000)}s 后重试`)
      await sleep(wait)
      continue
    }
    const text = await res.text()
    if (!res.ok) throw new Error(`${path} HTTP ${res.status}: ${text}`)
    const body = JSON.parse(text) as T & { error?: string | null }
    if (body.error) throw new Error(`${path} 返回错误: ${body.error}`)
    return body
  }
}

const postJson = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

/** 按文档的计费规则估算积分（只用于预算检查，实际以返回的 consumed 为准） */
function estimateCredits(job: Job): number {
  let credits = 0.5
  if (job.tier === 'Gen-2.5-Extreme-High') credits += 0.5
  if (job.params?.texture_mode === 'extreme-high') credits += 2
  return credits
}

async function jobHash(job: Job): Promise<string> {
  const h = createHash('sha256')
  h.update(JSON.stringify({ tier: job.tier, prompt: job.prompt ?? '', params: job.params ?? {} }))
  for (const image of job.images ?? []) h.update(await readFile(join(ROOT, image)))
  return h.digest('hex').slice(0, 16)
}

async function readCredits(): Promise<CreditEntry[]> {
  if (!existsSync(CREDITS_LOG)) return []
  const text = await readFile(CREDITS_LOG, 'utf8')
  return text
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line) as CreditEntry)
}

async function buildForm(job: Job): Promise<FormData> {
  const form = new FormData()
  form.append('tier', job.tier)
  if (job.prompt) form.append('prompt', job.prompt)
  for (const image of job.images ?? []) {
    const data = await readFile(join(ROOT, image))
    form.append('images', new Blob([data]), basename(image))
  }
  for (const [key, value] of Object.entries(job.params ?? {})) form.append(key, String(value))
  return form
}

async function saveMeta(dir: string, meta: CacheMeta) {
  await writeFile(join(dir, 'meta.json'), JSON.stringify(meta, null, 2) + '\n')
}

async function submit(job: Job, hash: string, dir: string): Promise<CacheMeta> {
  const res = await request<{
    uuid?: string
    consumed?: number
    jobs?: { uuids?: string[]; subscription_key?: string }
  }>('/rodin', { method: 'POST', body: await buildForm(job) })

  if (!res.uuid || !res.jobs?.subscription_key) {
    throw new Error(`提交返回缺少 uuid / subscription_key: ${JSON.stringify(res)}`)
  }
  // 提交成功后才建缓存目录，失败的请求不留空目录
  await mkdir(dir, { recursive: true })
  const meta: CacheMeta = {
    job,
    hash,
    uuid: res.uuid,
    subscriptionKey: res.jobs.subscription_key,
    consumed: res.consumed,
    status: 'submitted',
  }
  await saveMeta(dir, meta)

  const entry: CreditEntry = {
    time: new Date().toISOString(),
    beast: job.beast,
    job: job.id,
    hash,
    tier: job.tier,
    uuid: res.uuid,
    consumed: res.consumed ?? estimateCredits(job),
  }
  await appendFile(CREDITS_LOG, JSON.stringify(entry) + '\n')
  console.log(`  已提交 uuid=${res.uuid}，消耗 ${entry.consumed} 积分`)
  return meta
}

async function poll(subscriptionKey: string): Promise<void> {
  const deadline = Date.now() + POLL_DEADLINE_MS
  let delay = POLL_INITIAL_MS
  let last = ''
  while (Date.now() < deadline) {
    await sleep(delay)
    const { jobs } = await postJson<{ jobs: { uuid: string; status: string }[] }>('/status', {
      subscription_key: subscriptionKey,
    })
    const summary = jobs.map((j) => j.status).join(', ')
    if (summary !== last) console.log(`  状态: ${summary}`)
    last = summary
    if (jobs.some((j) => j.status === 'Failed')) throw new Error('生成失败')
    if (jobs.length > 0 && jobs.every((j) => j.status === 'Done')) return
    delay = Math.min(delay * 1.5, POLL_MAX_MS)
  }
  throw new Error('轮询超时（60 分钟），重跑同一任务会从缓存继续轮询')
}

async function download(taskUuid: string, dir: string): Promise<string[]> {
  const { list } = await postJson<{ list: { name: string; url: string }[] }>('/download', {
    task_uuid: taskUuid,
  })
  const files: string[] = []
  for (const item of list) {
    const name = basename(item.name)
    const res = await fetch(item.url)
    if (!res.ok) throw new Error(`下载 ${name} 失败: HTTP ${res.status}`)
    await writeFile(join(dir, name), Buffer.from(await res.arrayBuffer()))
    files.push(name)
    console.log(`  下载 ${name}`)
  }
  return files
}

async function run(jobPath: string, opts: { dryRun: boolean; force: boolean }) {
  const job = JSON.parse(await readFile(resolve(jobPath), 'utf8')) as Job
  const hash = await jobHash(job)
  const dir = join(CACHE_DIR, hash)
  const metaPath = join(dir, 'meta.json')
  console.log(`[${job.id}] hash=${hash}`)

  let meta: CacheMeta | undefined = existsSync(metaPath)
    ? (JSON.parse(await readFile(metaPath, 'utf8')) as CacheMeta)
    : undefined

  if (meta?.status === 'failed' && !opts.force) {
    throw new Error('该参数组合上次生成失败；确认要重新提交请加 --force')
  }

  if (!meta || (meta.status === 'failed' && opts.force)) {
    const spent = (await readCredits())
      .filter((e) => e.beast === job.beast)
      .reduce((sum, e) => sum + e.consumed, 0)
    const cost = estimateCredits(job)
    const budget = job.budget ?? DEFAULT_BEAST_BUDGET
    console.log(`  [${job.beast}] 已用 ${spent} / 上限 ${budget}，本次预计 ${cost}`)
    if (spent + cost > budget) throw new Error(`超出 ${job.beast} 的积分上限，已暂停`)

    if (opts.dryRun) {
      const form = await buildForm(job)
      console.log('  dry-run，表单字段:')
      for (const [key, value] of form.entries()) {
        console.log(`    ${key} = ${typeof value === 'string' ? value : `<file ${value.name}>`}`)
      }
      return
    }
    meta = await submit(job, hash, dir)
  } else {
    console.log(`  命中缓存（${meta.status}），不重复提交`)
  }

  if (meta.status === 'submitted') {
    try {
      await poll(meta.subscriptionKey!)
      meta.files = await download(meta.uuid!, dir)
      meta.status = 'done'
    } catch (err) {
      if (err instanceof Error && err.message === '生成失败') meta.status = 'failed'
      await saveMeta(dir, meta)
      throw err
    }
    await saveMeta(dir, meta)
  }

  const outDir = join(RAW_DIR, job.id)
  await mkdir(outDir, { recursive: true })
  for (const name of meta.files ?? (await readdir(dir)).filter((f) => f !== 'meta.json')) {
    await copyFile(join(dir, name), join(outDir, name))
  }
  console.log(`  完成 → ${outDir}`)
}

async function balance() {
  const res = await request<{ balance: number }>('/check_balance', { method: 'GET' })
  console.log(`剩余积分: ${res.balance}`)
}

async function main() {
  const args = process.argv.slice(2)
  if (args.includes('--balance')) return balance()
  const jobPath = args.find((a) => !a.startsWith('--'))
  if (!jobPath) {
    console.error('用法: pnpm rodin <job.json> [--dry-run] [--force] | pnpm rodin:balance')
    process.exit(1)
  }
  await run(jobPath, { dryRun: args.includes('--dry-run'), force: args.includes('--force') })
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : err)
  process.exit(1)
})
