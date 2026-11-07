import { chromium } from 'playwright-core'
import { mkdir, writeFile } from 'node:fs/promises'

const base=process.argv[2]??'http://localhost:5215'
const out=process.argv[3]??'/tmp/shanhai-check/fenghuang-quality'
await mkdir(out,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}}), errors=[]
page.on('pageerror',e=>{errors.push(String(e));console.error(String(e))})
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
await page.addInitScript(()=>{
  window.__scenes=[];window.__THREE_DEVTOOLS__=new EventTarget()
  window.__THREE_DEVTOOLS__.addEventListener('observe',e=>{if(e.detail.isScene)window.__scenes.push(e.detail)})
})
// Load the cached GLTF before mounting Fenghuang so cache invariance is checked
// against the original source tree, including the first StrictMode setup replay.
await page.goto(new URL('/?beast=jingwei',base).href)
await page.waitForFunction(()=>window.__scenes[0]?.getObjectByName('beak_attach'))
await page.evaluate(async()=>{
  window.moduleUrl=path=>{
    const entry=performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===path)
    if(!entry)throw Error('Missing Vite module '+path)
    return entry.name
  }
  window.app=(await import(window.moduleUrl('/src/app/store.ts'))).useApp
  window.app.getState().setQuality('high',true)
  const {AnimationMixer,Material}=await import(window.moduleUrl('/node_modules/.vite/deps/three.js'))
  const update=AnimationMixer.prototype.update,dispose=Material.prototype.dispose
  window.disposals=0
  Material.prototype.dispose=function(){window.disposals++;return dispose.call(this)}
  AnimationMixer.prototype.update=function(dt){if(this.getRoot().name==='fenghuang_scene')window.mixer=this;return update.call(this,dt)}
  window.audio=(await import(window.moduleUrl('/src/systems/audio/AudioEngine.ts'))).audio
  const {useGLTF}=await import(window.moduleUrl('/node_modules/.vite/deps/@react-three_drei.js'))
  const url='/models/fenghuang/body.glb'
  useGLTF.preload(url)
  // In this pinned R3F version useLoader synchronously reads suspend-react's
  // cache; an unresolved entry throws its loading promise, with no React hooks.
  for(;;){try{window.cached=useGLTF(url);break}catch(pending){if(!pending?.then)throw pending;await pending}}
  window.cachedNodes=[];window.sharedDisposals=[]
  const shared=new Set()
  window.cached.scene.traverse(o=>{
    window.cachedNodes.push({o,name:o.name,parent:o.parent,children:[...o.children],material:o.material,geometry:o.geometry,
      transform:[...o.position,...o.quaternion,...o.scale],frustumCulled:o.frustumCulled,skeleton:o.skeleton})
    if(o.geometry)shared.add(o.geometry)
    for(const material of o.material?(Array.isArray(o.material)?o.material:[o.material]):[]){
      shared.add(material)
      for(const value of Object.values(material))if(value?.isTexture)shared.add(value)
    }
  })
  for(const resource of shared)resource.addEventListener('dispose',()=>window.sharedDisposals.push(resource.uuid))
  window.cacheUnchanged=()=>window.sharedDisposals.length===0&&window.cachedNodes.every(({o,name,parent,children,material,geometry,transform,frustumCulled,skeleton})=>
    o.name===name&&o.parent===parent&&o.material===material&&o.geometry===geometry&&o.frustumCulled===frustumCulled&&o.skeleton===skeleton&&
    o.children.length===children.length&&children.every((child,i)=>o.children[i]===child)&&
    [...o.position,...o.quaternion,...o.scale].every((value,i)=>value===transform[i]))
  window.ownership=()=>{
    const root=window.__scenes[0].getObjectByName('fenghuang_scene'),nodes=new Set(window.cachedNodes.map(x=>x.o)),sourceSkeletons=new Set(window.cachedNodes.map(x=>x.skeleton).filter(Boolean))
    const result={ownScene:root!==window.cached.scene,ownNodes:true,ownSkeletons:true,ownBones:true,sharedGeometry:true,sharedTextures:true,cacheUnchanged:window.cacheUnchanged(),sharedDisposals:[...window.sharedDisposals]}
    root.traverse(o=>{
      if(nodes.has(o))result.ownNodes=false
      if(!o.isSkinnedMesh||o.userData.inkOutline)return
      if(sourceSkeletons.has(o.skeleton))result.ownSkeletons=false
      if(o.skeleton.bones.some(b=>nodes.has(b)))result.ownBones=false
      const source=window.cachedNodes.find(x=>x.o.name===o.name&&x.geometry===o.geometry)
      if(!source){result.sharedGeometry=false;result.sharedTextures=false;return}
      if(o.material.uniforms.uMap.value!==source.material.map)result.sharedTextures=false
    })
    return result
  }
  window.app.getState().select('fenghuang')
})
await page.waitForFunction(()=>window.mixer?.getRoot()===window.__scenes[0]?.getObjectByName('fenghuang_scene'))
await page.waitForTimeout(500)
const inspect=()=>page.evaluate(()=>{
  const scene=window.__scenes[0],root=scene.getObjectByName('fenghuang_scene')
  scene.updateMatrixWorld(true)
  const result={nodes:0,meshes:0,outlines:0,invalid:[],breastLegInfluence:0,roots:scene.children.filter(o=>o.getObjectByName('fenghuang_scene')).length,ownership:window.ownership()}
  root.traverse(o=>{
    result.nodes++;if(o.userData.inkOutline)result.outlines++
    if(!o.isMesh)return
    for(const [name,a] of Object.entries(o.geometry.attributes))for(const v of a.array)if(!Number.isFinite(v))result.invalid.push(name)
    if(o.skeleton){o.skeleton.update();for(const x of o.skeleton.boneMatrices)if(!Number.isFinite(x))result.invalid.push('bone')}
    if(o.isSkinnedMesh&&!o.userData.inkOutline){
      result.meshes++
      const v=o.position.clone()
      const position=o.geometry.getAttribute('position'),indices=o.geometry.getAttribute('skinIndex'),weights=o.geometry.getAttribute('skinWeight')
      for(let i=0;i<position.count;i++){
        // Front belly feathers must not follow the thigh/shank/toe skeleton.
        if(position.getY(i)>.27&&position.getY(i)<.44&&position.getZ(i)>.24&&Math.abs(position.getX(i))<.16){
          let influence=0
          for(let j=0;j<4;j++)if(/^(leg_|foot_)/.test(o.skeleton.bones[indices.getComponent(i,j)].name))influence+=weights.getComponent(i,j)
          result.breastLegInfluence=Math.max(result.breastLegInfluence,influence)
        }
        o.getVertexPosition(i,v);o.localToWorld(v)
        if(![v.x,v.y,v.z].every(Number.isFinite))result.invalid.push('deformed vertex')
      }
    }
  })
  return result
})
const advancing=async action=>{
  await page.evaluate(a=>window.app.getState().setAction(a),action)
  await page.waitForTimeout(300)
  const sample=()=>page.evaluate(action=>{
    const root=window.__scenes[0].getObjectByName('fenghuang_scene'),mixer=window.mixer
    const clip=mixer._actions.find(a=>a.getClip().name===(action==='special'?'alert':action)),pose=[]
    root.traverse(o=>{if(o.isBone)pose.push(...o.position,...o.quaternion)})
    return {root:root.uuid,mixerTime:mixer.time,clipTime:clip.time,playing:clip.isRunning(),pose}
  },action)
  const before=await sample();await page.waitForTimeout(260);const after=await sample()
  return {action,sameRoot:before.root===after.root,mixerSeconds:after.mixerTime-before.mixerTime,clipAdvanced:after.clipTime!==before.clipTime,
    playing:before.playing&&after.playing,maxBonePoseDelta:Math.max(...after.pose.map((v,i)=>Math.abs(v-before.pose[i])))}
}
const qa={idle:await inspect(),walk:[],special:[],remount:[],animation:[]}
for(const action of ['idle','walk','special'])qa.animation.push(await advancing(action))
for(const action of ['walk','special']){
  await page.evaluate(a=>window.app.getState().setAction(a),action)
  for(let i=0;i<6;i++){await page.waitForTimeout(action==='walk'?250:500);qa[action].push(await inspect())}
}
await page.evaluate(()=>window.app.getState().setAction('idle'))
await page.waitForTimeout(100)
await page.evaluate(()=>window.app.getState().setAction('special'))
await page.waitForFunction(()=>window.app.getState().action==='idle',null,{timeout:15000})
qa.specialReturn=await page.evaluate(()=>window.app.getState().action)
for(let i=0;i<3;i++){
  const before=await page.evaluate(()=>{
    const root=window.__scenes[0].getObjectByName('fenghuang_scene'),skeletons=new Set()
    root.traverse(o=>{if(o.isSkinnedMesh)skeletons.add(o.skeleton)})
    const textures=[...skeletons].map(s=>s.boneTexture)
    if(textures.some(t=>!t))throw Error('A rendered clone skeleton has no bone texture')
    window.retired={root,mixer:window.mixer,skeletons:[...skeletons],textures,disposals:new Map()}
    for(const texture of textures)texture.addEventListener('dispose',()=>window.retired.disposals.set(texture,(window.retired.disposals.get(texture)??0)+1))
    return window.disposals
  })
  await page.evaluate(()=>window.app.getState().select('jingwei'))
  await page.waitForTimeout(400)
  const retired=await page.evaluate(()=>{
    const r=window.retired
    return {removed:!window.__scenes[0].getObjectByName('fenghuang_scene')&&r.root.parent===null,disposed:window.disposals,
      skeletons:r.skeletons.length,boneTextures:r.textures.length,boneTextureDisposals:r.textures.map(t=>r.disposals.get(t)??0),
      skeletonTexturesCleared:r.skeletons.every(s=>s.boneTexture===null),mixerUncached:r.mixer._actions.length===0&&r.mixer._bindings.length===0,
      cacheUnchanged:window.cacheUnchanged(),sharedDisposals:[...window.sharedDisposals]}
  })
  await page.evaluate(()=>window.app.getState().select('fenghuang'))
  await page.waitForFunction(()=>window.mixer?.getRoot()===window.__scenes[0]?.getObjectByName('fenghuang_scene'))
  await page.waitForTimeout(450)
  const animation=[]
  for(const action of ['idle','walk','special'])animation.push(await advancing(action))
  qa.remount.push({...retired,disposed:retired.disposed-before,animation,...await inspect()})
  await page.evaluate(()=>window.app.getState().setAction('idle'))
  await page.waitForTimeout(100)
}
await page.evaluate(()=>{window.state=window.__scenes[0].__r3f.root.getState();window.state.setFrameloop('never')})
await page.evaluate(()=>{
  const root=window.state.scene.getObjectByName('fenghuang_scene'),candidates=[[],[]]
  window.state.scene.updateMatrixWorld(true)
  root.traverse(o=>{
    if(!o.isSkinnedMesh||o.userData.inkOutline)return
    o.skeleton.update();const v=o.position.clone()
    for(let i=0;i<o.geometry.getAttribute('position').count;i++){
      o.getVertexPosition(i,v);o.localToWorld(v);root.worldToLocal(v)
      if(v.y<.006&&Math.abs(v.x)>.045)candidates[v.x>0?0:1].push({o,i,rest:v.toArray()})
    }
  })
  window.soleCounts=candidates.map(x=>x.length)
  window.soles=candidates.map(list=>{
    if(list.length<3)throw Error('Missing actual sole vertices')
    const first=list[0],distance=x=>Math.hypot(x.rest[0]-first.rest[0],x.rest[2]-first.rest[2])
    const far=list.reduce((best,x)=>distance(x)>distance(best)?x:best)
    const a=far.rest.map((v,k)=>v-first.rest[k])
    const area=x=>{const b=x.rest.map((v,k)=>v-first.rest[k]);return Math.hypot(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])}
    const third=list.reduce((best,x)=>area(x)>area(best)?x:best)
    if(area(third)<1e-9)throw Error('Collinear sole triangle')
    return [first,far,third]
  })
})
for(const action of ['idle','walk','special']){
  await page.evaluate(a=>window.app.getState().setAction(a),action)
  await page.waitForTimeout(100)
  qa[action+'Support']=await page.evaluate(action=>{
    const state=window.state,mixer=window.mixer,clip=mixer._actions.find(a=>a.getClip().name===(action==='special'?'alert':action))
    for(const a of mixer._actions)if(a!==clip)a.stop()
    clip.reset().stopFading().setEffectiveWeight(1).play()
    const anchors=[null,null],segments=[];let now=state.clock.elapsedTime
    const render=state.gl.render;state.gl.render=()=>{}
    const frameCount=action==='special'?306:action==='walk'?384:240
    let minimumY=Infinity,maximumLift=0
    const normal=points=>{
      const u=points[1].map((v,k)=>v-points[0][k]),v=points[2].map((v,k)=>v-points[0][k])
      const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n)
      if(length<1e-9)throw Error('Sole triangle became degenerate')
      return n.map(v=>v/length)
    }
    for(let frame=0;frame<frameCount;frame++){
      now+=1/60;state.advance(now,true);state.scene.updateMatrixWorld(true)
      state.scene.traverse(o=>{if(o.skeleton)o.skeleton.update()})
      for(let foot=0;foot<2;foot++){
        if(frame<20)continue
        const raw=(clip.time/1.6+[0,.5][foot])%1,phase=raw>1-1e-6?0:raw
        const begin=[1,2.65][foot]
        const planted=action==='walk'?phase<.648:action==='special'?!(clip.time>begin-.01&&clip.time<begin+1.26):true
        const points=window.soles[foot].map(({o,i})=>{const v=o.position.clone();o.getVertexPosition(i,v);o.localToWorld(v);return v.toArray()})
        if(points.some(p=>p.some(v=>!Number.isFinite(v))))throw Error('Non-finite actual sole XYZ')
        minimumY=Math.min(minimumY,...points.map(p=>p[1]));maximumLift=Math.max(maximumLift,...points.map(p=>p[1]))
        const heading=Math.atan2(points[1][0]-points[0][0],points[1][2]-points[0][2])
        if(planted){
          if(!anchors[foot])anchors[foot]={foot:['left','right'][foot],first:points,heading,frames:0,maxXYZ:0,maxXZ:0,maxY:0,maxYawDegrees:0,maxPlaneNormalRadians:0}
          const a=anchors[foot];a.frames++
          const n=normal(points),n0=normal(a.first)
          a.maxPlaneNormalRadians=Math.max(a.maxPlaneNormalRadians,Math.acos(Math.max(-1,Math.min(1,n.reduce((sum,v,k)=>sum+v*n0[k],0)))))
          for(let i=0;i<points.length;i++){
            a.maxXYZ=Math.max(a.maxXYZ,Math.hypot(...points[i].map((v,k)=>v-a.first[i][k])))
            a.maxXZ=Math.max(a.maxXZ,Math.hypot(points[i][0]-a.first[i][0],points[i][2]-a.first[i][2]))
            a.maxY=Math.max(a.maxY,Math.abs(points[i][1]-a.first[i][1]))
          }
          const delta=heading-a.heading
          a.maxYawDegrees=Math.max(a.maxYawDegrees,Math.abs(Math.atan2(Math.sin(delta),Math.cos(delta)))*180/Math.PI)
        }else if(anchors[foot]){segments.push(anchors[foot]);anchors[foot]=null}
      }
    }
    for(const anchor of anchors)if(anchor)segments.push(anchor)
    state.gl.render=render
    return {method:'Actual 60Hz useFrame; three noncollinear deformed sole vertices per foot, full world XYZ and heading during every support phase',soleCandidates:window.soleCounts,minimumY,maximumLift,
      maxXYZ:Math.max(...segments.map(x=>x.maxXYZ)),maxXZ:Math.max(...segments.map(x=>x.maxXZ)),maxY:Math.max(...segments.map(x=>x.maxY)),maxYawDegrees:Math.max(...segments.map(x=>x.maxYawDegrees)),maxPlaneNormalRadians:Math.max(...segments.map(x=>x.maxPlaneNormalRadians)),segments:segments.map(({first,heading,...x})=>x)}
  },action)
}
await page.evaluate(()=>{window.state.setFrameloop('always');window.app.getState().setAction('idle')})
qa.audio=await page.evaluate(async()=>{
  const context=new AudioContext(),buffer=await context.decodeAudioData(await(await fetch('/audio/narration/fenghuang.mp3')).arrayBuffer())
  const samples=buffer.getChannelData(0);let sum=0,invalid=0
  for(const x of samples){sum+=x*x;if(!Number.isFinite(x))invalid++}
  await window.audio.unlock();const analyser=window.audio.context.createAnalyser();analyser.fftSize=2048
  window.audio.sfx.connect(analyser);window.audio.fenghuangCall()
  let callPeakRms=0;const data=new Float32Array(analyser.fftSize)
  for(let i=0;i<8;i++){await new Promise(r=>setTimeout(r,90));analyser.getFloatTimeDomainData(data);callPeakRms=Math.max(callPeakRms,Math.sqrt(data.reduce((s,x)=>s+x*x,0)/data.length))}
  window.audio.sfx.disconnect(analyser);await context.close()
  return {duration:buffer.duration,sampleRate:buffer.sampleRate,rms:Math.sqrt(sum/samples.length),invalid,callPeakRms,contextState:window.audio.context.state}
})
await page.locator('.story-btn').click()
await page.waitForFunction(()=>window.audio.narrationEl?.currentTime>.2&&!window.audio.narrationEl.paused)
qa.narration=await page.evaluate(()=>{const e=window.audio.narrationEl;return {duration:e.duration,currentTime:e.currentTime,paused:e.paused,error:e.error?.message??null}})
await page.screenshot({path:out+'/narration.png'})
await page.getByRole('button',{name:'停止评书解说',exact:true}).click()
qa.narrationStopped=await page.evaluate(()=>!window.audio.narrationEl||window.audio.narrationEl.paused)
qa.card=await page.locator('.card').textContent().catch(()=>null)
// A special cancelled by switching beasts must not leave delayed call timers.
await page.evaluate(()=>{
  window.calls=0;window.originalCall=window.audio.fenghuangCall
  window.audio.fenghuangCall=function(...args){window.calls++;return window.originalCall.apply(this,args)}
  window.app.getState().setAction('special')
})
await page.waitForTimeout(100)
await page.evaluate(()=>window.app.getState().select('jingwei'))
await page.waitForTimeout(2700)
qa.cancelledCalls=await page.evaluate(()=>{window.audio.fenghuangCall=window.originalCall;return window.calls})
await page.evaluate(()=>window.app.getState().select('fenghuang'))
await page.waitForFunction(()=>window.__scenes[0].getObjectByName('fenghuang_scene'))
qa.buttons=[]
for(const [label,action] of [['行','walk'],['静','idle'],['神通','special']]){
  await page.getByRole('button',{name:label,exact:true}).click()
  qa.buttons.push({label,expected:action,actual:await page.evaluate(()=>window.app.getState().action)})
}
qa.cardSections={source:await page.locator('.card-source').textContent(),inferred:await page.locator('.card-inferred').textContent(),inferredBorder:await page.locator('.card-inferred').evaluate(e=>getComputedStyle(e).borderColor)}
await page.evaluate(()=>window.app.getState().setAction('idle'))
await page.waitForTimeout(300)
await page.evaluate(()=>{window.state=window.__scenes[0].__r3f.root.getState();window.state.setFrameloop('never');window.state.controls.enabled=false})
await page.addStyleTag({content:'.card,.actions,.scroll-wrap,.controls,.title{visibility:hidden!important}'})
qa.views=[]
for(const [name,action,time,offset] of [
  ['front','idle',1,[0,.35,2.5]],['side','idle',1,[2.5,.25,0]],['back','idle',1,[0,.4,-2.5]],
  ['three-quarter','idle',1,[1.8,.6,1.8]],['other-side','idle',1,[-2.5,.3,0]],
  ['display','special',1.7,[1.7,.95,1.9]],['step','walk',1.25,[2.3,.4,.7]],
]){
  await page.evaluate(a=>window.app.getState().setAction(a),action);await page.waitForTimeout(80)
  const pose=await page.evaluate(({action,time,offset})=>{
    const s=window.state,root=s.scene.getObjectByName('fenghuang_scene'),m=window.mixer
    const a=m._actions.find(a=>a.getClip().name===(action==='special'?'alert':action))
    for(const other of m._actions)if(other!==a)other.stop()
    a.reset().stopFading().setEffectiveWeight(1).play();a.time=time;m.update(0)
    const center=root.position.clone();root.getWorldPosition(center);center.y=.50
    const direction=center.clone().set(...offset);direction.applyAxisAngle(center.clone().set(0,1,0),root.parent.rotation.y)
    s.controls.target.copy(center);s.camera.position.copy(center).add(direction);s.camera.filmOffset=0;s.camera.updateProjectionMatrix();s.camera.lookAt(center)
    s.advance(s.clock.elapsedTime+.001,true);s.scene.updateMatrixWorld(true)
    const bones={}
    for(const name of ['wing_l_1','wing_l_3','wing_r_1','wing_r_3','tail_feather']){
      const b=root.getObjectByName(name);bones[name]=b?.quaternion.toArray()
    }
    return {bones}
  },{action,time,offset})
  await page.screenshot({path:out+'/'+name+'.png'})
  qa.views.push({name,action,time,...pose})
}
qa.cacheAtEnd=await page.evaluate(()=>({unchanged:window.cacheUnchanged(),sharedDisposals:window.sharedDisposals}))
qa.errors=errors
await writeFile(out+'/qa.json',JSON.stringify(qa,null,2))
console.log(JSON.stringify(qa,null,2))
const badSupport=['idle','walk','special'].some(a=>{const s=qa[a+'Support'];return !Number.isFinite(s.maxXYZ)||s.maxXYZ>.0015||s.maxYawDegrees>.2||!Number.isFinite(s.maxPlaneNormalRadians)||s.maxPlaneNormalRadians>.0035||s.minimumY<-.002})
const badOwnership=[qa.idle,...qa.walk,...qa.special,...qa.remount].some(({ownership:o})=>
  !o.ownScene||!o.ownNodes||!o.ownSkeletons||!o.ownBones||!o.sharedGeometry||!o.sharedTextures||!o.cacheUnchanged||o.sharedDisposals.length)
