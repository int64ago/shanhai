// Actual compressed asset and StrictMode Stage QA; readiness is never changed on disk.
// node scripts/qa-xingtian-app.mjs BASE_URL NEW_EVIDENCE_DIRECTORY
import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { launchQABrowser } from './lib/browser.mjs'

const root = fileURLToPath(new URL('../', import.meta.url))
const [base = 'http://127.0.0.1:5203', output = '/tmp/xingtian-qa', diagnosticAsset] = process.argv.slice(2)
const out = resolve(output), sourceSHA = '7b8f311778d006197a22113b397193a651d66fb3a2de9801d1da2ede32622cc8'
await mkdir(out, { recursive: false })
const sha = b => createHash('sha256').update(b).digest('hex')
const asset = await readFile(diagnosticAsset ? resolve(diagnosticAsset) : join(root, 'public/models/xingtian/body.glb'))
const source = await readFile(join(root, 'raw/xingtian-production-20261115-closed-grip-whole-v7-high/base_high_pbr.glb'))
assert.equal(sha(source), sourceSHA)
const response = await fetch(new URL('/models/xingtian/body.glb', base))
assert.equal(response.status, 200)
if (!diagnosticAsset) assert.equal(sha(Buffer.from(await response.arrayBuffer())), sha(asset))
const jsonLength = source.readUInt32LE(12), doc = JSON.parse(source.subarray(20, 20 + jsonLength))
assert.deepEqual(doc.nodes, [{ mesh: 0, name: 'model' }], 'Native source transform changed')
const acc = doc.accessors[doc.meshes[0].primitives[0].attributes.POSITION], view = doc.bufferViews[acc.bufferView]
assert.equal(acc.componentType, 5126)
const points = Array.from({ length: acc.count }, (_, i) => Array.from({ length: 3 }, (_, k) => source.readFloatLE(28 + jsonLength + (view.byteOffset ?? 0) + (acc.byteOffset ?? 0) + i * (view.byteStride ?? 12) + k * 4)))
const low = [0, 1, 2].map(k => Math.min(...points.map(p => p[k]))), high = [0, 1, 2].map(k => Math.max(...points.map(p => p[k])))
const scale = 1 / (high[1] - low[1])
const reference = points.map(p => [(p[0] - (low[0] + high[0]) / 2) * scale, (p[1] - low[1]) * scale, (p[2] - (low[2] + high[2]) / 2) * scale])
const report = { candidateOnly: true, passed: false, sourceSHA256: sourceSHA, assetSHA256: sha(asset), assetBytes: asset.length, errors: [], snapshots: [], images: [] }
const browser = await launchQABrowser()
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  if (diagnosticAsset) await page.route('**/models/xingtian/body.glb*', route => route.fulfill({ body: asset, contentType: 'model/gltf-binary' }))
  page.on('pageerror', e => report.errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
  page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
  const ready = id => page.waitForSelector(`[data-stage-beast="${id}"][data-stage-state="ready"]`, { state: 'attached' })
  await page.goto(`${base}/?beast=jingwei&action=idle`)
  await ready('jingwei')
  report.setup = await page.evaluate(async () => {
    await import('/src/beasts/xingtian/Xingtian.tsx')
    const url = part => { const u = performance.getEntriesByType('resource').map(r => r.name).find(u => new URL(u).pathname.includes(part)); if (!u) throw Error(`Missing module ${part}`); return u }
    const fiber = await import(url('@react-three_fiber'))
    const { useGLTF } = await import(url('@react-three_drei'))
    const { useApp } = await import(url('/src/app/store.ts'))
    const { BEASTS } = await import(url('/src/app/beasts.ts'))
    const T = await import(url('/three.js'))
    const { clone } = await import(url('SkeletonUtils'))
    useGLTF.preload('/models/xingtian/body.glb')
    let gltf
    for (;;) { try { gltf = useGLTF('/models/xingtian/body.glb'); break } catch (p) { if (!p?.then) throw p; await p } }
    const entry = BEASTS.find(b => b.id === 'xingtian'), publishedReady = entry.ready
    entry.ready = true // isolated browser preview only, for the complete action UI
    const q = window.xingtianQA = { T, clone, gltf, useApp, state: [...fiber._roots.values()][0].store.getState(), sharedDisposals: 0 }
    q.cacheSnapshot = () => {
      const rows = []
      gltf.scene.traverse(n => rows.push([n.uuid, n.name, n.children.map(c => c.uuid), n.position.toArray(), n.quaternion.toArray(), n.scale.toArray(), n.geometry?.uuid, n.skeleton?.uuid, (Array.isArray(n.material) ? n.material : n.material ? [n.material] : []).map(m => m.uuid)]))
      return JSON.stringify(rows)
    }
    q.before = q.cacheSnapshot()
    const shared = new Set()
    gltf.scene.traverse(n => {
      if (n.geometry) shared.add(n.geometry)
      if (n.skeleton) shared.add(n.skeleton)
      for (const m of Array.isArray(n.material) ? n.material : n.material ? [n.material] : []) { shared.add(m); for (const v of Object.values(m)) if (v?.isTexture) shared.add(v) }
    })
    for (const r of shared) r.addEventListener?.('dispose', () => q.sharedDisposals++)
    useApp.getState().select('xingtian')
    return { publishedReady, cachedResourcesWatched: shared.size }
  })
  await ready('xingtian')
  report.candidateOnly = !report.setup.publishedReady
  // This detached clone uses the actual browser-decoded Meshopt asset and Three's
  // skinning implementation. Native masks are matched by positions, never weights.
  report.geometrySkippedForFramingIteration = !!process.env.XINGTIAN_QA_FRAMING_ONLY
  if (!report.geometrySkippedForFramingIteration) {
  report.geometry = await page.evaluate(reference => {
    const q = window.xingtianQA, T = q.T, scene = q.clone(q.gltf.scene)
    scene.updateMatrixWorld(true)
    const meshes = [], skins = []
    scene.traverse(n => { if (n.isMesh) meshes.push(n); if (n.isSkinnedMesh) skins.push(n) })
    if (skins.length !== 1) throw Error('One native body skin required')
    const body = skins[0], count = body.geometry.attributes.position.count
    const vec = new T.Vector3(), rest = [], index = body.geometry.index
    const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
    const cell = .0003, key = p => p.map(v => Math.floor(v / cell)).join(',')
    const grid = new Map()
    reference.forEach((p, i) => { const k = key(p); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i) })
    const match = p => {
      const c = p.map(v => Math.floor(v / cell)); let best = -1, d = Infinity
      for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) for (const i of grid.get([c[0] + x, c[1] + y, c[2] + z].join(',')) ?? []) {
        const e = distance(p, reference[i]); if (e < d) { best = i; d = e }
      }
      if (d > .00008) throw Error(`Unmatched compressed native vertex ${d}`)
      return { id: best, d }
    }
    const nativeIds = [], covered = new Set(); let maximumRestError = 0, invalid = 0, maxWeightError = 0
    body.skeleton.update()
    for (let i = 0; i < count; i++) {
      body.getVertexPosition(i, vec); body.localToWorld(vec); const p = vec.toArray(), m = match(p)
      rest.push(p); nativeIds.push(m.id); covered.add(key(reference[m.id])); maximumRestError = Math.max(maximumRestError, m.d)
      const w = body.geometry.attributes.skinWeight
      maxWeightError = Math.max(maxWeightError, Math.abs(w.getX(i) + w.getY(i) + w.getZ(i) + w.getW(i) - 1))
    }
    // Reverse matching detects missing source extremities even after vertex welding.
    const compressed = new Map()
    rest.forEach((p, i) => { const k = key(p); if (!compressed.has(k)) compressed.set(k, []); compressed.get(k).push(i) })
    let maximumReverseRestError = 0
    for (const p of reference) {
      const c = p.map(v => Math.floor(v / cell)); let d = Infinity
      for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) for (const i of compressed.get([c[0] + x, c[1] + y, c[2] + z].join(',')) ?? []) d = Math.min(d, distance(p, rest[i]))
      maximumReverseRestError = Math.max(maximumReverseRestError, d)
    }
    const masks = { chest: [], foot_l: [], foot_r: [], hand_l: [], hand_r: [] }
    const wrists = { l: [.3887363115, .5598528196, .0780318487], r: [-.3925834337, .5601599138, .0815318496] }
    const elbows = { l: [.3090565158, .6748950034, .0089321492], r: [-.3078872928, .6750952959, .0019264376] }
    const axes = Object.fromEntries(['l', 'r'].map(s => [s, new T.Vector3(...wrists[s]).sub(new T.Vector3(...elbows[s])).normalize().toArray()]))
    nativeIds.forEach((id, i) => {
      const p = reference[id]
      if (Math.abs(p[0]) < .18 && p[1] > .51) masks.chest.push(i)
      for (const [s, sign] of [['l', 1], ['r', -1]]) {
        if (sign * p[0] > 0 && Math.abs(p[0]) < .25 && p[1] < .112) masks[`foot_${s}`].push(i)
        const distal = p.reduce((sum, v, k) => sum + (v - wrists[s][k]) * axes[s][k], 0)
        if (sign * p[0] > .33 && distal >= -.006) masks[`hand_${s}`].push(i)
      }
    })
    const anchors = Object.fromEntries(Object.entries(masks).map(([name, ids]) => [name, [ids[0], ids[Math.floor(ids.length / 2)], ids.at(-1)]]))
    for (const mesh of meshes) for (const name of ['position', 'normal']) {
      const a = mesh.geometry.attributes[name]
      for (let i = 0; i < a.count; i++) if (![a.getX(i), a.getY(i), a.getZ(i)].every(Number.isFinite)) invalid++
    }
    const rigid = {}, clips = {}, toolAttachment = {}, support = { maximumStanceVertexDrift: 0, maximumSupportSoleHeight: 0, minimumVertexHeight: Infinity }
    const tools = meshes.filter(m => !m.isSkinnedMesh)
    const toolRest = new Map(tools.map(m => [m.name, m.matrixWorld.clone()]))
    const boneRest = new Map(['l', 'r'].map(s => [s, scene.getObjectByName(`xingtian_wrist_${s}`).matrixWorld.clone()]))
    // Triangle BVH surface intersection. AABBs prune every tool/body pair;
    // segment/triangle tests then use the actual decoded triangle coordinates.
    const faces = Array.from({ length: index.count / 3 }, (_, i) => [index.getX(i * 3), index.getX(i * 3 + 1), index.getX(i * 3 + 2)])
    const makeTree = (positions, ids) => {
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
      for (const i of ids) for (const j of faces[i]) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], positions[j][k]); hi[k] = Math.max(hi[k], positions[j][k]) }
      if (ids.length <= 16) return { lo, hi, ids }
      const axis = hi.map((v, k) => v - lo[k]).indexOf(Math.max(...hi.map((v, k) => v - lo[k])))
      ids.sort((a, b) => faces[a].reduce((s, i) => s + positions[i][axis], 0) - faces[b].reduce((s, i) => s + positions[i][axis], 0))
      const mid = Math.floor(ids.length / 2)
      return { lo, hi, children: [makeTree(positions, ids.slice(0, mid)), makeTree(positions, ids.slice(mid))] }
    }
    const segment = (p, end, a, b, c) => {
      const d = new T.Vector3(...end).sub(new T.Vector3(...p)), length = d.length()
      if (length < 1e-10) return false
      const ray = new T.Ray(new T.Vector3(...p), d.multiplyScalar(1 / length))
      const hit = ray.intersectTriangle(new T.Vector3(...a), new T.Vector3(...b), new T.Vector3(...c), false, vec)
      return !!hit && hit.distanceTo(ray.origin) < length - 1e-8 && hit.distanceTo(ray.origin) > 1e-8
    }
    const cross = (a, b) => {
      for (let i = 0; i < 3; i++) if (segment(a[i], a[(i + 1) % 3], ...b) || segment(b[i], b[(i + 1) % 3], ...a)) return true
      return false
    }
    const collisions = { samples: 0, intersections: [], method: 'Actual compressed triangle surfaces; BVH and bidirectional segment/triangle intersection, excluding exact coplanarity' }
    const collision = positions => {
      const tree = makeTree(positions, faces.map((_, i) => i))
      for (const mesh of tools) {
        const p = [], v = new T.Vector3(), a = mesh.geometry.attributes.position, ix = mesh.geometry.index
        for (let i = 0; i < a.count; i++) { v.fromBufferAttribute(a, i).applyMatrix4(mesh.matrixWorld); p.push(v.toArray()) }
        const scan = (node, triangle, lo, hi) => {
          if (lo.some((v, k) => v > node.hi[k] || hi[k] < node.lo[k])) return false
          if (node.children) return node.children.some(n => scan(n, triangle, lo, hi))
          return node.ids.some(i => cross(triangle, faces[i].map(j => positions[j])))
        }
        for (let i = 0; i < ix.count; i += 3) {
          const triangle = [p[ix.getX(i)], p[ix.getX(i + 1)], p[ix.getX(i + 2)]]
          const lo = [0, 1, 2].map(k => Math.min(...triangle.map(p => p[k]))), hi = [0, 1, 2].map(k => Math.max(...triangle.map(p => p[k])))
          if (scan(tree, triangle, lo, hi)) { collisions.intersections.push({ clip: currentClip, time: currentTime, tool: mesh.name }); break }
        }
      }
      collisions.samples++
    }
    // Exact perpendicular triangle clearance in the actual shaft frame.
    // Hand/body triangles whose axial interval intersects the grip are tested.
    const grip = {}
    for (const [side, toolName] of [['l', 'Axe_wooden_shaft'], ['r', 'Shield_back_handle']]) {
      const shaft = tools.find(m => m.name === toolName), inverse = shaft.matrixWorld.clone().invert()
      const metricScale = new T.Vector3().setFromMatrixScale(shaft.matrixWorld)
      if (Math.max(metricScale.x, metricScale.y, metricScale.z) - Math.min(metricScale.x, metricScale.y, metricScale.z) > .000001) throw Error('Nonuniform shaft quantization scale')
      const p = rest.map(p => new T.Vector3(...p).applyMatrix4(inverse).multiplyScalar(metricScale.x)), a = shaft.geometry.attributes.position
      // Blender's cylinder axis exports along glTF +Y.
      let radius = 0
      for (let i = 0; i < a.count; i++) radius = Math.max(radius, Math.hypot(a.getX(i), a.getZ(i)) * metricScale.x)
      const distEdge = (a, b) => { const dx = b.x - a.x, dz = b.z - a.z, u = Math.max(0, Math.min(1, -(a.x * dx + a.z * dz) / (dx * dx + dz * dz || 1))); return Math.hypot(a.x + u * dx, a.z + u * dz) }
      let clearance = Infinity, tested = 0
      const hand = new Set(masks[`hand_${side}`])
      for (const face of faces) {
        if (!face.some(i => hand.has(i))) continue
        const t = face.map(i => p[i]); if (Math.min(...t.map(p => p.y)) > .05 || Math.max(...t.map(p => p.y)) < -.05) continue
        const signs = t.map((a, i) => a.x * t[(i + 1) % 3].z - a.z * t[(i + 1) % 3].x)
        const inside = signs.every(v => v >= 0) || signs.every(v => v <= 0)
        const d = inside ? 0 : Math.min(...t.map((a, i) => distEdge(a, t[(i + 1) % 3])))
        clearance = Math.min(clearance, d - radius); tested++
      }
      grip[side] = { minimumConservativeRadialClearance: clearance, shaftRadius: radius, testedTriangles: tested }
    }
    const mixer = new T.AnimationMixer(scene)
    let currentClip = '', currentTime = 0
    for (const clip of q.gltf.animations) {
      currentClip = clip.name; mixer.stopAllAction(); const action = mixer.clipAction(clip).reset().play()
      action.setLoop(T.LoopOnce, 1); action.clampWhenFinished = true
      const lastPlants = {}, steps = Math.ceil(clip.duration / .1)
      let poseCount = 0
      for (let step = 0; step <= steps; step++) {
        currentTime = Math.min(clip.duration - 1e-5, step * .1); mixer.setTime(currentTime); scene.updateMatrixWorld(true); body.skeleton.update()
        const positions = []
        for (let i = 0; i < count; i++) { body.getVertexPosition(i, vec); body.localToWorld(vec); positions.push(vec.toArray()); support.minimumVertexHeight = Math.min(support.minimumVertexHeight, vec.y) }
        for (const [name, ids] of Object.entries(masks)) {
          let drift = 0
          for (const anchor of anchors[name]) for (const i of ids) drift = Math.max(drift, Math.abs(distance(positions[anchor], positions[i]) - distance(rest[anchor], rest[i])))
          rigid[name] = Math.max(rigid[name] ?? 0, drift)
        }
        for (const side of ['l', 'r']) {
          const shift = side === 'l' ? 0 : .5, absolute = currentTime / 2 + shift, cycle = Math.floor(absolute), phase = absolute - cycle
          const planted = clip.name !== 'walk' || phase < .64
          if (planted) {
            const ids = masks[`foot_${side}`], sole = Math.min(...ids.map(i => positions[i][1]))
            support.maximumSupportSoleHeight = Math.max(support.maximumSupportSoleHeight, Math.abs(sole))
            const plantId = clip.name === 'walk' ? cycle : 0, old = lastPlants[side]
            if (old?.id === plantId) for (let i = 0; i < ids.length; i++) {
              const d = distance(old.p[i], positions[ids[i]])
              if (d > support.maximumStanceVertexDrift) { support.maximumStanceVertexDrift = d; support.worstStance = { clip: clip.name, time: currentTime, side } }
            }
            else lastPlants[side] = { id: plantId, p: ids.map(i => positions[i]) }
          }
        }
        for (const mesh of tools) {
          const side = mesh.name.startsWith('Axe') ? 'l' : 'r', bone = scene.getObjectByName(`xingtian_wrist_${side}`)
          const expected = bone.matrixWorld.clone().multiply(boneRest.get(side).clone().invert()).multiply(toolRest.get(mesh.name))
          const drift = Math.max(...mesh.matrixWorld.elements.map((v, k) => Math.abs(v - expected.elements[k])))
          toolAttachment[mesh.name] = Math.max(toolAttachment[mesh.name] ?? 0, drift)
        }
        scene.traverse(n => { if (!n.matrixWorld.elements.every(Number.isFinite) || n.matrixWorld.determinant() <= 0) invalid++ })
        // 0.5s collision samples include all three complete clips and the entire turn.
        if (step % 5 === 0 || step === steps) collision(positions)
        poseCount++
      }
      clips[clip.name] = { duration: clip.duration, poseCount }
    }
    mixer.stopAllAction()
    const result = { nativeTriangles: index.count / 3, compressedVertices: count, nativeVertices: reference.length, bones: body.skeleton.bones.length, meshes: meshes.length, maximumRestError, maximumReverseRestError, maxWeightError, invalid, masks: Object.fromEntries(Object.entries(masks).map(([k, v]) => [k, v.length])), rigidMaximumPairDistanceDrift: rigid, support, toolAttachment, grip, collisions, clips }
    for (const skin of skins) skin.skeleton.dispose()
    return result
  }, reference)
  const g = report.geometry
  assert.equal(g.nativeTriangles, 50000); assert.equal(g.bones, 19); assert.equal(g.meshes, 7)
  assert.equal(g.invalid, 0); assert(g.maxWeightError < .0001)
  assert(g.maximumRestError < .00008 && g.maximumReverseRestError < .00008)
  for (const [name, drift] of Object.entries(g.rigidMaximumPairDistanceDrift)) assert(drift < .00002, `${name} rigid drift ${drift}`)
  assert(g.support.maximumStanceVertexDrift < .0001, `Planted foot drift ${g.support.maximumStanceVertexDrift}`)
  assert(g.support.maximumSupportSoleHeight < .0001, `Support height ${g.support.maximumSupportSoleHeight}`)
  assert(g.support.minimumVertexHeight > -.0001)
  for (const value of Object.values(g.toolAttachment)) assert(value < .000001)
  for (const value of Object.values(g.grip)) assert(value.minimumConservativeRadialClearance > .00005 && value.minimumConservativeRadialClearance < .001)
  assert.deepEqual(g.collisions.intersections, [], 'Tools intersect actual compressed body surfaces')
  }
  async function framing(label) {
    const result = await page.evaluate(() => {
      const q = window.xingtianQA, T = q.T, camera = q.state.camera.clone()
      q.state.scene.updateMatrixWorld(true)
      camera.updateMatrixWorld(true)
      const parent = new T.Group(), scene = q.clone(q.gltf.scene)
      parent.matrixAutoUpdate = false
      parent.matrix.copy(q.state.scene.getObjectByName('xingtian_root').matrixWorld)
      parent.add(scene)
      const meshes = [], skins = []
      scene.traverse(n => { if (n.isMesh) meshes.push(n); if (n.isSkinnedMesh) skins.push(n) })
      const width = innerWidth, height = innerHeight, rectangles = []
      for (const selector of ['.card', '.scroll-wrap', '.actions', '.controls']) {
        const r = document.querySelector(selector)?.getBoundingClientRect()
        if (r?.width && r.height) rectangles.push({ selector, left: r.left, top: r.top, right: r.right, bottom: r.bottom })
      }
      const minimumGaps = Object.fromEntries(['viewport', ...rectangles.map(r => r.selector)].map(k => [k, Infinity]))
      const worst = {}, mixer = new T.AnimationMixer(scene), v = new T.Vector3()
      const bounds = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity }
      let poses = 0, invalidProjection = 0
      for (const clip of q.gltf.animations) {
        mixer.stopAllAction(); const action = mixer.clipAction(clip).reset().play()
        action.setLoop(T.LoopOnce, 1); action.clampWhenFinished = true
        const steps = Math.ceil(clip.duration / .25)
        for (let step = 0; step <= steps; step++) {
          const time = Math.min(clip.duration - 1e-5, step * .25)
          mixer.setTime(time); parent.updateMatrixWorld(true)
          for (const skin of skins) skin.skeleton.update()
          for (const mesh of meshes) {
            const count = mesh.geometry.attributes.position.count, projected = new Float64Array(count * 2)
            for (let i = 0; i < count; i++) {
              mesh.getVertexPosition(i, v); mesh.localToWorld(v); v.project(camera)
              if (v.z < -1 || v.z > 1 || !v.toArray().every(Number.isFinite)) invalidProjection++
              const x = (v.x + 1) * width / 2, y = (1 - v.y) * height / 2
              bounds.left = Math.min(bounds.left, x); bounds.right = Math.max(bounds.right, x)
              bounds.top = Math.min(bounds.top, y); bounds.bottom = Math.max(bounds.bottom, y)
              projected[i * 2] = x; projected[i * 2 + 1] = y
              const d = Math.min(x, width - x, y, height - y)
              if (d < minimumGaps.viewport) {
                minimumGaps.viewport = d; worst.viewport = { clip: clip.name, time, mesh: mesh.name, vertex: i, x, y }
              }
            }
            // A projected triangle lies within its screen-space AABB. Measuring
            // every AABB gives a conservative lower bound for the entire surface,
            // including triangle interiors and edges between sampled vertices.
            const index = mesh.geometry.index, triangles = (index?.count ?? count) / 3
            for (let i = 0; i < triangles; i++) {
              const a = (index ? index.getX(i * 3) : i * 3) * 2
              const b = (index ? index.getX(i * 3 + 1) : i * 3 + 1) * 2
              const c = (index ? index.getX(i * 3 + 2) : i * 3 + 2) * 2
              const left = Math.min(projected[a], projected[b], projected[c]), right = Math.max(projected[a], projected[b], projected[c])
              const top = Math.min(projected[a + 1], projected[b + 1], projected[c + 1]), bottom = Math.max(projected[a + 1], projected[b + 1], projected[c + 1])
              for (const r of rectangles) {
                const d = Math.hypot(Math.max(r.left - right, left - r.right, 0), Math.max(r.top - bottom, top - r.bottom, 0))
                if (d < minimumGaps[r.selector]) {
                  minimumGaps[r.selector] = d
                  worst[r.selector] = { clip: clip.name, time, mesh: mesh.name, triangle: i, x: (left + right) / 2, y: (top + bottom) / 2 }
                }
              }
            }
          }
          poses++
        }
      }
      mixer.stopAllAction()
      for (const skin of skins) skin.skeleton.dispose()
      return { width, height, fov: camera.fov, filmOffset: camera.filmOffset, cameraPosition: camera.position.toArray(), target: q.state.controls.target.toArray(), poses, bounds, rectangles, minimumGaps, worst, invalidProjection, surfaceClearanceMethod: 'conservative projected triangle AABB to UI rectangles', minimumRequiredGap: 8 }
    })
    report.framing ??= {}
    report.framing[label] = result
    console.log(JSON.stringify({ framing: label, gaps: result.minimumGaps }))
  }
  async function inspect(label) {
    const s = await page.evaluate(() => {
      const q = window.xingtianQA, root = q.state.scene.getObjectByName('xingtian_root')
      let meshes = 0, outlines = 0, bones = 0, invalid = 0
      root.traverse(n => { if (n.userData.inkOutline) outlines++; else if (n.isMesh) meshes++; if (n.isBone) bones++; if (![...n.scale, ...n.matrixWorld.elements].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++ })
      return { meshes, outlines, bones, invalid, cacheUnchanged: q.before === q.cacheSnapshot(), sharedDisposals: q.sharedDisposals, action: q.useApp.getState().action }
    })
    report.snapshots.push({ label, ...s })
    assert.equal(s.meshes, 7); assert.equal(s.outlines, 7); assert.equal(s.bones, 19); assert.equal(s.invalid, 0)
    assert(s.cacheUnchanged); assert.equal(s.sharedDisposals, 0)
  }
  const shot = async name => { const p = join(out, `${name}.png`); await page.screenshot({ path: p }); report.images.push(p) }
  const settleCamera = () => page.waitForFunction(() => {
    const target = window.xingtianQA.state.controls.target
    return target.distanceTo(new window.xingtianQA.T.Vector3(0, innerWidth <= 640 ? 1.1 : .7, 0)) < .0001
  }, null, { timeout: 60000 })
  await settleCamera()
  const poseShot = async (label, clipName, time) => {
    await page.evaluate(name => window.xingtianQA.useApp.getState().setAction(name), clipName)
    await page.waitForTimeout(100)
    await page.evaluate(({ name, time }) => {
      const q = window.xingtianQA, mixer = q.state.scene.getObjectByName('xingtian_root').userData.animationMixer
      mixer.timeScale = 1; mixer.stopAllAction()
      const action = mixer.clipAction(q.gltf.animations.find(c => c.name === name)).reset()
      action.stopFading().setEffectiveWeight(1).setEffectiveTimeScale(1).setLoop(q.T.LoopOnce, 1)
      action.clampWhenFinished = true; action.play(); mixer.setTime(time); mixer.timeScale = 0
    }, { name: clipName, time })
    await page.waitForTimeout(180)
    await inspect(label); await shot(label)
    await page.evaluate(() => { window.xingtianQA.state.scene.getObjectByName('xingtian_root').userData.animationMixer.timeScale = 1 })
  }
  const extremeShots = async label => {
    const poses = new Map(Object.values(report.framing[label].worst).map(p => [`${p.clip}-${p.time}`, p]))
    for (const time of [8, 24]) poses.set(`walk-${time}`, { clip: 'walk', time })
    for (const pose of poses.values()) await poseShot(`${label}-extreme-${pose.clip}-${pose.time}`, pose.clip, pose.time)
  }
  await shot('stage-framing-desktop')
  await framing('desktop')
  await extremeShots('desktop')
  for (const action of ['idle', 'walk', 'special']) {
    await page.evaluate(a => window.xingtianQA.useApp.getState().setAction(a), action)
    await page.waitForTimeout(action === 'special' ? 1500 : 650)
    await inspect(action); await shot(`stage-${action}`)
    if (action === 'walk') for (let i = 0; i < 3; i++) { await shot(`walk-motion-${i}`); await page.waitForTimeout(280) }
  }
  await page.waitForFunction(() => window.xingtianQA.useApp.getState().action === 'idle', null, { timeout: 60000 })
  await inspect('special-finished')
  await page.evaluate(() => window.xingtianQA.useApp.getState().select('jingwei')); await ready('jingwei')
  await page.evaluate(() => window.xingtianQA.useApp.getState().select('xingtian')); await ready('xingtian')
  await page.waitForTimeout(500); await inspect('remounted'); await shot('stage-remounted')
  for (const [label, width, height] of [['tablet', 820, 1180], ['tablet700', 700, 1000], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height }); await settleCamera(); await inspect(label); await shot(`stage-${label}`); await framing(label)
    report.cardScroll ??= {}
    report.cardScroll[label] = await page.evaluate(() => {
      const card = document.querySelector('.card'), style = getComputedStyle(card), rows = [...card.querySelectorAll('.card-source, .card-inferred p')]
      const unreachable = []
      for (const [i, row] of rows.entries()) {
        row.scrollIntoView({ block: 'nearest' })
        const r = row.getBoundingClientRect(), c = card.getBoundingClientRect()
        if (r.top < c.top - 1 || r.bottom > c.bottom + 1) unreachable.push(i)
      }
      return { writingMode: style.writingMode, overflowY: style.overflowY, clientHeight: card.clientHeight, scrollHeight: card.scrollHeight, rows: rows.length, unreachable }
    })
    assert.equal(report.cardScroll[label].writingMode, 'horizontal-tb')
    assert.equal(report.cardScroll[label].overflowY, 'auto')
    assert.deepEqual(report.cardScroll[label].unreachable, [])
    await shot(`${label}-card-scrolled`)
    await page.evaluate(() => { document.querySelector('.card').scrollTop = 0 })
    if (label === 'mobile') {
      for (const [action, time] of [['idle', 1], ['walk', 4.25], ['special', 1.5]]) await poseShot(`mobile-${action}`, action, time)
      await extremeShots(label)
    }
  }
  for (const [label, result] of Object.entries(report.framing)) {
    assert.equal(result.invalidProjection, 0)
    for (const [name, gap] of Object.entries(result.minimumGaps)) assert(gap >= 8, `${label}: ${name} gap ${gap}px`)
  }
  assert.deepEqual(report.errors, [])
  report.passed = true
} catch (error) {
  report.failure = String(error.stack ?? error); process.exitCode = 1
} finally {
  await browser.close()
  await writeFile(join(out, 'xingtian-qa.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
}
