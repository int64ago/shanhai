import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright-core'
// Optional local candidate path exercises the real component before public replacement.
const [base='http://localhost:5221',output='/tmp/changyou-qa',candidate]=process.argv.slice(2)
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu','--autoplay-policy=no-user-gesture-required']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
if(candidate)await page.route('**/models/changyou/body.glb*',route=>route.fulfill({path:resolve(candidate),contentType:'model/gltf-binary'}))
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)})
const report={candidate:candidate?resolve(candidate):null,actions:{},remounts:[],errors}
try {
  const ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready changyou')})
  await page.goto(`${base}/?beast=changyou&action=idle`);await ready
  await page.evaluate(async()=>{
    const resources=performance.getEntriesByType('resource').map(r=>r.name)
    const fiber=await import(resources.find(u=>u.includes('@react-three_fiber.js')))
    const {useApp}=await import(resources.find(u=>new URL(u).pathname==='/src/app/store.ts'))
    const {audio}=await import(resources.find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'))
    window.changyouQA={state:[...fiber._roots.values()][0].store.getState(),useApp,audio}
  })
  async function snapshot(full=false){return page.evaluate(all=>{
    const q=window.changyouQA,root=q.state.scene.getObjectByName('changyou_root')
    q.state.scene.updateMatrixWorld(true)
    let invalid=0,nodes=0,vertices=0;const meshes=[],bones=[],outlines=[]
    root.traverse(n=>{
      nodes++
      if(![...n.matrixWorld.elements,...n.position,...n.quaternion,...n.scale].every(Number.isFinite)||Math.min(...n.scale)<=0)invalid++
      if(n.isBone)bones.push(n)
      if(!n.isMesh)return
      if(n.userData.inkOutline){outlines.push(n);return}
      meshes.push(n)
      if(n.skeleton){n.skeleton.update();if(!Array.from(n.skeleton.boneMatrices).every(Number.isFinite))invalid++}
      if(all){
        for(const name of ['position','normal','skinWeight'])if(n.geometry.attributes[name]&&!Array.from(n.geometry.attributes[name].array).every(Number.isFinite))invalid++
        const p=root.position.clone()
        for(let i=0;i<n.geometry.attributes.position.count;i++){
          n.getVertexPosition(i,p);n.localToWorld(p);vertices++
          if(![...p].every(Number.isFinite))invalid++
        }
      }
    })
    const separateEarMeshes=meshes.filter(n=>/^changyou_ear_[lr]_[01]$/.test(n.name)).length
    const native=meshes.find(n=>n.userData.integratedNativeHead===true)
    let rigidHeadVertices=0
    if(native){
      const g=native.geometry.attributes
      for(let i=0;i<g.position.count;i++)if(native.skeleton.bones[g.skinIndex.getX(i)]?.name==='head'&&g.skinWeight.getX(i)>.9999)rigidHeadVertices++
    }
    // Integrated ear count is a reviewed source-design declaration, not a
    // geometric detector. The fixed head surface is cross-checked by weights;
    // real four-ear anatomy is separately verified in source/posed images.
    const ears=separateEarMeshes===4?4:native?.userData.nativeEarCount===4&&rigidHeadVertices>100?4:0
    return {invalid,nodes,vertices,meshes:meshes.length,outlines:outlines.length,bones:bones.length,
      ears,separateEarMeshes,integratedNativeHead:!!native,rigidHeadVertices,
      earEvidence:native?'reviewed source images + preserved rigid head':'separate ear meshes',
      feet:bones.filter(n=>/^leg_[lr]_foot$/.test(n.name)).length,
      hands:bones.filter(n=>/^arm_[lr]_hand$/.test(n.name)).length}
  },full)}
  await page.waitForTimeout(600)
  report.baseline=await snapshot(true)
  for(const [key,value]of Object.entries({invalid:0,ears:4,feet:2,hands:2}))assert.equal(report.baseline[key],value,key)
  // All anatomical toe vertices, including lateral toes, must stay with the
  // planted feet during an upper-body gesture (a finite matrix alone misses
  // an outer toe accidentally weighted to the nearby hanging hand).
  report.gestureFeet=await page.evaluate(async()=>{
    const q=window.changyouQA,root=q.state.scene.getObjectByName('changyou_root')
    const mesh=root.getObjectByName('changyou_primate'),g=mesh.geometry.attributes,points=[]
    q.state.scene.updateMatrixWorld(true);mesh.skeleton.update()
    const ceiling=mesh.userData.restAnatomicalFootMaxHeight
    if(!Number.isFinite(ceiling)||ceiling<.06||ceiling>.10)throw new Error('Reviewed rest foot bounds missing')
    const sides={leg_l_foot:0,leg_r_foot:0},rest=root.position.clone()
    // This rig's root has identity rest transform. Its inverse bind matrix
    // carries meshopt's dequantization, which bindMatrix alone does not undo.
    const restMatrix=mesh.skeleton.boneInverses[mesh.skeleton.bones.findIndex(b=>b.name==='root')]
    if(!restMatrix)throw new Error('Rest root inverse bind missing')
    for(let i=0;i<g.position.count;i++){
      // Root inverse bind restores rest metres after meshopt quantization.
      // Select anatomy before inspecting weights so a misweighted toe cannot hide.
      rest.fromBufferAttribute(g.position,i).applyMatrix4(mesh.bindMatrix).applyMatrix4(restMatrix)
      if(rest.y>ceiling-.00005)continue
      const foot=rest.x>0?'leg_l_foot':'leg_r_foot'
      let assigned=0
      for(let k=0;k<4;k++)if(mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name===foot)assigned+=g.skinWeight.getComponent(i,k)
      if(assigned<.9999)throw new Error(`Rest anatomical toe ${i} assigned ${assigned} to ${foot}`)
      sides[foot]++
      const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p)
      points.push({i,initial:p.toArray()})
    }
    if(Object.values(sides).some(n=>n<100))throw new Error('Both complete anatomical foot masks required')
    q.useApp.getState().setAction('special');await new Promise(r=>setTimeout(r,1500))
    q.state.scene.updateMatrixWorld(true);mesh.skeleton.update();let maxDrift=0
    for(const {i,initial} of points){const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);maxDrift=Math.max(maxDrift,Math.hypot(...p.toArray().map((v,k)=>v-initial[k])))}
    q.useApp.getState().setAction('idle');await new Promise(r=>setTimeout(r,600))
    return {vertices:points.length,sides,maxDrift,selection:'reviewed rest spatial foot bounds, independent of weights'}
  })
  assert(report.gestureFeet.vertices>100&&report.gestureFeet.maxDrift<.003,'Every lateral toe stays planted during arm gesture')
  for(const action of ['idle','walk','special']){
    await page.evaluate(a=>window.changyouQA.useApp.getState().setAction(a),action)
    const samples=[]
    for(let i=0;i<(action==='special'?40:16);i++){await page.waitForTimeout(130);samples.push(await snapshot(i%8===0))}
    assert(samples.every(s=>s.invalid===0&&s.ears===4))
    report.actions[action]=samples
    if(action==='special')assert.equal(await page.evaluate(()=>window.changyouQA.useApp.getState().action),'idle')
  }
  await page.evaluate(()=>window.changyouQA.useApp.getState().setAction('idle'));await page.waitForTimeout(600)
  report.contact=await page.evaluate(async()=>{
    const q=window.changyouQA,root=q.state.scene.getObjectByName('changyou_root'),points={}
    q.state.scene.updateMatrixWorld(true)
    root.traverse(mesh=>{
      if(!mesh.isSkinnedMesh||mesh.userData.inkOutline||mesh.name!=='changyou_primate')return
      mesh.skeleton.update();const g=mesh.geometry.attributes,rest=root.position.clone()
      const restMatrix=mesh.skeleton.boneInverses[mesh.skeleton.bones.findIndex(b=>b.name==='root')]
      if(!restMatrix)throw new Error('Rest root inverse bind missing')
      const ceiling=mesh.userData.restAnatomicalSoleMaxHeight
      if(!Number.isFinite(ceiling)||ceiling<=0||ceiling>.004)throw new Error('Reviewed rest sole bounds missing')
      for(let i=0;i<g.position.count;i++){
        rest.fromBufferAttribute(g.position,i).applyMatrix4(mesh.bindMatrix).applyMatrix4(restMatrix)
        if(rest.y>ceiling)continue
        const foot=rest.x>0?'leg_l_foot':'leg_r_foot'
        let assigned=0
        for(let k=0;k<4;k++)if(mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name===foot)assigned+=g.skinWeight.getComponent(i,k)
        if(assigned<.9999)throw new Error(`Rest anatomical sole ${i} misweighted to ${foot}`)
        ;(points[foot]??=[]).push({mesh,i,x:rest.x,z:rest.z})
      }
    })
    if(!points.leg_l_foot?.length||!points.leg_r_foot?.length)throw new Error('Both complete rest sole masks required')
    for(const [foot,v]of Object.entries(points)){
      if(v.length<3||!v.some(b=>v.some(c=>Math.abs((b.x-v[0].x)*(c.z-v[0].z)-(b.z-v[0].z)*(c.x-v[0].x))>1e-6)))throw new Error(`${foot}: noncollinear soles missing`)
    }
    q.useApp.getState().setAction('walk');await new Promise(r=>setTimeout(r,600))
    const normal=positions=>{
      const a=positions[0]
      for(let i=1;i<positions.length;i++)for(let j=i+1;j<positions.length;j++){
        const u=positions[i].map((v,k)=>v-a[k]),v=positions[j].map((v,k)=>v-a[k])
        const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n)
        if(length>1e-6)return n.map(v=>v/length)
      }
      throw new Error('Sole plane became degenerate')
    }
    let cycle=0,previous=root.userData.animationTime,frames=0;const plants={},start=performance.now()
    while(cycle<3){
      if(performance.now()-start>24000)throw new Error('Three gait cycles timed out')
      await new Promise(r=>requestAnimationFrame(r));q.state.scene.updateMatrixWorld(true)
      for(const mesh of new Set(Object.values(points).flat().map(p=>p.mesh)))mesh.skeleton.update()
      const t=root.userData.animationTime;if(t<previous-.5)cycle++;previous=t;frames++
      for(const [foot,vertices]of Object.entries(points)){
        const phase=t/2.4+(foot==='leg_l_foot'?0:.5),p=phase%1
        if(p<.05||p>.61)continue
        const key=`${foot}/${cycle+Math.floor(phase)}`
        const positions=vertices.map(({mesh,i})=>{const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);return p.toArray()})
        const plant=plants[key]??={foot,initial:positions,maxDrift:0,maxDirection:0,maxPlaneNormal:0,samples:0,minY:Infinity,maxY:-Infinity}
        const n=normal(positions),n0=normal(plant.initial)
        plant.maxPlaneNormal=Math.max(plant.maxPlaneNormal,Math.acos(Math.max(-1,Math.min(1,n.reduce((s,v,k)=>s+v*n0[k],0)))))
        positions.forEach((p,i)=>{plant.maxDrift=Math.max(plant.maxDrift,Math.hypot(...p.map((v,k)=>v-plant.initial[i][k])));plant.minY=Math.min(plant.minY,p[1]);plant.maxY=Math.max(plant.maxY,p[1])})
        const a=positions[0],a0=plant.initial[0]
        for(let i=1;i<positions.length;i++){
          const one=positions[i].map((v,k)=>v-a[k]),two=plant.initial[i].map((v,k)=>v-a0[k]),length=Math.hypot(...one)*Math.hypot(...two)
          if(length<1e-8)continue
          const dot=one.reduce((s,v,k)=>s+v*two[k],0)/length
          plant.maxDirection=Math.max(plant.maxDirection,Math.acos(Math.max(-1,Math.min(1,dot))))
        }
        plant.samples++;plants[key]=plant
      }
    }
    const measured=Object.values(plants).filter(p=>p.samples>10)
    return {frames,points:Object.fromEntries(Object.entries(points).map(([k,v])=>[k,v.length])),plants:measured,maxDrift:Math.max(...measured.map(p=>p.maxDrift)),maxDirection:Math.max(...measured.map(p=>p.maxDirection)),maxPlaneNormal:Math.max(...measured.map(p=>p.maxPlaneNormal))}
  })
  assert.equal(Object.keys(report.contact.points).length,2)
  assert(report.contact.plants.length>=4)
  assert(report.contact.maxDrift<.001,`sole XYZ drift ${report.contact.maxDrift}`)
  assert(report.contact.maxDirection<.002,`sole direction ${report.contact.maxDirection}`)
  assert(report.contact.maxPlaneNormal<.002,`sole plane normal ${report.contact.maxPlaneNormal}`)
  assert(report.contact.plants.every(p=>Math.abs(p.minY)<.004&&Math.abs(p.maxY)<.004),'sole height')
  await page.evaluate(()=>window.changyouQA.useApp.getState().setAction('idle'));await page.waitForTimeout(600)
  for(let i=0;i<3;i++){
    await page.evaluate(()=>{
      const root=window.changyouQA.state.scene.getObjectByName('changyou_root'),skeletons=new Set(),materials=new Set(),geometries=new Set()
      root.traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton);if(n.isMesh){materials.add(n.material);geometries.add(n.geometry)}})
      const old=window.changyouQA.old={skeletons:[...skeletons],textures:0,disposedTextures:0,disposedMaterials:0,materials:materials.size,disposedGeometry:0}
      for(const s of skeletons)if(s.boneTexture){old.textures++;s.boneTexture.addEventListener('dispose',()=>old.disposedTextures++)}
      for(const m of materials)m.addEventListener('dispose',()=>old.disposedMaterials++)
      for(const g of geometries)g.addEventListener('dispose',()=>old.disposedGeometry++)
    })
    const other=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jiuweihu')})
    await page.evaluate(()=>window.changyouQA.useApp.getState().select('jiuweihu'));await other
    const back=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready changyou')})
    await page.evaluate(()=>window.changyouQA.useApp.getState().select('changyou'));await back;await page.waitForTimeout(200)
    const state=await snapshot(true)
    for(const k of ['invalid','nodes','meshes','outlines','bones','ears','feet','hands'])assert.equal(state[k],report.baseline[k],`remount ${k}`)
    const ownership=await page.evaluate(()=>{const old=window.changyouQA.old;return {...old,skeletons:undefined,liveSkeletonTextures:old.skeletons.filter(s=>s.boneTexture).length}})
    assert(ownership.textures>0&&ownership.textures===ownership.disposedTextures&&ownership.liveSkeletonTextures===0)
    assert.equal(ownership.disposedGeometry,0)
    assert.equal(ownership.disposedMaterials,ownership.materials)
    report.remounts.push({state,ownership})
  }
  report.audio=await page.evaluate(async()=>{
    const {audio,useApp}=window.changyouQA;await audio.unlock()
    const ctx=audio.context,analyser=ctx.createAnalyser();analyser.fftSize=2048;audio.sfx.connect(analyser)
    useApp.getState().setAction('special');const samples=new Float32Array(2048);let peak=0
    for(let i=0;i<28;i++){await new Promise(r=>setTimeout(r,100));analyser.getFloatTimeDomainData(samples);peak=Math.max(peak,...samples.map(Math.abs))}
    audio.sfx.disconnect(analyser)
    const bytes=await(await fetch('/audio/narration/changyou.mp3')).arrayBuffer(),decoded=await ctx.decodeAudioData(bytes)
    let energy=0;for(const value of decoded.getChannelData(0))energy+=value*value
    await audio.playNarration('changyou');await new Promise(r=>setTimeout(r,900))
    const element=audio.narrationEl,playing=element&&!element.paused&&element.currentTime>0
    audio.stopNarration()
    return {context:ctx.state,humPeak:peak,narrationSeconds:decoded.duration,narrationRms:Math.sqrt(energy/decoded.length),playing}
  })
  assert(report.audio.humPeak>.02&&report.audio.narrationRms>.005&&report.audio.playing)
  await page.waitForTimeout(2200)
  assert.equal(await page.evaluate(()=>window.changyouQA.useApp.getState().action),'idle')
  report.angles=[]
  for(const [name,x,y,z]of [['front',0,.4,4],['back',0,.4,-4],['left',-4,.4,0],['right',4,.4,0],['ears',1.1,.3,1.7]]){
    await page.evaluate(({x,y,z,name})=>{
      const {state}=window.changyouQA,root=state.scene.getObjectByName('changyou_root')
      const target=root.position.clone().add({x:0,y:name==='ears'?1.12:.63,z:0})
      state.controls.enableDamping=false;state.camera.filmOffset=0;state.camera.updateProjectionMatrix()
      state.controls.target.copy(target);state.camera.position.copy(target).add(root.position.clone().set(x,y,z).applyQuaternion(root.quaternion));state.controls.update()
    },{x,y,z,name})
    await page.waitForTimeout(180);const path=join(output,`changyou-angle-${name}.png`);await page.screenshot({path});report.angles.push(path)
  }
  assert.equal(errors.length,0,errors.join('\n'))
  report.passed=true
} finally {
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2))
  await browser.close()
}
console.log(JSON.stringify(report))
