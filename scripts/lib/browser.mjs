import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { inflateSync } from 'node:zlib'
import { chromium } from 'playwright-core'

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      const port = typeof addr === 'object' && addr ? addr.port : 0
      server.close((err) => (err ? reject(err) : resolve(port)))
    })
  })
}

/**
 * Launch Playwright Chromium in a cross-platform WebGL-ready mode.
 * Uses Playwright's bundled Chromium + SwiftShader ANGLE by default so Linux CI
 * and macOS run identically; honors PW_CHANNEL=chrome for local native GPU runs.
 */
export async function launchQABrowser() {
  const channel = process.env.PW_CHANNEL || undefined
  const useMetal = channel === 'chrome' && process.platform === 'darwin'
  const args = useMetal
    ? ['--use-angle=metal', '--enable-gpu', '--autoplay-policy=no-user-gesture-required', '--hide-scrollbars']
    : [
        '--use-gl=angle',
        '--use-angle=swiftshader',
        '--enable-webgl',
        '--ignore-gpu-blocklist',
        '--autoplay-policy=no-user-gesture-required',
        '--hide-scrollbars',
        ...(process.platform === 'linux' ? ['--no-sandbox', '--disable-dev-shm-usage'] : []),
      ]

  return chromium.launch({
    ...(channel ? { channel } : {}),
    args,
  })
}

/**
 * Run `fn(baseUrl)` against an existing URL (if `explicitUrl` is provided)
 * or an ephemeral Vite `preview` / `dev` server bound to 127.0.0.1.
 */
export async function withViteServer(mode, explicitUrl, fn) {
  if (explicitUrl) {
    return await fn(explicitUrl.replace(/\/$/, ''))
  }

  const port = await getFreePort()
  const baseUrl = `http://127.0.0.1:${port}`
  const viteArgs =
    mode === 'preview'
      ? ['exec', 'vite', 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort']
      : ['exec', 'vite', '--host', '127.0.0.1', '--port', String(port), '--strictPort']

  const proc = spawn('pnpm', viteArgs, { stdio: ['ignore', 'pipe', 'pipe'] })
  let logs = ''
  proc.stdout.on('data', (chunk) => {
    logs += chunk.toString()
  })
  proc.stderr.on('data', (chunk) => {
    logs += chunk.toString()
  })

  try {
    const deadline = Date.now() + 30_000
    let ready = false
    while (Date.now() < deadline) {
      if (proc.exitCode !== null) {
        throw new Error(`Vite (${mode}) exited prematurely with code ${proc.exitCode}:\n${logs}`)
      }
      try {
        const res = await fetch(`${baseUrl}/`)
        if (res.ok) {
          ready = true
          break
        }
      } catch {
        // waiting for server
      }
      await new Promise((r) => setTimeout(r, 200))
    }
    if (!ready) {
      throw new Error(`Timed out waiting for Vite (${mode}) at ${baseUrl}:\n${logs}`)
    }
    return await fn(baseUrl)
  } finally {
    if (proc.exitCode === null) {
      proc.kill('SIGTERM')
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          if (proc.exitCode === null) proc.kill('SIGKILL')
          resolve()
        }, 3000)
        proc.once('exit', () => {
          clearTimeout(timer)
          resolve()
        })
      })
    }
  }
}

/**
 * Decode an 8-bit RGBA/RGB PNG screenshot buffer and measure color spread
 * to confirm WebGL actually rendered visible variation (not a blank frame).
 */
export function measurePngSpread(pngBuffer) {
  let offset = 8
  let width = 0
  let height = 0
  let colorType = 6
  const idatChunks = []

  while (offset + 8 <= pngBuffer.length) {
    const length = pngBuffer.readUInt32BE(offset)
    const type = pngBuffer.toString('ascii', offset + 4, offset + 8)
    const dataStart = offset + 8
    const dataEnd = dataStart + length
    if (type === 'IHDR') {
      width = pngBuffer.readUInt32BE(dataStart)
      height = pngBuffer.readUInt32BE(dataStart + 4)
      colorType = pngBuffer[dataStart + 9]
    } else if (type === 'IDAT') {
      idatChunks.push(pngBuffer.subarray(dataStart, dataEnd))
    } else if (type === 'IEND') {
      break
    }
    offset = dataEnd + 4
  }

  const bpp = colorType === 6 ? 4 : colorType === 2 ? 3 : 0
  if (!width || !height || !bpp || idatChunks.length === 0) {
    throw new Error(`Unsupported PNG format (width=${width}, height=${height}, colorType=${colorType})`)
  }

  const raw = inflateSync(Buffer.concat(idatChunks))
  const stride = width * bpp
  const prev = new Uint8Array(stride)
  const curr = new Uint8Array(stride)
  let minLum = 255
  let maxLum = 0
  let cursor = 0

  const paeth = (a, b, c) => {
    const p = a + b - c
    const pa = Math.abs(p - a)
    const pb = Math.abs(p - b)
    const pc = Math.abs(p - c)
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c
  }

  for (let y = 0; y < height; y++) {
    const filter = raw[cursor++]
    for (let x = 0; x < stride; x++) {
      const val = raw[cursor++]
      const a = x >= bpp ? curr[x - bpp] : 0
      const b = prev[x]
      const c = x >= bpp ? prev[x - bpp] : 0
      if (filter === 0) curr[x] = val
      else if (filter === 1) curr[x] = (val + a) & 0xff
      else if (filter === 2) curr[x] = (val + b) & 0xff
      else if (filter === 3) curr[x] = (val + ((a + b) >> 1)) & 0xff
      else if (filter === 4) curr[x] = (val + paeth(a, b, c)) & 0xff
      else throw new Error(`Unsupported PNG filter ${filter}`)
    }
    if (y % 4 === 0) {
      for (let px = 0; px < width; px += 4) {
        const i = px * bpp
        const lum = 0.299 * curr[i] + 0.587 * curr[i + 1] + 0.114 * curr[i + 2]
        if (lum < minLum) minLum = lum
        if (lum > maxLum) maxLum = lum
      }
    }
    prev.set(curr)
  }

  return { width, height, minLum: Math.round(minLum), maxLum: Math.round(maxLum), spread: Math.round(maxLum - minLum) }
}
