// Actual Stage acceptance with a local compressed candidate; no public promotion.
// node scripts/qa-zhulong-app.mjs BASE_URL NEW_OUTPUT CANDIDATE.glb [REST_REFERENCE.json]
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const SOURCE_SHA = '02097f47531438ad80c6aef6ca1f6043b73dc461097ac7b872967ec880dd8b74'
const REFERENCE_SHA = 'fd9bff7083eba3e0387eae7e6acf4bdc53fed4dc4be8a4edc15e7874bc86e316'
const root = fileURLToPath(new URL('../', import.meta.url))
const [base, outputArg, candidateArg, referenceArg] = process.argv.slice(2)
assert(base && outputArg && candidateArg, 'Base URL, new evidence directory and compressed candidate required')
const output = resolve(outputArg), candidate = resolve(candidateArg)
const referencePath = resolve(referenceArg ?? join(root, 'raw/_build/zhulong-native-rig-20261114/rest-reference.json'))
const bytes = await readFile(candidate), referenceBytes = await readFile(referencePath)
const sha = data => createHash('sha256').update(data).digest('hex')
assert(bytes.length < 15 * 1024 * 1024, 'Runtime candidate exceeds 15MiB')
assert.equal(sha(referenceBytes), REFERENCE_SHA, 'Unreviewed native rest reference')
const reference = JSON.parse(referenceBytes)
assert.equal(reference.sourceSha256, SOURCE_SHA)
assert.equal(reference.beast, 'zhulong')
assert.equal(reference.points.length, 31954)
const content = JSON.parse(await readFile(join(root, 'content/beasts/zhulong.json'), 'utf8'))
await mkdir(output, { recursive: false })
const report = { candidate, candidateSha256: sha(bytes), referencePath, restReferenceSha256: sha(referenceBytes), sourceSha256: SOURCE_SHA, productionAccepted: false, sections: {}, errors: [], failures: [], images: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const publicAsset = candidate === resolve(root, 'public/models/zhulong/body.glb')
report.publicAsset = publicAsset
if (!publicAsset) await page.route('**/models/zhulong/body.glb*', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
else {
  assert.equal(content.production?.modelReady, true, 'Public asset requires recorded readiness')
  const response = await fetch(new URL('/models/zhulong/body.glb', base))
  assert.equal(response.status, 200)
  assert.equal(sha(Buffer.from(await response.arrayBuffer())), sha(bytes), 'Served public asset differs')
}
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
await page.addInitScript(() => {
  window.zhulongNarrations = []
  const play = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function (...args) { window.zhulongNarrations.push(this); return play.apply(this, args) }
})
async function screenshot(name) { const path = join(output, `${name}.png`); await page.screenshot({ path }); report.images.push(path) }
async function section(name, work) {
  try { await work(); report.sections[name] = { passed: true } }
  catch (e) { report.failures.push({ section: name, error: String(e) }); report.sections[name] = { passed: false, error: String(e) }; await screenshot(`failure-${name}`).catch(() => {}) }
}
async function action(name) { await page.evaluate(a => window.zhulongQA.useApp.getState().setAction(a), name) }
async function snapshot() { return page.evaluate(() => window.zhulongQA.snapshot()) }
function healthy(s) {
  assert.equal(s.invalid, 0); assert.equal(s.bones, 26); assert.equal(s.triangles, 50000)
  assert.equal(s.meshes, 1); assert.equal(s.outlines, 1); assert(s.maxWeightError < .0001)
  assert.deepEqual(s.rootPosition, [0, 0, 0]); assert.deepEqual(s.rootScale, [1, 1, 1])
  assert(s.maxBoneScaleError < .000002, `Bone scale error ${s.maxBoneScaleError}`)
  assert(s.maxNonRootTranslationError < .00001, 'Fixed non-root bone lengths')
  assert(s.low[1] > .1, `Native body above ground: ${s.low[1]}`)
  assert(s.nativeDeformation, 'Independent geometry masks installed')
  assert(s.nativeDeformation.completeHeadDistanceDriftM < .001, 'Complete human head stays rigid')
  for (const [name, strain] of Object.entries(s.nativeDeformation.edgeStrain)) assert(strain < .08, `${name} source edge strain ${strain}`)
}
function displacement(a, b) {
  assert.equal(a.length, b.length)
  let maximum = 0
  for (let i = 0; i < a.length; i++) maximum = Math.max(maximum, Math.hypot(...a[i].map((v, k) => v - b[i][k])))
  return maximum
}

// Executed in the real Stage. Native indices ONLY select native-reference masks.
// Each compressed vertex is matched independently by geometry, never by weights
// or by assuming the compressed GLB retained the source's vertex order.
function installNativeReference(reference) {
  const q = window.zhulongQA, T = q.T
  if (reference.sourceSha256 !== '02097f47531438ad80c6aef6ca1f6043b73dc461097ac7b872967ec880dd8b74') throw new Error('Unexpected native source')
  if (reference.points.length !== 31954) throw new Error('Unexpected native vertex count')
  const points = reference.points.map(([x, y, z]) => [x, z, -y]), cell = .001, tolerance = .00025
  const key = c => c.join(',')
  const gridFor = values => {
    const grid = new Map()
    values.forEach((p, i) => { const k = key(p.map(v => Math.floor(v / cell))); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i) })
    return grid
  }
  const nearest = (xyz, grid, values) => {
    const c = xyz.map(v => Math.floor(v / cell))
    let best = -1, error = Infinity
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      for (const j of grid.get(key([c[0] + dx, c[1] + dy, c[2] + dz])) ?? []) {
        const e = Math.hypot(...xyz.map((v, k) => v - values[j][k]))
        if (e < error) { error = e; best = j }
      }
    }
    if (best < 0 || error > tolerance) throw new Error(`Unmatched rest position: ${error}m`)
    return { best, error }
  }
  const sourceMeshes = []
  q.source.updateMatrixWorld(true)
  q.source.traverse(n => { if (n.isSkinnedMesh) sourceMeshes.push(n) })
  if (sourceMeshes.length !== 1) throw new Error('Expected one native skinned surface')
  const source = sourceMeshes[0], count = source.geometry.attributes.position.count
  source.skeleton.update()
  const grid = gridFor(points), nativeIndex = [], rest = [], p = new T.Vector3()
  let maximumRestError = 0, maximumReverseRestError = 0
  for (let i = 0; i < count; i++) {
    source.getVertexPosition(i, p); source.localToWorld(p)
    const xyz = p.toArray(), match = nearest(xyz, grid, points)
    maximumRestError = Math.max(maximumRestError, match.error)
    nativeIndex.push(match.best); rest.push(xyz)
  }
  // Bidirectional coverage also rejects candidates missing native anatomy.
  const compressedGrid = gridFor(rest)
  for (const xyz of points) maximumReverseRestError = Math.max(maximumReverseRestError, nearest(xyz, compressedGrid, rest).error)
  const masks = {}
  for (const name of ['head', 'neck', 'body', 'tail', 'all_native']) {
    const indices = reference.masks[name]
    if (!indices?.length || indices.some(i => !Number.isInteger(i) || i < 0 || i >= points.length)) throw new Error(`Invalid native mask ${name}`)
    const set = new Set(indices)
    masks[name] = nativeIndex.flatMap((id, i) => set.has(id) ? [i] : [])
    if (!masks[name].length) throw new Error(`Missing native mask ${name}`)
  }
  const sample = (ids, n) => Array.from({ length: Math.min(n, ids.length) }, (_, i) => ids[Math.floor(i * ids.length / Math.min(n, ids.length))])
  const distance = (a, b) => Math.hypot(...a.map((v, k) => v - b[k]))
  const anchors = sample(masks.head, 3)
  const headDistances = anchors.map(i => masks.head.map(j => distance(rest[i], rest[j])))
  const index = source.geometry.index
  if (!index || index.count !== 150000) throw new Error('Native triangle topology missing')
  const edges = {}
  for (const name of ['neck', 'body', 'tail']) {
    const set = new Set(masks[name]), unique = new Map()
    for (let i = 0; i < index.count; i += 3) {
      const ids = [index.getX(i), index.getX(i + 1), index.getX(i + 2)]
      for (let k = 0; k < 3; k++) {
        const a = Math.min(ids[k], ids[(k + 1) % 3]), b = Math.max(ids[k], ids[(k + 1) % 3])
        if (set.has(a) && set.has(b)) {
          const d = distance(rest[a], rest[b])
          // Ignore sub-5mm edges where compression noise dominates strain.
          if (d >= .005) unique.set(`${a},${b}`, { a, b, d })
        }
      }
    }
    edges[name] = [...unique.values()]
    if (!edges[name].length) throw new Error(`Missing native edges ${name}`)
  }
  q.nativeMasks = masks
  const probes = Object.fromEntries(['head', 'neck', 'body', 'tail'].map(name => [name, sample(masks[name], 48)]))
  q.nativeMetrics = positions => {
    let completeHeadDistanceDriftM = 0
    anchors.forEach((anchor, k) => masks.head.forEach((id, i) => { completeHeadDistanceDriftM = Math.max(completeHeadDistanceDriftM, Math.abs(distance(positions[anchor], positions[id]) - headDistances[k][i])) }))
    const edgeStrain = {}
    for (const [name, values] of Object.entries(edges)) {
      let maximum = 0
      for (const e of values) maximum = Math.max(maximum, Math.abs(distance(positions[e.a], positions[e.b]) / e.d - 1))
      edgeStrain[name] = maximum
    }
    return { completeHeadDistanceDriftM, edgeStrain, maskProbes: Object.fromEntries(Object.entries(probes).map(([name, ids]) => [name, ids.map(i => positions[i])])) }
  }
  q.restBonePositions = Object.fromEntries(source.skeleton.bones.map(b => [b.name, b.position.toArray()]))
  return { sourceSha256: reference.sourceSha256, nativeVertices: points.length, matchedCompressedVertices: count, maximumRestError, maximumReverseRestError, matchingToleranceM: tolerance, maskMethod: 'Bidirectional rest-position geometry matching; no compressed-index or weight-derived masks', maskCounts: Object.fromEntries(Object.entries(masks).map(([name, ids]) => [name, ids.length])), completeHeadAnchorCount: anchors.length, edgeCounts: Object.fromEntries(Object.entries(edges).map(([name, values]) => [name, values.length])), minimumEdgeLengthM: .005 }
}

