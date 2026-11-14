// Actual Stage review with a candidate GLB intercepted before public promotion.
// node scripts/qa-jiaochong-app.mjs BASE_URL NEW_OUTPUT_DIR CANDIDATE.glb REST_REFERENCE.json
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const [base, outputArg, candidate, referencePath] = process.argv.slice(2)
assert(base && outputArg && candidate && referencePath, 'Base URL, new output, candidate and native rest reference required')
const output = resolve(outputArg), bytes = await readFile(resolve(candidate))
const reference = JSON.parse(await readFile(resolve(referencePath), 'utf8'))
assert.equal(reference.sourceSha256, '44e1537945dd66315cd2ec6dc65932942a04e792043da8b468f814b212e4e1d0')
assert(bytes.length < 15 * 1024 * 1024)
await mkdir(output, { recursive: false })
const report = { candidate: resolve(candidate), candidateSha256: createHash('sha256').update(bytes).digest('hex'),
  referenceSha256: createHash('sha256').update(await readFile(resolve(referencePath))).digest('hex'),
  productionAccepted: false, sections: {}, failures: [], errors: [], images: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route('**/models/jiaochong/body.glb*', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
await page.addInitScript(() => {
  window.jiaochongNarrations = []
  const play = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function (...args) { window.jiaochongNarrations.push(this); return play.apply(this, args) }
})
async function section(name, work) {
  try { await work(); report.sections[name] = { passed: true } }
  catch (error) { report.sections[name] = { passed: false, error: String(error) }; report.failures.push({ section: name, error: String(error) }); await page.screenshot({ path: join(output, `failure-${name}.png`) }).catch(() => {}) }
}
async function action(name) { await page.evaluate(a => window.jiaochongQA.useApp.getState().setAction(a), name) }
async function screenshot(name) { const path = join(output, `${name}.png`); await page.screenshot({ path }); report.images.push(path) }
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready jiaochong'), timeout: 60000 })
  await page.goto(`${base}/?beast=jiaochong&action=idle`); await ready; await page.waitForTimeout(700)
  report.anatomy = await page.evaluate(async reference => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(u => new URL(u).pathname === '/src/app/store.ts'))
    const T = await import(resources.find(u => new URL(u).pathname.endsWith('/three.js')))
    const q = window.jiaochongQA = { T, useApp, state: [...fiber._roots.values()][0].store.getState() }
    q.root = () => q.state.scene.getObjectByName('jiaochong_root')
    q.mesh = () => { const list = []; q.root().traverse(n => { if (n.isSkinnedMesh && !n.userData.inkOutline) list.push(n) }); if (list.length !== 1) throw new Error('Exactly one native skinned body required'); return list[0] }
    q.points = ids => { const mesh = q.mesh(), p = new T.Vector3(); q.state.scene.updateMatrixWorld(true); mesh.skeleton.update(); return ids.map(i => { mesh.getVertexPosition(i, p); mesh.localToWorld(p); return p.toArray() }) }
    q.distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]))
    const mesh = q.mesh(), g = mesh.geometry.attributes, rootBone = mesh.skeleton.bones.find(b => b.name === 'root')
    q.state.scene.updateMatrixWorld(true); mesh.skeleton.update()
    const index = mesh.skeleton.bones.indexOf(rootBone)
    if (index < 0 || Math.abs(mesh.userData.restHeight - 1.8) > 1e-5) throw new Error('Native rig metadata missing')
    const matrix = q.root().matrixWorld.clone().invert().multiply(mesh.matrixWorld).multiply(mesh.bindMatrixInverse).multiply(rootBone.matrixWorld).multiply(mesh.skeleton.boneInverses[index]).multiply(mesh.bindMatrix)
    const cell = .0003, grid = new Map(), memberships = reference.points.map(() => [])
    for (const [name, ids] of Object.entries(reference.masks)) for (const i of ids) memberships[i].push(name)
    const key = p => p.map(v => Math.floor(v / cell)).join('/')
    reference.points.forEach((p, i) => { const v = [p[0], p[2], -p[1]], k = key(v); if (!grid.has(k)) grid.set(k, []); grid.get(k).push({ i, p: v }) })
    q.masks = Object.fromEntries(Object.keys(reference.masks).map(k => [k, []]))
    let unmatched = 0, maxPositionError = 0, maxWeightError = 0
    const boneFor = name => name.startsWith('head_') ? name : name.startsWith('hand_') ? `arm_${name.slice(-1)}_hand` : name.startsWith('foot_') ? `leg_${name.slice(-1)}_foot` : null
    for (let i = 0; i < g.position.count; i++) {
      const p = new T.Vector3().fromBufferAttribute(g.position, i).applyMatrix4(matrix).toArray(), cellPos = p.map(v => Math.floor(v / cell))
      let best = null, error = Infinity
      for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) for (const item of grid.get([cellPos[0] + x, cellPos[1] + y, cellPos[2] + z].join('/')) ?? []) {
        const d = q.distance(p, item.p); if (d < error) { best = item; error = d }
      }
      if (!best || error > .00015) { unmatched++; continue }
      maxPositionError = Math.max(maxPositionError, error)
      for (const name of memberships[best.i]) {
        q.masks[name].push(i)
        const bone = boneFor(name)
        if (bone) { let sum = 0; for (let k = 0; k < 4; k++) if (mesh.skeleton.bones[g.skinIndex.getComponent(i, k)]?.name === bone) sum += g.skinWeight.getComponent(i, k); maxWeightError = Math.max(maxWeightError, 1 - sum) }
      }
    }
    q.rigid = Object.fromEntries(Object.entries(q.masks).filter(([k]) => /^(head|hand|foot)_/.test(k)))
    q.referenceShapes = {}
    for (const [name, ids] of Object.entries(q.rigid)) { if (!ids.length) throw new Error('Missing protected '+name); const p = q.points(ids); let far = 0; for (let i = 1; i < p.length; i++) if (q.distance(p[i], p[0]) > q.distance(p[far], p[0])) far = i; q.referenceShapes[name] = { far, lengths: p.map(v => [q.distance(v, p[0]), q.distance(v, p[far])]) } }
    q.rigidError = () => { let error = 0; for (const [name, ids] of Object.entries(q.rigid)) { const p = q.points(ids), ref = q.referenceShapes[name]; for (let i = 0; i < p.length; i++) for (const [j, anchor] of [0, ref.far].entries()) error = Math.max(error, Math.abs(q.distance(p[i], p[anchor]) - ref.lengths[i][j])) } return error }
    q.snapshot = () => { let bones = 0, meshes = 0, outlines = 0, invalid = 0; q.root().traverse(n => { if (n.isBone) bones++; if (n.isMesh) n.userData.inkOutline ? outlines++ : meshes++; if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++ }); return { bones, meshes, outlines, invalid } }
    return { unmatched, maxPositionError, maxWeightError, masks: Object.fromEntries(Object.entries(q.masks).map(([k, v]) => [k, v.length])), triangles: (mesh.geometry.index?.count ?? g.position.count) / 3, ...q.snapshot() }
  }, reference)
  await section('native-anatomy', async () => { assert.equal(report.anatomy.unmatched, 0); assert(report.anatomy.maxWeightError < .0001); assert.equal(report.anatomy.triangles, 50000); assert.equal(report.anatomy.meshes, 1); assert.equal(report.anatomy.outlines, 1); assert.equal(report.anatomy.bones, 19); assert.equal(report.anatomy.invalid, 0) })
  for (const name of ['idle', 'walk', 'special']) await section(`motion-${name}`, async () => {
    await action('idle'); await page.waitForTimeout(500); await action(name); await page.waitForTimeout(500)
    const result = { maxStanceDrift: 0, maxRigidError: 0, minFootHeight: Infinity, samples: 0, intervals: new Set() }, plants = new Map()
    let previous = null, cycles = 0
    for (let sample = 0; sample < (name === 'walk' ? 150 : 36); sample++) {
      const data = await page.evaluate(() => { const q = window.jiaochongQA; return { action: q.useApp.getState().action, time: q.root().userData.animationTime, rigidError: q.rigidError(), feet: Object.fromEntries(['l', 'r'].map(s => [s, q.points(q.masks['foot_'+s])])), ...q.snapshot() } })
      if (data.action !== name) break
      assert.equal(data.invalid, 0)
      if (previous !== null && data.time < previous) cycles++
      previous = data.time
      result.maxRigidError = Math.max(result.maxRigidError, data.rigidError)
      for (const side of ['l', 'r']) {
        const feet = data.feet[side], raw = cycles + data.time / 2.4 + (side === 'r' ? .5 : 0), phase = raw % 1
        result.minFootHeight = Math.min(result.minFootHeight, ...feet.map(p => p[1]))
        if (name === 'walk' && (phase < .025 || phase > .635)) continue
        const key = side+'/'+(name === 'walk' ? Math.floor(raw) : 0)
        if (!plants.has(key)) plants.set(key, feet)
        result.intervals.add(key)
        const initial = plants.get(key)
        for (let i = 0; i < feet.length; i++) result.maxStanceDrift = Math.max(result.maxStanceDrift, Math.hypot(...feet[i].map((v, k) => v - initial[i][k])))
      }
      result.samples++; await page.waitForTimeout(50)
    }
    result.intervals = [...result.intervals]; report[name] = result
    assert(result.samples > 15); assert(result.maxRigidError < .0001); assert(result.maxStanceDrift < .001); assert(result.minFootHeight >= -.001)
    if (name === 'walk') assert(cycles >= 2, 'At least three circular gait cycles observed')
    if (name === 'special') { await page.waitForFunction(() => window.jiaochongQA.useApp.getState().action === 'idle', null, { timeout: 6000 }) }
  })
  await section('actual-stage-images', async () => {
    await action('idle'); await page.waitForTimeout(600); await screenshot('desktop-idle')
    await page.addStyleTag({ content: '.qa-anatomy-only .card,.qa-anatomy-only .story-caption,.qa-anatomy-only .scroll-wrap,.qa-anatomy-only .controls,.qa-anatomy-only .actions,.qa-anatomy-only .title{visibility:hidden!important}' })
    await page.evaluate(() => { const q = window.jiaochongQA, c = q.state.controls; q.saved = { position: q.state.camera.position.clone(), target: c.target.clone(), lerp: c.target.lerp, minDistance: c.minDistance, damping: c.enableDamping, offset: q.state.camera.filmOffset }; c.target.lerp = function () { return this }; c.minDistance = .2; c.enableDamping = false; document.body.classList.add('qa-anatomy-only') })
    try {
      for (const [name, regions, direction, distance] of [['front', null, [0,.12,1],4], ['back', null, [0,.12,-1],4], ['34', null, [.65,.18,1],4], ['dual-neck', ['head_l','head_r','neck_l','neck_r'], [0,.12,1],1.5], ['hand-l',['hand_l'],[0,.1,1],.7], ['hand-r',['hand_r'],[0,.1,1],.7], ['feet',['foot_l','foot_r'],[.2,.7,1],1.2]]) {
        await page.evaluate(({ regions, direction, distance }) => { const q = window.jiaochongQA, target = new q.T.Vector3(); if (regions) { const points = q.points(regions.flatMap(k => q.masks[k])); for (const p of points) target.add(new q.T.Vector3(...p)); target.divideScalar(points.length) } else target.set(0,.9,0).applyMatrix4(q.root().matrixWorld); q.state.camera.filmOffset = 0; q.state.camera.updateProjectionMatrix(); q.state.controls.target.copy(target); q.state.camera.position.copy(target).add(new q.T.Vector3(...direction).normalize().multiplyScalar(distance).applyQuaternion(q.root().quaternion)); q.state.controls.update() }, { regions, direction, distance }); await screenshot('anatomy-'+name)
      }
      for (const name of ['walk','special']) { await action(name); await page.waitForTimeout(650); for (let i = 0; i < 3; i++) { await page.evaluate(() => { const q = window.jiaochongQA, t = new q.T.Vector3(0,.9,0).applyMatrix4(q.root().matrixWorld); q.state.controls.target.copy(t); q.state.camera.position.copy(t).add(new q.T.Vector3(.65,.18,1).normalize().multiplyScalar(4).applyQuaternion(q.root().quaternion)); q.state.controls.update() }); await screenshot(`${name}-${i}`); await page.waitForTimeout(300) } }
    } finally { await page.evaluate(() => { const q = window.jiaochongQA, c = q.state.controls, b = q.saved; c.target.lerp = b.lerp; c.minDistance = b.minDistance; c.enableDamping = b.damping; c.target.copy(b.target); q.state.camera.position.copy(b.position); q.state.camera.filmOffset = b.offset; q.state.camera.updateProjectionMatrix(); c.update(); document.body.classList.remove('qa-anatomy-only') }) }
  })
  await section('responsive-and-remount', async () => {
    await action('idle'); await page.waitForTimeout(500); report.remounts = []
    for (const width of [641, 800, 390]) { await page.setViewportSize({width,height:900}); await page.waitForTimeout(650); assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); await screenshot('responsive-'+width) }
    for (let cycle = 0; cycle < 3; cycle++) {
      await page.evaluate(() => { const q=window.jiaochongQA; const old=q.old={skeletons:new Set(),materials:new Set(),geometry:new Set(),textures:new Set(),disposedSkeletons:0,disposedMaterials:0,disposedGeometry:0,disposedTextures:0}; q.root().traverse(n=>{if(n.isSkinnedMesh)old.skeletons.add(n.skeleton);if(n.isMesh){old.geometry.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:[n.material]){old.materials.add(m);if(m.map)old.textures.add(m.map);for(const u of Object.values(m.uniforms??{}))if(u.value?.isTexture)old.textures.add(u.value)}}});for(const s of old.skeletons)if(s.boneTexture)s.boneTexture.addEventListener('dispose',()=>old.disposedSkeletons++);for(const m of old.materials)m.addEventListener('dispose',()=>old.disposedMaterials++);for(const g of old.geometry)g.addEventListener('dispose',()=>old.disposedGeometry++);for(const t of old.textures)t.addEventListener('dispose',()=>old.disposedTextures++) })
      const away = page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jiuweihu'),timeout:30000}); await page.evaluate(()=>window.jiaochongQA.useApp.getState().select('jiuweihu')); await away
      const back = page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jiaochong'),timeout:30000}); await page.evaluate(()=>window.jiaochongQA.useApp.getState().select('jiaochong')); await back; await page.waitForTimeout(500)
      const result=await page.evaluate(()=>{const q=window.jiaochongQA,o=q.old;return{...q.snapshot(),disposedSkeletons:o.disposedSkeletons,skeletons:o.skeletons.size,disposedMaterials:o.disposedMaterials,materials:o.materials.size,disposedGeometry:o.disposedGeometry,disposedTextures:o.disposedTextures,liveOldTextures:[...o.skeletons].filter(s=>s.boneTexture).length,geometryReused:o.geometry.has(q.mesh().geometry)}})
      report.remounts.push(result); assert.equal(result.invalid,0);assert.equal(result.meshes,1);assert.equal(result.outlines,1);assert.equal(result.disposedSkeletons,result.skeletons);assert.equal(result.disposedMaterials,result.materials);assert.equal(result.disposedGeometry,0);assert.equal(result.disposedTextures,0);assert.equal(result.liveOldTextures,0);assert(result.geometryReused)
    }
  })
  await section('controls-and-narration', async () => {
    for (const [name, label] of [['idle','静'],['walk','行'],['special','神通']]) {
      const button = page.getByRole('button', {name:label,exact:true}), box = await button.boundingBox()
      assert(box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 390 && box.y + box.height <= 900)
      await button.click(); assert.equal(await page.evaluate(() => window.jiaochongQA.useApp.getState().action), name)
    }
    await page.waitForFunction(() => window.jiaochongQA.useApp.getState().action === 'idle', null, {timeout:6000})
    await page.locator('.card .story-btn').click()
    await page.waitForFunction(() => window.jiaochongNarrations.some(e => e.src.includes('/jiaochong.mp3') && !e.paused && e.currentTime > .15), null, {timeout:30000})
    await page.locator('.card .story-btn').click()
    assert(await page.evaluate(() => window.jiaochongNarrations.filter(e => e.src.includes('/jiaochong.mp3')).every(e => e.paused)))
    report.narrationPlayedAndStopped = true
  })
  await section('runtime-errors', async () => { assert.equal(report.errors.length,0,report.errors.join('\n')) })
} catch (error) { report.failures.push({section:'setup',error:String(error),stack:error.stack}); await screenshot('failure-setup').catch(()=>{}) }
finally { report.passed = report.failures.length === 0; await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n'); await browser.close() }
console.log(JSON.stringify({passed:report.passed,failures:report.failures,report:join(output,'report.json')}))
if (!report.passed) process.exitCode=1
