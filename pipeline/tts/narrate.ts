/**
 * 阿里云百炼 CosyVoice v2 评书人（龙三叔 longsanshu）语音解说生成脚本
 *
 * 用法：
 *   pnpm tts                      # 为已上线 + 核心代表神兽生成语音（已存在则跳过）
 *   pnpm tts <beast-id> [...]     # 为指定神兽生成语音
 *   pnpm tts --all                # 为《山海经》全图鉴 56 尊神兽批量生成语音
 *   pnpm tts --force <beast-id>   # 强制重新生成
 */
import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BEASTS, type BeastEntry } from '../../src/app/beasts.ts'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const OUT_DIR = join(ROOT, 'public/audio/narration')
const WS_URL = 'wss://dashscope.aliyuncs.com/api-ws/v1/inference/'

// 龙三叔：百炼 CosyVoice v2 官方经典古风评书/说书人音色
const MODEL = 'cosyvoice-v2'
const VOICE = 'longsanshu'

function getApiKey(): string {
  const envFile = join(ROOT, '.env.local')
  if (!process.env.DASHSCOPE_API_KEY && existsSync(envFile)) {
    process.loadEnvFile(envFile)
  }
  const key = process.env.DASHSCOPE_API_KEY
  if (!key) throw new Error('缺少 DASHSCOPE_API_KEY，请在 .env.local 中配置百炼 API Key')
  return key
}

export async function synthesizeStory(text: string, apiKey = getApiKey()): Promise<Buffer> {
  return new Promise<Buffer>((resolveBuf, reject) => {
    const ws = new WebSocket(WS_URL, {
      headers: { Authorization: `Bearer ${apiKey}` },
    } as unknown as string[])
    const taskId = randomUUID().replace(/-/g, '')
    const chunks: Buffer[] = []

    const timer = setTimeout(() => {
      ws.close()
      reject(new Error('CosyVoice WebSocket 合成超时 (45s)'))
    }, 45_000)

    ws.addEventListener('open', () => {
      ws.send(
        JSON.stringify({
          header: { action: 'run-task', task_id: taskId, streaming: 'duplex' },
          payload: {
            task_group: 'audio',
            task: 'tts',
            function: 'SpeechSynthesizer',
            model: MODEL,
            parameters: {
              text_type: 'PlainText',
              voice: VOICE,
              format: 'mp3',
              sample_rate: 22050,
              volume: 65,
              rate: 0.94,
              pitch: 0.96,
            },
            input: {},
          },
        }),
      )
    })

    ws.addEventListener('message', async (ev) => {
      if (typeof ev.data === 'string') {
        const msg = JSON.parse(ev.data) as {
          header: { event: string; error_message?: string }
        }
        if (msg.header.event === 'task-started') {
          ws.send(
            JSON.stringify({
              header: { action: 'continue-task', task_id: taskId, streaming: 'duplex' },
              payload: { input: { text } },
            }),
          )
          ws.send(
            JSON.stringify({
              header: { action: 'finish-task', task_id: taskId, streaming: 'duplex' },
              payload: { input: {} },
            }),
          )
        } else if (msg.header.event === 'task-finished') {
          clearTimeout(timer)
          ws.close()
          resolveBuf(Buffer.concat(chunks))
        } else if (msg.header.event === 'task-failed') {
          clearTimeout(timer)
          ws.close()
          reject(new Error(`CosyVoice 合成失败: ${msg.header.error_message || '未知错误'}`))
        }
      } else if (ev.data instanceof Blob) {
        chunks.push(Buffer.from(await ev.data.arrayBuffer()))
      } else if (ev.data instanceof ArrayBuffer) {
        chunks.push(Buffer.from(ev.data))
      }
    })

    ws.addEventListener('error', (err) => {
      clearTimeout(timer)
      reject(new Error(`WebSocket 连接错误: ${String(err)}`))
    })
  })
}

async function generateOne(beast: BeastEntry, force: boolean) {
  await mkdir(OUT_DIR, { recursive: true })
  const outPath = join(OUT_DIR, `${beast.id}.mp3`)
  if (!force && existsSync(outPath)) {
    console.log(`[skip] ${beast.id} (${beast.name}) 已存在`)
    return
  }
  const buf = await synthesizeStory(beast.story)
  await writeFile(outPath, buf)
  console.log(`[done] ${beast.id} (${beast.name}) -> ${(buf.byteLength / 1024).toFixed(1)} KB`)
}

async function main() {
  const args = process.argv.slice(2)
  const force = args.includes('--force')
  const all = args.includes('--all')
  const ids = args.filter((a) => !a.startsWith('--'))

  let targets: BeastEntry[]
  if (all) {
    targets = BEASTS
  } else if (ids.length > 0) {
    targets = BEASTS.filter((b) => ids.includes(b.id))
  } else {
    // 默认生成已上线及首批核心十神兽
    const core = new Set([
      'jiuweihu',
      'dijiang',
      'bo',
      'luwu',
      'bifang',
      'qiongqi',
      'taotie',
      'kaiming',
      'fenghuang',
      'yinglong',
      'zhulong',
      'xingtian',
    ])
    targets = BEASTS.filter((b) => b.ready || core.has(b.id))
  }

  console.log(`准备用百炼 CosyVoice (${MODEL} / ${VOICE}) 生成 ${targets.length} 尊神兽的说书人解说...`)
  const concurrency = 3
  for (let i = 0; i < targets.length; i += concurrency) {
    const batch = targets.slice(i, i + concurrency)
    await Promise.all(batch.map((b) => generateOne(b, force)))
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error(err)
    process.exit(1)
  })
}
