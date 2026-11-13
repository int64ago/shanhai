// Verify an already deployed, exact-commit model release through HTTP and real UI.
// node scripts/verify-model-release.mjs SHA BEAST_ID NEW_OUTPUT_DIR [https://shanhaiworld.org]
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright-core'

const [sha, id, output, base = 'https://shanhaiworld.org'] = process.argv.slice(2)
assert(/^[a-f0-9]{40}$/.test(sha ?? ''), 'Full release commit SHA required')
assert(/^[a-z_]+$/.test(id ?? '') && output, 'Beast ID and unique output directory required')
const root = resolve(import.meta.dirname, '..')
const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8' })
assert.equal(git(['rev-parse', 'HEAD']).trim(), sha, 'Retain the exact checked release build')
await mkdir(output, { recursive: false })
const hash = b => createHash('sha256').update(b).digest('hex')
const report = { sha, id, base, checkedAt: new Date().toISOString(), files: [], actions: [], layouts: [], errors: [], passed: false }
async function verify(path, expected) {
  let bytes
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(new URL(path.replace(/^public\//, '/'), base), { signal: AbortSignal.timeout(120000) })
      assert.equal(response.status, 200, `${path}: HTTP status`)
      bytes = Buffer.from(await response.arrayBuffer())
      break
    } catch (error) {
      if (error.code === 'ERR_ASSERTION' || attempt === 2) throw error
    }
  }
  assert.equal(bytes.length, expected.bytes, `${path}: bytes`)
  assert.equal(hash(bytes), expected.sha256, `${path}: SHA256`)
  report.files.push({ path, ...expected, matched: true })
  return bytes
}
function pointer(path) {
  const text = git(['show', `${sha}:${path}`])
  const sha256 = text.match(/^oid sha256:([a-f0-9]{64})$/m)?.[1]
  const bytes = Number(text.match(/^size (\d+)$/m)?.[1])
  assert(sha256 && bytes, `Expected committed LFS pointer: ${path}`)
  return { sha256, bytes }
}
let browser
try {
  const index = await readFile(join(root, 'dist/index.html'))
  await verify('/', { bytes: index.length, sha256: hash(index) })
  for (const path of new Set([...index.toString().matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)].map(m => m[1]))) {
    const bytes = await readFile(join(root, 'dist', path.slice(1)))
    await verify(path, { bytes: bytes.length, sha256: hash(bytes) })
  }
  for (const path of [`public/models/${id}/body.glb`, `public/audio/narration/${id}.mp3`]) await verify(path, pointer(path))
  const content = JSON.parse(git(['show', `${sha}:content/beasts/${id}.json`]))
  assert.equal(content.production.modelReady, true, 'Committed readiness required')
  browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu', '--autoplay-policy=no-user-gesture-required'] })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', e => report.errors.push(String(e)))
  page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
  await page.addInitScript(() => {
    window.playedNarrations = []
    const play = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = function (...args) { window.playedNarrations.push(this); return play.apply(this, args) }
  })
  const modelResponse = page.waitForResponse(r => new URL(r.url()).pathname === `/models/${id}/body.glb`, { timeout: 120000 })
  const response = await page.goto(`${base}/?beast=${id}&action=idle`)
  assert.equal(response.status(), 200)
  const loadedModel = await modelResponse
  assert.equal(loadedModel.status(), 200)
  assert.equal(await loadedModel.finished(), null)
  await page.getByRole('heading', { name: content.name, exact: true }).waitFor()
  await page.getByRole('toolbar', { name: '动作', exact: true }).waitFor()
  await page.evaluate(() => document.fonts.ready)
  const sources = await page.locator('.card-source').allTextContents()
  assert.equal(sources.length, content.source.length)
  content.source.forEach((source, i) => assert(sources[i].includes(source.text)))
  assert(!(await page.locator('.card-note').allTextContents()).some(t => t.includes('模型待铸')))
  for (const [action, label] of [['idle', '静'], ['walk', '行'], ['special', '神通']]) {
    const button = page.getByRole('button', { name: label, exact: true })
    await button.click()
    await page.waitForFunction(text => [...document.querySelectorAll('.action-btn.is-active')].some(b => b.textContent === text), label)
    await page.waitForTimeout(1300)
    const path = join(output, `${id}-${action}.png`)
    await page.screenshot({ path })
    report.actions.push({ action, selectedThroughUI: true, image: path })
  }
  await page.waitForFunction(() => document.querySelector('.action-btn.is-active')?.textContent === '静', null, { timeout: 20000 })
  report.specialReturnedToIdle = true
  await page.locator('.card .story-btn').click()
  await page.waitForFunction(id => window.playedNarrations.some(e => e.src.includes(`/audio/narration/${id}.mp3`) && !e.paused && e.currentTime > .15), id, { timeout: 120000 })
  await page.locator('.card .story-btn').click()
  assert(await page.evaluate(id => window.playedNarrations.filter(e => e.src.includes(`/audio/narration/${id}.mp3`)).every(e => e.paused), id))
  report.narrationPlayedAndStopped = true
  for (const width of [390, 800]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(800)
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    const controls = await page.locator('.action-btn').all()
    for (const button of controls) {
      const b = await button.boundingBox()
      assert(b && b.x >= 0 && b.y >= 0 && b.x + b.width <= width && b.y + b.height <= 900, 'Reachable action control')
    }
    const path = join(output, `${id}-${width}.png`)
    await page.screenshot({ path }); report.layouts.push({ width, image: path })
  }
  assert.equal(report.errors.length, 0, report.errors.join('\n'))
  report.passed = true
} finally {
  if (browser) await browser.close()
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n')
}
console.log(JSON.stringify({ passed: report.passed, sha, id, files: report.files.length, output }))
