// Parent runs this against the actual Stage after candidate compression/routing.
// node scripts/qa-jimeng-app.mjs BASE_URL NEW_OUTPUT_DIR CANDIDATE.glb REST_REFERENCE.json
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const [base, outputArg, candidate, referencePath] = process.argv.slice(2)
assert(base && outputArg && candidate && referencePath, 'Base URL, new output, candidate and independent native rest reference required')
const output = resolve(outputArg), bytes = await readFile(resolve(candidate)), referenceBytes = await readFile(resolve(referencePath))
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const reference = JSON.parse(referenceBytes.toString('utf8'))
assert.equal(reference.sourceSha256, 'ffac63d46490bf6c1177c9ecc8f8744491a4f089d2110e12a50f7a0342765556')
assert.equal(hash(referenceBytes), '0a8c8c0c038af9e92b18af955786fed0dd466c7e309ae6b41a6327814ff1ad64', 'Use the independently reviewed export-v6 rest-reference.json')
assert.equal(reference.schemaVersion, 1)
assert.equal(reference.beast, 'jimeng')
assert.equal(reference.boneCount, 17)
assert.equal(reference.coordinates, 'Blender [x,y,z] normalized height1.8')
const protectedNames = ['head', 'hand_l', 'hand_r', 'foot_l', 'foot_r', 'sole_l', 'sole_r']
for (const name of protectedNames) {
  assert(reference.masks[name]?.length >= 3, 'Missing source mask '+name)
  assert(reference.masks[name].every(i => Number.isInteger(i) && i >= 0 && i < reference.points.length))
}
assert(reference.points.every(p => p.length === 3 && p.every(Number.isFinite)))
assert(bytes.length < 15 * 1024 * 1024, 'Parent must compress the full-PBR offline candidate before runtime QA')
await mkdir(output, { recursive: false })
const report = { candidate: resolve(candidate), candidateSha256: hash(bytes), referenceSha256: hash(referenceBytes),
  productionAccepted: false, sections: {}, failures: [], errors: [], images: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.route('**/models/jimeng/body.glb*', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
page.on('pageerror', error => report.errors.push(String(error)))
page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()) })
page.on('response', response => { if (response.status() >= 400) report.errors.push(`${response.status()} ${response.url()}`) })
await page.addInitScript(() => {
  window.jimengNarrations = []
  const play = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function (...args) { window.jimengNarrations.push(this); return play.apply(this, args) }
})
async function screenshot(name) {
  const path = join(output, `${name}.png`)
  await page.screenshot({ path }); report.images.push(path)
}
async function section(name, work) {
  try { await work(); report.sections[name] = { passed: true } }
  catch (error) {
    report.sections[name] = { passed: false, error: String(error) }
    report.failures.push({ section: name, error: String(error) })
    await screenshot('failure-'+name).catch(() => {})
  }
}
async function action(name) { await page.evaluate(name => window.jimengQA.useApp.getState().setAction(name), name) }
async function runtime() { return page.evaluate(() => window.jimengQA.runtime()) }
function checkRuntime(data) {
  assert.equal(data.invalid, 0)
  assert(data.scale.every(value => Math.abs(value - 1) < 1e-7), 'Identity runtime scale required')
  assert(Number.isFinite(data.elapsedWalkSeconds) && data.elapsedWalkSeconds >= 0)
  const angle = Math.PI / 2 - .08 * data.elapsedWalkSeconds
  assert(Math.abs(data.worldAngle - angle) < 1e-7)
  assert(Math.hypot(data.position[0]-Math.cos(angle), data.position[1], data.position[2]-Math.sin(angle)) < 1e-6)
  assert(Math.abs(data.yaw - (Math.PI-angle)) < 1e-7)
}
async function checkFraming() {
  const frame=await page.evaluate(()=>window.jimengQA.framing())
  assert(frame.low.every(v=>v>=8)&&frame.high[0]<=frame.width-8&&frame.high[1]<=frame.height-8,JSON.stringify(frame))
  assert.equal(frame.coveredVertices,0,JSON.stringify(frame))
  return frame
}
async function aim(regions, direction, distance) {
  await page.evaluate(({ regions, direction, distance }) => {
    const q = window.jimengQA, target = new q.T.Vector3()
    if (regions) {
      const points = q.points(regions.flatMap(name => q.masks[name]))
      for (const point of points) target.add(new q.T.Vector3(...point))
      target.divideScalar(points.length)
    } else target.set(0,.9,0).applyMatrix4(q.root().matrixWorld)
    q.state.camera.filmOffset = 0; q.state.camera.updateProjectionMatrix()
    q.state.controls.target.copy(target)
    q.state.camera.position.copy(target).add(new q.T.Vector3(...direction).normalize().multiplyScalar(distance).applyQuaternion(q.root().quaternion))
    q.state.controls.update()
  }, { regions, direction, distance })
}
try {
  const ready = page.waitForEvent('console', { predicate: message => message.text().includes('[beast] ready jimeng'), timeout: 60000 })
  await page.goto(`${base}/?beast=jimeng&action=idle`); await ready; await page.waitForTimeout(700)
  report.anatomy = await page.evaluate(async reference => {
    const resources = performance.getEntriesByType('resource').map(resource => resource.name)
    const fiber = await import(resources.find(url => url.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(url => new URL(url).pathname === '/src/app/store.ts'))
    const { BEASTS } = await import(resources.find(url => new URL(url).pathname === '/src/app/beasts.ts'))
    const beast = BEASTS.find(b => b.id === 'jimeng'), previewReadyOverride = !beast.ready
    if (previewReadyOverride) beast.ready = true
    const T = await import(resources.find(url => new URL(url).pathname.endsWith('/three.js')))
    const q = window.jimengQA = { T, useApp, state: [...fiber._roots.values()][0].store.getState() }
    q.root = () => q.state.scene.getObjectByName('jimeng_root')
    q.mesh = () => {
      const meshes = []; q.root().traverse(node => { if (node.isSkinnedMesh && !node.userData.inkOutline) meshes.push(node) })
      if (meshes.length !== 1) throw new Error('Exactly one native skinned body required')
      return meshes[0]
    }
    q.distance = (a, b) => Math.hypot(...a.map((value, i) => value-b[i]))
    q.points = ids => {
      const mesh = q.mesh(), point = new T.Vector3()
      q.state.scene.updateMatrixWorld(true); mesh.skeleton.update()
      return ids.map(index => { mesh.getVertexPosition(index, point); mesh.localToWorld(point); return point.toArray() })
    }
    q.snapshot = () => {
      let bones = 0, meshes = 0, outlines = 0, invalid = 0
      q.root().traverse(node => {
        if (node.isBone) bones++
        if (node.isMesh) node.userData.inkOutline ? outlines++ : meshes++
        if (![...node.matrixWorld.elements,...node.scale].every(Number.isFinite) || Math.min(...node.scale) <= 0) invalid++
      })
      return { bones, meshes, outlines, invalid }
    }
    q.framing = () => {
      const mesh=q.mesh(), p=new T.Vector3(), low=[Infinity,Infinity],high=[-Infinity,-Infinity]
      q.state.scene.updateMatrixWorld(true);mesh.skeleton.update()
      const blockers=['.card','.actions','.scroll-wrap','.controls','.title'].flatMap(selector=>[...document.querySelectorAll(selector)].filter(e=>getComputedStyle(e).visibility!=='hidden').map(e=>e.getBoundingClientRect()))
      let coveredVertices=0
      for(let i=0;i<mesh.geometry.attributes.position.count;i++){
        mesh.getVertexPosition(i,p);mesh.localToWorld(p);p.project(q.state.camera)
        const xy=[(p.x+1)*innerWidth/2,(1-p.y)*innerHeight/2]
        for(let k=0;k<2;k++){low[k]=Math.min(low[k],xy[k]);high[k]=Math.max(high[k],xy[k])}
        if(blockers.some(r=>xy[0]>r.left&&xy[0]<r.right&&xy[1]>r.top&&xy[1]<r.bottom))coveredVertices++
      }
      return{low,high,coveredVertices,width:innerWidth,height:innerHeight}
    }
    q.runtime = () => {
      const root = q.root()
      return { ...q.snapshot(), action: q.useApp.getState().action, time: root.userData.animationTime,
        weight: root.userData.animationWeight, elapsedWalkSeconds: root.userData.elapsedWalkSeconds,
        worldAngle: root.userData.worldAngle, position: root.position.toArray(), yaw: root.rotation.y, scale: root.scale.toArray() }
    }
    const mesh = q.mesh(), attributes = mesh.geometry.attributes, rootBone = mesh.skeleton.bones.find(bone => bone.name === 'root')
    q.state.scene.updateMatrixWorld(true); mesh.skeleton.update()
    const rootIndex = mesh.skeleton.bones.indexOf(rootBone)
    if (rootIndex < 0 || Math.abs(mesh.userData.restHeight - 1.8) > 1e-5) throw new Error('Native rig metadata missing')
    // Reconstruct decoded rest positions independently of weights/mask names.
    // Matching uses the reviewed source geometry, not the rig's weight groups.
    const matrix = q.root().matrixWorld.clone().invert().multiply(mesh.matrixWorld).multiply(mesh.bindMatrixInverse)
      .multiply(rootBone.matrixWorld).multiply(mesh.skeleton.boneInverses[rootIndex]).multiply(mesh.bindMatrix)
    const cell = .0003, grid = new Map(), memberships = reference.points.map(() => [])
    for (const [name, ids] of Object.entries(reference.masks)) for (const i of ids) memberships[i].push(name)
    const key = point => point.map(value => Math.floor(value/cell)).join('/')
    reference.points.forEach((point, index) => {
      const p = [point[0],point[2],-point[1]], k = key(p)
      if (!grid.has(k)) grid.set(k, [])
      grid.get(k).push({ index, point: p })
    })
    q.masks = Object.fromEntries(Object.keys(reference.masks).map(name => [name, []]))
    q.sourcePoints = []
    q.decodedPoints = []
    let unmatched = 0, maxPositionError = 0, maxWeightError = 0, maxWeightSumError = 0, invalidAttributes = 0
    const boneFor = name => name === 'head' ? 'head' : name.startsWith('hand_') ? `arm_${name.slice(-1)}_hand`
      : /^(foot|sole)_/.test(name) ? `leg_${name.slice(-1)}_foot` : null
    for (const name of ['position','normal','uv','skinIndex','skinWeight']) if (!attributes[name]) throw new Error('Missing attribute '+name)
    for (let i = 0; i < attributes.position.count; i++) {
      for (const attribute of Object.values(attributes)) for (let k = 0; k < attribute.itemSize; k++) {
        if (!Number.isFinite(attribute.getComponent(i,k))) invalidAttributes++
      }
      let weightSum = 0
      for (let k = 0; k < 4; k++) {
        const index = attributes.skinIndex.getComponent(i,k), weight = attributes.skinWeight.getComponent(i,k)
        if (!Number.isInteger(index) || index < 0 || index >= mesh.skeleton.bones.length || weight < 0) invalidAttributes++
        weightSum += weight
      }
      maxWeightSumError = Math.max(maxWeightSumError,Math.abs(weightSum-1))
      const point = new T.Vector3().fromBufferAttribute(attributes.position,i).applyMatrix4(matrix).toArray()
      const cellPos = point.map(value => Math.floor(value/cell))
      let best = null, error = Infinity
      for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
        for (const item of grid.get([cellPos[0]+x,cellPos[1]+y,cellPos[2]+z].join('/')) ?? []) {
          const distance = q.distance(point,item.point)
          if (distance < error) { best = item; error = distance }
        }
      }
      if (!best || error > .00015) { unmatched++; continue }
      maxPositionError = Math.max(maxPositionError,error)
      q.sourcePoints[i] = best.point
      q.decodedPoints[i] = point
      for (const name of memberships[best.index]) {
        q.masks[name].push(i)
        const bone = boneFor(name)
        if (bone) {
          let weight = 0
          for (let k = 0; k < 4; k++) if (mesh.skeleton.bones[attributes.skinIndex.getComponent(i,k)]?.name === bone) weight += attributes.skinWeight.getComponent(i,k)
          maxWeightError = Math.max(maxWeightError,Math.abs(1-weight))
        }
      }
    }
    q.rigid = Object.fromEntries(['head','hand_l','hand_r','foot_l','foot_r'].map(name => [name,q.masks[name]]))
    q.referenceShapes = {}
    for (const [name, ids] of Object.entries(q.rigid)) {
      if (!ids.length) throw new Error('Missing protected '+name)
      // Source matching bounds compression error separately. Rigid-shape motion
      // compares against decoded rest geometry, never an animated/weighted pose.
      const points = ids.map(i => q.decodedPoints[i]); let far = 0
      for (let i = 1; i < points.length; i++) if (q.distance(points[i],points[0]) > q.distance(points[far],points[0])) far = i
      q.referenceShapes[name] = { far, lengths: points.map(point => [q.distance(point,points[0]),q.distance(point,points[far])]) }
    }
    q.rigidError = () => {
      let error = 0
      for (const [name, ids] of Object.entries(q.rigid)) {
        const points = q.points(ids), reference = q.referenceShapes[name]
        for (let i = 0; i < points.length; i++) for (const [j, anchor] of [0,reference.far].entries()) {
          error = Math.max(error,Math.abs(q.distance(points[i],points[anchor])-reference.lengths[i][j]))
        }
      }
      return error
    }
    q.soleAnchors = {}
    for (const side of ['l','r']) {
      const ids = q.masks['sole_'+side], feet = new Set(q.masks['foot_'+side])
      if (ids.length < 3 || !ids.every(i => feet.has(i))) throw new Error('Complete source sole must be a foot subset: '+side)
      const points = ids.map(i => new T.Vector3(...q.sourcePoints[i])); let far = 0, across = 0, area = 0
      for (let i = 1; i < points.length; i++) if (points[i].distanceTo(points[0]) > points[far].distanceTo(points[0])) far = i
      const axis = points[far].clone().sub(points[0])
      for (let i = 1; i < points.length; i++) {
        const cross = axis.clone().cross(points[i].clone().sub(points[0])).length()
        if (cross > area) { area = cross; across = i }
      }
      if (area < .001) throw new Error('Independent sole frame is degenerate: '+side)
      q.soleAnchors[side] = [0,far,across]
    }
    q.soleFrame = (side, points) => {
      const [a,b,c] = q.soleAnchors[side], origin = new T.Vector3(...points[a])
      const axis = new T.Vector3(...points[b]).sub(origin), across = new T.Vector3(...points[c]).sub(origin)
      return [axis.clone().normalize().toArray(),axis.cross(across).normalize().toArray()]
    }
    return { previewReadyOverride, unmatched, maxPositionError, maxWeightError, maxWeightSumError, invalidAttributes,
      masks: Object.fromEntries(Object.entries(q.masks).map(([name,ids]) => [name,ids.length])),
      triangles: (mesh.geometry.index?.count ?? attributes.position.count)/3, ...q.snapshot() }
  }, reference)
  await section('native-anatomy', async () => {
    const anatomy = report.anatomy
    assert.equal(anatomy.unmatched,0); assert(anatomy.maxWeightError < .0001); assert(anatomy.maxWeightSumError < .00001)
    assert.equal(anatomy.invalidAttributes,0); assert.equal(anatomy.triangles,50000)
    assert.equal(anatomy.meshes,1); assert.equal(anatomy.outlines,1); assert.equal(anatomy.bones,17); assert.equal(anatomy.invalid,0)
    for (const name of protectedNames) assert(anatomy.masks[name] >= 3)
    checkRuntime(await runtime())
  })
  await section('initial-framing',async()=>{report.initialFrame=await checkFraming();await screenshot('initial-desktop-idle')})
  for (const name of ['idle','walk','special']) await section('motion-'+name, async () => {
    await action('idle'); await page.waitForTimeout(500); await action(name); await page.waitForTimeout(500)
    const result = { maxFullFootStanceDrift:0, maxFullSoleStanceDrift:0, maxSoleOrientationRadians:0, maxRigidError:0,
      minFootHeight:Infinity, minSoleHeight:Infinity, samples:0, intervals:new Set() }, plants = new Map()
    let previous = null, cycles = 0
    for (let sample = 0; sample < (name === 'walk' ? 150 : 36); sample++) {
      const data = await page.evaluate(() => {
        const q = window.jimengQA
        return { ...q.runtime(), rigidError:q.rigidError(), contacts:Object.fromEntries(['l','r'].map(side => {
          const foot = q.points(q.masks['foot_'+side]), sole = q.points(q.masks['sole_'+side])
          return [side,{ foot,sole,frame:q.soleFrame(side,sole) }]
        })) }
      })
      if (data.action !== name) break
      checkRuntime(data); assert(data.weight > .999, 'Stance measurements require the full-weight clip')
      if (previous !== null && data.time < previous) cycles++
      previous = data.time; result.maxRigidError = Math.max(result.maxRigidError,data.rigidError)
      for (const side of ['l','r']) {
        const contact = data.contacts[side], raw = cycles+data.time/2.4+(side === 'r' ? .5 : 0)
        result.minFootHeight = Math.min(result.minFootHeight,...contact.foot.map(point => point[1]))
        result.minSoleHeight = Math.min(result.minSoleHeight,...contact.sole.map(point => point[1]))
        if (name === 'walk' && raw%1 >= .66) continue
        const key = side+'/'+(name === 'walk' ? Math.floor(raw) : 0)
        if (!plants.has(key)) plants.set(key,contact)
        result.intervals.add(key)
        const initial = plants.get(key)
        for (const [part,field] of [['foot','maxFullFootStanceDrift'],['sole','maxFullSoleStanceDrift']]) {
          for (let i = 0; i < contact[part].length; i++) result[field] = Math.max(result[field],Math.hypot(...contact[part][i].map((value,k) => value-initial[part][i][k])))
        }
        const orientation = Math.max(...contact.frame.map((axis,i) => Math.acos(Math.max(-1,Math.min(1,axis.reduce((sum,value,k) => sum+value*initial.frame[i][k],0))))))
        result.maxSoleOrientationRadians = Math.max(result.maxSoleOrientationRadians,orientation)
      }
      result.samples++; await page.waitForTimeout(50)
    }
    result.intervals = [...result.intervals]; report[name] = result
    assert(result.samples > 15); assert(result.maxRigidError < .0001)
    assert(result.maxFullFootStanceDrift < .001); assert(result.maxFullSoleStanceDrift < .001)
    assert(result.maxSoleOrientationRadians < .001); assert(result.minFootHeight >= -.001); assert(result.minSoleHeight >= -.001)
    if (name === 'walk') assert(cycles >= 2, 'Observe at least three circular gait cycles')
    if (name === 'special') await page.waitForFunction(() => window.jimengQA.useApp.getState().action === 'idle',null,{timeout:6000})
  })
  await section('world-clock-across-action-restarts', async () => {
    await action('walk'); await page.waitForTimeout(900)
    const first = await runtime(); checkRuntime(first)
    assert(first.elapsedWalkSeconds > .5)
    await action('idle'); await page.waitForTimeout(650)
    const paused = await runtime(); checkRuntime(paused)
    await page.waitForTimeout(500)
    const still = await runtime(); checkRuntime(still)
    assert(paused.elapsedWalkSeconds >= first.elapsedWalkSeconds)
    assert.equal(still.elapsedWalkSeconds,paused.elapsedWalkSeconds)
    await action('special'); await page.waitForTimeout(700)
    const special = await runtime(); checkRuntime(special)
    assert.equal(special.elapsedWalkSeconds,paused.elapsedWalkSeconds)
    await action('walk'); await page.waitForTimeout(700)
    const resumed = await runtime(); checkRuntime(resumed)
    assert(resumed.elapsedWalkSeconds > special.elapsedWalkSeconds+.3, 'World time must continue, not reset on walk re-entry')
    assert(resumed.time > .3 && resumed.time < 1.4, 'Local walk clip restarts independently of accumulated world time')
    report.restarts = { first,paused,still,special,resumed }
  })
  await section('full-orbit-framing', async () => {
    report.orbitFrames = []
    for (const width of [1440, 390]) {
      await page.setViewportSize({width,height:900}); await action('walk'); await page.waitForTimeout(700)
      const start = (await runtime()).elapsedWalkSeconds, deadline = Date.now()+150000
      let quarter = 0
      while ((await runtime()).elapsedWalkSeconds-start < 2*Math.PI/.08) {
        assert(Date.now()<deadline,'A complete real-time orbit must finish before timeout')
        const data=await runtime(); checkRuntime(data)
        report.orbitFrames.push({width,elapsedWalkSeconds:data.elapsedWalkSeconds,...await checkFraming()})
        const progress=(data.elapsedWalkSeconds-start)*.08/(2*Math.PI)
        if(progress>=quarter/4&&quarter<4){await screenshot(`orbit-${width}-quarter-${quarter}`);quarter++}
        await page.waitForTimeout(1000)
      }
    }
    await action('idle'); await page.setViewportSize({width:1440,height:900}); await page.waitForTimeout(700)
  })
  await section('actual-stage-images', async () => {
    await action('idle'); await page.waitForTimeout(600); await screenshot('desktop-idle')
    await page.addStyleTag({content:'.qa-anatomy-only .card,.qa-anatomy-only .story-caption,.qa-anatomy-only .scroll-wrap,.qa-anatomy-only .controls,.qa-anatomy-only .actions,.qa-anatomy-only .title{visibility:hidden!important}'})
    await page.evaluate(() => {
      const q = window.jimengQA, c = q.state.controls
      q.saved = { position:q.state.camera.position.clone(),target:c.target.clone(),lerp:c.target.lerp,minDistance:c.minDistance,
        minPolarAngle:c.minPolarAngle,maxPolarAngle:c.maxPolarAngle,damping:c.enableDamping,offset:q.state.camera.filmOffset }
      c.target.lerp = function () { return this }; c.minDistance = .2; c.minPolarAngle = 0; c.maxPolarAngle = Math.PI; c.enableDamping = false
      document.body.classList.add('qa-anatomy-only')
    })
    try {
      for (const [name,regions,direction,distance] of [
        ['front',null,[0,.12,1],4],['back',null,[0,.12,-1],4],['34',null,[.65,.18,1],4],
        ['head-neck',['head','neck'],[0,.12,1],1.5],['hand-l',['hand_l'],[0,.1,1],.7],['hand-l-back',['hand_l'],[0,.1,-1],.7],
        ['hand-r',['hand_r'],[0,.1,1],.7],['hand-r-back',['hand_r'],[0,.1,-1],.7],['feet',['foot_l','foot_r'],[.2,.7,1],1.2]
      ]) { await aim(regions,direction,distance); await screenshot('anatomy-'+name) }
      for (const name of ['walk','special']) {
        await action(name); await page.waitForTimeout(650)
        for (let i = 0; i < 3; i++) {
          await aim(null,[.65,.18,1],4); await screenshot(`${name}-${i}`); await page.waitForTimeout(300)
        }
        for (const [region,masks,distance] of [['feet',['foot_l','foot_r'],1.2],['hand-l',['hand_l'],.7],['hand-r',['hand_r'],.7]]) {
          // Restart the one-shot special for each closeup so every capture uses it.
          if (name === 'special') { await action('idle'); await page.waitForTimeout(350); await action('special'); await page.waitForTimeout(1400) }
          await aim(masks,[.2,.5,1],distance); await screenshot(`${name}-${region}`)
        }
      }
    } finally {
      await page.evaluate(() => {
        const q = window.jimengQA, c = q.state.controls, saved = q.saved
        c.target.lerp = saved.lerp; c.minDistance = saved.minDistance; c.minPolarAngle = saved.minPolarAngle; c.maxPolarAngle = saved.maxPolarAngle
        c.enableDamping = saved.damping; c.target.copy(saved.target); q.state.camera.position.copy(saved.position)
        q.state.camera.filmOffset = saved.offset; q.state.camera.updateProjectionMatrix(); c.update(); document.body.classList.remove('qa-anatomy-only')
      })
    }
  })
  await section('responsive-and-remount', async () => {
    await action('idle'); await page.waitForTimeout(500); report.remounts = []
    for (const width of [641,800,390]) {
      await page.setViewportSize({width,height:900}); await page.waitForTimeout(650)
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); await screenshot('responsive-'+width)
      const frame=await checkFraming();(report.responsive??=[]).push(frame)
      const card=await page.locator('.card').evaluate(element=>{
        const source=element.querySelector('.card-source'),design=element.querySelector('.card-inferred')
        element.scrollTop=element.scrollHeight
        const rect=element.getBoundingClientRect(),inferred=design.getBoundingClientRect()
        const result={width:innerWidth,source:source.textContent,design:design.textContent,scrollWidth:element.scrollWidth,clientWidth:element.clientWidth,
          designVisible:getComputedStyle(design).display!=='none'&&inferred.bottom<=rect.bottom+1&&inferred.top>=rect.top-1}
        element.scrollTop=0;return result
      })
      assert(card.source.includes('其狀人身而龍首')&&card.source.includes('中次八经'))
      assert(card.design.includes('设计')&&card.designVisible&&card.scrollWidth<=card.clientWidth,JSON.stringify(card))
      ;(report.cards??=[]).push(card)
    }
    for (let cycle = 0; cycle < 3; cycle++) {
      await page.evaluate(() => {
        const q = window.jimengQA, old = q.old = { skeletons:new Set(),materials:new Set(),geometry:new Set(),textures:new Set(),
          disposedSkeletons:0,disposedMaterials:0,disposedGeometry:0,disposedTextures:0 }
        q.root().traverse(node => {
          if (node.isSkinnedMesh) old.skeletons.add(node.skeleton)
          if (node.isMesh) {
            old.geometry.add(node.geometry)
            for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
              old.materials.add(material); if (material.map) old.textures.add(material.map)
              for (const uniform of Object.values(material.uniforms ?? {})) if (uniform.value?.isTexture) old.textures.add(uniform.value)
            }
          }
        })
        for (const skeleton of old.skeletons) if (skeleton.boneTexture) skeleton.boneTexture.addEventListener('dispose',() => old.disposedSkeletons++)
        for (const material of old.materials) material.addEventListener('dispose',() => old.disposedMaterials++)
        for (const geometry of old.geometry) geometry.addEventListener('dispose',() => old.disposedGeometry++)
        for (const texture of old.textures) texture.addEventListener('dispose',() => old.disposedTextures++)
      })
      const away = page.waitForEvent('console',{predicate:message => message.text().includes('[beast] ready jiuweihu'),timeout:30000})
      await page.evaluate(() => window.jimengQA.useApp.getState().select('jiuweihu')); await away
      const back = page.waitForEvent('console',{predicate:message => message.text().includes('[beast] ready jimeng'),timeout:30000})
      await page.evaluate(() => window.jimengQA.useApp.getState().select('jimeng')); await back; await page.waitForTimeout(500)
      const result = await page.evaluate(() => {
        const q = window.jimengQA, old = q.old, mesh = q.mesh(), textures = new Set()
        for (const uniform of Object.values(mesh.material.uniforms ?? {})) if (uniform.value?.isTexture) textures.add(uniform.value)
        return { ...q.snapshot(),disposedSkeletons:old.disposedSkeletons,skeletons:old.skeletons.size,
          disposedMaterials:old.disposedMaterials,materials:old.materials.size,disposedGeometry:old.disposedGeometry,
          disposedTextures:old.disposedTextures,liveOldBoneTextures:[...old.skeletons].filter(skeleton => skeleton.boneTexture).length,
          geometryReused:old.geometry.has(mesh.geometry),skeletonIsNew:!old.skeletons.has(mesh.skeleton),materialIsNew:!old.materials.has(mesh.material),
          sourceTexturesReused:textures.size > 0 && [...textures].every(texture => old.textures.has(texture)) }
      })
      report.remounts.push({...result,frame:await checkFraming()})
      assert.equal(result.invalid,0); assert.equal(result.meshes,1); assert.equal(result.outlines,1); assert.equal(result.bones,17)
      assert.equal(result.disposedSkeletons,result.skeletons); assert.equal(result.disposedMaterials,result.materials)
      assert.equal(result.disposedGeometry,0); assert.equal(result.disposedTextures,0); assert.equal(result.liveOldBoneTextures,0)
      assert(result.geometryReused && result.skeletonIsNew && result.materialIsNew && result.sourceTexturesReused)
    }
  })
  await section('controls-and-narration', async () => {
    for (const [name,label] of [['idle','静'],['walk','行'],['special','神通']]) {
      const button = page.getByRole('button',{name:label,exact:true}), box = await button.boundingBox()
      assert(box && box.x >= 0 && box.y >= 0 && box.x+box.width <= 390 && box.y+box.height <= 900)
      await button.click(); assert.equal(await page.evaluate(() => window.jimengQA.useApp.getState().action),name)
    }
    await page.waitForFunction(() => window.jimengQA.useApp.getState().action === 'idle',null,{timeout:6000})
    await page.locator('.card .story-btn').click()
    await page.waitForFunction(() => window.jimengNarrations.some(element => element.src.includes('/jimeng.mp3') && !element.paused && element.currentTime > .15),null,{timeout:30000})
    await page.locator('.card .story-btn').click()
    assert(await page.evaluate(() => window.jimengNarrations.filter(element => element.src.includes('/jimeng.mp3')).every(element => element.paused)))
    report.narrationPlayedAndStopped = true
  })
  await section('runtime-errors', async () => { assert.equal(report.errors.length,0,report.errors.join('\n')) })
} catch (error) {
  report.failures.push({section:'setup',error:String(error),stack:error.stack})
  await screenshot('failure-setup').catch(() => {})
} finally {
  report.passed = report.failures.length === 0
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n')
  await browser.close()
}
console.log(JSON.stringify({passed:report.passed,failures:report.failures,report:join(output,'report.json')}))
if (!report.passed) process.exitCode = 1
