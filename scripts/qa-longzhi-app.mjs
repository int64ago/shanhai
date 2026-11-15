// Actual Stage candidate QA. Does not alter the catalog's acceptance flag.
// node scripts/qa-longzhi-app.mjs BASE NEW_EVIDENCE_DIR CANDIDATE.glb
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'
const [base, outArg, candidateArg] = process.argv.slice(2)
assert(base && outArg && candidateArg)
const out = resolve(outArg), candidate = resolve(candidateArg), bytes = await readFile(candidate)
assert(bytes.length < 15 * 1024 * 1024)
await mkdir(out, { recursive: false })
const report = { candidate, sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length, errors: [], passed: false, images: [], sections: {} }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route('**/models/longzhi/body.glb*', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
await page.addInitScript(() => {
  window.longzhiNarrations = []
  const play = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function (...args) { window.longzhiNarrations.push(this); return play.apply(this, args) }
})
const shot = async name => { const path = join(out, `${name}.png`); await page.screenshot({ path }); report.images.push(path) }
const ready = () => page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready longzhi'), timeout: 60000 })
try {
  const pending = ready(); await page.goto(`${base}/?beast=longzhi&action=idle`); await pending
  await page.waitForTimeout(800)
  report.setup = await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const module = suffix => { const url = resources.find(u => new URL(u).pathname.endsWith(suffix)); if (!url) throw Error(`Missing ${suffix}`); return url }
    const fiber = await import(module('/@react-three_fiber.js')), { useGLTF } = await import(module('/@react-three_drei.js')), { useApp } = await import(module('/src/app/store.ts')), T = await import(module('/three.js'))
    const { BEASTS } = await import(module('/src/app/beasts.ts'))
    const entry = BEASTS.find(beast => beast.id === 'longzhi'), catalogReady = entry.ready
    entry.ready = true // Browser-local candidate controls; never changes source acceptance.
    const body = useGLTF('/models/longzhi/body.glb'), q = window.longzhiQA = { T, useApp, body, state: [...fiber._roots.values()][0].store.getState(), sharedDisposals: 0 }
    q.catalogReady = catalogReady
    q.root = () => { const root = q.state.scene.getObjectByName('longzhi_root'); if (!root) throw Error('Missing longzhi root'); return root }
    q.sourceSnapshot = () => { const nodes = []; body.scene.traverse(n => nodes.push([n.uuid, n.children.map(c => c.uuid), n.position.toArray(), n.quaternion.toArray(), n.scale.toArray(), n.skeleton?.uuid, (Array.isArray(n.material) ? n.material : n.material ? [n.material] : []).map(m => m.uuid)])); return JSON.stringify(nodes) }
    q.before = q.sourceSnapshot()
    const shared = new Set()
    body.scene.traverse(n => { if (n.geometry) shared.add(n.geometry); for (const m of Array.isArray(n.material) ? n.material : n.material ? [n.material] : []) { shared.add(m); for (const v of Object.values(m)) if (v?.isTexture) shared.add(v) } })
    for (const resource of shared) resource.addEventListener('dispose', () => q.sharedDisposals++)
    q.snapshot = () => {
      const root = q.root(), p = new T.Vector3(), low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity], screenLow = [Infinity, Infinity], screenHigh = [-Infinity, -Infinity]
      let meshes = 0, outlines = 0, bones = 0, invalid = 0, triangles = 0, maxWeightError = 0, ink = 0
      root.updateMatrixWorld(true)
      root.traverse(n => {
        if (![...n.matrixWorld.elements].every(Number.isFinite)) invalid++
        if (n.isBone) bones++
        if (n.userData.inkOutline) { outlines++; return }
        if (!n.isMesh) return
        meshes++; if (n.material.isShaderMaterial) ink++
        if (!n.isSkinnedMesh) throw Error('Continuous skin must remain skinned')
        const a = n.geometry.attributes
        for (const key of ['position', 'normal', 'skinWeight', 'skinIndex']) if (!a[key] || !Array.from(a[key].array).every(Number.isFinite)) invalid++
        triangles += (n.geometry.index?.count ?? a.position.count) / 3
        n.skeleton.update()
        for (let i = 0; i < a.position.count; i += 53) {
          let sum = 0; for (let k = 0; k < 4; k++) sum += a.skinWeight.getComponent(i, k)
          maxWeightError = Math.max(maxWeightError, Math.abs(sum - 1))
          n.getVertexPosition(i, p); n.localToWorld(p)
          if (!p.toArray().every(Number.isFinite)) invalid++
          for (let k = 0; k < 3; k++) { low[k] = Math.min(low[k], p.getComponent(k)); high[k] = Math.max(high[k], p.getComponent(k)) }
          p.project(q.state.camera); const xy = [(p.x + 1) * innerWidth / 2, (1 - p.y) * innerHeight / 2]
          for (let k = 0; k < 2; k++) { screenLow[k] = Math.min(screenLow[k], xy[k]); screenHigh[k] = Math.max(screenHigh[k], xy[k]) }
        }
      })
      return { meshes, outlines, bones, invalid, triangles, maxWeightError, ink, low, high, screenLow, screenHigh, action: useApp.getState().action, animationTime: root.userData.animationTime }
    }
    return { catalogReady: q.catalogReady, clips: body.animations.map(c => ({ name: c.name, duration: c.duration })), snapshot: q.snapshot() }
  })
  const healthy = s => { assert.equal(s.invalid, 0); assert.equal(s.meshes, 1); assert.equal(s.outlines, 1); assert.equal(s.bones, 89); assert.equal(s.ink, 1); assert(s.maxWeightError < .0001); assert(s.low[1] > -.003) }
  healthy(report.setup.snapshot)
  assert.deepEqual(report.setup.clips.map(c => c.name).sort(), ['idle', 'special', 'walk'])
  report.motion = {}
  report.actionButtons = await page.locator('.actions button').count()
  for (const name of ['idle', 'walk', 'special']) {
    if (report.actionButtons === 3) await page.getByRole('toolbar', { name: '动作' }).getByRole('button', { name: { idle: '静', walk: '行', special: '神通' }[name], exact: true }).click()
    else await page.evaluate(name => window.longzhiQA.useApp.getState().setAction(name), name)
    const samples = []
    for (let i = 0; i < 5; i++) { await page.waitForTimeout(350); const s = await page.evaluate(() => window.longzhiQA.snapshot()); healthy(s); assert.equal(s.action, name); samples.push(s) }
    await shot(`desktop-${name}`); report.motion[name] = samples
    assert(samples.at(-1).animationTime > samples[0].animationTime)
  }
  await page.waitForFunction(() => window.longzhiQA.useApp.getState().action === 'idle', null, { timeout: 20000 }); report.specialReturnedToIdle = true
  await page.evaluate(() => {
    const q = window.longzhiQA, root = q.root(), mesh = root.getObjectByProperty('isSkinnedMesh', true), p = new q.T.Vector3(), feet = { front_l: [], front_r: [], back_l: [], back_r: [] }
    root.updateMatrixWorld(true); mesh.skeleton.update()
    for (let i = 0; i < mesh.geometry.attributes.position.count; i++) {
      mesh.getVertexPosition(i, p); mesh.localToWorld(p); root.worldToLocal(p)
      if (p.y < .035) feet[`${p.z > 0 ? 'front' : 'back'}_${p.x > 0 ? 'l' : 'r'}`].push(i)
    }
    q.pawIndices = Object.fromEntries(Object.entries(feet).map(([key, ids]) => { if (ids.length < 10) throw Error(`Missing ${key}`); return [key, [ids[0], ids[Math.floor(ids.length / 2)], ids.at(-1)]] }))
    q.pawSnapshot = () => {
      root.updateMatrixWorld(true); mesh.skeleton.update()
      return { time: root.userData.animationTime, feet: Object.fromEntries(Object.entries(q.pawIndices).map(([key, ids]) => [key, ids.map(i => { mesh.getVertexPosition(i, p); mesh.localToWorld(p); return p.toArray() })])) }
    }
    q.useApp.getState().setAction('walk')
  })
  const anchors = new Map(), phases = { back_l: 0, front_l: .25, back_r: .5, front_r: .75 }
  let worldDrift = 0, worldSamples = 0, loop = 0, previousTime = 0
  for (let i = 0; i < 36; i++) {
    await page.waitForTimeout(65)
    const sample = await page.evaluate(() => window.longzhiQA.pawSnapshot())
    if (sample.time < previousTime) loop++
    previousTime = sample.time
    if (loop === 0 && sample.time < .4) continue
    for (const [foot, points] of Object.entries(sample.feet)) {
      const phase = loop + sample.time / 2.4 + phases[foot]
      if (phase % 1 >= .68) continue
      const key = `${foot}:${Math.floor(phase)}`
      if (!anchors.has(key)) anchors.set(key, points)
      for (let k = 0; k < points.length; k++) worldDrift = Math.max(worldDrift, Math.hypot(...points[k].map((v, j) => v - anchors.get(key)[k][j])))
      worldSamples++
    }
  }
  report.worldPlantedPaws = { samples: worldSamples, maximumDriftM: worldDrift }
  assert(worldSamples > 20 && worldDrift < .0007, JSON.stringify(report.worldPlantedPaws))
  await page.evaluate(() => window.longzhiQA.useApp.getState().setAction('idle'))
  report.remounts = []
  for (let cycle = 0; cycle < 3; cycle++) {
    await page.evaluate(() => { const q = window.longzhiQA; q.previousSkeletons = []; q.root().traverse(n => { if (n.isSkinnedMesh && !n.userData.inkOutline) q.previousSkeletons.push(n.skeleton) }); q.useApp.getState().select('jiuweihu') })
    await page.waitForTimeout(700)
    const pending = ready(); await page.evaluate(() => window.longzhiQA.useApp.getState().select('longzhi')); await pending; await page.waitForTimeout(350)
    const result = await page.evaluate(() => { const q = window.longzhiQA; return { snapshot: q.snapshot(), cacheUnchanged: q.before === q.sourceSnapshot(), sharedDisposals: q.sharedDisposals, oldTexturesReleased: q.previousSkeletons.every(s => !s.boneTexture) } })
    healthy(result.snapshot); assert(result.cacheUnchanged && result.oldTexturesReleased); assert.equal(result.sharedDisposals, 0); report.remounts.push(result)
  }
  report.responsive = []
  for (const size of [{ width: 1024, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(size); await page.waitForTimeout(1200)
    const s = await page.evaluate(() => window.longzhiQA.snapshot()); healthy(s)
    assert(s.screenLow[0] >= 0 && s.screenLow[1] >= 0 && s.screenHigh[0] <= size.width && s.screenHigh[1] <= size.height, JSON.stringify({ size, s }))
    await shot(`responsive-${size.width}`); report.responsive.push({ size, snapshot: s })
  }
  assert(await page.locator('.card-source').textContent().then(t => t.includes('而九尾、九首、虎爪')))
  assert.equal(await page.locator('.card-inferred p').count(), 4)
  await page.locator('.card .story-btn').click()
  await page.waitForFunction(() => window.longzhiNarrations.some(e => e.src.includes('/longzhi.mp3') && !e.paused && e.currentTime > .15), null, { timeout: 30000 })
  report.narration = await page.evaluate(() => window.longzhiNarrations.filter(e => e.src.includes('/longzhi.mp3')).map(e => ({ src: e.src, currentTime: e.currentTime, readyState: e.readyState })))
  await page.locator('.card .story-btn').click()
  assert(await page.evaluate(() => window.longzhiNarrations.filter(e => e.src.includes('/longzhi.mp3')).every(e => e.paused)))
  report.narrationPlayedAndStopped = true
  await page.evaluate(async () => {
    const url = performance.getEntriesByType('resource').map(r => r.name).find(u => new URL(u).pathname.endsWith('/src/systems/audio/AudioEngine.ts'))
    const { audio } = await import(url), q = window.longzhiQA
    q.audio = audio; q.cryCalls = 0; q.originalCry = audio.infantCry
    audio.infantCry = function (...args) { q.cryCalls++; return q.originalCry.apply(this, args) }
    q.analyser = audio.context.createAnalyser(); audio.sfx.connect(q.analyser)
    q.useApp.getState().setAction('special')
  })
  await page.waitForFunction(() => window.longzhiQA.cryCalls > 0)
  const peaks = []
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(100)
    peaks.push(await page.evaluate(() => { const q = window.longzhiQA, data = new Float32Array(q.analyser.fftSize); q.analyser.getFloatTimeDomainData(data); return Math.max(...data.map(Math.abs)) }))
  }
  report.beastCall = await page.evaluate(() => ({ calls: window.longzhiQA.cryCalls, contextState: window.longzhiQA.audio.context.state }))
  report.beastCall.peakAmplitude = Math.max(...peaks)
  assert.equal(report.beastCall.calls, 1); assert.equal(report.beastCall.contextState, 'running'); assert(report.beastCall.peakAmplitude > .00001)
  await page.evaluate(() => { const q = window.longzhiQA; q.audio.infantCry = q.originalCry; q.audio.sfx.disconnect(q.analyser); q.analyser.disconnect(); q.useApp.getState().setAction('idle') })
  await page.setViewportSize({ width: 1100, height: 1100 }); await page.waitForTimeout(800)
  await page.addStyleTag({ content: '.card,.controls,.scroll-wrap,.actions{visibility:hidden!important}' })
  for (const view of [
    { name: 'ink-shoulder', target: [0, .72, .15], eye: [1.25, 1.15, 1.8], fov: 24 },
    { name: 'ink-nape', target: [0, .96, .12], eye: [-1.7, 1.25, .30], fov: 25 },
    { name: 'ink-rump', target: [0, .57, -.40], eye: [.95, 1.05, -1.8], fov: 23 },
  ]) {
    await page.evaluate(view => { const q = window.longzhiQA, root = q.root(), camera = q.state.camera; root.updateMatrixWorld(true); q.state.controls.update = () => {}; camera.position.copy(root.localToWorld(new q.T.Vector3(...view.eye))); camera.lookAt(root.localToWorld(new q.T.Vector3(...view.target))); camera.fov = view.fov; camera.filmOffset = 0; camera.updateProjectionMatrix() }, view)
    await page.waitForTimeout(150); await shot(view.name)
  }
  assert.deepEqual(report.errors, [])
  report.passed = true
} catch (e) { report.failure = String(e); report.stack = e.stack; await shot('failure').catch(() => {}) }
finally { await writeFile(join(out, 'report.json'), JSON.stringify(report, null, 2) + '\n'); await browser.close() }
console.log(JSON.stringify({ passed: report.passed, failure: report.failure, report: join(out, 'report.json') }))
if (!report.passed) process.exitCode = 1