const badRelease=qa.remount.some(x=>x.boneTextures!==x.skeletons||x.boneTextures===0||x.boneTextureDisposals.some(n=>n!==1)||!x.skeletonTexturesCleared||!x.mixerUncached||!x.cacheUnchanged||x.sharedDisposals.length)
const badAnimation=[...qa.animation,...qa.remount.flatMap(x=>x.animation)].some(x=>!x.sameRoot||!x.playing||!x.clipAdvanced||x.mixerSeconds<=0||x.maxBonePoseDelta<1e-7)
if(errors.length||badSupport||badOwnership||badRelease||badAnimation||!qa.cacheAtEnd.unchanged||qa.cacheAtEnd.sharedDisposals.length||qa.buttons.some(x=>x.actual!==x.expected)||!qa.cardSections.source.includes('膺文曰仁，腹文曰信')||!qa.cardSections.inferred.includes('设计')||qa.specialReturn!=='idle'||qa.remount.some(x=>!x.removed||x.disposed<qa.idle.meshes*2||x.nodes!==qa.idle.nodes||x.roots!==1||x.invalid.length)||qa.idle.meshes!==qa.idle.outlines||[qa.idle,...qa.walk,...qa.special].some(x=>x.invalid.length||x.breastLegInfluence>.001)||qa.audio.invalid||qa.audio.rms<=0||qa.audio.callPeakRms<=0||!qa.narrationStopped||qa.narration.error||qa.cancelledCalls)process.exitCode=1
await browser.close()
