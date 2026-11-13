import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { BEASTS } from '../src/app/beasts.ts'

// Run against Vite: node --import tsx scripts/qa-source-narration.mjs <base> <output> <id>...
const [base = 'http://localhost:5215', output = '/tmp/source-narration-qa', ...ids] = process.argv.slice(2)
assert(ids.length > 0, 'Specify the beasts whose source and narration changed')
const entries = ids.map(id => {
  const entry = BEASTS.find(beast => beast.id === id)
  assert(entry, `Unknown beast: ${id}`)
  return entry
})
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu', '--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(String(error)))
page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`) })
const report = { entries: [], errors, passed: false }
try {
  for (const entry of entries) {
    const content = JSON.parse(await readFile(new URL(`../content/beasts/${entry.id}.json`, import.meta.url), 'utf8'))
    await page.goto(`${base}/?beast=${entry.id}`)
    await page.getByRole('heading', { name: entry.name, exact: true }).waitFor()
    await page.evaluate(() => document.fonts.ready)
    if (entry.id === 'tianwu') {
      const loaded = await page.evaluate(async () => {
        const faces = await document.fonts.load('16px "Shanhai Rare Han"', '𧈫𧔥')
        return faces.length > 0 && faces.every(face => face.status === 'loaded')
      })
      assert(loaded, 'Rare-character font must actually load for Tianwu')
    }
    const sourceText = await page.locator('.card-source').allTextContents()
    assert.equal(sourceText.length, content.source.length, `${entry.id}: source paragraph count`)
    content.source.forEach((source, index) => assert(sourceText[index].includes(source.text), `${entry.id}: actual card quote`))
    await page.getByRole('button', { name: '说书', exact: true }).click()
    await page.locator('.story-caption summary').click()
    assert.equal(await page.locator('.story-caption p').textContent(), entry.story, `${entry.id}: actual caption`)
    const audio = await page.evaluate(async id => {
      const url = performance.getEntriesByType('resource').map(resource => resource.name).find(name => new URL(name).pathname === '/src/systems/audio/AudioEngine.ts')
      if (!url) throw Error('Vite audio module was not loaded')
      const { audio } = await import(url)
      const response = await fetch(`/audio/narration/${id}.mp3`)
      if (!response.ok) throw Error(`Narration HTTP ${response.status}`)
      const bytes = await response.arrayBuffer()
      const sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('')
      const decoded = await audio.context.decodeAudioData(bytes.slice(0))
      const samples = decoded.getChannelData(0)
      let energy = 0
      for (const value of samples) energy += value * value
      const start = performance.now()
      while ((!audio.narrationEl || audio.narrationEl.paused || audio.narrationEl.currentTime <= 0) && performance.now() - start < 5000) await new Promise(resolve => setTimeout(resolve, 50))
      const element = audio.narrationEl
      return { bytes: bytes.byteLength, sha256, seconds: decoded.duration, decodedSampleRate: decoded.sampleRate, contextSampleRate: audio.context.sampleRate, channels: decoded.numberOfChannels, rms: Math.sqrt(energy / samples.length), playing: Boolean(element && !element.paused && element.currentTime > 0) }
    }, entry.id)
    const local = await readFile(new URL(`../public/audio/narration/${entry.id}.mp3`, import.meta.url))
    assert.equal(audio.sha256, createHash('sha256').update(local).digest('hex'), `${entry.id}: served audio bytes`)
    assert(audio.seconds > 5 && audio.rms > .005 && audio.playing, `${entry.id}: decoded, audible, playing`)
    // Web Audio resamples to the output device. Inspect the encoded file
    // separately instead of mistaking its decoded buffer for the MP3 rate.
    assert.equal(audio.decodedSampleRate, audio.contextSampleRate, `${entry.id}: browser output sample rate`)
    const encodedInfo = execFileSync('afinfo', [fileURLToPath(new URL(`../public/audio/narration/${entry.id}.mp3`, import.meta.url))], { encoding: 'utf8' })
    audio.encodedSampleRate = Number(encodedInfo.match(/Data format:\s+\d+ ch,\s+(\d+) Hz/)?.[1])
    assert.equal(audio.encodedSampleRate, 22050, `${entry.id}: encoded sample rate`)
    await page.getByRole('button', { name: '止语', exact: true }).click()
    await page.locator('.story-caption').waitFor({ state: 'detached' })
    const stopped = await page.evaluate(async () => {
      const url = performance.getEntriesByType('resource').map(resource => resource.name).find(name => new URL(name).pathname === '/src/systems/audio/AudioEngine.ts')
      const { audio } = await import(url)
      return !audio.narrationEl || audio.narrationEl.paused
    })
    assert(stopped, `${entry.id}: actual stop`)
    const layouts = []
    for (const width of [390, 800]) {
      await page.setViewportSize({ width, height: 900 })
      const bounds = await page.locator('.story-btn').boundingBox()
      assert(bounds && bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= width && bounds.y + bounds.height <= 900, `${entry.id}: reachable audio button at ${width}`)
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${entry.id}: horizontal overflow at ${width}`)
      layouts.push({ width, button: bounds })
      if (width === 390) await page.screenshot({ path: join(output, `${entry.id}-390.png`) })
    }
    await page.setViewportSize({ width: 1440, height: 900 })
    report.entries.push({ id: entry.id, storySha256: createHash('sha256').update(entry.story).digest('hex'), sourceParagraphs: sourceText.length, audio, stopped, layouts })
  }
  assert.equal(errors.length, 0, errors.join('\n'))
  report.passed = true
} finally {
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n')
  await browser.close()
}
console.log(JSON.stringify({ passed: report.passed, verified: report.entries.length, output }))
