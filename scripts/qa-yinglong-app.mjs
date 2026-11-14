// Actual Stage acceptance with a locally intercepted candidate; no public promotion.
// node scripts/qa-yinglong-app.mjs BASE_URL NEW_OUTPUT_DIR CANDIDATE.glb
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'
import { installNativeReference } from './yinglong-native-stage-reference.mjs'

const [base, outputArg, candidateArg] = process.argv.slice(2)
assert(base && outputArg && candidateArg, 'Base URL, new evidence directory and candidate required')
const output = resolve(outputArg), candidate = resolve(candidateArg), bytes = await readFile(candidate)
assert(bytes.length < 15 * 1024 * 1024)
await mkdir(output, { recursive: false })
const report = { candidate, candidateSha256: createHash('sha256').update(bytes).digest('hex'), productionAccepted: false, sections: {}, errors: [], failures: [], images: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route('**/models/yinglong/body.glb*', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
await page.addInitScript(() => {
  window.yinglongNarrations = []
  const play = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function (...args) { window.yinglongNarrations.push(this); return play.apply(this, args) }
})
async function section(name, work) {
  try { await work(); report.sections[name] = { passed: true } }
  catch (e) { report.failures.push({ section: name, error: String(e) }); report.sections[name] = { passed: false, error: String(e) }; await screenshot(`failure-${name}`).catch(() => {}) }
}
async function screenshot(name) { const path = join(output, `${name}.png`); await page.screenshot({ path }); report.images.push(path) }
async function action(name) { await page.evaluate(a => window.yinglongQA.useApp.getState().setAction(a), name) }
async function snapshot(full = false) { return page.evaluate(full => window.yinglongQA.snapshot(full), full) }
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready yinglong'), timeout: 60000 })
  await page.goto(`${base}/?beast=yinglong&action=idle`); await ready; await page.waitForTimeout(750)
  report.setup = await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const module = suffix => resources.find(u => new URL(u).pathname.endsWith(suffix))
    const fiber = await import(module('/@react-three_fiber.js'))
    const { useGLTF } = await import(module('/@react-three_drei.js'))
    const { useApp } = await import(module('/src/app/store.ts'))
    const { BEASTS } = await import(module('/src/app/beasts.ts'))
    const beast = BEASTS.find(b => b.id === 'yinglong'), previewReadyOverride = !beast.ready
    // Candidate-only preview exposes the real controls without promoting files.
    if (previewReadyOverride) beast.ready = true
    const T = await import(module('/three.js'))
    const body = useGLTF('/models/yinglong/body.glb')
    const q = window.yinglongQA = { T, useApp, source: body.scene, state: [...fiber._roots.values()][0].store.getState(), sharedDisposals: 0 }
    q.root = () => q.state.scene.getObjectByName('yinglong_root')
    q.meshes = () => { const list = []; q.root().traverse(n => { if (n.isMesh && !n.userData.inkOutline) list.push(n) }); return list }
    q.sourceSnapshot = () => { const list = []; q.source.traverse(n => list.push({ uuid: n.uuid, children: n.children.map(c => c.uuid), position: n.position.toArray(), quaternion: n.quaternion.toArray(), scale: n.scale.toArray(), geometry: n.geometry?.uuid, skeleton: n.skeleton?.uuid, materials: (Array.isArray(n.material) ? n.material : n.material ? [n.material] : []).map(m => m.uuid) })); return JSON.stringify(list) }
    q.before = q.sourceSnapshot()
    const shared = new Set()
    q.source.traverse(n => { if (n.geometry) shared.add(n.geometry); for (const m of Array.isArray(n.material) ? n.material : n.material ? [n.material] : []) { shared.add(m); for (const v of Object.values(m)) if (v?.isTexture) shared.add(v) } })
    for (const resource of shared) resource.addEventListener('dispose', () => q.sharedDisposals++)
    q.snapshot = full => {
      q.state.scene.updateMatrixWorld(true)
      let invalid = 0, bones = 0, outlines = 0, triangles = 0, maxWeightError = 0
      const p = new T.Vector3(), low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity], screenLow = [Infinity, Infinity], screenHigh = [-Infinity, -Infinity], probes = []
      const blockers = ['.card','.actions','.scroll-wrap','.controls','.title'].flatMap(selector => [...document.querySelectorAll(selector)].filter(element => getComputedStyle(element).visibility !== 'hidden').map(element => ({ selector, rect: element.getBoundingClientRect() })))
      let coveredVertices = 0
      const meshes = q.meshes()
      q.root().traverse(n => { if (n.isBone) bones++; if (n.userData.inkOutline) outlines++; if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++ })
      for (const mesh of meshes) {
        if (!mesh.isSkinnedMesh) throw new Error('Native body must be skinned')
        mesh.skeleton.update(); const a = mesh.geometry.attributes
        triangles += (mesh.geometry.index?.count ?? a.position.count) / 3
        if (full) {
          for (const key of ['position', 'normal', 'skinWeight']) if (!a[key] || !Array.from(a[key].array).every(Number.isFinite)) invalid++
          for (let i = 0; i < a.skinWeight.count; i++) { let sum = 0; for (let k = 0; k < 4; k++) { const w = a.skinWeight.getComponent(i,k); if (w < 0 || a.skinIndex.getComponent(i,k) >= mesh.skeleton.bones.length) invalid++; sum += w } maxWeightError = Math.max(maxWeightError, Math.abs(sum-1)) }
        }
        for (let i = 0; i < a.position.count; i += full ? 1 : 13) {
          mesh.getVertexPosition(i, p); mesh.localToWorld(p)
          if (!p.toArray().every(Number.isFinite)) invalid++
          for (let k = 0; k < 3; k++) { low[k] = Math.min(low[k],p.getComponent(k)); high[k] = Math.max(high[k],p.getComponent(k)) }
          if (i % 169 === 0) probes.push(p.toArray())
          p.project(q.state.camera); const xy = [(p.x+1)*innerWidth/2,(1-p.y)*innerHeight/2]
          for (let k = 0; k < 2; k++) { screenLow[k] = Math.min(screenLow[k],xy[k]); screenHigh[k] = Math.max(screenHigh[k],xy[k]) }
          if (blockers.some(({rect:r}) => xy[0] > r.left && xy[0] < r.right && xy[1] > r.top && xy[1] < r.bottom)) coveredVertices++
        }
      }
      return { nativeDeformation: q.nativeMetrics?.(), coveredVertices, invalid, bones, outlines, meshes: meshes.length, triangles, maxWeightError, low, high, screenLow, screenHigh, probes, time: q.root().userData.animationTime, action: q.useApp.getState().action, rootPosition: q.root().position.toArray(), rootScale: q.root().scale.toArray() }
    }
    return { previewReadyOverride, clips: body.animations.map(c => ({ name: c.name, duration: c.duration })), baseline: q.snapshot(true) }
  })
  await section('native-reference', async () => {
    const reference = JSON.parse(await readFile('raw/_build/yinglong-native-rig-20261114/rest-reference.json','utf8'))
    report.nativeReference = await page.evaluate(installNativeReference, reference)
  })
  await section('native-stage', async () => {
    const s = report.setup.baseline
    assert.equal(s.invalid,0); assert.equal(s.triangles,50000); assert.equal(s.meshes,1); assert.equal(s.outlines,1); assert(s.bones >= 31 && s.bones <= 45); assert(s.maxWeightError < .0001)
    assert.deepEqual(s.rootPosition,[0,0,0]); assert.deepEqual(s.rootScale,[1,1,1]); assert(s.low[1] > .1)
    for (const name of ['idle','walk','special']) assert(report.setup.clips.some(c => c.name === name && c.duration > 0))
  })
  for (const name of ['idle','walk','special']) await section(`motion-${name}`, async () => {
    await action('idle'); await page.waitForTimeout(400); await action(name); await page.waitForTimeout(400)
    const samples = [], duration = report.setup.clips.find(c => c.name === name).duration
    const end = Date.now() + 1000 * (name === 'walk' ? duration*3.2 : Math.min(duration*.7,4))
    while (Date.now() < end) {
      const s = await snapshot(samples.length === 0); assert.equal(s.invalid,0); assert(s.low[1] > .1, `${name} stays above ground`)
      assert(s.nativeDeformation, 'Independent source masks installed')
      for (const [mask,drift] of Object.entries(s.nativeDeformation.rigidDistanceDrift)) assert(drift < (mask.startsWith('feather_') ? .015 : .001), `${name} ${mask} pair drift ${drift}m`)
      for (const [mask,strain] of Object.entries(s.nativeDeformation.rootEdgeStrain)) assert(strain < .18, `${name} ${mask} edge strain ${strain}`)
      samples.push(s); await page.waitForTimeout(100)
    }
    let maxDisplacement = 0
    for (const s of samples) for (let i = 0; i < s.probes.length; i++) maxDisplacement = Math.max(maxDisplacement, Math.hypot(...s.probes[i].map((v,k) => v-samples[0].probes[i][k])))
    assert(maxDisplacement > .001, `${name} actual skin motion`)
    report[name] = { samples, maxDisplacement }
    await screenshot(`desktop-${name}`)
    if (name === 'special') { await page.waitForFunction(() => window.yinglongQA.useApp.getState().action === 'idle',null,{timeout:15000}); report.specialReturnedToIdle = true }
  })
  await section('transitions', async () => {
    for (const name of ['special','walk','idle','special','idle','walk']) { await action(name); await page.waitForTimeout(200); assert.equal((await snapshot(true)).invalid,0) }
  })
  await action('idle'); report.responsive = []
  for (const width of [1440,800,641,390]) await section(`responsive-${width}`, async () => {
    await page.setViewportSize({width,height:900}); await page.waitForTimeout(1000)
    const s = await snapshot(true); report.responsive.push({width,...s}); await screenshot(`responsive-${width}`)
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    assert(s.screenLow[0] >= 8 && s.screenHigh[0] <= width-8 && s.screenLow[1] >= 8 && s.screenHigh[1] <= 790, `Full wing/body frame at ${width}px`)
    assert.equal(s.coveredVertices,0, `Model clear of source card and controls at ${width}px`)
    if (width <= 1000) {
      const card = await page.evaluate(() => {
        const panel=document.querySelector('.card'), design=panel.querySelector('.card-inferred')
        panel.scrollTop=panel.scrollHeight
        const a=panel.getBoundingClientRect(),b=design.getBoundingClientRect()
        const result={sourceCount:panel.querySelectorAll('.card-source').length,designVisible:getComputedStyle(design).display!=='none'&&b.bottom<=a.bottom&&b.bottom>a.top,horizontalOverflow:panel.scrollWidth>panel.clientWidth}
        panel.scrollTop=0;return result
      })
      assert.equal(card.sourceCount,3); assert(card.designVisible); assert(!card.horizontalOverflow)
    }
  })
  await section('remount-ownership', async () => {
    report.remounts = []
    for (let cycle=0; cycle<3; cycle++) {
      await page.evaluate(() => { const q=window.yinglongQA,o=q.old={skeletons:new Set(),materials:new Set(),geometries:new Set(),disposedSkeletons:0,disposedMaterials:0}; q.root().traverse(n=>{if(n.isSkinnedMesh)o.skeletons.add(n.skeleton);if(n.isMesh){o.geometries.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:[n.material])o.materials.add(m)}}); for(const s of o.skeletons){if(!s.boneTexture)throw new Error('Rendered bone texture missing');s.boneTexture.addEventListener('dispose',()=>o.disposedSkeletons++)}for(const m of o.materials)m.addEventListener('dispose',()=>o.disposedMaterials++) })
      const away=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jiuweihu'),timeout:30000}); await page.evaluate(()=>window.yinglongQA.useApp.getState().select('jiuweihu'));await away
      const back=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready yinglong'),timeout:30000});await page.evaluate(()=>window.yinglongQA.useApp.getState().select('yinglong'));await back;await page.waitForTimeout(500)
      const result=await page.evaluate(()=>{const q=window.yinglongQA,o=q.old;return{snapshot:q.snapshot(true),disposedSkeletons:o.disposedSkeletons,skeletons:o.skeletons.size,disposedMaterials:o.disposedMaterials,materials:o.materials.size,liveOldTextures:[...o.skeletons].filter(s=>s.boneTexture).length,geometryReused:q.meshes().every(m=>o.geometries.has(m.geometry)),cacheUnchanged:q.before===q.sourceSnapshot(),sharedDisposals:q.sharedDisposals}})
      report.remounts.push(result);assert.equal(result.snapshot.invalid,0);assert.equal(result.snapshot.meshes,1);assert.equal(result.snapshot.outlines,1);assert.equal(result.disposedSkeletons,result.skeletons);assert.equal(result.disposedMaterials,result.materials);assert.equal(result.liveOldTextures,0);assert(result.geometryReused&&result.cacheUnchanged);assert.equal(result.sharedDisposals,0)
    }
  })
  await section('controls-narration', async () => {
    for (const [name,label] of [['idle','静'],['walk','行'],['special','神通']]) { const button=page.getByRole('button',{name:label,exact:true}),box=await button.boundingBox();assert(box&&box.x>=0&&box.y>=0&&box.x+box.width<=390&&box.y+box.height<=900);await button.click();assert.equal(await page.evaluate(()=>window.yinglongQA.useApp.getState().action),name) }
    await page.waitForFunction(()=>window.yinglongQA.useApp.getState().action==='idle',null,{timeout:15000})
    await page.locator('.card .story-btn').click();await page.waitForFunction(()=>window.yinglongNarrations.some(e=>e.src.includes('/yinglong.mp3')&&!e.paused&&e.currentTime>.15),null,{timeout:30000});await page.locator('.card .story-btn').click();assert(await page.evaluate(()=>window.yinglongNarrations.filter(e=>e.src.includes('/yinglong.mp3')).every(e=>e.paused)));report.narrationPlayedAndStopped=true
  })
  await section('runtime-errors',async()=>assert.deepEqual(report.errors,[]))
} catch(e) { report.failures.push({section:'setup',error:String(e),stack:e.stack});await screenshot('failure-setup').catch(()=>{}) }
finally { report.passed=report.failures.length===0;await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n');await browser.close() }
console.log(JSON.stringify({passed:report.passed,failures:report.failures,report:join(output,'report.json')}))
if(!report.passed)process.exitCode=1
