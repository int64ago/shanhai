// Boyi browser QA: source anatomy, live skinning, contact, remounts, audio.
// node scripts/qa-boyi.mjs [http://localhost:5226] [/tmp/boyi-quality-qa]
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const [base='http://localhost:5226', output='/tmp/boyi-quality-qa']=process.argv.slice(2)
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error') errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400) errors.push(`${r.status()} ${r.url()}`)})
const report={actions:{},remounts:[],angles:[],errors}
try {
  const initialReady=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei')})
  await page.goto(`${base}/?beast=jingwei&action=idle`)
  await initialReady
  // Observe the cached source before the first Boyi StrictMode mount.
  await page.evaluate(async()=>{
    const moduleUrl=path=>performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname===path)?.name
    const {useGLTF}=await import(moduleUrl('/node_modules/.vite/deps/@react-three_drei.js'))
    useGLTF.preload('/models/boyi/body.glb')
    for(;;){try{window.boyiSource=useGLTF('/models/boyi/body.glb').scene;break}catch(pending){if(!pending?.then)throw pending;await pending}}
    window.boyiSourceSnapshot=()=>{
      const rows=[]
      window.boyiSource.traverse(n=>rows.push({uuid:n.uuid,name:n.name,children:n.children.map(c=>c.uuid),position:n.position.toArray(),quaternion:n.quaternion.toArray(),scale:n.scale.toArray(),geometry:n.geometry?.uuid,skeleton:n.skeleton?.uuid,outline:!!n.userData.inkOutline,materials:(Array.isArray(n.material)?n.material:n.material?[n.material]:[]).map(m=>({uuid:m.uuid,type:m.type,color:m.color?.getHexString(),map:m.map?.uuid,normalMap:m.normalMap?.uuid,roughness:m.roughness,metalness:m.metalness,side:m.side,transparent:m.transparent,opacity:m.opacity,userData:JSON.stringify(m.userData)}))}))
      return JSON.stringify(rows)
    }
    window.boyiSourceBefore=window.boyiSourceSnapshot()
    window.boyiShared=new Set();window.boyiSharedDisposals=0
    window.boyiSource.traverse(n=>{if(n.geometry)window.boyiShared.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){window.boyiShared.add(m);for(const v of Object.values(m))if(v?.isTexture)window.boyiShared.add(v)}})
    for(const r of window.boyiShared)r.addEventListener('dispose',()=>window.boyiSharedDisposals++)
  })
  const ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready boyi')})
  await page.evaluate(async()=>{const url=performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname==='/src/app/store.ts').name;const {useApp}=await import(url);useApp.getState().select('boyi')})
  await ready
  await page.evaluate(async()=>{
    const url=performance.getEntriesByType('resource').map(r=>r.name).find(u=>u.includes('@react-three_fiber.js'))
    const fiber=await import(url)
    const storeUrl=performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts')
    if(!storeUrl) throw new Error('Loaded application store not found')
    const {useApp}=await import(storeUrl)
    const audioUrl=performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')
    const {audio}=await import(audioUrl)
    const calls={boyi:0,footsteps:0}
    const call=audio.boyiCall.bind(audio),step=audio.footstep.bind(audio)
    audio.boyiCall=(...args)=>{calls.boyi++;return call(...args)}
    audio.footstep=(...args)=>{calls.footsteps++;return step(...args)}
    window.boyiQA={state:[...fiber._roots.values()][0].store.getState(),useApp,audio,calls}
  })
  async function snapshot(full=false) {
    return page.evaluate(all=>{
      const {state}=window.boyiQA
      const root=state.scene.getObjectByName('boyi_root')
      if(!root) throw new Error('Missing Boyi root')
      state.scene.updateMatrixWorld(true)
      const meshes=[],bones=[],outlines=[]
      let invalid=0,nodes=0
      root.traverse(node=>{
        nodes++
        if(![...node.matrixWorld.elements,...node.position,...node.quaternion,...node.scale].every(Number.isFinite)) invalid++
        if(node.scale.x<=0||node.scale.y<=0||node.scale.z<=0) invalid++
        if(node.isBone) bones.push(node)
        if(!node.isMesh) return
        if(node.userData.inkOutline) {outlines.push(node);return}
        meshes.push(node)
        if(all) for(const key of ['position','normal','skinWeight']) {
          const attr=node.geometry.attributes[key]
          if(attr&&!Array.from(attr.array).every(Number.isFinite)) invalid++
        }
        if(node.skeleton) {
          node.skeleton.update()
          if(!Array.from(node.skeleton.boneMatrices).every(Number.isFinite)) invalid++
        }
      })
      const feet={}
      const p=root.position.clone()
      for(const mesh of meshes) {
        const hoof=mesh.name.startsWith('boyi_hoof_')
        if(!hoof&&!all) continue
        const position=mesh.geometry.attributes.position
        let min=Infinity
        for(let i=0;i<position.count;i++) {
          mesh.getVertexPosition(i,p)
          if(![...p].every(Number.isFinite)) invalid++
          if(hoof) min=Math.min(min,mesh.localToWorld(p).y)
        }
        if(hoof) feet[mesh.name]=min
      }
      return {invalid,nodes,meshes:meshes.length,outlines:outlines.length,bones:bones.length,
        tails:meshes.filter(n=>/^boyi_tail_\d\d$/.test(n.name)).length,
        tailBones:bones.filter(n=>n.name.startsWith('boyi_tail_')).length,
        ears:meshes.filter(n=>n.name.startsWith('boyi_ear_')&&n.name.endsWith('_outer')).length,
        eyes:meshes.filter(n=>n.name.startsWith('boyi_dorsal_')&&n.name.endsWith('_sclera')).length,
        facialEyes:meshes.filter(n=>n.name.includes('face_eye')).length,
        horns:meshes.filter(n=>n.name.includes('horn')).length,
        legs:bones.filter(n=>/^(front|back)_[lr]_foot$/.test(n.name)).length,
        feet}
    },full)
  }
  const baseline=await snapshot(true)
  report.baseline=baseline
  for(const [key,value] of Object.entries({invalid:0,tails:9,tailBones:72,ears:4,eyes:2,facialEyes:0,horns:0,legs:4})) assert.equal(baseline[key],value,key)
  assert.equal(Object.keys(baseline.feet).length,4)
  for(const action of ['idle','walk','special']) {
    await page.evaluate(a=>window.boyiQA.useApp.getState().setAction(a),action)
    const samples=[]
    for(let i=0;i<(action==='special'?43:24);i++) {
      await page.waitForTimeout(120)
      samples.push(await snapshot(i%12===0))
    }
    assert(samples.every(s=>s.invalid===0&&s.tails===9&&s.ears===4&&s.eyes===2))
    // A lifted walk hoof unfolds during the 0.32 s crossfade into a display.
    if(action!=='walk') assert(samples.slice(4).every(s=>Object.values(s.feet).every(y=>Math.abs(y)<.008)),`${action}: hoof contact`)
    if(action==='walk') assert(samples.every(s=>Math.min(...Object.values(s.feet))>-.008&&Math.min(...Object.values(s.feet))<.012),'walk: support contact')
    report.actions[action]=samples
    if(action==='special') assert.equal(await page.evaluate(()=>window.boyiQA.useApp.getState().action),'idle','display automatically returns to idle')
  }
  // CPU-skin every actual sole vertex during the real running circular gait.
  // Three noncollinear sole points give the plane normal and its direction;
  // sampling a bone origin alone would miss a rotating or deforming hoof.
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('walk'))
  await page.waitForTimeout(1200)
  report.stance=await page.evaluate(async()=>{
    const {state}=window.boyiQA
    const root=state.scene.getObjectByName('boyi_root')
    const feet=[]
    const phases={back_l:0,front_l:.25,back_r:.5,front_r:.75}
    root.traverse(mesh=>{
      if(!mesh.isMesh||mesh.userData.inkOutline||!mesh.name.startsWith('boyi_hoof_')) return
      const attr=mesh.geometry.attributes.position
      let low=Infinity
      for(let i=0;i<attr.count;i++) low=Math.min(low,attr.getY(i))
      const vertices=[]
      for(let i=0;i<attr.count;i++) if(attr.getY(i)<low+.001) vertices.push(i)
      if(vertices.length<3) throw new Error(`Too few real sole vertices: ${mesh.name}`)
      const points=vertices.map(()=>root.position.clone())
      feet.push({mesh,vertices,points,phase:phases[mesh.name.slice(10)],anchor:null,previousPhase:1,
        drift:0,vertical:0,direction:0,tilt:0,samples:0,stanceCount:0,range:[Infinity,-Infinity],examples:[]})
    })
    const normal=root.position.clone(),tangent=normal.clone(),other=normal.clone()
    const angle=(a,b)=>Math.acos(Math.max(-1,Math.min(1,a.dot(b))))
    for(let frame=0;frame<360;frame++){
      await new Promise(requestAnimationFrame)
      state.scene.updateMatrixWorld(true)
      for(const foot of feet){
        foot.mesh.skeleton.update()
        foot.points.forEach((p,i)=>{foot.mesh.getVertexPosition(foot.vertices[i],p);foot.mesh.localToWorld(p)})
        if(!foot.points.every(p=>p.toArray().every(Number.isFinite))) throw new Error('Nonfinite sole skin')
        const phase=(root.userData.walkPhase+foot.phase)%1
        const planted=phase>.06&&phase<.62
        const a=foot.points[0]
        let b=foot.points[1],distance=0
        for(const p of foot.points) if(p.distanceToSquared(a)>distance){b=p;distance=p.distanceToSquared(a)}
        tangent.subVectors(b,a).normalize()
        let area=0,c=foot.points[2]
        for(const p of foot.points){other.subVectors(p,a).cross(tangent);if(other.lengthSq()>area){area=other.lengthSq();c=p}}
        normal.subVectors(c,a).cross(tangent).normalize()
        if(normal.y<0) normal.negate()
        foot.range[0]=Math.min(foot.range[0],...foot.points.map(p=>p.y))
        foot.range[1]=Math.max(foot.range[1],...foot.points.map(p=>p.y))
        if(planted){
          if(!foot.anchor||phase<foot.previousPhase){
            foot.anchor={points:foot.points.map(p=>p.clone()),normal:normal.clone(),tangent:tangent.clone()}
            foot.stanceCount++
            if(foot.examples.length<3) foot.examples.push(foot.points.map(p=>p.toArray()))
          }
          foot.points.forEach((p,i)=>{foot.drift=Math.max(foot.drift,p.distanceTo(foot.anchor.points[i]));foot.vertical=Math.max(foot.vertical,Math.abs(p.y))})
          foot.direction=Math.max(foot.direction,angle(tangent,foot.anchor.tangent),angle(normal,foot.anchor.normal))
          foot.tilt=Math.max(foot.tilt,Math.acos(Math.max(-1,Math.min(1,normal.y))))
          foot.samples++
        }else foot.anchor=null
        foot.previousPhase=phase
      }
    }
    return feet.map(f=>({name:f.mesh.name,soleVertices:f.vertices.length,maxStanceDrift:f.drift,maxStanceHeight:f.vertical,
      maxDirectionRadians:f.direction,maxPlaneTiltRadians:f.tilt,samples:f.samples,stances:f.stanceCount,heightRange:f.range,actualWorldSoleXYZ:f.examples}))
  })
  assert.equal(report.stance.length,4)
  assert(report.stance.every(f=>f.samples>25&&f.stances>=2&&f.maxStanceDrift<.001&&f.maxStanceHeight<.008&&f.maxDirectionRadians<.005&&f.maxPlaneTiltRadians<.02),JSON.stringify(report.stance.map(({actualWorldSoleXYZ,...metrics})=>metrics)))
  // Interrupt a full display, then finish a walk-to-idle transition.
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('special'))
  await page.waitForTimeout(1400)
  const before=await snapshot()
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('walk'))
  await page.waitForTimeout(80)
  const after=await snapshot()
  assert.equal(after.invalid,0)
  await page.waitForTimeout(500)
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(500)
  report.interruption={before,after,settled:await snapshot(true)}
  assert(Object.values(report.interruption.settled.feet).every(y=>Math.abs(y)<.008),'interruption settles all real hooves')
  const callsBefore=await page.evaluate(()=>window.boyiQA.calls.boyi)
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('special'))
  await page.waitForTimeout(60)
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(300)
  report.cancelledCall={before:callsBefore,after:await page.evaluate(()=>window.boyiQA.calls.boyi)}
  assert.equal(report.cancelledCall.after,callsBefore,'cancel pending sheep call on interruption')
  for(let i=0;i<3;i++) {
    // Wait for actual rendering to allocate all bone textures before observing
    // cleanup. Counting materials alone would miss the cloned skeletons' GPU data.
    await page.waitForFunction(()=>{
      const root=window.boyiQA.state.scene.getObjectByName('boyi_root')
      const skeletons=new Set()
      root?.traverse(n=>{if(n.isSkinnedMesh) skeletons.add(n.skeleton)})
      return skeletons.size>0&&[...skeletons].every(s=>s.boneTexture!==null)
    })
    await page.evaluate(()=>{
      const root=window.boyiQA.state.scene.getObjectByName('boyi_root')
      const materials=new Set(),skeletons=new Set(),geometries=new Set(),textures=new Set()
      root.traverse(n=>{
        if(n.isSkinnedMesh) skeletons.add(n.skeleton)
        if(!n.isMesh) return
        geometries.add(n.geometry)
        for(const mat of Array.isArray(n.material)?n.material:[n.material]) {
          materials.add(mat)
          if(mat.uniforms) for(const uniform of Object.values(mat.uniforms)) if(uniform.value?.isTexture) textures.add(uniform.value)
          for(const value of Object.values(mat)) if(value?.isTexture) textures.add(value)
        }
      })
      const boneTextures=new Map([...skeletons].map(s=>[s.boneTexture,0]))
      const disposal={expected:materials.size,disposed:0,sharedGeometriesDisposed:0,sharedTexturesDisposed:0}
      for(const mat of materials) mat.addEventListener('dispose',()=>disposal.disposed++)
      for(const texture of boneTextures.keys()) texture.addEventListener('dispose',()=>boneTextures.set(texture,boneTextures.get(texture)+1))
      for(const geometry of geometries) geometry.addEventListener('dispose',()=>disposal.sharedGeometriesDisposed++)
      for(const texture of textures) texture.addEventListener('dispose',()=>disposal.sharedTexturesDisposed++)
      window.boyiQA.disposal={disposal,skeletons,boneTextures}
    })
    let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready ershu')})
    await page.evaluate(()=>window.boyiQA.useApp.getState().select('ershu'))
    await ready
    const disposal=await page.evaluate(()=>{
      const {disposal,skeletons,boneTextures}=window.boyiQA.disposal
      return {...disposal,skeletons:skeletons.size,boneTextures:boneTextures.size,
        boneTextureDisposals:[...boneTextures.values()],
        clearedSkeletons:[...skeletons].filter(s=>s.boneTexture===null).length}
    })
    assert.equal(disposal.disposed,disposal.expected,'owned ink/outline materials released')
    assert(disposal.boneTextures>0&&disposal.skeletons>0,'observe allocated GPU bone textures')
    assert(disposal.boneTextureDisposals.every(count=>count===1),'every old bone texture disposed exactly once')
    assert.equal(disposal.clearedSkeletons,disposal.skeletons,'all old skeleton.boneTexture references cleared')
    assert.equal(disposal.sharedGeometriesDisposed,0,'cached geometry stays shared')
    assert.equal(disposal.sharedTexturesDisposed,0,'cached material textures stay shared')
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready boyi')})
    await page.evaluate(()=>window.boyiQA.useApp.getState().select('boyi'))
    await ready
    const current=await snapshot(true)
    for(const key of ['invalid','nodes','meshes','outlines','bones','tails','tailBones','ears','eyes','facialEyes','horns','legs']) assert.equal(current[key],baseline[key],`remount ${key}`)
    const animations={}
    for(const action of ['idle','walk','special']) {
      await page.evaluate(a=>window.boyiQA.useApp.getState().setAction(a),action)
      await page.waitForTimeout(450)
      animations[action]=await page.evaluate(async()=>{
        const {state,disposal}=window.boyiQA
        const root=state.scene.getObjectByName('boyi_root')
        const tails=[],skeletons=new Set()
        root.traverse(n=>{
          if(n.isSkinnedMesh) skeletons.add(n.skeleton)
          if(n.isMesh&&!n.userData.inkOutline&&/^boyi_tail_\d\d$/.test(n.name)) {
            const count=n.geometry.attributes.position.count
            tails.push({mesh:n,vertices:[0,Math.floor(count/4),Math.floor(count/2),Math.floor(3*count/4),count-1],start:null,maxDisplacement:0})
          }
        })
        let invalid=0
        for(let frame=0;frame<24;frame++) {
          await new Promise(requestAnimationFrame)
          state.scene.updateMatrixWorld(true)
          for(const tail of tails) {
            tail.mesh.skeleton.update()
            const points=tail.vertices.map(index=>tail.mesh.getVertexPosition(index,root.position.clone()))
            if(!points.every(p=>p.toArray().every(Number.isFinite))) invalid++
            if(!tail.start) tail.start=points
            points.forEach((p,i)=>{tail.maxDisplacement=Math.max(tail.maxDisplacement,p.distanceTo(tail.start[i]))})
          }
        }
        return {invalid,tails:tails.map(t=>({name:t.mesh.name,maxDisplacement:t.maxDisplacement})),
          skeletons:skeletons.size,freshSkeletons:[...skeletons].every(s=>!disposal.skeletons.has(s)),
          freshBoneTextures:[...skeletons].every(s=>s.boneTexture!==null&&!disposal.boneTextures.has(s.boneTexture))}
      })
      const sample=animations[action]
      assert.equal(sample.invalid,0,`remount ${i} ${action}: finite tail skinning`)
      assert.equal(sample.tails.length,9,`remount ${i} ${action}: nine tails`)
      assert(sample.tails.every(t=>t.maxDisplacement>1e-6),`remount ${i} ${action}: every tail keeps deforming`)
      assert.equal(sample.skeletons,disposal.skeletons,'same number of owned skeletons after remount')
      assert(sample.freshSkeletons&&sample.freshBoneTextures,`remount ${i} ${action}: fresh skeletons and GPU bone textures`)
      const state=await snapshot(true)
      assert.equal(state.invalid,0,`remount ${i} ${action}: finite full scene`)
    }
    await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('idle'))
    await page.waitForTimeout(450)
    report.remounts.push({...current,disposal,animations})
  }
  for(const [name,x,y,z] of [['front',0,1,4.6],['back',0,1,-4.6],['left',-4.8,1,0],['right',4.8,1,0],['dorsal',1.8,4.3,-1.8]]) {
    await page.evaluate(({x,y,z})=>{
      const {state}=window.boyiQA
      const root=state.scene.getObjectByName('boyi_root')
      const target=root.position.clone().add({x:0,y:.49,z:0})
      const offset=root.position.clone().set(x,y,z).applyQuaternion(root.quaternion)
      state.controls.enableDamping=false
      state.camera.filmOffset=0
      state.camera.updateProjectionMatrix()
      state.controls.target.copy(target)
      state.camera.position.copy(target).add(offset)
      state.controls.update()
    },{x,y,z})
    await page.waitForTimeout(200)
    const path=join(output,`boyi-angle-${name}.png`)
    await page.screenshot({path})
    report.angles.push(path)
  }
  await page.locator('.story-btn').click()
  await page.waitForTimeout(1800)
  report.audio=await page.evaluate(async()=>{
    const audioUrl=performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')
    if(!audioUrl) throw new Error('Loaded audio engine not found')
    const {audio}=await import(audioUrl)
    const el=audio.narrationEl
    audio.boyiCall(0)
    const buffer=await audio.context.decodeAudioData(await (await fetch(el.src)).arrayBuffer())
    const channel=buffer.getChannelData(0)
    let energy=0
    for(const value of channel) energy+=value*value
    return {src:el?.src,duration:el?.duration,currentTime:el?.currentTime,error:el?.error,context:audio.context?.state,
      decodedRMS:Math.sqrt(energy/channel.length),decodedSeconds:buffer.duration,calls:window.boyiQA.calls}
  })
  assert(report.audio.src.endsWith('/audio/narration/boyi.mp3')&&report.audio.currentTime>0&&report.audio.duration>45)
  assert.equal(report.audio.error,null)
  assert.equal(report.audio.context,'running')
  assert(report.audio.decodedRMS>.01&&report.audio.calls.boyi>0&&report.audio.calls.footsteps>4,'audible narration and action audio')
  await page.waitForTimeout(1000)
  await page.evaluate(()=>window.boyiQA.useApp.getState().stopNarration())
  report.cache=await page.evaluate(()=>{
    let outlines=0,ownedSkeletons=true
    const sourceSkeletons=new Set()
    window.boyiSource.traverse(n=>{if(n.userData.inkOutline)outlines++;if(n.skeleton)sourceSkeletons.add(n.skeleton)})
    const root=window.boyiQA.state.scene.getObjectByName('boyi_root')
    root.traverse(n=>{if(n.skeleton&&sourceSkeletons.has(n.skeleton))ownedSkeletons=false})
    return {snapshottedBeforeFirstMount:true,unchanged:window.boyiSourceSnapshot()===window.boyiSourceBefore,sharedResources:window.boyiShared.size,sharedDisposals:window.boyiSharedDisposals,sourceOutlines:outlines,ownedSkeletons}
  })
  assert(report.cache.unchanged&&report.cache.ownedSkeletons&&report.cache.sharedDisposals===0&&report.cache.sourceOutlines===0,'immutable cached source and owned clone skeletons')
  assert.equal(errors.length,0,errors.join('\n'))
  console.log(JSON.stringify({baseline,remounts:report.remounts.length,finiteSamples:Object.values(report.actions).reduce((n,a)=>n+a.length,0),stance:report.stance.map(({actualWorldSoleXYZ,...metrics})=>metrics),audio:report.audio,errors},null,2))
} finally {
  await writeFile(join(output,'browser-qa.json'),JSON.stringify(report,null,2))
  await browser.close()
}
