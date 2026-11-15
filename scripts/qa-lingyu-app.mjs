// Actual Stage candidate QA; no ready/provenance mutation on disk.
// node scripts/qa-lingyu-app.mjs BASE_URL NEW_OUTPUT CANDIDATE.glb REST_REFERENCE.json
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'
const [base, outArg, modelArg, refArg] = process.argv.slice(2)
assert(base && outArg && modelArg && refArg)
const out = resolve(outArg), model = resolve(modelArg), ref = JSON.parse(await readFile(resolve(refArg), 'utf8')), bytes = await readFile(model)
assert.equal(ref.beast, 'lingyu'); assert.equal(ref.acceptedStaticPatchSha256, 'b4a02d4ae07c06a35b8bdc818e8da789640ffaf4e46b33cfb87cc3f8b787184b'); assert(bytes.length < 15 * 1024 * 1024)
await mkdir(out, { recursive: false })
const report = { candidate: model, candidateSha256: createHash('sha256').update(bytes).digest('hex'), candidateBytes: bytes.length, productionAccepted: false, sections: {}, failures: [], errors: [], images: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route('**/models/lingyu/body.glb*', r => r.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
page.on('pageerror', e => report.errors.push(String(e))); page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) }); page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
async function shot(name) { const path = join(out, name + '.png'); await page.screenshot({ path }); report.images.push(path) }
async function section(name, fn) { try { await fn(); report.sections[name] = { passed: true } } catch (e) { report.sections[name] = { passed: false, error: String(e) }; report.failures.push({ section: name, error: String(e), stack: e.stack }); await shot('failure-' + name).catch(() => {}) } console.log(JSON.stringify({ section: name, ...report.sections[name] })) }
async function action(name) { await page.evaluate(n => window.lingyuQA.useApp.getState().setAction(n), name) }
async function snapshot() { return page.evaluate(() => window.lingyuQA.snapshot()) }
function healthy(s) {
  assert.equal(s.invalid, 0); assert.equal(s.bones, 30); assert.equal(s.triangles, 53648); assert.equal(s.meshes, 6); assert.equal(s.outlines, 6)
  assert(s.maxWeightError < .0001); assert(s.maxBoneScaleError < .000002); assert(s.maxNonRootTranslationError < .00001)
  assert(s.low[1] > .12, `Aquatic world clearance ${s.low[1]}m`); assert(s.rigidDrift < .0005, `Complete face/palms/forefeet drift ${s.rigidDrift}m`)
  assert.deepEqual(s.rootPosition, [0, 0, 0]); assert.deepEqual(s.rootScale, [1, 1, 1]); assert.deepEqual(s.rootQuaternion, [0, 0, 0, 1])
}
function displacement(a, b) { let v = 0; for (let i = 0; i < a.length; i++) v = Math.max(v, Math.hypot(...a[i].map((x, k) => x - b[i][k]))); return v }
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready lingyu'), timeout: 60000 })
  await page.goto(`${base}/?beast=lingyu&action=idle`); await ready; await page.waitForTimeout(600)
  report.setup = await page.evaluate(async reference => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const module = suffix => { const url = resources.find(u => new URL(u).pathname.endsWith(suffix)); if (!url) throw new Error(`Missing ${suffix}`); return url }
    const T = await import(module('/three.js')), fiber = await import(module('/@react-three_fiber.js')), { useGLTF } = await import(module('/@react-three_drei.js')), { useApp } = await import(module('/src/app/store.ts')), { BEASTS } = await import(module('/src/app/beasts.ts'))
    const entry = BEASTS.find(b => b.id === 'lingyu'), previewReadyOverride = !entry.ready; entry.ready = true // Browser-local controls preview only.
    const body = useGLTF('/models/lingyu/body.glb'), q = window.lingyuQA = { T, useApp, source: body.scene, animations: body.animations, state: [...fiber._roots.values()][0].store.getState(), sharedDisposals: 0 }
    q.root = () => { const r = q.state.scene.getObjectByName('lingyu_root'); if (!r) throw new Error('Lingyu Stage root missing'); return r }
    q.meshes = root => { const list = []; (root ?? q.root()).traverse(n => { if (n.isMesh && !n.userData.inkOutline) list.push(n) }); return list }
    q.sourceSnapshot = () => { const list = []; q.source.traverse(n => list.push({ uuid: n.uuid, children: n.children.map(c => c.uuid), p: n.position.toArray(), q: n.quaternion.toArray(), s: n.scale.toArray(), geometry: n.geometry?.uuid, skeleton: n.skeleton?.uuid, materials: (Array.isArray(n.material) ? n.material : n.material ? [n.material] : []).map(m => m.uuid) })); return JSON.stringify(list) }
    q.before = q.sourceSnapshot()
    const shared = new Set(); q.source.traverse(n => { if (n.geometry) shared.add(n.geometry); for (const m of Array.isArray(n.material) ? n.material : n.material ? [n.material] : []) { shared.add(m); for (const v of Object.values(m)) if (v?.isTexture) shared.add(v) } }); for (const r of shared) r.addEventListener('dispose', () => q.sharedDisposals++)
    q.positions = root => { const pts = [], p = new T.Vector3(); root.updateMatrixWorld(true); for (const m of q.meshes(root)) { m.skeleton.update(); for (let i = 0; i < m.geometry.attributes.position.count; i++) { m.getVertexPosition(i, p); m.localToWorld(p); pts.push(p.toArray()) } } return pts }
    const points = reference.points, rest = q.positions(q.source), cell = .001, grid = new Map(), key = p => p.join(',')
    points.forEach((p, i) => { const k = key(p.map(x => Math.floor(x / cell))); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i) })
    let maximumRestError = 0
    const nativeIds = rest.map(p => {
      const c = p.map(x => Math.floor(x / cell)); let best = -1, err = Infinity
      for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) for (const j of grid.get(key([c[0] + x, c[1] + y, c[2] + z])) ?? []) { const e = Math.hypot(...p.map((v, k) => v - points[j][k])); if (e < err) { best = j; err = e } }
      if (best < 0 || err > .0003) throw new Error(`Unmatched source rest vertex ${err}m`); maximumRestError = Math.max(maximumRestError, err); return best
    })
    q.masks = Object.fromEntries(Object.entries(reference.masks).map(([name, ids]) => { const set = new Set(ids), selected = nativeIds.flatMap((id, i) => set.has(id) ? [i] : []); if (!selected.length) throw new Error(`Missing ${name}`); return [name, selected] }))
    q.rest = rest
    q.anchors = Object.fromEntries(Object.entries(q.masks).filter(([name]) => name === 'face' || /hand|foot/.test(name)).map(([name, ids]) => [name, [ids[0], ids[Math.floor(ids.length / 2)], ids.at(-1)]]))
    q.probeIds = Object.fromEntries(Object.entries(q.masks).map(([name, ids]) => [name, Array.from({ length: Math.min(24, ids.length) }, (_, i) => ids[Math.floor(i * ids.length / Math.min(24, ids.length))])]))
    q.restBonePositions = {}; q.source.traverse(n => { if (n.isBone) q.restBonePositions[n.name] = n.position.toArray() })
    q.snapshot = () => {
      q.state.scene.updateMatrixWorld(true)
      let invalid = 0, bones = 0, outlines = 0, triangles = 0, maxWeightError = 0, maxBoneScaleError = 0, maxNonRootTranslationError = 0, coveredVertices = 0, clippedVertices = 0, rigidDrift = 0
      const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity], screenLow = [Infinity, Infinity], screenHigh = [-Infinity, -Infinity], p = new T.Vector3(), positions = q.positions(q.root())
      const blockers = ['.card', '.actions', '.scroll-wrap', '.controls', '.title'].flatMap(s => [...document.querySelectorAll(s)].filter(e => getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none').map(e => e.getBoundingClientRect()))
      q.root().traverse(n => {
        if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++
        if (n.isBone) { bones++; maxBoneScaleError = Math.max(maxBoneScaleError, ...n.scale.toArray().map(x => Math.abs(x - 1))); const r = q.restBonePositions[n.name]; if (r && n.name !== 'root') maxNonRootTranslationError = Math.max(maxNonRootTranslationError, ...n.position.toArray().map((x, k) => Math.abs(x - r[k]))) }
        if (n.userData.inkOutline) outlines++
      })
      for (const m of q.meshes()) {
        const a = m.geometry.attributes; triangles += (m.geometry.index?.count ?? a.position.count) / 3
        for (const name of ['position', 'normal', 'skinWeight', 'skinIndex']) if (!a[name] || !Array.from(a[name].array).every(Number.isFinite)) invalid++
        for (let i = 0; i < a.position.count; i++) { let sum = 0; for (let k = 0; k < 4; k++) { const w = a.skinWeight.getComponent(i, k), j = a.skinIndex.getComponent(i, k); sum += w; if (w < 0 || !Number.isInteger(j) || j < 0 || j >= 30) invalid++ } maxWeightError = Math.max(maxWeightError, Math.abs(sum - 1)) }
      }
      for (const xyz of positions) {
        if (!xyz.every(Number.isFinite)) invalid++
        xyz.forEach((v, k) => { low[k] = Math.min(low[k], v); high[k] = Math.max(high[k], v) }); p.fromArray(xyz).project(q.state.camera)
        if (p.z < -1 || p.z > 1) clippedVertices++
        const xy = [(p.x + 1) * innerWidth / 2, (1 - p.y) * innerHeight / 2]; xy.forEach((v, k) => { screenLow[k] = Math.min(screenLow[k], v); screenHigh[k] = Math.max(screenHigh[k], v) })
        if (blockers.some(r => xy[0] > r.left && xy[0] < r.right && xy[1] > r.top && xy[1] < r.bottom)) coveredVertices++
      }
      const distance = (a, b) => Math.hypot(...a.map((v, k) => v - b[k]))
      for (const [name, anchors] of Object.entries(q.anchors)) for (const a of anchors) for (const i of q.masks[name]) rigidDrift = Math.max(rigidDrift, Math.abs(distance(positions[a], positions[i]) - distance(q.rest[a], q.rest[i])))
      return { invalid, bones, outlines, triangles, meshes: q.meshes().length, maxWeightError, maxBoneScaleError, maxNonRootTranslationError, low, high, screenLow, screenHigh, coveredVertices, clippedVertices, rigidDrift, probes: Object.fromEntries(Object.entries(q.probeIds).map(([name, ids]) => [name, ids.map(i => positions[i])])), time: q.root().userData.animationTime, action: useApp.getState().action, rootPosition: q.root().position.toArray(), rootScale: q.root().scale.toArray(), rootQuaternion: q.root().quaternion.toArray() }
    }
    return { previewReadyOverride, clips: body.animations.map(c => ({ name: c.name, duration: c.duration })), sourceMeshes: q.meshes(q.source).length, matchedCompressedVertices: rest.length, maximumRestError, maskCounts: Object.fromEntries(Object.entries(q.masks).map(([n, ids]) => [n, ids.length])), maskMethod: 'Independent rest-geometry nearest match; never weight-derived' }
  }, ref)
  await section('eye-material', async () => {
    report.eyeMaterial = await page.evaluate(() => {
      const q = window.lingyuQA, image = q.meshes(q.source)[0].material.map.image, canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height
      const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0); const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      const sample = ([u, v]) => { const x = Math.floor(u * canvas.width), y = Math.floor(v * canvas.height), rgb = [0, 0, 0]; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) for (let k = 0; k < 3; k++) rgb[k] += data[((y + dy) * canvas.width + x + dx) * 4 + k] / (9 * 255); return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722 }
      return [[[.62999725, .69507701], [.63756362, .69889453]], [[.89346289, .86970499], [.88323076, .86979141]]].map(([iris, sclera]) => ({ irisLuminance: sample(iris), scleraLuminance: sample(sclera) }))
    })
    for (const eye of report.eyeMaterial) assert(eye.irisLuminance < .25 && eye.scleraLuminance - eye.irisLuminance > .25, `Eye lost contrast after runtime WebP: ${JSON.stringify(eye)}`)
  })
  await section('native-stage', async () => { healthy(await snapshot()); for (const [name, d] of [['idle', 6], ['walk', 4], ['special', 6]]) assert(report.setup.clips.some(c => c.name === name && Math.abs(c.duration - d) < .00001)) })
  await section('clip-boundaries', async () => {
    report.clipBoundaries = await page.evaluate(() => {
      const q = window.lingyuQA, T = q.T, rig = q.source.clone(true), original = [], copies = []; q.source.traverse(n => original.push(n)); rig.traverse(n => copies.push(n)); const map = new Map(original.map((n, i) => [n.uuid, copies[i]])), cloned = new Map()
      original.forEach((n, i) => { if (n.isSkinnedMesh) { if (!cloned.has(n.skeleton)) cloned.set(n.skeleton, new T.Skeleton(n.skeleton.bones.map(b => map.get(b.uuid)), n.skeleton.boneInverses.map(m => m.clone()))); copies[i].skeleton = cloned.get(n.skeleton) } })
      const mixer = new T.AnimationMixer(rig), results = {}, starts = {}, dt = .01
      const delta = (a, b) => { let d = 0; for (let i = 0; i < a.length; i++) d = Math.max(d, Math.hypot(...a[i].map((v, k) => v - b[i][k]))); return d }, deriv = (a, b) => a.map((p, i) => p.map((v, k) => (v - b[i][k]) / dt)), accel = (a, b, c) => a.map((p, i) => p.map((v, k) => (v - 2 * b[i][k] + c[i][k]) / dt ** 2))
      try { for (const clip of q.animations) { const action = mixer.clipAction(clip), at = t => { action.reset().setLoop(T.LoopOnce, 1); action.clampWhenFinished = true; action.play(); mixer.setTime(t); return q.positions(rig) }, [a, b, c, d, e, f] = [0, dt, 2 * dt, clip.duration - 2 * dt, clip.duration - dt, clip.duration].map(at); starts[clip.name] = { position: a, velocity: deriv(b, a), acceleration: accel(c, b, a) }; results[clip.name] = { positionSeamM: delta(a, f), velocityDifferenceMps: delta(deriv(b, a), deriv(f, e)), accelerationDifferenceMps2: delta(accel(c, b, a), accel(f, e, d)), sampledVertices: a.length, dt }; mixer.stopAllAction() } results.specialIdle = Object.fromEntries(['position', 'velocity', 'acceleration'].map(n => [n, delta(starts.special[n], starts.idle[n])])) } finally { mixer.stopAllAction(); mixer.uncacheRoot(rig); for (const s of cloned.values()) s.dispose() } return results
    })
    for (const name of ['idle', 'walk', 'special']) { const r = report.clipBoundaries[name]; assert(r.positionSeamM < .0005 && r.velocityDifferenceMps < .02 && r.accelerationDifferenceMps2 < .2, JSON.stringify(r)) }
    const r = report.clipBoundaries.specialIdle; assert(r.position < .0005 && r.velocity < .002 && r.acceleration < .05)
    assert(await page.evaluate(() => window.lingyuQA.before === window.lingyuQA.sourceSnapshot()))
  })
  for (const name of ['idle', 'walk', 'special']) await section(`motion-${name}`, async () => {
    await action(name === 'idle' ? 'walk' : 'idle'); await page.waitForTimeout(350); await action(name); await page.waitForTimeout(350)
    const duration = report.setup.clips.find(c => c.name === name).duration, samples = []; let wraps = 0, previous = -1, returned = false, captured = false
    const deadline = Date.now() + duration * 9000
    while (Date.now() < deadline) {
      const s = await snapshot(); healthy(s)
      if (name === 'special' && s.action === 'idle') { returned = true; break }
      assert.equal(s.action, name); if (previous >= 0 && s.time < previous - duration / 2) wraps++; previous = s.time; samples.push(s)
      if (!captured && s.time > duration * .25 && s.time < duration * .8) { await shot(`desktop-${name}`); captured = true }
      if (name !== 'special' && wraps >= 2) break
      await page.waitForTimeout(120)
    }
    assert(samples.length > 3 && captured); if (name === 'special') assert(returned); else assert(wraps >= 2)
    const maskMovement = Object.fromEntries(Object.keys(samples[0].probes).map(mask => [mask, Math.max(...samples.map(s => displacement(s.probes[mask], samples[0].probes[mask])))]))
    for (const [mask, d] of Object.entries(maskMovement)) assert(d > (mask === 'tail' ? .01 : .002), `${name} actual ${mask} movement ${d}`)
    report[name] = { wraps, returnedToIdle: returned, maskMovementM: maskMovement, minimumWorldHeightM: Math.min(...samples.map(s => s.low[1])), maximumRigidDriftM: Math.max(...samples.map(s => s.rigidDrift)), samples }
  })
  await section('transitions', async () => {
    report.transitions = []
    for (const name of ['walk', 'special', 'idle', 'special', 'walk', 'idle']) { let previous = await snapshot(), maximumStepM = 0; await action(name); for (let i = 0; i < 6; i++) { await page.waitForTimeout(70); const s = await snapshot(); healthy(s); for (const k of Object.keys(s.probes)) maximumStepM = Math.max(maximumStepM, displacement(s.probes[k], previous.probes[k])); previous = s } assert(maximumStepM < .2); report.transitions.push({ name, maximumStepM }) }
  })
  await section('ink-closeups', async () => {
    await page.addStyleTag({ content: '.qa-closeup .card,.qa-closeup .story-caption,.qa-closeup .scroll-wrap,.qa-closeup .controls,.qa-closeup .actions,.qa-closeup .title{visibility:hidden!important}' })
    await page.evaluate(() => { const q = window.lingyuQA, c = q.state.controls; q.savedCamera = { p: q.state.camera.position.clone(), t: c.target.clone(), lerp: c.target.lerp, min: c.minDistance, pmin: c.minPolarAngle, pmax: c.maxPolarAngle, damping: c.enableDamping, offset: q.state.camera.filmOffset }; c.target.lerp = function () { return this }; c.minDistance = .1; c.minPolarAngle = 0; c.maxPolarAngle = Math.PI; c.enableDamping = false; document.body.classList.add('qa-closeup') })
    try { for (const name of ['walk', 'special']) { await action(name); await page.waitForTimeout(450); for (const [mask, direction, distance] of [['face', [0, .1, 1], 1.5], ['hand_-1', [-.2, -.15, 1], .65], ['hand_+1', [.2, -.15, 1], .65], ['foot_-1', [0, .23, 1], .60], ['foot_+1', [0, .23, 1], .60]]) { await page.evaluate(({ mask, direction, distance }) => { const q = window.lingyuQA, T = q.T, positions = q.positions(q.root()), target = new T.Vector3(); for (const i of q.masks[mask]) target.add(new T.Vector3(...positions[i])); target.divideScalar(q.masks[mask].length); q.state.controls.target.copy(target); q.state.camera.filmOffset = 0; q.state.camera.updateProjectionMatrix(); q.state.camera.position.copy(target).add(new T.Vector3(...direction).normalize().multiplyScalar(distance)); q.state.controls.update() }, { mask, direction, distance }); const s = await snapshot(); healthy(s); assert.equal(s.action, name); await shot(`${name}-${mask}`) } } } finally { await page.evaluate(() => { const q = window.lingyuQA, c = q.state.controls, s = q.savedCamera; c.target.lerp = s.lerp; c.minDistance = s.min; c.minPolarAngle = s.pmin; c.maxPolarAngle = s.pmax; c.enableDamping = s.damping; c.target.copy(s.t); q.state.camera.position.copy(s.p); q.state.camera.filmOffset = s.offset; q.state.camera.updateProjectionMatrix(); c.update(); document.body.classList.remove('qa-closeup') }) }
  })
  report.responsive = []
  for (const [width, height] of [[1440, 900], [1024, 768], [800, 900], [641, 900], [390, 900], [390, 844]]) await section(`framing-${width}x${height}`, async () => {
    await page.setViewportSize({ width, height }); await action('idle'); await page.waitForTimeout(1000); const poses = []
    for (const name of ['idle', 'walk', 'special']) { await action(name === 'idle' ? 'walk' : 'idle'); await page.waitForTimeout(120); await action(name); const duration = report.setup.clips.find(c => c.name === name).duration; await page.waitForFunction(({ name, time }) => { const q = window.lingyuQA, t = q.root().userData.animationTime; return q.useApp.getState().action === name && t >= time && t < time + .5 }, { name, time: duration * .4 }, { timeout: 30000 }); const s = await snapshot(); healthy(s); poses.push({ name, ...s }); assert(s.screenLow[0] >= 8 && s.screenHigh[0] <= width - 8 && s.screenLow[1] >= 8 && s.screenHigh[1] <= height - 8, `Bounds ${s.screenLow} ${s.screenHigh}`); assert.equal(s.coveredVertices, 0, `UI overlaps ${s.coveredVertices} vertices`); assert.equal(s.clippedVertices, 0); await shot(`framing-${width}x${height}-${name}`) }
    const readability = await page.evaluate(() => { const panel = document.querySelector('.card[data-beast="lingyu"]'); if (!panel) throw new Error('Card missing'); const visible = n => { n.scrollIntoView({ block: 'nearest' }); const a = panel.getBoundingClientRect(), b = n.getBoundingClientRect(); return b.top >= Math.max(0, a.top) - 2 && b.bottom <= Math.min(innerHeight, a.bottom) + 2 }; const source = panel.querySelector('.card-source'), inferred = panel.querySelector('.card-inferred'); const r = { exactSource: source?.textContent.includes('陵魚人面，手足，魚身，在海中。') && source.textContent.includes('海内北经'), sourceReadable: !!source && visible(source), inferredReadable: inferred ? [...inferred.querySelectorAll('p')].every(visible) : false, overflow: panel.scrollWidth > panel.clientWidth || document.documentElement.scrollWidth > innerWidth }; panel.scrollTop = 0; return r }); assert(readability.exactSource && readability.sourceReadable && readability.inferredReadable && !readability.overflow); report.responsive.push({ width, height, poses, readability })
  })
  await section('strictmode-remount-ownership', async () => {
    report.remounts = []
    for (let cycle = 0; cycle < 3; cycle++) {
      await page.evaluate(() => { const q = window.lingyuQA, o = q.old = { skeletons: new Set(), materials: new Set(), geometries: new Set(), disposedSkeletons: 0, disposedMaterials: 0 }; q.root().traverse(n => { if (n.isSkinnedMesh) o.skeletons.add(n.skeleton); if (n.isMesh) { o.geometries.add(n.geometry); for (const m of Array.isArray(n.material) ? n.material : [n.material]) o.materials.add(m) } }); for (const s of o.skeletons) { if (!s.boneTexture) throw new Error('Rendered bone texture missing'); s.boneTexture.addEventListener('dispose', () => o.disposedSkeletons++) } for (const m of o.materials) m.addEventListener('dispose', () => o.disposedMaterials++) })
      const away = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready jiuweihu'), timeout: 30000 }); await page.evaluate(() => window.lingyuQA.useApp.getState().select('jiuweihu')); await away
      const back = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready lingyu'), timeout: 30000 }); await page.evaluate(() => window.lingyuQA.useApp.getState().select('lingyu')); await back; await page.waitForTimeout(400)
      const r = await page.evaluate(() => { const q = window.lingyuQA, o = q.old; return { snapshot: q.snapshot(), disposedSkeletons: o.disposedSkeletons, skeletons: o.skeletons.size, disposedMaterials: o.disposedMaterials, materials: o.materials.size, liveOldTextures: [...o.skeletons].filter(s => s.boneTexture).length, geometryReused: q.meshes().every(m => o.geometries.has(m.geometry)), cacheUnchanged: q.before === q.sourceSnapshot(), sharedDisposals: q.sharedDisposals } }); healthy(r.snapshot); assert.equal(r.disposedSkeletons, r.skeletons); assert.equal(r.disposedMaterials, r.materials); assert.equal(r.liveOldTextures, 0); assert(r.geometryReused && r.cacheUnchanged); assert.equal(r.sharedDisposals, 0); report.remounts.push(r)
    }
  })
  await section('controls-narration', async () => {
    await page.setViewportSize({ width: 390, height: 900 }); await page.waitForTimeout(500)
    for (const [name, label] of [['idle', '静'], ['walk', '行'], ['special', '神通']]) { const button = page.getByRole('button', { name: label, exact: true }), box = await button.boundingBox(); assert(box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 390 && box.y + box.height <= 900); await button.click(); assert.equal(await page.evaluate(() => window.lingyuQA.useApp.getState().action), name) }
    await page.waitForFunction(() => window.lingyuQA.useApp.getState().action === 'idle', null, { timeout: 20000 }); await page.locator('.card .story-btn').click(); await page.waitForTimeout(500); assert(await page.evaluate(() => window.lingyuQA.useApp.getState().narrating)); await page.locator('.card .story-btn').click(); assert.equal(await page.evaluate(() => window.lingyuQA.useApp.getState().narrating), false)
  })
  await section('runtime-errors', async () => assert.deepEqual(report.errors, []))
} catch (e) { report.failures.push({ section: 'setup', error: String(e), stack: e.stack }); await shot('failure-setup').catch(() => {}) }
finally { report.passed = report.failures.length === 0; await writeFile(join(out, 'report.json'), JSON.stringify(report, null, 2) + '\n'); await browser.close() }
console.log(JSON.stringify({ passed: report.passed, failures: report.failures, report: join(out, 'report.json') }))
if (!report.passed) process.exitCode = 1
