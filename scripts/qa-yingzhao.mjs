// Actual rendered world-space hoof vertices, anatomy, finite skinning and remount/audio QA.
// node scripts/qa-yingzhao.mjs [http://localhost:5213] [/tmp/yingzhao-qa]
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'
const [base='http://localhost:5213',output='/tmp/yingzhao-qa']=process.argv.slice(2)
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)})
const report={actions:{},remounts:[],angles:[],errors}
try {
  let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready yingzhao')})
  await page.goto(`${base}/?beast=yingzhao&action=idle`);await ready
  await page.evaluate(async()=>{
    const url=performance.getEntriesByType('resource').map(r=>r.name).find(u=>u.includes('@react-three_fiber.js'))
    const fiber=await import(url);const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'))
    window.yingzhaoQA={state:[...fiber._roots.values()][0].store.getState(),useApp}
  })
  async function snapshot(full=false) {
    return page.evaluate(all=>{
      const root=window.yingzhaoQA.state.scene.getObjectByName('yingzhao_root');window.yingzhaoQA.state.scene.updateMatrixWorld(true)
      const meshes=[],bones=[],outlines=[];let invalid=0,nodes=0
      root.traverse(n=>{
        nodes++
        if(![...n.matrixWorld.elements,...n.position,...n.quaternion,...n.scale].every(Number.isFinite))invalid++
        if(Math.min(...n.scale)<=0)invalid++
        if(n.isBone)bones.push(n)
        if(!n.isMesh)return
        if(n.userData.inkOutline){outlines.push(n);return}
        meshes.push(n)
        if(all)for(const key of ['position','normal','skinWeight']){
          const a=n.geometry.attributes[key];if(a&&!Array.from(a.array).every(Number.isFinite))invalid++
        }
        if(n.skeleton){n.skeleton.update();if(!Array.from(n.skeleton.boneMatrices).every(Number.isFinite))invalid++}
      })
      const feet={};const p=root.position.clone()
      for(const mesh of meshes){
        const body=mesh.name.startsWith('yingzhao_horse_body');if(!all&&!body)continue
        const g=mesh.geometry.attributes
        for(let i=0;i<g.position.count;i++){
          const foot=body&&g.skinIndex?mesh.skeleton.bones[g.skinIndex.getX(i)]?.name:null
          if(!all&&(!foot?.endsWith('_foot')||g.position.getY(i)>.01))continue
          mesh.getVertexPosition(i,p)
          if(![...p].every(Number.isFinite))invalid++
          if(foot?.endsWith('_foot')&&g.position.getY(i)<.01){mesh.localToWorld(p);feet[foot]=Math.min(feet[foot]??Infinity,p.y)}
        }
      }
      return {invalid,nodes,meshes:meshes.length,outlines:outlines.length,bones:bones.length,
        wings:meshes.filter(n=>/^yingzhao_wing_[lr]$/.test(n.name)).length,
        wingBones:bones.filter(n=>n.name.startsWith('yingzhao_wing_')).length,
        heads:root.getObjectByName('yingzhao_human_head')?1:0,
        tails:meshes.filter(n=>n.name==='yingzhao_horse_tail').length,
        horns:meshes.filter(n=>n.name.includes('horn')).length,
        legs:bones.filter(n=>/^(front|back)_[lr]_foot$/.test(n.name)).length,feet}
    },full)
  }
  const baseline=await snapshot(true);report.baseline=baseline
  for(const [k,v]of Object.entries({invalid:0,wings:2,wingBones:10,heads:1,tails:1,horns:0,legs:4}))assert.equal(baseline[k],v,k)
  assert.equal(Object.keys(baseline.feet).length,4)
  for(const action of ['idle','walk','special']){
    await page.evaluate(a=>window.yingzhaoQA.useApp.getState().setAction(a),action)
    const samples=[]
    for(let i=0;i<(action==='special'?42:24);i++){await page.waitForTimeout(120);samples.push(await snapshot(i%12===0))}
    assert(samples.every(s=>s.invalid===0&&s.wings===2&&s.heads===1))
    if(action!=='walk')assert(samples.slice(4).every(s=>Object.values(s.feet).every(y=>Math.abs(y)<.008)),`${action}: settled ground contact`)
    else assert(samples.every(s=>Math.abs(Math.min(...Object.values(s.feet)))<.008),'walk support contact')
    report.actions[action]=samples
  }
  // Sample actual displayed vertices in world coordinates through three gait
  // cycles. Track several separated points across each sole, not just min Y.
  await page.evaluate(()=>window.yingzhaoQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(650)
  report.worldContact=await page.evaluate(async()=>{
    const root=window.yingzhaoQA.state.scene.getObjectByName('yingzhao_root')
    const points={};const p=root.position.clone()
    root.traverse(mesh=>{
      if(!mesh.isMesh||mesh.userData.inkOutline||!mesh.name.startsWith('yingzhao_horse_body'))return
      const g=mesh.geometry.attributes
      mesh.skeleton.update()
      for(let i=0;i<g.position.count;i++){
        // Choose actual skinned resting soles after idle settles, so neither
        // quantization nor inverse-bind frames can select higher shank points.
        mesh.getVertexPosition(i,p);mesh.localToWorld(p)
        if(p.y>.003)continue
        const foot=mesh.skeleton.bones[g.skinIndex.getX(i)]?.name
        if(!foot?.endsWith('_foot')||g.skinWeight.getX(i)<.99999)continue
        ;(points[foot]??=[]).push({mesh,i,x:g.position.getX(i),z:g.position.getZ(i)})
      }
    })
    for(const [foot,vertices] of Object.entries(points)){
      if(vertices.length<3)throw new Error(`${foot}: fewer than three sole vertices`)
      const a=vertices[0]
      const spansPlane=vertices.some(b=>vertices.some(c=>Math.abs((b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x))>1e-6))
      if(!spansPlane)throw new Error(`${foot}: sole points are collinear`)
    }
    // Keep every actual sole vertex, including toe/heel and lateral extremes.
    // scene.updateMatrixWorld invokes SkinnedMesh's inverse-bind update too;
    // updateWorldMatrix alone would leave attached bindMatrixInverse stale.
    window.yingzhaoQA.state.scene.updateMatrixWorld(true)
    window.yingzhaoQA.useApp.getState().setAction('walk')
    await new Promise(resolve=>setTimeout(resolve,650))
    const offsets={back_l_foot:0,front_l_foot:.25,back_r_foot:.5,front_r_foot:.75}
    const plants={};let cycle=0,previous=root.userData.animationTime,frames=0
    const start=performance.now()
    while(cycle<4){
      if(performance.now()-start>25000)throw new Error('Four actual gait cycles did not finish within 25 seconds')
      await new Promise(resolve=>requestAnimationFrame(resolve));window.yingzhaoQA.state.scene.updateMatrixWorld(true)
      for(const mesh of new Set(Object.values(points).flat().map(p=>p.mesh)))mesh.skeleton.update()
      const t=root.userData.animationTime;if(t<previous-.5)cycle++;previous=t;frames++
      for(const [foot,vertices]of Object.entries(points)){
        const phase=t/1.8+offsets[foot];const p=phase%1
        if(p<.04||p>.64)continue
        const key=`${foot}/${cycle+Math.floor(phase)}`
        const positions=vertices.map(({mesh,i})=>{const q=root.position.clone();mesh.getVertexPosition(i,q);mesh.localToWorld(q);return q.toArray()})
        const plant=plants[key]??={foot,initial:positions,maxDrift:0,maxDirection:0,samples:0,minY:Infinity,maxY:-Infinity}
        positions.forEach((q,i)=>{plant.maxDrift=Math.max(plant.maxDrift,Math.hypot(...q.map((v,j)=>v-plant.initial[i][j])));plant.minY=Math.min(plant.minY,q[1]);plant.maxY=Math.max(plant.maxY,q[1])})
        const a=positions[0],a0=plant.initial[0]
        // All nonzero sole edges include both longitudinal and lateral directions.
        for(let i=1;i<positions.length;i++){
          const one=positions[i].map((v,k)=>v-a[k]),two=plant.initial[i].map((v,k)=>v-a0[k])
          const length=Math.hypot(...one)*Math.hypot(...two)
          if(length<1e-8)continue
          const dot=one.reduce((sum,v,k)=>sum+v*two[k],0)/length
          plant.maxDirection=Math.max(plant.maxDirection,Math.acos(Math.max(-1,Math.min(1,dot))))
        }
        plant.samples++;plants[key]=plant
      }
    }
    const measured=Object.values(plants).filter(p=>p.samples>12)
    return {frames,pointsPerFoot:Object.fromEntries(Object.entries(points).map(([k,v])=>[k,v.length])),plants:measured,maxDrift:Math.max(...measured.map(p=>p.maxDrift)),maxDirection:Math.max(...measured.map(p=>p.maxDirection))}
  })
  assert.equal(Object.keys(report.worldContact.pointsPerFoot).length,4)
  assert(report.worldContact.plants.length>=8,'at least two stances on every hoof')
  for(const foot of Object.keys(report.worldContact.pointsPerFoot))assert(report.worldContact.plants.filter(p=>p.foot===foot).length>=2,`two stances for ${foot}`)
  assert(report.worldContact.maxDrift<.0006,`world sole drift ${report.worldContact.maxDrift}m`)
  assert(report.worldContact.maxDirection<Math.PI/3600,'Sole direction drift')
  await page.evaluate(()=>window.yingzhaoQA.useApp.getState().setAction('special'));await page.waitForTimeout(1400)
  report.interruption={before:await snapshot()}
  await page.evaluate(()=>window.yingzhaoQA.useApp.getState().setAction('walk'));await page.waitForTimeout(80)
  report.interruption.after=await snapshot();assert.equal(report.interruption.after.invalid,0)
  await page.evaluate(()=>window.yingzhaoQA.useApp.getState().setAction('idle'));await page.waitForTimeout(550)
  report.interruption.settled=await snapshot(true)
  report.skeletonCleanup=[]
  for(let i=0;i<3;i++){
    await page.evaluate(()=>{
      const skeletons=new Set()
      window.yingzhaoQA.state.scene.getObjectByName('yingzhao_root').traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton)})
      const textures=[...skeletons].map(s=>s.boneTexture).filter(Boolean)
      window.yingzhaoQA.oldSkeletons={skeletons:[...skeletons],textures,disposed:0}
      for(const texture of textures)texture.addEventListener('dispose',()=>window.yingzhaoQA.oldSkeletons.disposed++)
    })
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready boyi')})
    await page.evaluate(()=>window.yingzhaoQA.useApp.getState().select('boyi'));await ready
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready yingzhao')})
    await page.evaluate(()=>window.yingzhaoQA.useApp.getState().select('yingzhao'));await ready
    const current=await snapshot(true)
    for(const k of ['invalid','nodes','meshes','outlines','bones','wings','wingBones','heads','tails','horns','legs'])assert.equal(current[k],baseline[k],`remount ${k}`)
    report.remounts.push(current)
    const cleanup=await page.evaluate(()=>{
      const old=window.yingzhaoQA.oldSkeletons
      return {textures:old.textures.length,disposed:old.disposed,live:old.skeletons.filter(s=>s.boneTexture).length}
    })
    assert(cleanup.textures>0&&cleanup.textures===cleanup.disposed&&cleanup.live===0,'Old clone skeleton textures released')
    report.skeletonCleanup.push(cleanup)
  }
  await page.evaluate(()=>window.yingzhaoQA.useApp.getState().setAction('special'));await page.waitForTimeout(1400)
  for(const [name,x,y,z]of [['front',0,1.2,4],['back',0,1.2,-4],['left',-4,1.2,0],['right',4,1.2,0],['dorsal',1.3,3.8,-1.3]]){
    await page.evaluate(({x,y,z})=>{
      const {state}=window.yingzhaoQA;const root=state.scene.getObjectByName('yingzhao_root')
      const target=root.position.clone().add({x:0,y:.56,z:0});const offset=root.position.clone().set(x,y,z).applyQuaternion(root.quaternion)
      state.controls.enableDamping=false;state.camera.filmOffset=0;state.camera.updateProjectionMatrix()
      state.controls.target.copy(target);state.camera.position.copy(target).add(offset);state.controls.update()
    },{x,y,z})
    await page.waitForTimeout(150);const path=join(output,`yingzhao-angle-${name}.png`);await page.screenshot({path});report.angles.push(path)
  }
  await page.evaluate(()=>window.yingzhaoQA.useApp.getState().setAction('special'))
  await page.waitForFunction(()=>window.yingzhaoQA.useApp.getState().action==='idle',null,{timeout:20000})
  report.specialReturn=await page.evaluate(()=>window.yingzhaoQA.useApp.getState().action)
  assert.equal(report.specialReturn,'idle')
  await page.locator('.story-btn').click();await page.waitForTimeout(1800)
  report.audio=await page.evaluate(async()=>{const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'));const el=audio.narrationEl;audio.yingzhaoCall(0);return {src:el?.src,duration:el?.duration,currentTime:el?.currentTime,error:el?.error,context:audio.context?.state}})
  assert(report.audio.src.endsWith('/audio/narration/yingzhao.mp3')&&report.audio.currentTime>0&&report.audio.duration>45)
  assert.equal(report.audio.error,null);await page.waitForTimeout(900)
  await page.locator('.story-btn').click()
  report.narrationStopped=await page.evaluate(async()=>{
    const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'))
    return !audio.narrationEl&&!window.yingzhaoQA.useApp.getState().narrating
  })
  assert(report.narrationStopped,'Actual card button releases narration')
  report.sfx=await page.evaluate(async()=>{
    const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'))
    const analyser=audio.context.createAnalyser();analyser.fftSize=2048;audio.sfx.connect(analyser)
    const samples=new Float32Array(analyser.fftSize);let peakRMS=0
    audio.yingzhaoCall(0)
    for(let i=0;i<24;i++){
      await new Promise(resolve=>setTimeout(resolve,30));analyser.getFloatTimeDomainData(samples)
      peakRMS=Math.max(peakRMS,Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length))
    }
    audio.sfx.disconnect(analyser);analyser.disconnect()
    return {peakRMS,context:audio.context.state}
  })
  assert(report.sfx.peakRMS>.0001,'Audible Yingzhao call on actual SFX bus')
  assert.equal(errors.length,0,errors.join('\n'))
  console.log(JSON.stringify({baseline,worldContact:{...report.worldContact,plants:report.worldContact.plants.map(p=>({foot:p.foot,samples:p.samples,maxDrift:p.maxDrift}))},remounts:report.remounts.length,audio:report.audio,errors},null,2))
} finally {await writeFile(join(output,'browser-qa.json'),JSON.stringify(report,null,2));await browser.close()}
