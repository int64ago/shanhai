// Actual app lifecycle/appearance review; candidate routing changes only this browser.
// node scripts/qa-bashe-app.mjs [base] [candidate.glb|-] [NEW evidence directory]
// With a candidate, intercept Bashe and the preloaded Zhuyan v3 fixture. Without
// one, use public assets and existing Stage wiring exactly as the server serves them.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright-core'

const root=resolve(import.meta.dirname,'..')
const [base='http://localhost:5215',candidateArg='-',outArg]=process.argv.slice(2)
const candidate=candidateArg==='-'?null:resolve(candidateArg)
const out=outArg?resolve(outArg):join(root,`raw/_build/bashe-app-review-${Date.now()}`)
await mkdir(out,{recursive:false})
const bytes=candidate?await readFile(candidate):null
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[],report={candidate,candidateSha256:bytes?createHash('sha256').update(bytes).digest('hex'):null,candidateBytes:bytes?.length,temporaryBrowserOverrides:!!bytes,stagePreviewOverride:false,productionFilesChanged:false,errors,images:[],actions:{},remounts:[]}
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)})
try{
if(bytes){
  await page.route('**/models/bashe/body.glb',r=>r.fulfill({body:bytes,contentType:'model/gltf-binary'}))
  const zhuyan=join(root,'raw/_build/zhuyan-native-high-candidate-20261113-v3/body.glb')
  const zhuyanBytes=await readFile(zhuyan)
  await page.route('**/models/zhuyan/body.glb',r=>r.fulfill({body:zhuyanBytes,contentType:'model/gltf-binary'}))
  report.zhuyanPreloadOverride={path:zhuyan,sha256:createHash('sha256').update(zhuyanBytes).digest('hex')}
  await page.route('**/src/scene/Stage.tsx*',async route=>{
    const response=await route.fetch();let text=await response.text()
    if(!text.includes('/beasts/bashe/Bashe')){
      assert.equal(text.split('_jsxDEV(PlaceholderBeast,').length,2,'one temporary fallback hook')
      text='import { Bashe } from "/src/beasts/bashe/Bashe.tsx";\n'+text.replace('_jsxDEV(PlaceholderBeast,','_jsxDEV(selected === "bashe" ? Bashe : PlaceholderBeast,')
      report.stagePreviewOverride=true
    }
    await route.fulfill({response,body:text})
  })
}
  let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei'),timeout:60000})
  await page.goto(`${base}/?beast=jingwei&action=idle`);await ready
  await page.evaluate(async()=>{
    const url=path=>performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname===path).name
    const fiber=await import(url('/node_modules/.vite/deps/@react-three_fiber.js'))
    const {useGLTF}=await import(url('/node_modules/.vite/deps/@react-three_drei.js'))
    const {useApp}=await import(url('/src/app/store.ts'))
    let body
    for(;;){try{body=useGLTF('/models/bashe/body.glb');break}catch(pending){if(!pending?.then)throw pending;await pending}}
    const source=body.scene
    const snapshot=()=>{const rows=[];source.traverse(n=>rows.push({uuid:n.uuid,name:n.name,children:n.children.map(c=>c.uuid),position:n.position.toArray(),quaternion:n.quaternion.toArray(),scale:n.scale.toArray(),geometry:n.geometry?.uuid,skeleton:n.skeleton?.uuid,materials:(Array.isArray(n.material)?n.material:n.material?[n.material]:[]).map(m=>({uuid:m.uuid,type:m.type,map:m.map?.uuid,normalMap:m.normalMap?.uuid,color:m.color?.getHexString(),side:m.side}))}));return JSON.stringify(rows)}
    const shared=new Set();source.traverse(n=>{if(n.geometry)shared.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){shared.add(m);for(const value of Object.values(m))if(value?.isTexture)shared.add(value)}})
    const qa=window.basheApp={state:[...fiber._roots.values()][0].store.getState(),useApp,source,snapshot,before:snapshot(),sharedDisposals:0,clipDurations:body.animations.map(c=>({name:c.name,duration:c.duration}))}
    for(const resource of shared)resource.addEventListener('dispose',()=>qa.sharedDisposals++)
  })
  async function mount(){const ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready bashe'),timeout:30000});await page.evaluate(()=>window.basheApp.useApp.getState().select('bashe'));await ready;await page.waitForTimeout(650)}
  async function snapshot(full=false){return page.evaluate(full=>{
    const qa=window.basheApp,state=qa.state;state.scene.updateMatrixWorld(true)
    const roots=[];state.scene.traverse(n=>{if(n.name==='bashe_root')roots.push(n)})
    const root=roots[0],meshes=[],outlines=[],bones=[];let invalid=0
    root.traverse(n=>{if(![...n.matrixWorld.elements,...n.scale].every(Number.isFinite)||Math.min(...n.scale)<=0)invalid++;if(n.isBone)bones.push(n);if(n.isMesh){if(n.userData.inkOutline)outlines.push(n);else meshes.push(n)}})
    const floors=Array(24).fill(Infinity),q=root.position.clone();let minimum=Infinity,zmin=Infinity,zmax=-Infinity
    for(const mesh of meshes){const p=mesh.geometry.attributes.position;for(let i=0;i<p.count;i++){zmin=Math.min(zmin,p.getZ(i));zmax=Math.max(zmax,p.getZ(i))}}
    for(const mesh of meshes){mesh.skeleton?.update();const a=mesh.geometry.attributes;if(full)for(const key of ['position','normal','skinWeight'])if(!Array.from(a[key].array).every(Number.isFinite))invalid++
      for(let i=0;i<a.position.count;i++){mesh.getVertexPosition(i,q);mesh.localToWorld(q);if(!q.toArray().every(Number.isFinite))invalid++;minimum=Math.min(minimum,q.y);const p=(zmax-a.position.getZ(i))/(zmax-zmin),bin=Math.max(0,Math.min(23,Math.floor(p*24)));floors[bin]=Math.min(floors[bin],q.y)}
    }
    return {roots:roots.length,meshes:meshes.length,outlines:outlines.length,bones:bones.length,invalid,minimum,torsoFloor:Math.max(...floors.slice(4,19)),posteriorFloor:Math.max(...floors.slice(10,19)),floors,position:root.position.toArray(),quaternion:root.quaternion.toArray(),scale:root.scale.toArray(),time:root.userData.animationTime,saturations:meshes.map(m=>m.material.uniforms.uSat.value)}
  },full)}
  await mount();report.baseline=await snapshot(true)
  assert.equal(report.baseline.roots,1);assert.equal(report.baseline.meshes,1);assert.equal(report.baseline.outlines,1);assert.equal(report.baseline.bones,25);assert.equal(report.baseline.invalid,0);assert.deepEqual(report.baseline.saturations,[.65])
  for(const action of ['idle','walk','special']){
    await page.evaluate(action=>window.basheApp.useApp.getState().setAction(action),action)
    await page.waitForTimeout(600)
    const samples=[]
    for(let i=0;i<12;i++){await page.waitForTimeout(120);samples.push(await snapshot(i===0))}
    assert(samples.every(s=>s.invalid===0&&s.minimum>.004&&s.minimum<.009),`${action} actual Stage contact`)
    const expectedQuaternion=[0,Math.sin(Math.PI*5/36),0,Math.cos(Math.PI*5/36)]
    assert(samples.every(s=>JSON.stringify(s.position)==='[0,0,0]'&&s.quaternion.every((v,i)=>Math.abs(v-expectedQuaternion[i])<1e-12)&&s.scale.every(v=>v===1)),`${action} keeps fixed 50-degree yaw, identity scale and stays in place`)
    assert(samples.every(s=>(action==='special'?s.posteriorFloor:s.torsoFloor)<.045),`${action} actual torso clearance`)
    report.actions[action]=samples
    const path=join(out,`app-${action}.png`);await page.screenshot({path});report.images.push(path)
  }
  await page.waitForFunction(()=>window.basheApp.useApp.getState().action==='idle',null,{timeout:30000});report.specialReturnsIdle=true
  await page.evaluate(()=>window.basheApp.useApp.getState().setAction('special'));await page.waitForTimeout(150)
  await page.evaluate(()=>window.basheApp.useApp.getState().setAction('walk'));await page.waitForTimeout(450)
  report.interruptedSpecial={action:await page.evaluate(()=>window.basheApp.useApp.getState().action),snapshot:await snapshot(true)}
  assert.equal(report.interruptedSpecial.action,'walk');assert.equal(report.interruptedSpecial.snapshot.invalid,0)
  // Two complete unmount/remount cycles, checking every owned GPU/material resource.
  for(let cycle=0;cycle<2;cycle++){
    await page.waitForFunction(()=>{const set=new Set();window.basheApp.state.scene.getObjectByName('bashe_root').traverse(n=>{if(n.isSkinnedMesh)set.add(n.skeleton)});return [...set].every(s=>s.boneTexture!==null)})
    await page.evaluate(()=>{const qa=window.basheApp,root=qa.state.scene.getObjectByName('bashe_root'),skeletons=new Set(),materials=new Map();root.traverse(n=>{if(n.skeleton)skeletons.add(n.skeleton);if(n.isMesh)for(const m of Array.isArray(n.material)?n.material:[n.material])materials.set(m,0)});const textures=new Map([...skeletons].map(s=>[s.boneTexture,0]));for(const material of materials.keys())material.addEventListener('dispose',()=>materials.set(material,materials.get(material)+1));for(const texture of textures.keys())texture.addEventListener('dispose',()=>textures.set(texture,textures.get(texture)+1));qa.old={skeletons,materials,textures}})
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei')});await page.evaluate(()=>window.basheApp.useApp.getState().select('jingwei'));await ready;await page.waitForTimeout(150)
    const cleanup=await page.evaluate(()=>{const {skeletons,materials,textures}=window.basheApp.old;return {materials:[...materials.values()],textures:[...textures.values()],liveSkeletonTextures:[...skeletons].filter(s=>s.boneTexture!==null).length}})
    assert.deepEqual(cleanup.materials,[1,1]);assert.deepEqual(cleanup.textures,[1]);assert.equal(cleanup.liveSkeletonTextures,0)
    await mount();const current=await snapshot(true);assert.equal(current.roots,1);assert.equal(current.meshes,1);assert.equal(current.outlines,1);assert.equal(current.invalid,0)
    const animations={}
    for(const action of ['idle','walk','special']){
      await page.evaluate(action=>window.basheApp.useApp.getState().setAction(action),action);await page.waitForTimeout(400)
      animations[action]=await page.evaluate(async()=>{const qa=window.basheApp,root=qa.state.scene.getObjectByName('bashe_root');let mesh;root.traverse(n=>{if(n.isSkinnedMesh&&!n.userData.inkOutline)mesh=n});const count=mesh.geometry.attributes.position.count,indices=[0,.03,.13,.35,.67,.93].map(p=>Math.floor((count-1)*p)),q=root.position.clone();let initial,maxDisplacement=0,invalid=0;const startTime=root.userData.animationTime;for(let frame=0;frame<16;frame++){await new Promise(requestAnimationFrame);root.updateMatrixWorld(true);mesh.skeleton.update();const points=indices.map(i=>mesh.getVertexPosition(i,q.clone()));if(!points.every(p=>p.toArray().every(Number.isFinite)))invalid++;if(!initial)initial=points;points.forEach((p,i)=>maxDisplacement=Math.max(maxDisplacement,p.distanceTo(initial[i])))}return {invalid,maxDisplacement,startTime,endTime:root.userData.animationTime,freshSkeleton:!qa.old.skeletons.has(mesh.skeleton),freshTexture:!qa.old.textures.has(mesh.skeleton.boneTexture)}})
      assert.equal(animations[action].invalid,0);assert(animations[action].maxDisplacement>1e-6);assert(animations[action].freshSkeleton&&animations[action].freshTexture);assert.notEqual(animations[action].startTime,animations[action].endTime)
    }
    report.remounts.push({cleanup,current,animations})
  }
  report.cache=await page.evaluate(()=>{const qa=window.basheApp;return {unchanged:qa.snapshot()===qa.before,sharedDisposals:qa.sharedDisposals}})
  assert(report.cache.unchanged&&report.cache.sharedDisposals===0)
  await page.evaluate(()=>window.basheApp.useApp.getState().setAction('idle'));await page.waitForTimeout(600)
  report.defaultViewports=[]
  for(const [width,height]of [[1440,900],[800,1000],[390,844]]){
    await page.setViewportSize({width,height});await page.waitForTimeout(1100)
    const path=join(out,`app-default-${width}.png`)
    await page.screenshot({path});report.images.push(path)
    const framing=await page.evaluate(()=>{const {state}=window.basheApp,root=state.scene.getObjectByName('bashe_root'),head=state.scene.getObjectByName('head'),tip=root.position.clone().set(0,0,0);head.getWorldPosition(tip);tip.project(state.camera);const card=document.querySelector('.card')?.getBoundingClientRect();return {projectedHead:[(tip.x+1)*innerWidth/2,(1-tip.y)*innerHeight/2],card:card?{left:card.left,top:card.top,right:card.right,bottom:card.bottom}:null,camera:state.camera.position.toArray(),fov:state.camera.fov}})
    report.defaultViewports.push({width,height,path,framing})
  }
  await page.setViewportSize({width:1440,height:900});await page.waitForTimeout(900)
  await page.addStyleTag({content:'.card,.actions,.scroll-wrap,.controls,.title{visibility:hidden!important}'})
  await page.evaluate(()=>{const {state}=window.basheApp;state.setFrameloop('never');state.controls.enabled=false;state.controls.enableDamping=false;state.camera.filmOffset=0;state.camera.updateProjectionMatrix()})
  for(const [name,target,position,up]of [['head',[0,.16,2.1],[1.1,.62,3.15],[0,1,0]],['dorsalHead',[0,.13,2.1],[0,1.65,2.1],[0,0,-1]],['side',[0,.17,0],[6.5,.8,0],[0,1,0]]]){
    await page.evaluate(({target,position,up})=>{const {state}=window.basheApp,root=state.scene.getObjectByName('bashe_root'),point=values=>root.position.clone().fromArray(values).multiply(root.scale).applyQuaternion(root.quaternion).add(root.position);state.controls.target.copy(point(target));state.camera.position.copy(point(position));state.camera.up.fromArray(up).applyQuaternion(root.quaternion);state.camera.lookAt(state.controls.target);state.advance(state.clock.elapsedTime+.001,true)},{target,position,up})
    const path=join(out,`app-close-${name}.png`);await page.screenshot({path});report.images.push(path)
  }
  report.clipDurations=await page.evaluate(()=>window.basheApp.clipDurations)
  assert.equal(errors.length,0,errors.join('\n'));report.passed=true
  console.log(JSON.stringify({passed:report.passed,baseline:report.baseline,specialReturnsIdle:report.specialReturnsIdle,remounts:report.remounts.length,cache:report.cache,images:report.images,errors},null,2))
}finally{await writeFile(join(out,'app-qa.json'),JSON.stringify(report,null,2)+'\n');await browser.close()}
