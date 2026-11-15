// Native High Shuhu app acceptance. node scripts/qa-shuhu.mjs [BASE_URL] [OUTPUT_DIR]
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const base = process.argv[2] ?? 'http://localhost:5204'
const output = resolve(process.argv[3] ?? 'raw/_build/shuhu-runtime-qa')
await mkdir(output, { recursive: true })
const bytes = await readFile(new URL('../public/models/shuhu/body.glb', import.meta.url))
assert(bytes.length <= 15 * 1024 * 1024)
const report = { catalogReady: null, sizeBytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), errors: [], checks: {}, images: [], deviceScope: 'Local Chrome Metal; phone viewport emulation, not a physical phone benchmark' }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
async function shot(name) { const path = join(output, name+'.png'); await page.screenshot({ path }); report.images.push(path) }
async function check(name, fn) { try { report.checks[name] = { passed: true, ...(await fn()) } } catch (e) { report.checks[name] = { passed: false, error: String(e) }; await shot('failure-'+name) } }
async function action(name) { await page.evaluate(name => window.shuhuQA.useApp.getState().setAction(name), name) }
async function bootstrap() {
  return page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(u => new URL(u).pathname === '/src/app/store.ts'))
    const { BEASTS } = await import(resources.find(u => new URL(u).pathname === '/src/app/beasts.ts'))
    const catalogEntry = BEASTS.find(b => b.id === 'shuhu')
    const catalogReady = catalogEntry.ready
    catalogEntry.ready = true // Browser-only controls for candidates awaiting acceptance.
    const T = await import(resources.find(u => new URL(u).pathname.endsWith('/three.js')))
    const q = window.shuhuQA = { T, useApp, state: [...fiber._roots.values()][0].store.getState() }
    q.root = () => q.state.scene.getObjectByName('shuhu_root')
    const meshes = []; q.root().traverse(n => { if (n.isSkinnedMesh && !n.userData.inkOutline) meshes.push(n) })
    if (meshes.length !== 1) throw new Error('Require one native skinned mesh')
    q.mesh = meshes[0]
    const a = q.mesh.geometry.attributes, bones = q.mesh.skeleton.bones
    let invalid = 0, weightError = 0, outlines = 0
    q.root().traverse(n => {
      if (n.userData.inkOutline) outlines++
      if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++
    })
    for (let i=0;i<a.position.count;i++) {
      let sum=0
      for(let k=0;k<4;k++) {
        const w=a.skinWeight.getComponent(i,k), b=a.skinIndex.getComponent(i,k)
        if (!Number.isFinite(w) || w<0 || !Number.isInteger(b) || b<0 || b>=bones.length) invalid++
        sum+=w
      }
      weightError=Math.max(weightError,Math.abs(sum-1))
    }
    // Native rest coordinates reconstructed from the bind transform, independent
    // of the current animation pose; no animated bounds used for source masks.
    q.root().updateMatrixWorld(true)
    const rootBone=bones.find(b=>b.name==='root'), ri=bones.indexOf(rootBone)
    // This source keeps its positive normalization in inverse-bind matrices.
    // The root's rest transform is identity; its parent excludes animated bob.
    const rest=q.root().matrixWorld.clone().invert().multiply(rootBone.parent.matrixWorld).multiply(q.mesh.skeleton.boneInverses[ri])
    const protectedMasks={ head: [], front_l: [], front_r: [], back_l: [], back_r: [] }, v=new T.Vector3()
    for(let i=0;i<a.position.count;i++) {
      v.fromBufferAttribute(a.position,i).applyMatrix4(rest).divideScalar(1.7)
      const [x,z,yNeg]=v.toArray(), y=-yNeg
      let name
      if(Math.abs(x-.015)<.09 && z>.66 && y<-.27) name='head'
      if(z<.043) name=(y<-.12?'front':'back')+(x>0?'_l':'_r')
      if(name) protectedMasks[name].push(i)
    }
    q.points=ids=>{ q.state.scene.updateMatrixWorld(true);q.mesh.skeleton.update();return ids.map(i=>{ q.mesh.getVertexPosition(i,v);q.mesh.localToWorld(v);return v.toArray() }) }
    q.rigid={};q.soles={}
    for(const [name,ids] of Object.entries(protectedMasks)) {
      if(ids.length<10) throw new Error('Missing independent native mask '+name)
      const sampled=ids.filter((_,i)=>i%Math.max(1,Math.floor(ids.length/45))===0)
      const pts=q.points(sampled)
      q.rigid[name]={ ids:sampled, distances:pts.map(p=>Math.hypot(...p.map((n,k)=>n-pts[0][k]))) }
      if(name!=='head') q.soles[name]=sampled.slice(0,3)
    }
    q.snapshot=()=>{
      let error=0
      for(const {ids,distances} of Object.values(q.rigid)) {
        const pts=q.points(ids)
        pts.forEach((p,i)=>{error=Math.max(error,Math.abs(Math.hypot(...p.map((n,k)=>n-pts[0][k]))-distances[i]))})
      }
      return { ...q.root().userData, rigidError:error, position:q.root().position.toArray(), yaw:q.root().rotation.y,
        soles:Object.fromEntries(Object.entries(q.soles).map(([name,ids])=>[name,q.points(ids)])) }
    }
    q.framing=()=>{
      const low=[Infinity,Infinity], high=[-Infinity,-Infinity]
      q.state.scene.updateMatrixWorld(true);q.mesh.skeleton.update()
      for(let i=0;i<a.position.count;i+=20) {
        q.mesh.getVertexPosition(i,v);q.mesh.localToWorld(v);v.project(q.state.camera)
        const xy=[(v.x+1)*innerWidth/2,(1-v.y)*innerHeight/2]
        for(let k=0;k<2;k++){low[k]=Math.min(low[k],xy[k]);high[k]=Math.max(high[k],xy[k])}
      }
      return {low,high,width:innerWidth,height:innerHeight}
    }
    return { catalogReady, triangles:(q.mesh.geometry.index?.count??a.position.count)/3, boneCount:bones.length, outlines, invalid, weightError, masks:Object.fromEntries(Object.entries(protectedMasks).map(([name,ids])=>[name,ids.length])) }
  })
}
try {
  const ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready shuhu'),timeout:60000})
  const started=Date.now();await page.goto(base+'/?beast=shuhu&action=idle');await ready
  report.loadMs=Date.now()-started;await page.waitForTimeout(900)
  await check('nativeRig',async()=>{const data=await bootstrap();report.catalogReady=data.catalogReady;assert.equal(data.triangles,500000);assert.equal(data.boneCount,40);assert.equal(data.invalid,0);assert.equal(data.outlines,1);assert(data.weightError<.001);return data})
  await shot('desktop-idle')
  for(const name of ['idle','walk','special']) await check(name,async()=>{
    await action(name);await page.waitForTimeout(650)
    const samples=await page.evaluate(async()=>{
      const q=window.shuhuQA, samples=[], start=performance.now();let previous=start
      while(performance.now()-start<2500){await new Promise(requestAnimationFrame);const now=performance.now();samples.push({dt:now-previous,...q.snapshot()});previous=now}
      return samples
    })
    const maxRigidError=Math.max(...samples.map(s=>s.rigidError))
    assert(maxRigidError<.0001, 'Rigid head/hoof deformation '+maxRigidError)
    const dts=samples.slice(2).map(s=>s.dt).sort((a,b)=>a-b), p95=dts[Math.floor(dts.length*.95)]
    assert(p95<150, 'Frame responsiveness '+p95)
    let plantedDrift=0
    if(name==='walk') {
      for(const s of samples){const angle=Math.PI/2+1.4-.1*s.elapsedWalkSeconds;assert(Math.abs(s.worldAngle-angle)<1e-6);assert(Math.hypot(s.position[0]-Math.cos(angle),s.position[2]-Math.sin(angle))<1e-6)}
      const phases={back_l:0,front_l:.25,back_r:.5,front_r:.75}
      for(const [leg,offset] of Object.entries(phases)) {
        let anchor=null, lastPhase=0
        for(const s of samples) {
          const phase=(s.animationTime/2.4+offset)%1
          if(phase<.08||phase>.60||phase<lastPhase) anchor=null
          if(phase>=.08&&phase<=.60) {
            anchor??=s.soles[leg]
            s.soles[leg].forEach((p,i)=>{plantedDrift=Math.max(plantedDrift,Math.hypot(...p.map((v,k)=>v-anchor[i][k])))})
          }
          lastPhase=phase
        }
      }
      assert(plantedDrift<.006,'Planted hoof drift '+plantedDrift)
    }
    await shot('desktop-'+name)
    return {maxRigidError,plantedDrift,frames:samples.length,frameMsP95:p95}
  })
  await check('specialReturnsIdle',async()=>{await page.waitForTimeout(4000);assert.equal(await page.evaluate(()=>window.shuhuQA.useApp.getState().action),'idle')})
  await check('nativeCloseups',async()=>{
    await page.evaluate(()=>{
      const q=window.shuhuQA, T=q.T
      q.originalCamera={position:q.state.camera.position.toArray(),target:q.state.controls.target.toArray(),filmOffset:q.state.camera.filmOffset}
      q.state.camera.filmOffset=0;q.state.camera.updateProjectionMatrix()
      const center=new T.Vector3(0,.82,.03).applyMatrix4(q.root().matrixWorld)
      q.state.controls.target.copy(center)
      q.state.camera.position.copy(center).add(new T.Vector3(1,.2,1.6).normalize().multiplyScalar(2.7).applyQuaternion(q.root().quaternion))
      q.state.controls.update()
    })
    await shot('closeup-human-face-wings')
    await page.evaluate(()=>{
      const q=window.shuhuQA, T=q.T, center=new T.Vector3(0,.78,-.18).applyMatrix4(q.root().matrixWorld)
      q.state.controls.target.copy(center)
      q.state.camera.position.copy(center).add(new T.Vector3(1,.3,-1.8).normalize().multiplyScalar(2.7).applyQuaternion(q.root().quaternion))
      q.state.controls.update()
    })
    await shot('closeup-wing-tail-roots')
    await page.evaluate(()=>{const q=window.shuhuQA;q.state.camera.position.fromArray(q.originalCamera.position);q.state.controls.target.fromArray(q.originalCamera.target);q.state.camera.filmOffset=q.originalCamera.filmOffset;q.state.camera.updateProjectionMatrix();q.state.controls.update()})
  })
  await check('mobileViewport',async()=>{
    await page.setViewportSize({width:390,height:844});await action('idle');await page.waitForTimeout(1800)
    const framing=await page.evaluate(()=>window.shuhuQA.framing());await shot('phone-idle')
    assert(framing.low.every(x=>x>=5)&&framing.high[0]<385&&framing.high[1]<839,JSON.stringify(framing))
    await action('walk');await page.waitForTimeout(1400);await shot('phone-walk')
    const frameMs=await page.evaluate(async()=>{const values=[],end=performance.now()+1800;let last=performance.now();while(performance.now()<end){await new Promise(requestAnimationFrame);const now=performance.now();values.push(now-last);last=now}return values.slice(2).sort((a,b)=>a-b)})
    const frameMsP95=frameMs[Math.floor(frameMs.length*.95)]
    assert(frameMsP95<150,'Phone viewport responsiveness '+frameMsP95)
    await action('special');await page.waitForTimeout(1700);await shot('phone-special')
    return {...framing,frameMsP95}
  })
  await check('rapidBeastSwitch',async()=>{
    // Reuse the verified candidate as a static placeholder fixture in this
    // sparse LFS worktree; only Shuhu's unmount/remount is under test.
    await page.route('**/models/_placeholder/fox.glb',route=>route.fulfill({body:bytes,contentType:'model/gltf-binary'}))
    await page.evaluate(()=>window.shuhuQA.useApp.getState().select('xingtian'))
    await page.waitForTimeout(1000)
    await page.evaluate(()=>window.shuhuQA.useApp.getState().select('shuhu'));await page.waitForTimeout(1500)
    const data=await bootstrap();assert.equal(data.outlines,1);assert.equal(data.invalid,0);return data
  })
} finally {
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n');await browser.close()
}
console.log(JSON.stringify(report,null,2))
assert.equal(report.errors.length,0,'Browser errors')
assert(Object.values(report.checks).every(c=>c.passed),'Shuhu acceptance checks failed')