try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready zhulong'), timeout: 60000 })
  await page.goto(`${base}/?beast=zhulong&action=idle`); await ready; await page.waitForTimeout(750)
  report.setup = await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const module = suffix => { const url = resources.find(u => new URL(u).pathname.endsWith(suffix)); if (!url) throw new Error(`Missing Vite module ${suffix}`); return url }
    const fiber = await import(module('/@react-three_fiber.js'))
    const { useGLTF } = await import(module('/@react-three_drei.js'))
    const { useApp } = await import(module('/src/app/store.ts'))
    const { BEASTS } = await import(module('/src/app/beasts.ts'))
    const beast = BEASTS.find(b => b.id === 'zhulong'), previewReadyOverride = !beast.ready
    // Browser-local candidate preview only. This never edits ready/provenance files.
    if (previewReadyOverride) beast.ready = true
    const T = await import(module('/three.js')), body = useGLTF('/models/zhulong/body.glb')
    const q = window.zhulongQA = { T, useApp, source: body.scene, animations: body.animations, state: [...fiber._roots.values()][0].store.getState(), sharedDisposals: 0 }
    q.root = () => { const root = q.state.scene.getObjectByName('zhulong_root'); if (!root) throw new Error('Zhulong Stage root missing'); return root }
    q.meshes = () => { const list = []; q.root().traverse(n => { if (n.isMesh && !n.userData.inkOutline) list.push(n) }); return list }
    q.sourceSnapshot = () => {
      const list = []
      q.source.traverse(n => list.push({ uuid: n.uuid, children: n.children.map(c => c.uuid), position: n.position.toArray(), quaternion: n.quaternion.toArray(), scale: n.scale.toArray(), geometry: n.geometry?.uuid, skeleton: n.skeleton?.uuid, materials: (Array.isArray(n.material) ? n.material : n.material ? [n.material] : []).map(m => m.uuid) }))
      return JSON.stringify(list)
    }
    q.before = q.sourceSnapshot()
    const shared = new Set()
    q.source.traverse(n => { if (n.geometry) shared.add(n.geometry); for (const m of Array.isArray(n.material) ? n.material : n.material ? [n.material] : []) { shared.add(m); for (const v of Object.values(m)) if (v?.isTexture) shared.add(v) } })
    for (const resource of shared) resource.addEventListener('dispose', () => q.sharedDisposals++)
    q.snapshot = () => {
      q.state.scene.updateMatrixWorld(true)
      let invalid = 0, bones = 0, outlines = 0, triangles = 0, vertices = 0, maxWeightError = 0, maxBoneScaleError = 0, maxNonRootTranslationError = 0
      const p = new T.Vector3(), low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity], screenLow = [Infinity, Infinity], screenHigh = [-Infinity, -Infinity], positions = []
      const blockers = ['.card', '.actions', '.scroll-wrap', '.controls', '.title'].flatMap(selector => [...document.querySelectorAll(selector)].filter(e => getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none').map(e => e.getBoundingClientRect()))
      let coveredVertices = 0, clippedVertices = 0
      q.root().traverse(n => {
        if (n.isBone) {
          bones++; maxBoneScaleError = Math.max(maxBoneScaleError, ...n.scale.toArray().map(v => Math.abs(v - 1)))
          const rest = q.restBonePositions?.[n.name]
          if (rest && n.name !== 'root') maxNonRootTranslationError = Math.max(maxNonRootTranslationError, ...n.position.toArray().map((v, k) => Math.abs(v - rest[k])))
        }
        if (n.userData.inkOutline) outlines++
        if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++
      })
      for (const mesh of q.meshes()) {
        if (!mesh.isSkinnedMesh) throw new Error('Native body must be skinned')
        mesh.skeleton.update()
        const a = mesh.geometry.attributes
        triangles += (mesh.geometry.index?.count ?? a.position.count) / 3; vertices += a.position.count
        for (const key of ['position', 'normal', 'skinWeight', 'skinIndex']) if (!a[key] || !Array.from(a[key].array).every(Number.isFinite)) invalid++
        for (let i = 0; i < a.position.count; i++) {
          let sum = 0
          for (let k = 0; k < 4; k++) { const w = a.skinWeight.getComponent(i, k), joint = a.skinIndex.getComponent(i, k); if (w < 0 || !Number.isInteger(joint) || joint < 0 || joint >= mesh.skeleton.bones.length) invalid++; sum += w }
          maxWeightError = Math.max(maxWeightError, Math.abs(sum - 1))
          mesh.getVertexPosition(i, p); mesh.localToWorld(p)
          const xyz = p.toArray(); positions.push(xyz)
          if (!xyz.every(Number.isFinite)) invalid++
          for (let k = 0; k < 3; k++) { low[k] = Math.min(low[k], xyz[k]); high[k] = Math.max(high[k], xyz[k]) }
          p.project(q.state.camera)
          if (p.z < -1 || p.z > 1) clippedVertices++
          const xy = [(p.x + 1) * innerWidth / 2, (1 - p.y) * innerHeight / 2]
          for (let k = 0; k < 2; k++) { screenLow[k] = Math.min(screenLow[k], xy[k]); screenHigh[k] = Math.max(screenHigh[k], xy[k]) }
          if (blockers.some(r => xy[0] > r.left && xy[0] < r.right && xy[1] > r.top && xy[1] < r.bottom)) coveredVertices++
        }
      }
      return { nativeDeformation: q.nativeMetrics?.(positions), coveredVertices, clippedVertices, invalid, bones, outlines, meshes: q.meshes().length, triangles, vertices, maxWeightError, maxBoneScaleError, maxNonRootTranslationError, low, high, screenLow, screenHigh, time: q.root().userData.animationTime, action: useApp.getState().action, rootPosition: q.root().position.toArray(), rootScale: q.root().scale.toArray() }
    }
    return { previewReadyOverride, clips: body.animations.map(c => ({ name: c.name, duration: c.duration })), baseline: q.snapshot() }
  })
  await section('native-reference', async () => { report.nativeReference = await page.evaluate(installNativeReference, reference) })
  await section('native-stage', async () => {
    healthy(await snapshot())
    for (const [name, duration] of [['idle', 6], ['walk', 4], ['special', 6]]) assert(report.setup.clips.some(c => c.name === name && Math.abs(c.duration - duration) < .00001), `${name} ${duration}s`)
  })
  await section('clip-boundaries', async () => {
    report.clipBoundaries = await page.evaluate(() => {
      const q = window.zhulongQA, T = q.T, rig = q.source.clone(true), originals = [], copies = []
      q.source.traverse(n => originals.push(n)); rig.traverse(n => copies.push(n))
      const byId = new Map(originals.map((n, i) => [n.uuid, copies[i]])), skeletons = []
      for (let i = 0; i < originals.length; i++) if (originals[i].isSkinnedMesh) {
        const s = originals[i].skeleton
        copies[i].skeleton = new T.Skeleton(s.bones.map(b => byId.get(b.uuid)), s.boneInverses.map(m => m.clone()))
        skeletons.push(copies[i].skeleton)
      }
      const mesh = copies.find(n => n.isSkinnedMesh), mixer = new T.AnimationMixer(rig), p = new T.Vector3(), results = {}, starts = {}
      const dt = .01
      const delta = (a, b) => { let maximum = 0; for (let i = 0; i < a.length; i++) maximum = Math.max(maximum, Math.hypot(...a[i].map((v, k) => v - b[i][k]))); return maximum }
      try {
        for (const clip of q.animations) {
          const action = mixer.clipAction(clip)
          const at = t => {
            action.reset().setLoop(T.LoopOnce, 1); action.clampWhenFinished = true; action.play(); mixer.setTime(t)
            rig.updateMatrixWorld(true); mesh.skeleton.update()
            return Array.from({ length: mesh.geometry.attributes.position.count }, (_, i) => { mesh.getVertexPosition(i, p); mesh.localToWorld(p); return p.toArray() })
          }
          const [a, b, c, d, e, f] = [0, dt, 2 * dt, clip.duration - 2 * dt, clip.duration - dt, clip.duration].map(at)
          const derivative = (x, y) => x.map((p, i) => p.map((v, k) => (v - y[i][k]) / dt))
          const acceleration = (x, y, z) => x.map((p, i) => p.map((v, k) => (v - 2 * y[i][k] + z[i][k]) / dt ** 2))
          const velocityStart = derivative(b, a), accelerationStart = acceleration(c, b, a)
          starts[clip.name] = { position: a, velocity: velocityStart, acceleration: accelerationStart }
          results[clip.name] = { positionSeamM: delta(a, f), wrapVelocityDifferenceMps: delta(velocityStart, derivative(f, e)), wrapAccelerationDifferenceMps2: delta(accelerationStart, acceleration(f, e, d)), dt, sampledVertices: a.length }
          mixer.stopAllAction()
        }
        results.specialIdleEndpoint = Object.fromEntries(['position', 'velocity', 'acceleration'].map(name => [name, delta(starts.special[name], starts.idle[name])]))
        return results
      } finally { mixer.stopAllAction(); mixer.uncacheRoot(rig); for (const s of skeletons) s.dispose() }
    })
    for (const name of ['idle', 'walk', 'special']) {
      const c = report.clipBoundaries[name]
      assert(c.positionSeamM < .0005); assert(c.wrapVelocityDifferenceMps < .01); assert(c.wrapAccelerationDifferenceMps2 < .1)
    }
    const e = report.clipBoundaries.specialIdleEndpoint
    assert(e.position < .0005 && e.velocity < .002 && e.acceleration < .05)
    assert(await page.evaluate(() => window.zhulongQA.before === window.zhulongQA.sourceSnapshot()), 'Boundary QA left cached scene unchanged')
  })
  for (const name of ['idle', 'walk', 'special']) await section(`motion-${name}`, async () => {
    await action(name === 'idle' ? 'walk' : 'idle'); await page.waitForTimeout(400); await action(name); await page.waitForTimeout(400)
    const samples = [], duration = report.setup.clips.find(c => c.name === name).duration
    const deadline = Date.now() + duration * 7000 + 5000
    let wraps = 0, previousTime = -1, returned = false, captured = false
    while (Date.now() < deadline) {
      const s = await snapshot(); healthy(s)
      if (name === 'special' && s.action === 'idle') { returned = true; break }
      assert.equal(s.action, name); assert(Number.isFinite(s.time), 'Actual mixer time exposed')
      if (previousTime >= 0 && s.time < previousTime - duration / 2) wraps++
      previousTime = s.time; samples.push(s)
      if (!captured && s.time >= duration / 3 && s.time <= duration * .8) { await screenshot(`desktop-${name}`); captured = true }
      if (name !== 'special' && wraps >= 2) break
      await page.waitForTimeout(100)
    }
    assert(samples.length >= 4)
    if (name === 'special') { assert(returned, 'Special actually returned to idle'); report.specialReturnedToIdle = true }
    else assert(wraps >= 2, `${name} observed two actual mixer wraps`)
    const maskMaximumDisplacementM = {}
    for (const mask of ['head', 'neck', 'body', 'tail']) {
      maskMaximumDisplacementM[mask] = Math.max(...samples.map(s => displacement(s.nativeDeformation.maskProbes[mask], samples[0].nativeDeformation.maskProbes[mask])))
      const minimum = mask === 'neck' ? .0005 : mask === 'body' || mask === 'tail' ? .02 : .001
      assert(maskMaximumDisplacementM[mask] > minimum, `${name} actual ${mask} displacement`)
    }
    assert(captured, `${name} screenshot captured during the actual clip`)
    report[name] = { samples, wraps, maskMaximumDisplacementM }
  })
  await section('transitions', async () => {
    report.transitions = []
    for (const name of ['special', 'walk', 'idle', 'special', 'idle', 'walk']) {
      let previous = await snapshot(), maximumStepM = 0
      await action(name)
      for (let step = 0; step < 6; step++) {
        await page.waitForTimeout(50)
        const s = await snapshot(); healthy(s)
        for (const mask of ['head', 'neck', 'body', 'tail']) maximumStepM = Math.max(maximumStepM, displacement(s.nativeDeformation.maskProbes[mask], previous.nativeDeformation.maskProbes[mask]))
        previous = s
      }
      assert(maximumStepM < .2, `${name} crossfade displacement ${maximumStepM}m`)
      report.transitions.push({ action: name, maximumStepM })
    }
  })
  await section('native-ink-closeups', async () => {
    await action('idle'); await page.waitForTimeout(400)
    await page.addStyleTag({content:'.qa-native-closeup .card,.qa-native-closeup .story-caption,.qa-native-closeup .scroll-wrap,.qa-native-closeup .controls,.qa-native-closeup .actions,.qa-native-closeup .title{visibility:hidden!important}'})
    await page.evaluate(()=>{
      const q=window.zhulongQA,c=q.state.controls
      q.savedCamera={position:q.state.camera.position.clone(),target:c.target.clone(),lerp:c.target.lerp,minDistance:c.minDistance,minPolarAngle:c.minPolarAngle,maxPolarAngle:c.maxPolarAngle,damping:c.enableDamping,offset:q.state.camera.filmOffset}
      c.target.lerp=function(){return this};c.minDistance=.2;c.minPolarAngle=0;c.maxPolarAngle=Math.PI;c.enableDamping=false
      document.body.classList.add('qa-native-closeup')
    })
    try {
      for(const name of ['walk','special']) {
        await action(name);await page.waitForTimeout(1300)
        for(const [view,mask,direction,distance] of [['head-front','head',[0,.05,1],1.35],['neck-side','neck',[1,.18,.2],1.4],['neck-back','neck',[0,.35,-1],1.4]]) {
          await page.evaluate(({mask,direction,distance})=>{
            const q=window.zhulongQA,T=q.T,mesh=q.meshes()[0],point=new T.Vector3(),target=new T.Vector3(),ids=q.nativeMasks[mask]
            q.state.scene.updateMatrixWorld(true);mesh.skeleton.update()
            for(const id of ids){mesh.getVertexPosition(id,point);mesh.localToWorld(point);target.add(point)}
            target.divideScalar(ids.length);q.state.controls.target.copy(target)
            q.state.camera.filmOffset=0;q.state.camera.updateProjectionMatrix()
            q.state.camera.position.copy(target).add(new T.Vector3(...direction).normalize().multiplyScalar(distance));q.state.controls.update()
          },{mask,direction,distance})
          healthy(await snapshot());await screenshot(`${name}-${view}`)
        }
      }
    } finally {
      await page.evaluate(()=>{
        const q=window.zhulongQA,c=q.state.controls,s=q.savedCamera
        c.target.lerp=s.lerp;c.minDistance=s.minDistance;c.minPolarAngle=s.minPolarAngle;c.maxPolarAngle=s.maxPolarAngle;c.enableDamping=s.damping
        c.target.copy(s.target);q.state.camera.position.copy(s.position);q.state.camera.filmOffset=s.offset;q.state.camera.updateProjectionMatrix();c.update()
        document.body.classList.remove('qa-native-closeup')
      })
    }
  })
  report.responsive = []
  for (const { width, height } of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }, { width: 800, height: 900 }, { width: 641, height: 900 }, { width: 390, height: 900 }, { width: 390, height: 844 }]) await section(`responsive-${width}x${height}`, async () => {
    await action('idle'); await page.setViewportSize({ width, height }); await page.waitForTimeout(1200)
    const poses = []
    for (const name of ['idle', 'walk', 'special']) {
      await action(name === 'idle' ? 'walk' : 'idle'); await page.waitForTimeout(100); await action(name); await page.waitForTimeout(100)
      const duration = report.setup.clips.find(c => c.name === name).duration
      for (const phase of [.2, .5, .8]) {
        await page.waitForFunction(({ name, time }) => {
          const q = window.zhulongQA, t = q.root().userData.animationTime
          return q.useApp.getState().action === name && t >= time && t <= time + .25
        }, { name, time: duration * phase }, { timeout: 25000 })
        const s = await snapshot(); healthy(s); poses.push({ name, phase, ...s })
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal page overflow')
        assert(s.screenLow[0] >= 8 && s.screenHigh[0] <= width - 8 && s.screenLow[1] >= 8 && s.screenHigh[1] <= height - 8, `Full native body frame at ${width}x${height}, ${name} phase ${phase}`)
        assert.equal(s.clippedVertices, 0); assert.equal(s.coveredVertices, 0, `Model clear of source card and controls at ${width}x${height}, ${name} phase ${phase}`)
        if (phase === .5) await screenshot(`responsive-${width}x${height}-${name}`)
      }
    }
    await action('idle'); await page.waitForTimeout(350)
    await screenshot(`responsive-${width}x${height}`)
    const readability = await page.evaluate(expected => {
      const panel = document.querySelector('.card[data-beast="zhulong"]')
      if (!panel) throw new Error('Zhulong source card missing')
      const sources = [...panel.querySelectorAll('.card-source')], design = panel.querySelector('.card-inferred')
      const visible = node => {
        node.scrollIntoView({ block: 'nearest' })
        const a = panel.getBoundingClientRect(), b = node.getBoundingClientRect(), style = getComputedStyle(node)
        return style.display !== 'none' && style.visibility !== 'hidden' && b.top >= Math.max(0, a.top) - 2 && b.bottom <= Math.min(innerHeight, a.bottom) + 2 && b.width > 0
      }
      const sourceResults = expected.map((s, i) => ({ exactQuote: sources[i]?.textContent.includes(s.text) && sources[i]?.textContent.includes(s.book), readable: !!sources[i] && visible(sources[i]) }))
      const designs = design ? [...design.querySelectorAll('p')].map(visible) : []
      const result = { sourceCount: sources.length, sourceResults, designItemCount: designs.length, designs, horizontalOverflow: panel.scrollWidth > panel.clientWidth }
      panel.scrollTop = 0
      return result
    }, content.source)
    assert.equal(readability.sourceCount, content.source.length)
    assert(readability.sourceResults.every(s => s.exactQuote && s.readable), 'Each full original quotation is readable')
    assert.equal(readability.designItemCount, content.inferred.length); assert(readability.designs.every(Boolean)); assert(!readability.horizontalOverflow)
    report.responsive.push({ width, height, poses, readability })
  })
  await section('remount-ownership', async () => {
    report.remounts = []
    for (let cycle = 0; cycle < 3; cycle++) {
      await page.evaluate(() => {
        const q = window.zhulongQA, o = q.old = { skeletons: new Set(), materials: new Set(), geometries: new Set(), disposedSkeletons: 0, disposedMaterials: 0 }
        q.root().traverse(n => { if (n.isSkinnedMesh) o.skeletons.add(n.skeleton); if (n.isMesh) { o.geometries.add(n.geometry); for (const m of Array.isArray(n.material) ? n.material : [n.material]) o.materials.add(m) } })
        for (const s of o.skeletons) { if (!s.boneTexture) throw new Error('Rendered bone texture missing'); s.boneTexture.addEventListener('dispose', () => o.disposedSkeletons++) }
        for (const m of o.materials) m.addEventListener('dispose', () => o.disposedMaterials++)
      })
      const away = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready jiuweihu'), timeout: 30000 })
      await page.evaluate(() => window.zhulongQA.useApp.getState().select('jiuweihu')); await away
      const back = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready zhulong'), timeout: 30000 })
      await page.evaluate(() => window.zhulongQA.useApp.getState().select('zhulong')); await back; await page.waitForTimeout(500)
      const result = await page.evaluate(() => {
        const q = window.zhulongQA, o = q.old
        return { snapshot: q.snapshot(), disposedSkeletons: o.disposedSkeletons, skeletons: o.skeletons.size, disposedMaterials: o.disposedMaterials, materials: o.materials.size, liveOldTextures: [...o.skeletons].filter(s => s.boneTexture).length, geometryReused: q.meshes().every(m => o.geometries.has(m.geometry)), cacheUnchanged: q.before === q.sourceSnapshot(), sharedDisposals: q.sharedDisposals }
      })
      report.remounts.push(result); healthy(result.snapshot)
      assert.equal(result.disposedSkeletons, result.skeletons); assert.equal(result.disposedMaterials, result.materials); assert.equal(result.liveOldTextures, 0)
      assert(result.geometryReused && result.cacheUnchanged); assert.equal(result.sharedDisposals, 0)
    }
  })
  await section('controls-narration', async () => {
    await page.setViewportSize({ width: 390, height: 900 }); await page.waitForTimeout(700)
    for (const [name, label] of [['idle', '静'], ['walk', '行'], ['special', '神通']]) {
      const button = page.getByRole('button', { name: label, exact: true }), box = await button.boundingBox()
      assert(box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 390 && box.y + box.height <= 900)
      await button.click(); assert.equal(await page.evaluate(() => window.zhulongQA.useApp.getState().action), name)
    }
    await page.waitForFunction(() => window.zhulongQA.useApp.getState().action === 'idle', null, { timeout: 20000 })
    await page.locator('.card .story-btn').click()
    await page.waitForFunction(() => window.zhulongNarrations.some(e => e.src.includes('/zhulong.mp3') && !e.paused && e.currentTime > .15), null, { timeout: 30000 })
    report.narrationPlayback = await page.evaluate(() => window.zhulongNarrations.filter(e => e.src.includes('/zhulong.mp3')).map(e => ({ src: e.src, currentTime: e.currentTime, paused: e.paused, readyState: e.readyState })))
    await page.locator('.card .story-btn').click()
    assert(await page.evaluate(() => window.zhulongNarrations.filter(e => e.src.includes('/zhulong.mp3')).every(e => e.paused)))
    assert.equal(await page.evaluate(() => window.zhulongQA.useApp.getState().narrating), false)
    report.narrationPlayedAndStopped = true
  })
  await section('runtime-errors', async () => assert.deepEqual(report.errors, []))
} catch (e) { report.failures.push({ section: 'setup', error: String(e), stack: e.stack }); await screenshot('failure-setup').catch(() => {}) }
finally { report.passed = report.failures.length === 0; await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n'); await browser.close() }
console.log(JSON.stringify({ passed: report.passed, previewReadyOverride: report.setup?.previewReadyOverride, failures: report.failures, report: join(output, 'report.json') }))
if (!report.passed) process.exitCode = 1
