// Verify the actual deployment, including SPA fallbacks that return HTTP 200 for missing models.
// Run after building and deploying: node scripts/check-deployment.mjs https://shanhaiworld.org
import { createHash } from 'node:crypto'
import { readFile, readdir } from 'node:fs/promises'
import { join, relative, resolve } from 'node:path'

const root = resolve('dist')
const base = new URL(process.argv[2] ?? 'https://shanhaiworld.org')
const hash = (data) => createHash('sha256').update(data).digest('hex')

async function modelFiles(dir) {
  const files = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...await modelFiles(path))
    else if (entry.name.endsWith('.glb')) files.push(path)
  }
  return files
}

try {
  for (const file of [join(root, 'index.html'), ...await modelFiles(join(root, 'models'))]) {
    const path = relative(root, file).split('\\').join('/')
    const expected = await readFile(file)
    const url = new URL(path === 'index.html' ? '/' : `/${path}`, base)
    url.searchParams.set('verify', hash(expected).slice(0, 16))
    const response = await fetch(url, { signal: AbortSignal.timeout(30_000), cache: 'no-store' })
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`)
    const actual = Buffer.from(await response.arrayBuffer())
    if (hash(actual) !== hash(expected)) throw new Error(`${path}: deployed bytes do not match dist (possibly a missing asset or stale deployment)`)
    console.log(`✔ deployed ${path} (${actual.length} bytes)`)
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : error)
  process.exitCode = 1
}
