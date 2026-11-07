import { chromium } from 'playwright-core'
import { mkdir, writeFile } from 'node:fs/promises'
const base=process.argv[2]??'http://localhost:5215'
const out=process.argv[3]??'/tmp/shanhai-check/bifang-quality'
await mkdir(out,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
await page.addInitScript(()=>{window.__scenes=[];window.__THREE_DEVTOOLS__=new EventTarget();window.__THREE_DEVTOOLS__.addEventListener('observe',e=>{if(e.detail.isScene)window.__scenes.push(e.detail)})})
// Snapshot the cache before the first Bifang StrictMode mount.
await page.goto(new URL('/?beast=jingwei',base).href)
await page.waitForFunction(()=>window.__scenes[0]?.getObjectByName('beak_attach'))
await page.evaluate(async()=>{
 window.moduleUrl=path=>{const entry=performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===path);if(!entry)throw Error('Missing Vite module '+path);return entry.name}
 window.app=(await import(window.moduleUrl('/src/app/store.ts'))).useApp
 window.app.getState().setQuality('high',true)
 const {AnimationMixer,Object3D}=await import(window.moduleUrl('/node_modules/.vite/deps/three.js'));const original=AnimationMixer.prototype.update
 AnimationMixer.prototype.update=function(dt){if(this.getRoot().name==='bifang_scene')window.mixer=this;return original.call(this,dt)}
 const {useGLTF}=await import(window.moduleUrl('/node_modules/.vite/deps/@react-three_drei.js'))
 useGLTF.preload('/models/bifang/body.glb')
 for(;;){try{window.cachedScene=useGLTF('/models/bifang/body.glb').scene;break}catch(pending){if(!pending?.then)throw pending;await pending}}
 window.cacheSnapshot=()=>{const rows=[];window.cachedScene.traverse(n=>rows.push({uuid:n.uuid,name:n.name,children:n.children.map(c=>c.uuid),material:(Array.isArray(n.material)?n.material:n.material?[n.material]:[]).map(m=>({uuid:m.uuid,type:m.type,color:m.color?.getHexString(),roughness:m.roughness,metalness:m.metalness,opacity:m.opacity,transparent:m.transparent,side:m.side,depthWrite:m.depthWrite,depthTest:m.depthTest,map:m.map?.uuid,normalMap:m.normalMap?.uuid,userData:JSON.stringify(m.userData)})),geometry:n.geometry?.uuid,skeleton:n.skeleton?.uuid,position:n.position.toArray(),quaternion:n.quaternion.toArray(),scale:n.scale.toArray(),outline:!!n.userData.inkOutline}));return JSON.stringify(rows)}
 window.cacheBefore=window.cacheSnapshot();window.cachedResources=new Set();window.cacheDisposals=0
 window.cachedScene.traverse(n=>{if(n.geometry)window.cachedResources.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){window.cachedResources.add(m);for(const v of Object.values(m))if(v?.isTexture)window.cachedResources.add(v)}})
 for(const r of window.cachedResources)r.addEventListener('dispose',()=>window.cacheDisposals++)
 window.emitters=new Map();const getWorldPosition=Object3D.prototype.getWorldPosition
 Object3D.prototype.getWorldPosition=function(target){const result=getWorldPosition.call(this,target);if(['wing_l_attach','wing_r_attach','beak_attach','tail_attach'].includes(this.name)){let e=window.emitters.get(this);if(!e){e={count:0,first:result.toArray(),maxMotion:0};window.emitters.set(this,e)}e.count++;e.maxMotion=Math.max(e.maxMotion,result.distanceTo({x:e.first[0],y:e.first[1],z:e.first[2]}))}return result}
 window.audio=(await import(window.moduleUrl('/src/systems/audio/AudioEngine.ts'))).audio
 window.calls=0;const call=window.audio.bifangCall.bind(window.audio);window.audio.bifangCall=(...args)=>{window.calls++;return call(...args)}
})
await page.evaluate(()=>window.app.getState().select('bifang'))
await page.waitForFunction(()=>window.mixer)
await page.waitForTimeout(500)
const inspect=()=>page.evaluate(()=>{
 const scene=window.__scenes[0],root=scene.getObjectByName('bifang_scene');scene.updateMatrixWorld(true)
 let nodes=0,meshes=0,outlines=0;const invalid=[]
 root.traverse(o=>{nodes++;if(o.userData.inkOutline)outlines++;if(!o.isMesh)return;for(const [name,a] of Object.entries(o.geometry.attributes))for(const v of a.array)if(!Number.isFinite(v))invalid.push(name);if(o.skeleton){o.skeleton.update();for(const v of o.skeleton.boneMatrices)if(!Number.isFinite(v))invalid.push('matrix')};if(o.isSkinnedMesh&&!o.userData.inkOutline)meshes++})
 return {nodes,meshes,outlines,invalid,roots:scene.children.filter(o=>o.getObjectByName('bifang_scene')).length}
})
const qa={idle:await inspect(),remount:[],errors}
qa.cache=await page.evaluate(()=>{const root=window.__scenes[0].getObjectByName('bifang_scene');let outlines=0;window.cachedScene.traverse(n=>{if(n.userData.inkOutline)outlines++});return {ownedScene:root!==window.cachedScene,cachedOutlineCount:outlines,trackedSharedResources:window.cachedResources.size}})
// Cancel both action-delayed and unmount-delayed calls.
await page.evaluate(()=>{window.calls=0;window.app.getState().setAction('special')})
await page.waitForTimeout(120);await page.evaluate(()=>window.app.getState().setAction('idle'));await page.waitForTimeout(1050)
qa.interruptCalls=await page.evaluate(()=>window.calls)
await page.evaluate(()=>{window.calls=0;window.app.getState().setAction('special')})
await page.waitForTimeout(120);await page.evaluate(()=>window.app.getState().select('jingwei'));await page.waitForTimeout(1050)
qa.unmountCalls=await page.evaluate(()=>window.calls)
await page.evaluate(()=>window.app.getState().select('bifang'));await page.waitForFunction(()=>window.__scenes[0].getObjectByName('bifang_scene'))
for(let i=0;i<3;i++){
 await page.waitForTimeout(150)
 await page.evaluate(()=>{const root=window.__scenes[0].getObjectByName('bifang_scene'),skeletons=new Set();root.traverse(n=>{if(n.skeleton)skeletons.add(n.skeleton)});window.oldBones=[...skeletons].map(skeleton=>{const row={skeleton,texture:skeleton.boneTexture,disposed:0};row.texture?.addEventListener('dispose',()=>{row.disposed++});return row})})
 await page.evaluate(()=>window.app.getState().select('jingwei'));await page.waitForTimeout(350)
 const released=await page.evaluate(()=>({removed:!window.__scenes[0].getObjectByName('bifang_scene'),skeletons:window.oldBones.length,allocated:window.oldBones.filter(x=>x.texture).length,disposedTextures:window.oldBones.filter(x=>x.disposed).length,disposalCounts:window.oldBones.map(x=>x.disposed),allSkeletonTexturesNull:window.oldBones.every(x=>x.skeleton.boneTexture===null),cacheUnchanged:window.cacheSnapshot()===window.cacheBefore,sharedDisposals:window.cacheDisposals}))
 await page.evaluate(()=>window.app.getState().select('bifang'));await page.waitForFunction(()=>{const root=window.__scenes[0].getObjectByName('bifang_scene');return root&&window.mixer?.getRoot()===root});await page.waitForTimeout(350)
 const actions=[]
 for(const action of ['idle','walk','special']){
  await page.evaluate(a=>{window.emitters.clear();window.app.getState().setAction(a)},action);await page.waitForTimeout(100)
  const before=await page.evaluate(a=>window.mixer._actions.find(x=>x.getClip().name===a).time,action)
  await page.waitForTimeout(250)
  actions.push(await page.evaluate(({action,before})=>{const root=window.__scenes[0].getObjectByName('bifang_scene'),names=['wing_l_attach','wing_r_attach','beak_attach','tail_attach'];const sourceSkeletons=new Set();window.cachedScene.traverse(n=>{if(n.skeleton)sourceSkeletons.add(n.skeleton)});let separate=true;root.traverse(n=>{if(n.skeleton&&sourceSkeletons.has(n.skeleton))separate=false});return {action,timeAdvance:window.mixer._actions.find(x=>x.getClip().name===action).time-before,ownedSkeletons:separate,emitterReads:names.map(name=>{const node=root.getObjectByName(name),sample=window.emitters.get(node);return {name,reads:sample?.count??0,maxMotion:sample?.maxMotion??0,cloned:node!==window.cachedScene.getObjectByName(name)}}),cachedEmitterReads:names.reduce((n,name)=>n+(window.emitters.get(window.cachedScene.getObjectByName(name))?.count??0),0),cacheUnchanged:window.cacheSnapshot()===window.cacheBefore}}, {action,before}))
 }
 await page.evaluate(()=>window.app.getState().setAction('idle'));await page.waitForTimeout(300)
 qa.remount.push({...released,actions,...await inspect()})
}
qa.cache.final=await page.evaluate(()=>({unchanged:window.cacheSnapshot()===window.cacheBefore,sharedDisposals:window.cacheDisposals}))
await page.evaluate(()=>{window.state=window.__scenes[0].__r3f.root.getState();window.state.setFrameloop('never')})
await page.evaluate(()=>{
 const root=window.state.scene.getObjectByName('bifang_scene'),candidates=[];window.state.scene.updateMatrixWorld(true)
 root.traverse(o=>{if(!o.isSkinnedMesh||o.userData.inkOutline)return;o.skeleton.update();const v=o.position.clone();for(let i=0;i<o.geometry.getAttribute('position').count;i++){o.getVertexPosition(i,v);o.localToWorld(v);if(v.y<.004)candidates.push({o,i,rest:v.toArray()})}})
 window.soleCount=candidates.length;if(candidates.length<3)throw Error('Missing actual sole vertices')
 const first=candidates[0],far=candidates.reduce((best,x)=>Math.hypot(x.rest[0]-first.rest[0],x.rest[2]-first.rest[2])>Math.hypot(best.rest[0]-first.rest[0],best.rest[2]-first.rest[2])?x:best)
 const a=far.rest.map((v,i)=>v-first.rest[i]);const area=x=>{const b=x.rest.map((v,i)=>v-first.rest[i]);return Math.hypot(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])}
 const third=candidates.reduce((best,x)=>area(x)>area(best)?x:best);if(area(third)<1e-6)throw Error('Collinear actual sole triangle')
 window.sole=[first,far,third]
})
for(const action of ['idle','walk','special']){
 await page.evaluate(a=>window.app.getState().setAction(a),action);await page.waitForTimeout(50)
 qa[action+'Support']=await page.evaluate(action=>{
  const s=window.state,m=window.mixer,clip=m._actions.find(a=>a.getClip().name===action)
  for(const a of m._actions)if(a!==clip)a.stop();clip.reset().setEffectiveWeight(1).play()
  let now=s.clock.elapsedTime,anchor=null;const segments=[];let minSoleY=Infinity,maxSoleY=-Infinity
  const render=s.gl.render;s.gl.render=()=>{}
  const normal=points=>{
   const u=points[1].map((v,k)=>v-points[0][k]),v=points[2].map((v,k)=>v-points[0][k])
   const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n)
   if(length<1e-9)throw Error('Sole plane became degenerate')
   return n.map(v=>v/length)
  }
  for(let frame=0;frame<(action==='walk'?420:252);frame++){
   now+=1/60;s.advance(now,true);s.scene.updateMatrixWorld(true);s.scene.getObjectByName('bifang_scene').traverse(o=>{if(o.skeleton)o.skeleton.update()})
   if(frame<20)continue
   const phase=(clip.time/clip.getClip().duration)%1,planted=action!=='walk'||phase<=.38
   const pts=window.sole.map(({o,i})=>{const v=o.position.clone();o.getVertexPosition(i,v);o.localToWorld(v);return v.toArray()})
   if(pts.some(p=>p.some(x=>!Number.isFinite(x))))throw Error('Invalid deformed world-space toe vertex')
   const heading=Math.atan2(pts[1][0]-pts[0][0],pts[1][2]-pts[0][2])
   if(planted){
    for(const p of pts){minSoleY=Math.min(minSoleY,p[1]);maxSoleY=Math.max(maxSoleY,p[1])}
    if(!anchor)anchor={first:pts,heading,beginPhase:phase,frames:0,maxXYZ:0,maxXZ:0,maxY:0,maxYawDegrees:0,maxPlaneNormalRadians:0}
    anchor.frames++
    const n=normal(pts),n0=normal(anchor.first)
    anchor.maxPlaneNormalRadians=Math.max(anchor.maxPlaneNormalRadians,Math.acos(Math.max(-1,Math.min(1,n.reduce((sum,v,k)=>sum+v*n0[k],0)))))
    for(let i=0;i<3;i++){anchor.maxXYZ=Math.max(anchor.maxXYZ,Math.hypot(...pts[i].map((v,k)=>v-anchor.first[i][k])));anchor.maxXZ=Math.max(anchor.maxXZ,Math.hypot(pts[i][0]-anchor.first[i][0],pts[i][2]-anchor.first[i][2]));anchor.maxY=Math.max(anchor.maxY,Math.abs(pts[i][1]-anchor.first[i][1]))}
    const d=heading-anchor.heading;anchor.maxYawDegrees=Math.max(anchor.maxYawDegrees,Math.abs(Math.atan2(Math.sin(d),Math.cos(d)))*180/Math.PI)
   }else if(anchor){segments.push(anchor);anchor=null}
  }
  if(anchor)segments.push(anchor);s.gl.render=render
  return {method:'Three non-collinear actual deformed toe sole vertices, real useFrame at 60Hz, full world XYZ and toe heading through each support phase',candidates:window.soleCount,minSoleY,maxSoleY,maxXYZ:Math.max(...segments.map(x=>x.maxXYZ)),maxXZ:Math.max(...segments.map(x=>x.maxXZ)),maxY:Math.max(...segments.map(x=>x.maxY)),maxYawDegrees:Math.max(...segments.map(x=>x.maxYawDegrees)),maxPlaneNormalRadians:Math.max(...segments.map(x=>x.maxPlaneNormalRadians)),segments:segments.map(({first,heading,...x})=>x)}
 },action)
}
await page.evaluate(()=>{window.state.setFrameloop('always');window.app.getState().setAction('idle')})
await page.waitForTimeout(250);await page.evaluate(()=>window.app.getState().setAction('special'))
await page.waitForFunction(()=>window.app.getState().action==='idle',null,{timeout:15000})
qa.specialReturn=await page.evaluate(()=>window.app.getState().action)
qa.audio=await page.evaluate(async()=>{
 const c=new AudioContext(),buf=await c.decodeAudioData(await(await fetch('/audio/narration/bifang.mp3')).arrayBuffer());let sum=0,invalid=0;const a=buf.getChannelData(0);for(const x of a){sum+=x*x;if(!Number.isFinite(x))invalid++}
 const e=window.audio;await e.unlock();const analyser=e.context.createAnalyser();analyser.fftSize=2048;e.sfx.connect(analyser);e.bifangCall()
 let callPeakRms=0;const data=new Float32Array(analyser.fftSize)
 for(let i=0;i<10;i++){await new Promise(r=>setTimeout(r,90));analyser.getFloatTimeDomainData(data);callPeakRms=Math.max(callPeakRms,Math.sqrt(data.reduce((s,x)=>s+x*x,0)/data.length))}
 e.sfx.disconnect(analyser);await c.close();return {duration:buf.duration,sampleRate:buf.sampleRate,channels:buf.numberOfChannels,rms:Math.sqrt(sum/a.length),invalid,callPeakRms,contextState:e.context.state}
})
await page.locator('.story-btn').click()
await page.waitForFunction(()=>window.audio.narrationEl?.currentTime>.2&&!window.audio.narrationEl.paused)
qa.narration=await page.evaluate(()=>{const e=window.audio.narrationEl;return {duration:e.duration,currentTime:e.currentTime,paused:e.paused,error:e.error?.message??null}})
await page.getByRole('button',{name:'停止评书解说',exact:true}).click()
qa.narrationStopped=await page.evaluate(()=>!window.audio.narrationEl||window.audio.narrationEl.paused)
await page.screenshot({path:out+'/qa-idle.png'})
// Inspect real runtime materials and the opposing wing roots, not just concepts.
await page.evaluate(()=>{window.state.setFrameloop('never');window.state.controls.enabled=false})
await page.addStyleTag({content:'.card,.actions,.scroll-wrap,.controls,.title{visibility:hidden!important}'})
qa.views=[]
for(const [name,action,time,offset] of [
 ['front','idle',1,[0,.3,2.6]],['side','idle',1,[2.6,.25,0]],
 ['back','idle',1,[0,.3,-2.6]],['other-side','idle',1,[-2.6,.25,0]],
 ['display','special',2,[1.8,.65,2]],['step','walk',1.05,[2.3,.25,.7]],
]){
 await page.evaluate(a=>window.app.getState().setAction(a),action);await page.waitForTimeout(80)
 await page.evaluate(({action,time,offset})=>{
  const s=window.state,root=s.scene.getObjectByName('bifang_scene'),m=window.mixer
  const clip=m._actions.find(a=>a.getClip().name===action)
  for(const a of m._actions)if(a!==clip)a.stop()
  clip.reset().stopFading().setEffectiveWeight(1).play();clip.time=time;m.update(0)
  const center=root.position.clone();root.getWorldPosition(center);center.y=.8
  const direction=center.clone().set(...offset);direction.applyAxisAngle(center.clone().set(0,1,0),root.parent.rotation.y).multiplyScalar(1.45)
  s.controls.target.copy(center);s.camera.position.copy(center).add(direction)
  s.camera.filmOffset=0;s.camera.updateProjectionMatrix();s.camera.lookAt(center)
  s.advance(s.clock.elapsedTime+.001,true);s.scene.updateMatrixWorld(true)
 },{action,time,offset})
 await page.screenshot({path:out+'/'+name+'.png'});qa.views.push({name,action,time})
}
await writeFile(out+'/qa.json',JSON.stringify(qa,null,2));console.log(JSON.stringify(qa,null,2))
const supportBad=['idle','walk','special'].some(a=>!Number.isFinite(qa[a+'Support'].maxXYZ)||qa[a+'Support'].maxXYZ>.0015||Math.abs(qa[a+'Support'].minSoleY)>.0015||Math.abs(qa[a+'Support'].maxSoleY)>.0015||qa[a+'Support'].maxYawDegrees>.2||!Number.isFinite(qa[a+'Support'].maxPlaneNormalRadians)||qa[a+'Support'].maxPlaneNormalRadians>.0035)
const ownershipBad=!qa.cache.ownedScene||qa.cache.cachedOutlineCount!==0||!qa.cache.final.unchanged||qa.cache.final.sharedDisposals!==0||qa.remount.some(x=>!x.cacheUnchanged||x.sharedDisposals!==0||x.allocated===0||x.allocated!==x.disposedTextures||x.disposalCounts.some(n=>n!==1)||!x.allSkeletonTexturesNull||x.actions.some(a=>a.timeAdvance<.1||!a.ownedSkeletons||!a.cacheUnchanged||a.cachedEmitterReads!==0||a.emitterReads.some(e=>!e.cloned||e.reads===0||e.maxMotion<1e-6)))
if(errors.length||supportBad||ownershipBad||qa.interruptCalls||qa.unmountCalls||qa.specialReturn!=='idle'||qa.remount.some(x=>!x.removed||x.roots!==1||x.nodes!==qa.idle.nodes||x.meshes!==qa.idle.meshes||x.outlines!==qa.idle.outlines||x.invalid.length)||qa.audio.invalid||qa.audio.rms<=0||qa.audio.callPeakRms<=0||qa.audio.contextState!=='running'||qa.narration.error||!qa.narrationStopped)process.exitCode=1
await browser.close()
