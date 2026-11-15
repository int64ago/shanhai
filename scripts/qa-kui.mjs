// Actual browser acceptance for the native one-legged Kui candidate.
// node scripts/qa-kui.mjs [BASE_URL] [OUTPUT_DIR]
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const base = process.argv[2] ?? 'http://localhost:5204'
const output = resolve(process.argv[3] ?? 'raw/_build/kui-runtime-qa')
await mkdir(output, { recursive: true })
const bytes = await readFile(new URL('../public/models/kui/body.glb', import.meta.url))
assert(bytes.length < 15 * 1024 * 1024)
const report = { productionAccepted: false, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), errors: [], checks: {}, images: [], deviceScope: 'Local Chrome Metal; 390x844 and 360x740 phone viewport emulation, not physical-device performance' }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
async function shot(name) { const path = join(output, name + '.png'); await page.screenshot({ path }); report.images.push(path) }
async function check(name, fn) { try { report.checks[name] = { passed: true, ...(await fn()) } } catch (e) { report.checks[name] = { passed: false, error: String(e) }; await shot('failure-' + name) } }
async function action(name) { await page.evaluate(name => window.kuiQA.useApp.getState().setAction(name), name) }
async function bootstrap() {
  return page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(u => new URL(u).pathname === '/src/app/store.ts'))
    const { BEASTS } = await import(resources.find(u => new URL(u).pathname === '/src/app/beasts.ts'))
    const catalogReady = BEASTS.find(b => b.id === 'kui').ready
    BEASTS.find(b => b.id === 'kui').ready = true // Browser-local preview controls only.
    const T = await import(resources.find(u => new URL(u).pathname.endsWith('/three.js')))
    const q = window.kuiQA = { T, useApp, state: [...fiber._roots.values()][0].store.getState() }
    q.root = () => q.state.scene.getObjectByName('kui_root')
    const meshes = []; q.root().traverse(n => { if (n.isSkinnedMesh && !n.userData.inkOutline) meshes.push(n) })
    if (meshes.length !== 1) throw new Error('Expected one native skinned mesh')
    q.mesh = meshes[0]; const a = q.mesh.geometry.attributes, bones = q.mesh.skeleton.bones
    let invalid = 0, weightError = 0, outlines = 0
    q.root().traverse(n => {
      if (n.userData.inkOutline) outlines++
      if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++
      const materials = Array.isArray(n.material) ? n.material : n.material ? [n.material] : []
      if (materials.some(m => m.blending === T.AdditiveBlending)) invalid++
    })
    for (let i = 0; i < a.position.count; i++) {
      let sum = 0
      for (let k = 0; k < 4; k++) {
        const w = a.skinWeight.getComponent(i, k), b = a.skinIndex.getComponent(i, k)
        if (!Number.isFinite(w) || w < 0 || !Number.isInteger(b) || b < 0 || b >= bones.length) invalid++
        sum += w
      }
      weightError = Math.max(weightError, Math.abs(sum - 1))
    }
    q.root().updateMatrixWorld(true)
    const rootBone = bones.find(b => b.name === 'root'), ri = bones.indexOf(rootBone)
    const rest = q.root().matrixWorld.clone().invert().multiply(rootBone.parent.matrixWorld).multiply(q.mesh.skeleton.boneInverses[ri])
    const masks = { head: [], hoof: [], sole: [] }, v = new T.Vector3()
    for (let i = 0; i < a.position.count; i++) {
      v.fromBufferAttribute(a.position, i).applyMatrix4(rest).divideScalar(1.6)
      const x = v.x, y = -v.z, z = v.y
      if (y < -.365 && z > .66 && Math.abs(x) < .14) masks.head.push(i)
      if (z < .11) masks.hoof.push(i)
      if (z < .003) masks.sole.push(i)
    }
    for (const [name, ids] of Object.entries(masks)) if (ids.length < 5) throw new Error('Missing native mask ' + name)
    q.points = ids => { q.state.scene.updateMatrixWorld(true); q.mesh.skeleton.update(); return ids.map(i => { q.mesh.getVertexPosition(i, v); q.mesh.localToWorld(v); return v.toArray() }) }
    q.rigid = {}
    for (const name of ['head', 'hoof']) {
      const ids = masks[name].filter((_, i) => i % Math.max(1, Math.floor(masks[name].length / 35)) === 0), pts = q.points(ids)
      q.rigid[name] = { ids, distances: pts.map(p => Math.hypot(...p.map((n, k) => n - pts[0][k]))) }
    }
    q.soles = masks.sole.filter((_, i) => i % Math.max(1, Math.floor(masks.sole.length / 12)) === 0)
    q.snapshot = () => {
      let rigidError = 0
      for (const { ids, distances } of Object.values(q.rigid)) {
        const pts = q.points(ids)
        pts.forEach((p, i) => { rigidError = Math.max(rigidError, Math.abs(Math.hypot(...p.map((n, k) => n - pts[0][k])) - distances[i])) })
      }
      return { ...q.root().userData, rigidError, position: q.root().position.toArray(), soles: q.points(q.soles) }
    }
    q.framing = () => {
      const low = [Infinity, Infinity], high = [-Infinity, -Infinity]
      q.state.scene.updateMatrixWorld(true); q.mesh.skeleton.update()
      const blocked = [...document.querySelectorAll('.card,.title,.controls,.actions,.scroll-wrap')]
        .filter(el => getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden')
        .map(el => { const r = el.getBoundingClientRect(); return { name: el.className, left: r.left, right: r.right, top: r.top, bottom: r.bottom } })
        .filter(r => r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight)
      const hits = new Set()
      let radius = 0
      for (let i = 0; i < a.position.count; i++) {
        q.mesh.getVertexPosition(i, v); q.mesh.localToWorld(v); radius = Math.max(radius, Math.hypot(v.x, v.z)); v.project(q.state.camera)
        const xy = [(v.x + 1) * innerWidth / 2, (1 - v.y) * innerHeight / 2]
        for (let k = 0; k < 2; k++) { low[k] = Math.min(low[k], xy[k]); high[k] = Math.max(high[k], xy[k]) }
        for (const r of blocked) {
          if (xy[0] > r.left - 8 && xy[0] < r.right + 8 && xy[1] > r.top - 8 && xy[1] < r.bottom + 8) hits.add(r.name)
        }
      }
      return { low, high, radius, overlaps: [...hits], width: innerWidth, height: innerHeight, blocked }
    }
    return { catalogReady, triangles: (q.mesh.geometry.index?.count ?? a.position.count) / 3, boneCount: bones.length, boneNames: bones.map(b => b.name), outlines, invalid, weightError, masks: Object.fromEntries(Object.entries(masks).map(([n, ids]) => [n, ids.length])) }
  })
}
function safe(f) {
  assert(f.low.every(x => x >= 6) && f.high[0] <= f.width - 6 && f.high[1] <= f.height - 6, 'Viewport clipping ' + JSON.stringify(f))
  assert(f.radius < 2, 'Outside stage radius ' + f.radius)
  assert.deepEqual(f.overlaps, [], 'UI overlap ' + JSON.stringify(f))
}
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready kui'), timeout: 60000 })
  const started = Date.now(); await page.goto(base + '/?beast=kui&action=idle'); await ready
  report.loadMs = Date.now() - started; await page.waitForTimeout(1200)
  await check('nativeRig', async () => {
    const data = await bootstrap(); assert.equal(data.triangles, 50000); assert.equal(data.boneCount, 16); assert.equal(data.invalid, 0); assert.equal(data.outlines, 1); assert(data.weightError < .001)
    assert.equal(data.boneNames.filter(n => n.endsWith('_foot')).length, 1); return data
  })
  for (const name of ['idle', 'walk', 'special']) await check('desktop-' + name, async () => {
    await action(name); await page.waitForTimeout(500)
    const samples = await page.evaluate(async () => {
      const q = window.kuiQA, samples = [], start = performance.now(); let previous = start
      while (performance.now() - start < 3700) { await new Promise(requestAnimationFrame); const now = performance.now(); const sample = { dt: now - previous, ...q.snapshot() }; if (samples.length % 12 === 0) sample.framing = q.framing(); samples.push(sample); previous = now }
      return samples
    })
    const maxRigidError = Math.max(...samples.map(s => s.rigidError)); assert(maxRigidError < .00015, 'Rigid face/hoof ' + maxRigidError)
    const frameMs = samples.slice(2).map(s => s.dt).sort((a, b) => a - b), p95 = frameMs[Math.floor(frameMs.length * .95)]; assert(p95 < 150)
    let plantedDrift = 0, minGround = Infinity, maxFlight = 0, anchor = null, previousPhase = 0, supportSamples = 0, flightSamples = 0
    for (const s of samples) {
      if (s.framing) safe(s.framing)
      const phase = s.animationTime / 1.8 % 1
      const supported = name !== 'walk' || (phase > .06 && phase < .55)
      if (!supported || phase < previousPhase) anchor = null
      if (supported) {
        anchor ??= s.soles
        s.soles.forEach((p, i) => { plantedDrift = Math.max(plantedDrift, Math.hypot(...p.map((v, k) => v - anchor[i][k]))) })
        supportSamples++
      }
      minGround = Math.min(minGround, ...s.soles.map(p => p[1]))
      if (name === 'walk' && phase > .7 && phase < .9) { maxFlight = Math.max(maxFlight, ...s.soles.map(p => p[1])); flightSamples++ }
      if (name === 'walk') {
        const angle = Math.PI / 2 + 1.2 - .16 / .65 * s.elapsedWalkSeconds
        assert(Math.abs(s.worldAngle - angle) < 1e-6)
        assert(Math.hypot(s.position[0] - .65 * Math.cos(angle), s.position[2] - .65 * Math.sin(angle)) < 1e-6)
      }
      previousPhase = phase
    }
    assert(plantedDrift < .006, 'Single planted hoof drift ' + plantedDrift); assert(minGround > -.003, 'Hoof penetration ' + minGround)
    if (name === 'walk') { assert(supportSamples > 15); assert(flightSamples > 10); assert(maxFlight > .09, 'No true airborne phase ' + maxFlight) }
    await shot('desktop-' + name)
    return { maxRigidError, plantedDrift, minGround, maxFlight, supportSamples, flightSamples, frameMsP95: p95, frames: samples.length }
  })
  await check('specialReturnsIdle', async () => { await page.waitForTimeout(1500); assert.equal(await page.evaluate(() => window.kuiQA.useApp.getState().action), 'idle') })
  await check('nativeInkCloseups', async () => {
    await action('idle'); await page.waitForTimeout(400)
    const original = await page.evaluate(() => { const q = window.kuiQA; return { p: q.state.camera.position.toArray(), t: q.state.controls.target.toArray(), offset: q.state.camera.filmOffset } })
    const hiddenUI = await page.addStyleTag({ content: '.card,.title,.controls,.actions,.scroll-wrap { visibility:hidden !important }' })
    for (const [name, target, direction, distance] of [
      ['face-neck', [0, 1.16, .52], [.8, .1, 1.5], 1.7],
      ['belly-ankle', [0, .53, -.02], [1, .05, .25], 2.2],
      ['tail-root', [0, .92, -.68], [1, .2, -1], 1.6],
    ]) {
      await page.evaluate(({ target, direction, distance }) => {
        const q = window.kuiQA, center = new q.T.Vector3(...target).applyMatrix4(q.root().matrixWorld)
        q.state.camera.filmOffset = 0; q.state.camera.updateProjectionMatrix(); q.state.controls.target.copy(center)
        q.state.camera.position.copy(center).add(new q.T.Vector3(...direction).normalize().multiplyScalar(distance).applyQuaternion(q.root().quaternion)); q.state.controls.update()
      }, { target, direction, distance }); await shot('closeup-' + name)
    }
    await hiddenUI.evaluate(el => el.remove())
    await page.evaluate(original => { const q = window.kuiQA; q.state.camera.position.fromArray(original.p); q.state.controls.target.fromArray(original.t); q.state.camera.filmOffset = original.offset; q.state.camera.updateProjectionMatrix(); q.state.controls.update() }, original)
  })
  for (const [width, height] of [[390, 844], [360, 740]]) await check('phone-' + width, async () => {
    await page.setViewportSize({ width, height }); const result = {}
    for (const name of ['idle', 'walk', 'special']) {
      await action(name); await page.waitForTimeout(850)
      const frames = []
      for (let i = 0; i < 12; i++) { const f = await page.evaluate(() => window.kuiQA.framing()); safe(f); frames.push(f); await page.waitForTimeout(150) }
      await shot('phone-' + width + '-' + name); result[name] = { frames, final: frames.at(-1) }
    }
    const dts = await page.evaluate(async () => { const values = [], end = performance.now() + 1200; let last = performance.now(); while (performance.now() < end) { await new Promise(requestAnimationFrame); const now = performance.now(); values.push(now - last); last = now } return values.slice(2).sort((a, b) => a - b) })
    const frameMsP95 = dts[Math.floor(dts.length * .95)]; assert(frameMsP95 < 150); return { states: result, frameMsP95 }
  })
  await check('fullCircleFraming', async () => {
    const views = {}
    for (const [label, width, height] of [['desktop', 1440, 900], ['phone', 390, 844]]) {
      await page.setViewportSize({ width, height })
      await action('idle'); await page.waitForTimeout(700)
      await page.evaluate(() => {
        const q = window.kuiQA
        q.state.setFrameloop('never'); q.frameTime = 0
        q.step = count => { for (let i = 0; i < count; i++) q.state.advance(q.frameTime += .05, false) }
        q.step(40)
      })
      try {
        await action('walk'); await page.waitForTimeout(30)
        const frames = []
        for (let i = 0; i < 60; i++) {
          const frame = await page.evaluate(() => { const q = window.kuiQA; q.step(10); return { ...q.framing(), angle: q.root().userData.worldAngle } })
          safe(frame); frames.push(frame)
          if (i % 15 === 14) await shot(`${label}-circle-${(i + 1) / 15}`)
        }
        const radians = Math.abs(frames.at(-1).angle - frames[0].angle)
        assert(radians > Math.PI * 2, 'Incomplete circular walk')
        views[label] = { width, height, simulatedWalkSeconds: 30, radians, frames }
      } finally { await page.evaluate(() => window.kuiQA.state.setFrameloop('always')) }
    }
    return views
  })
  await check('strictModeRemount', async () => {
    await page.route('**/models/_placeholder/fox.glb', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => window.kuiQA.useApp.getState().select('xingtian')); await page.waitForTimeout(450)
      await page.evaluate(() => window.kuiQA.useApp.getState().select('kui')); await page.waitForTimeout(650)
      const data = await bootstrap(); assert.equal(data.outlines, 1); assert.equal(data.invalid, 0)
    }
    return { remounts: 3, outlines: 1 }
  })
  await page.setViewportSize({ width: 1440, height: 900 }); await action('walk'); await page.waitForTimeout(700)
  for (let i = 0; i < 6; i++) { await shot('motion-' + i); await page.waitForTimeout(210) }
} finally { await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n'); await browser.close() }
console.log(JSON.stringify({ ...report, checks: Object.fromEntries(Object.entries(report.checks).map(([key, value]) => [key, { ...value, states: value.states ? Object.keys(value.states) : undefined }])) }, null, 2))
assert.equal(report.errors.length, 0, 'Browser errors')
assert(Object.values(report.checks).every(c => c.passed), 'Kui acceptance checks failed')
