// Actual Stage QA, candidate route interception only; never changes public assets.
// node scripts/qa-zhuyan-app.mjs BASE_URL NEW_OUTPUT_DIR CANDIDATE.glb
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const [base = 'http://localhost:5215', output, candidate] = process.argv.slice(2)
assert(output && candidate, 'Unique evidence directory and candidate GLB required')
await mkdir(output, { recursive: false })
const bytes = await readFile(resolve(candidate))
assert.equal(bytes.toString('ascii', 0, 4), 'glTF')
const jsonLength = bytes.readUInt32LE(12)
const gltf = JSON.parse(bytes.toString('utf8', 20, 20 + jsonLength))
const durations = Object.fromEntries(gltf.animations.map(animation => [animation.name, Math.max(...animation.samplers.map(s => gltf.accessors[s.input].max[0]))]))
const report = { candidate: resolve(candidate), candidateSha256: createHash('sha256').update(bytes).digest('hex'), scriptSha256: createHash('sha256').update(await readFile(new URL(import.meta.url))).digest('hex'), base, durations, productionAccepted: false, thresholds: { stanceDrift: .001, supportShapeDrift: .001, soleDirectionRadians: .002, soleNormalRadians: .002, rigidShapeDrift: .0001, minSoleHeight: -.001, maxSoleHeight: .004 }, sections: {}, failures: [], errors: [], readyEvents: [], images: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu', '--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route('**/models/zhuyan/body.glb*', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
page.on('pageerror', e => report.errors.push(String(e)))
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()); if (m.text().includes('[beast] ready zhuyan')) report.readyEvents.push({ text: m.text(), time: Date.now() }) })
async function section(name, work) {
  try { await work(); report.sections[name] = { passed: true } }
  catch (error) { report.sections[name] = { passed: false, error: String(error), stack: error.stack }; report.failures.push({ section: name, error: String(error) }); await page.screenshot({ path: join(output, `failure-${name}.png`) }).catch(() => {}) }
}
async function action(name) { await page.evaluate(a => window.zhuyanAppQA.useApp.getState().setAction(a), name) }
async function idle() { await action('idle'); await page.waitForTimeout(600) }
async function capture(name, view) {
  const state = await page.evaluate(({ view }) => {
    const q = window.zhuyanAppQA, root = q.root(), state = q.state, h = q.height
    state.scene.updateMatrixWorld(true)
    let target = root.position.clone().set(0, h * .50, 0).applyMatrix4(root.matrixWorld)
    let direction = [0, .12, 1], distance = 3.45
    if (view === 'back') direction = [0, .12, -1]
    if (view === 'left') direction = [-1, .12, 0]
    if (view === 'right') direction = [1, .12, 0]
    if (view === '34') direction = [.65, .18, 1]
    if (view === 'joints') { target = root.position.clone().set(0, h * .69, 0).applyMatrix4(root.matrixWorld); direction = [.65, .08, 1]; distance = 1.9 }
    if (view === 'chin') { target = root.position.clone().set(0, h * .81, .06).applyMatrix4(root.matrixWorld); direction = [1, 0, .3]; distance = 1.05 }
    if (view === 'feet' || view === 'hand-l' || view === 'hand-r') {
      const ids = view === 'feet' ? [...q.feet.l, ...q.feet.r] : q.hands[view.slice(-1)]
      const points = q.points(ids)
      target.set(0, 0, 0); for (const p of points) target.x += p[0], target.y += p[1], target.z += p[2]
      target.multiplyScalar(1 / points.length)
      direction = view === 'feet' ? [.3, .5, 1] : [view === 'hand-l' ? 1 : -1, -.15, .4]
      distance = view === 'feet' ? 1.8 : .75
    }
    const offset = root.position.clone().set(...direction).normalize().multiplyScalar(distance).applyQuaternion(root.quaternion)
    state.controls.enableDamping = false
    state.camera.filmOffset = 0; state.camera.updateProjectionMatrix()
    state.controls.target.copy(target); state.camera.position.copy(target).add(offset); state.controls.update()
    return { action: q.useApp.getState().action, animationTime: root.userData.animationTime, camera: state.camera.position.toArray(), target: target.toArray(), uiHiddenForAnatomy: document.body.classList.contains('qa-anatomy-only') }
  }, { view })
  const path = join(output, `${name}.png`)
  await page.screenshot({ path })
  report.images.push({ path, view, ...state })
}
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready zhuyan'), timeout: 45000 })
  await page.goto(`${base}/?beast=zhuyan&action=idle`)
  await ready
  await page.waitForTimeout(600)
  await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(u => new URL(u).pathname === '/src/app/store.ts'))
    const T = await import(resources.find(u => new URL(u).pathname.endsWith('/three.js')))
    const q = window.zhuyanAppQA = { state: [...fiber._roots.values()][0].store.getState(), useApp, T, specialEvents: [] }
    q.root = () => q.state.scene.getObjectByName('zhuyan_root')
    q.mesh = () => { const meshes = []; q.root().traverse(n => { if (n.isSkinnedMesh && !n.userData.inkOutline) meshes.push(n) }); if (meshes.length !== 1) throw new Error('One native skinned source mesh required'); return meshes[0] }
    q.points = ids => { const mesh = q.mesh(); q.state.scene.updateMatrixWorld(true); mesh.skeleton.update(); const p = new T.Vector3(); return ids.map(i => { mesh.getVertexPosition(i, p); mesh.localToWorld(p); return p.toArray() }) }
    q.distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])
    q.initializeMasks = () => {
      const root = q.root(), mesh = q.mesh(), g = mesh.geometry.attributes
      q.state.scene.updateMatrixWorld(true); mesh.skeleton.update()
      const rootBone = mesh.skeleton.bones.find(b => b.name === 'root'), ri = mesh.skeleton.bones.indexOf(rootBone)
      if (ri < 0) throw new Error('Rest root inverse bind required')
      // Remove Stage/root placement and retain inverse-bind dequantization.
      // Called only in settled idle, where the rig root has its rest transform.
      const restMatrix = root.matrixWorld.clone().invert().multiply(mesh.matrixWorld).multiply(mesh.bindMatrixInverse).multiply(rootBone.matrixWorld).multiply(mesh.skeleton.boneInverses[ri]).multiply(mesh.bindMatrix)
      const h = q.height = mesh.userData.restAnatomicalFootMaxHeight / .085
      if (!Number.isFinite(h) || h < 1 || h > 2) throw new Error('Reviewed rest anatomy bounds missing')
      q.feet = { l: [], r: [] }; q.soles = { l: [], r: [] }; q.head = []; q.chest = []; q.rest = []
      const smooth = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t) }
      for (let i = 0; i < g.position.count; i++) {
        const p = new T.Vector3().fromBufferAttribute(g.position, i).applyMatrix4(restMatrix), side = p.x > 0 ? 'l' : 'r', z = p.y / h
        q.rest.push(p)
        if (p.y < h * .085 - .00001) { q.feet[side].push(i); if (p.y < .003 - .00001) q.soles[side].push(i) }
        const floor = .835 - .125 * (1 - smooth(-.08, .16, -p.z)), width = .215 + .040 * smooth(.80, .86, z)
        if ((z > floor && Math.abs(p.x) < width) || z > .89) q.head.push(i)
        if (Math.abs(p.x) < .20 && z > .46 && z < .69) q.chest.push(i)
      }
      const graph = Array.from({ length: g.position.count }, () => new Set()), indices = mesh.geometry.index
      const edge = (a, b) => { graph[a].add(b); graph[b].add(a) }
      for (let i = 0; i < (indices?.count ?? g.position.count); i += 3) { const a = indices ? indices.getX(i) : i, b = indices ? indices.getX(i + 1) : i + 1, c = indices ? indices.getX(i + 2) : i + 2; edge(a, b); edge(b, c); edge(c, a) }
      const coincident = new Map()
      q.rest.forEach((p, i) => { const key = p.toArray().map(v => v.toFixed(5)).join('/'); if (coincident.has(key)) edge(i, coincident.get(key)); else coincident.set(key, i) })
      q.hands = {}
      for (const [side, sign] of [['l', 1], ['r', -1]]) {
        const seen = new Set(); q.rest.forEach((p, i) => { if (sign * p.x > .39 && p.y > h * .22 && p.y < h * .32) seen.add(i) })
        const pending = [...seen]
        while (pending.length) for (const i of graph[pending.pop()]) { const p = q.rest[i]; if (!seen.has(i) && p.y > h * .17 && p.y < h * .385) { seen.add(i); pending.push(i) } }
        q.hands[side] = [...seen]
      }
      const assigned = (i, bone) => { let sum = 0; for (let k = 0; k < 4; k++) if (mesh.skeleton.bones[g.skinIndex.getComponent(i, k)]?.name === bone) sum += g.skinWeight.getComponent(i, k); return sum }
      const issues = []
      for (const side of ['l', 'r']) {
        if (q.feet[side].length < 100 || q.soles[side].length < 10 || q.hands[side].length < 300) issues.push('Incomplete anatomy mask ' + side)
        for (const i of q.feet[side]) if (assigned(i, 'leg_' + side + '_foot') < .9999) issues.push('Misweighted actual foot ' + i)
        for (const i of q.hands[side]) if (assigned(i, 'arm_' + side + '_hand') < .9999) issues.push('Misweighted native hand ' + i)
      }
      for (const i of q.head) if (assigned(i, 'head') < .9999) issues.push('Misweighted native head/chin/ear ' + i)
      for (const i of q.chest) for (let k = 0; k < 4; k++) if (g.skinWeight.getComponent(i, k) > .0001 && mesh.skeleton.bones[g.skinIndex.getComponent(i, k)]?.name.startsWith('arm_')) issues.push('Chest arm influence ' + i)
      q.rigidMasks = { head: q.head, hand_l: q.hands.l, hand_r: q.hands.r, foot_l: q.feet.l, foot_r: q.feet.r }
      q.rigidReference = {}
      for (const [name, ids] of Object.entries(q.rigidMasks)) {
        const p = q.points(ids), first = p[0]
        let far = 0; for (let i = 1; i < p.length; i++) if (q.distance(p[i], first) > q.distance(p[far], first)) far = i
        q.rigidReference[name] = { anchors: [0, far], lengths: p.map(point => [q.distance(point, first), q.distance(point, p[far])]) }
      }
      return { height: h, head: q.head.length, hands: Object.fromEntries(Object.entries(q.hands).map(([k, v]) => [k, v.length])), feet: Object.fromEntries(Object.entries(q.feet).map(([k, v]) => [k, v.length])), soles: Object.fromEntries(Object.entries(q.soles).map(([k, v]) => [k, v.length])), protectedChest: q.chest.length, issues, selection: 'Full spatial native head mask, connected native hands, spatial complete feet/soles; root inverse bind dequantization; masks selected before weights' }
    }
    q.snapshot = (full = false) => {
      const root = q.root(), mesh = q.mesh(), g = mesh.geometry.attributes
      q.state.scene.updateMatrixWorld(true); mesh.skeleton.update()
      let nodes = 0, bones = 0, meshes = 0, outlines = 0, invalid = 0
      root.traverse(n => { nodes++; if (n.isBone) bones++; if (n.isMesh) n.userData.inkOutline ? outlines++ : meshes++; if (![...n.matrixWorld.elements, ...n.position, ...n.quaternion, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++ })
      if (!Array.from(mesh.skeleton.boneMatrices).every(Number.isFinite)) invalid++
      if (full) { for (const name of ['position', 'normal', 'skinWeight']) if (!Array.from(g[name].array).every(Number.isFinite)) invalid++; const p = new T.Vector3(); for (let i = 0; i < g.position.count; i++) { mesh.getVertexPosition(i, p); if (!p.toArray().every(Number.isFinite)) invalid++ } }
      return { nodes, bones, meshes, outlines, invalid, vertices: g.position.count, animationTime: root.userData.animationTime, action: useApp.getState().action }
    }
    q.rigidSample = () => {
      const result = {}
      for (const [name, ids] of Object.entries(q.rigidMasks)) {
        const points = q.points(ids), r = q.rigidReference[name]; let error = 0
        for (let i = 0; i < points.length; i++) for (let a = 0; a < 2; a++) error = Math.max(error, Math.abs(q.distance(points[i], points[r.anchors[a]]) - r.lengths[i][a]))
        result[name] = error
      }
      return { errors: result, action: useApp.getState().action, animationTime: q.root().userData.animationTime }
    }
    useApp.subscribe((next, previous) => { if (previous.action === 'special' && next.action === 'idle') q.specialEvents.push({ clipTime: q.root()?.userData.animationTime, wallTime: performance.now() }) })
  })
  await section('baseline', async () => {
    report.masks = await page.evaluate(() => window.zhuyanAppQA.initializeMasks())
    report.baseline = await page.evaluate(() => window.zhuyanAppQA.snapshot(true))
    assert.equal(report.masks.issues.length, 0, report.masks.issues.join('\n'))
    assert(report.masks.head > 9000, 'Full native head, not crown-only sample')
    for (const [k, v] of Object.entries({ invalid: 0, meshes: 1, outlines: 1, bones: 17 })) assert.equal(report.baseline[k], v, k)
    assert(report.readyEvents.length >= 2, 'StrictMode effect setup repeated on initial mount')
  })
  await section('transitions', async () => {
    report.transitions = []
    for (const name of ['walk', 'special', 'idle', 'special', 'walk', 'idle']) {
      await action(name)
      const samples = []
      for (let i = 0; i < 12; i++) { await page.waitForTimeout(45); samples.push(await page.evaluate(() => window.zhuyanAppQA.rigidSample())) }
      report.transitions.push({ target: name, samples })
    }
    for (const transition of report.transitions) for (const sample of transition.samples) for (const [part, error] of Object.entries(sample.errors)) assert(error < .0001, `${transition.target} ${part} shape ${error}`)
  })
  await section('special-duration-and-feet', async () => {
    await idle()
    const result = await page.evaluate(async duration => {
      const q = window.zhuyanAppQA, ids = [...q.feet.l, ...q.feet.r], initial = q.points(ids), start = performance.now()
      q.specialEvents.length = 0; q.useApp.getState().setAction('special')
      let maxDrift = 0, maxRigid = 0, samples = 0
      while (q.useApp.getState().action === 'special' && performance.now() - start < 18000) {
        await new Promise(r => requestAnimationFrame(r)); const points = q.points(ids)
        for (let i = 0; i < points.length; i++) maxDrift = Math.max(maxDrift, q.distance(points[i], initial[i]))
        if (samples % 4 === 0) maxRigid = Math.max(maxRigid, ...Object.values(q.rigidSample().errors))
        samples++
      }
      return { expectedDuration: duration, finalAction: q.useApp.getState().action, events: q.specialEvents, maxWholeFootDrift: maxDrift, maxRigidShapeDrift: maxRigid, wallMs: performance.now() - start, samples }
    }, durations.special)
    report.special = result
    assert.equal(result.finalAction, 'idle')
    assert.equal(result.events.length, 1)
    assert(Math.abs(result.events[0].clipTime - durations.special) < .002, 'Actual exported duration controls special return')
    assert(result.maxWholeFootDrift < .003, `Whole-foot gesture drift ${result.maxWholeFootDrift}`)
    assert(result.maxRigidShapeDrift < .0001, 'Rigid whole hands/head/feet during special')
  })
  await section('circular-contact', async () => {
    await idle(); await action('walk'); await page.waitForTimeout(600)
    report.contact = await page.evaluate(async duration => {
      const q = window.zhuyanAppQA, plants = {}, start = performance.now(), ids = q.soles
      const basis = points => {
        let far = 1; for (let i = 2; i < points.length; i++) if (q.distance(points[i], points[0]) > q.distance(points[far], points[0])) far = i
        const u = points[far].map((v, k) => v - points[0][k]); let cross = null, area = 0, third = -1
        for (let i = 1; i < points.length; i++) { const v = points[i].map((x, k) => x - points[0][k]), c = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]], length = Math.hypot(...c); if (length > area) { area = length; cross = c; third = i } }
        if (area < 1e-6) throw new Error('Actual sole is not a broad noncollinear patch')
        return { far, third, area, normal: cross.map(v => v / area) }
      }
      const normal = (p, b) => { const u=p[b.far].map((v,k)=>v-p[0][k]),v=p[b.third].map((v,k)=>v-p[0][k]),n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n);return n.map(v=>v/length) }
      let cycles = 0, wraps = 0, animationSeconds = 0, previous = q.root().userData.animationTime, frames = 0
      while (animationSeconds < duration * 3 && performance.now() - start < 26000) {
        await new Promise(r => requestAnimationFrame(r))
        const t = q.root().userData.animationTime
        const wrapped = t < previous - .5
        if (wrapped) wraps++
        animationSeconds += t - previous + (wrapped ? duration : 0)
        cycles = Math.floor((animationSeconds + 1e-8) / duration)
        previous = t; frames++
        for (const [side, offset] of [['l', 0], ['r', .5]]) {
          const raw = t / duration + offset, phase = raw % 1
          if (phase < .05 || phase > .61) continue
          const key = side + '/' + (wraps + Math.floor(raw)), positions = q.points(ids[side])
          const plant = plants[key] ??= { side, initial: positions, basis: basis(positions), maxDrift: 0, maxShapeDrift: 0, maxDirection: 0, maxPlaneNormal: 0, minY: Infinity, maxY: -Infinity, samples: 0 }
          const n = normal(positions, plant.basis), dot = n.reduce((s,v,k) => s+v*plant.basis.normal[k],0)
          plant.maxPlaneNormal = Math.max(plant.maxPlaneNormal, Math.acos(Math.max(-1,Math.min(1,dot))))
          for (let i = 0; i < positions.length; i++) {
            const p=positions[i],r=plant.initial[i]
            plant.maxDrift=Math.max(plant.maxDrift,q.distance(p,r));plant.minY=Math.min(plant.minY,p[1]);plant.maxY=Math.max(plant.maxY,p[1])
            const one=p.map((v,k)=>v-positions[0][k]),two=r.map((v,k)=>v-plant.initial[0][k]);plant.maxShapeDrift=Math.max(plant.maxShapeDrift,q.distance(one,two))
            const length=Math.hypot(...one)*Math.hypot(...two);if(length>1e-8)plant.maxDirection=Math.max(plant.maxDirection,Math.acos(Math.max(-1,Math.min(1,one.reduce((s,v,k)=>s+v*two[k],0)/length))))
          }
          plant.samples++
        }
      }
      const measured=Object.values(plants).filter(p=>p.samples>10)
      return { cycles,wraps,animationSeconds,frames,wallMs:performance.now()-start,points:Object.fromEntries(Object.entries(ids).map(([k,v])=>[k,v.length])),plants:measured,maxDrift:Math.max(...measured.map(p=>p.maxDrift)),maxShapeDrift:Math.max(...measured.map(p=>p.maxShapeDrift)),maxDirection:Math.max(...measured.map(p=>p.maxDirection)),maxPlaneNormal:Math.max(...measured.map(p=>p.maxPlaneNormal)),selection:'Actual deformed anatomical soles, independent of weights; three real circular clip cycles' }
    }, durations.walk)
    const c=report.contact
    assert.equal(c.cycles,3);assert(c.animationSeconds>=durations.walk*3);assert(c.plants.length>=4)
    assert(c.maxDrift<.001,`Actual world sole drift ${c.maxDrift}`)
    assert(c.maxShapeDrift<.001,`Actual support shape drift ${c.maxShapeDrift}`)
    assert(c.maxDirection<.002,`Actual sole direction ${c.maxDirection}`)
    assert(c.maxPlaneNormal<.002,`Actual sole plane ${c.maxPlaneNormal}`)
    assert(c.plants.every(p=>p.minY>-.001&&p.maxY<.004),'Actual sole height')
  })
  await section('action-and-anatomy-images', async () => {
    await idle();await capture('app-context','34')
    await page.addStyleTag({content:'.qa-anatomy-only .card,.qa-anatomy-only .story-caption,.qa-anatomy-only .scroll-wrap,.qa-anatomy-only .controls,.qa-anatomy-only .actions,.qa-anatomy-only .title{visibility:hidden!important}'})
    await page.evaluate(()=>{
      const q=window.zhuyanAppQA,c=q.state.controls
      document.body.classList.add('qa-anatomy-only')
      q.captureControls={minDistance:c.minDistance,lerp:c.target.lerp}
      c.minDistance=.25
      // Freeze only camera following for closeups. Stage, pose, mixer and root
      // continue running unchanged; every numeric check uses normal controls.
      c.target.lerp=function(){return this}
    })
    report.captureInstrumentation='Actual Stage renderer/postprocessing; DOM overlays hidden and camera target-follow/zoom limit relaxed only during anatomy captures; no model/action timing overrides'
    try {
      for(const view of ['front','back','left','right','34'])await capture(`angle-${view}`,view)
      await capture('idle','34')
      await action('walk');await page.waitForTimeout(600)
      for(let i=0;i<4;i++){await capture(`walk-${i}`,'34');await page.waitForTimeout(450)}
      await capture('walk-joints','joints');await capture('walk-feet','feet')
      await idle();await action('special');await page.waitForTimeout(1500)
      await capture('special','34');await capture('special-joints','joints');await capture('special-chin','chin');await capture('special-hand-l','hand-l');await capture('special-hand-r','hand-r');await capture('special-feet','feet')
    } finally {
      await page.evaluate(()=>{const q=window.zhuyanAppQA,c=q.state.controls;c.minDistance=q.captureControls.minDistance;c.target.lerp=q.captureControls.lerp;document.body.classList.remove('qa-anatomy-only')})
    }
  })
  await section('remount-ownership', async () => {
    await idle();report.remounts=[]
    for(let cycle=0;cycle<3;cycle++){
      await page.evaluate(()=>{
        const q=window.zhuyanAppQA,skeletons=new Set(),materials=new Set(),geometries=new Set(),sharedTextures=new Set()
        q.root().traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton);if(n.isMesh){geometries.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:[n.material]){materials.add(m);if(m.map)sharedTextures.add(m.map);for(const u of Object.values(m.uniforms??{}))if(u.value?.isTexture)sharedTextures.add(u.value)}}})
        const old=q.old={skeletons:[...skeletons],materials:[...materials],geometries:[...geometries],sharedTextures:[...sharedTextures],boneTextures:0,disposedBoneTextures:0,disposedMaterials:0,disposedGeometry:0,disposedSharedTextures:0}
        for(const s of skeletons)if(s.boneTexture){old.boneTextures++;s.boneTexture.addEventListener('dispose',()=>old.disposedBoneTextures++)}
        for(const m of materials)m.addEventListener('dispose',()=>old.disposedMaterials++)
        for(const g of geometries)g.addEventListener('dispose',()=>old.disposedGeometry++)
        for(const t of sharedTextures)t.addEventListener('dispose',()=>old.disposedSharedTextures++)
      })
      const away=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jiuweihu'),timeout:30000})
      await page.evaluate(()=>window.zhuyanAppQA.useApp.getState().select('jiuweihu'));await away
      const back=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready zhuyan'),timeout:30000})
      await page.evaluate(()=>window.zhuyanAppQA.useApp.getState().select('zhuyan'));await back;await page.waitForTimeout(500)
      const state=await page.evaluate(()=>window.zhuyanAppQA.snapshot(true))
      const ownership=await page.evaluate(()=>{
        const q=window.zhuyanAppQA,old=q.old,newMaterials=new Set(),newGeometry=new Set(),newTextures=new Set(),newSkeletons=new Set()
        q.root().traverse(n=>{if(n.isSkinnedMesh)newSkeletons.add(n.skeleton);if(n.isMesh){newGeometry.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:[n.material]){newMaterials.add(m);if(m.map)newTextures.add(m.map);for(const u of Object.values(m.uniforms??{}))if(u.value?.isTexture)newTextures.add(u.value)}}})
        return {boneTextures:old.boneTextures,disposedBoneTextures:old.disposedBoneTextures,materials:old.materials.length,disposedMaterials:old.disposedMaterials,disposedGeometry:old.disposedGeometry,disposedSharedTextures:old.disposedSharedTextures,liveOldSkeletonTextures:old.skeletons.filter(s=>s.boneTexture).length,sharedGeometryReused:old.geometries.every(g=>newGeometry.has(g)),sharedTextures:old.sharedTextures.length,sharedTexturesReused:old.sharedTextures.every(t=>newTextures.has(t)),materialsAreNew:old.materials.every(m=>!newMaterials.has(m)),skeletonsAreNew:old.skeletons.every(s=>!newSkeletons.has(s))}
      })
      report.remounts.push({cycle,state,ownership})
      for(const k of ['invalid','nodes','bones','meshes','outlines','vertices'])assert.equal(state[k],report.baseline[k],`Remount ${cycle} ${k}`)
      assert(ownership.boneTextures>0&&ownership.boneTextures===ownership.disposedBoneTextures&&ownership.liveOldSkeletonTextures===0,'Owned skeleton textures disposed')
      assert.equal(ownership.disposedMaterials,ownership.materials,'All owned materials disposed')
      assert.equal(ownership.disposedGeometry,0);assert.equal(ownership.disposedSharedTextures,0)
      assert(ownership.sharedTextures>0&&ownership.sharedGeometryReused&&ownership.sharedTexturesReused&&ownership.materialsAreNew&&ownership.skeletonsAreNew,'Cached geometry/textures preserved and clone ownership renewed')
    }
    assert(report.readyEvents.length>=8,'StrictMode setup repeated across initial mount and three remounts')
  })
  await section('runtime-errors',async()=>{assert.equal(report.errors.length,0,report.errors.join('\n'))})
} catch(error) {
  report.failures.push({section:'setup',error:String(error),stack:error.stack})
  await page.screenshot({path:join(output,'failure-setup.png')}).catch(()=>{})
} finally {
  report.passed=report.failures.length===0
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n')
  await browser.close()
}
console.log(JSON.stringify({passed:report.passed,sections:report.sections,failures:report.failures,report:join(output,'report.json')}))
if(!report.passed)process.exitCode=1
