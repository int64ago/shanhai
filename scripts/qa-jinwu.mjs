import {chromium} from 'playwright-core'
import {writeFile} from 'node:fs/promises'
const b=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const p=await b.newPage({viewport:{width:1440,height:900}}),errors=[]
p.on('pageerror',e=>errors.push(String(e)));p.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
await p.addInitScript(()=>{window.__scenes=[];window.__THREE_DEVTOOLS__=new EventTarget();window.__THREE_DEVTOOLS__.addEventListener('observe',e=>{if(e.detail.isScene)window.__scenes.push(e.detail)})})
await p.goto('http://localhost:5215/?beast=jinwu');await p.waitForFunction(()=>window.__scenes[0]?.getObjectByName('jinwu_scene'))
await p.evaluate(async()=>{
 window.moduleUrl=path=>{const e=performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===path);if(!e)throw Error('Missing actual Vite module '+path);return e.name}
 window.app=(await import(window.moduleUrl('/src/app/store.ts'))).useApp;window.app.getState().setQuality('high',true)
 const {AnimationMixer}=await import(window.moduleUrl('/node_modules/.vite/deps/three.js'));const update=AnimationMixer.prototype.update
 AnimationMixer.prototype.update=function(dt){if(this.getRoot().name==='jinwu_scene')window.mixer=this;return update.call(this,dt)}
})
await p.waitForFunction(()=>window.mixer);await p.waitForTimeout(700)
const inspect=()=>p.evaluate(()=>{
 const scene=window.__scenes[0],root=scene.getObjectByName('jinwu_scene');scene.updateMatrixWorld(true)
 let nodes=0,meshes=0,outlines=0;const invalid=[],footMin=[Infinity,Infinity]
 root.traverse(o=>{nodes++;if(o.userData.inkOutline)outlines++;if(!o.isMesh)return;for(const [name,a] of Object.entries(o.geometry.attributes))for(const v of a.array)if(!Number.isFinite(v))invalid.push(name);if(o.skeleton){o.skeleton.update();for(const x of o.skeleton.boneMatrices)if(!Number.isFinite(x))invalid.push('matrix')};if(o.isSkinnedMesh&&!o.userData.inkOutline){meshes++;const v=o.position.clone();for(let i=0;i<o.geometry.getAttribute('position').count;i++){o.getVertexPosition(i,v);o.localToWorld(v);root.worldToLocal(v);if(![v.x,v.y,v.z].every(Number.isFinite))invalid.push('deformed');if(v.y<.13&&Math.abs(v.x)>.05)footMin[v.x>0?0:1]=Math.min(footMin[v.x>0?0:1],v.y)}}})
 return {nodes,meshes,outlines,invalid,footMin,roots:scene.children.filter(o=>o.getObjectByName('jinwu_scene')).length}
})
const q={idle:await inspect(),walk:[],special:[],remount:[]}
for(const a of ['walk','special']){await p.evaluate(a=>window.app.getState().setAction(a),a);for(let i=0;i<8;i++){await p.waitForTimeout(a==='walk'?280:500);q[a].push(await inspect())}}
await p.evaluate(()=>window.app.getState().setAction('idle'));await p.waitForTimeout(100);await p.evaluate(()=>window.app.getState().setAction('special'));await p.waitForFunction(()=>window.app.getState().action==='idle',null,{timeout:20000})
q.specialReturn=await p.evaluate(()=>window.app.getState().action)
for(let i=0;i<3;i++){await p.evaluate(()=>window.app.getState().select('jingwei'));await p.waitForTimeout(650);const removed=await p.evaluate(()=>!window.__scenes[0].getObjectByName('jinwu_scene'));await p.evaluate(()=>window.app.getState().select('jinwu'));await p.waitForFunction(()=>window.__scenes[0].getObjectByName('jinwu_scene'));await p.waitForTimeout(500);q.remount.push({removed,...await inspect()})}
await p.evaluate(()=>{window.state=window.__scenes[0].__r3f.root.getState();window.state.setFrameloop('never')})
await p.evaluate(()=>{
 const root=window.state.scene.getObjectByName('jinwu_scene'),candidates=[[],[]];window.state.scene.updateMatrixWorld(true)
 root.traverse(o=>{if(!o.isSkinnedMesh||o.userData.inkOutline)return;o.skeleton.update();const v=o.position.clone();for(let i=0;i<o.geometry.getAttribute('position').count;i++){o.getVertexPosition(i,v);o.localToWorld(v);root.worldToLocal(v);if(v.y<.004&&Math.abs(v.x)>.05)candidates[v.x>0?0:1].push({o,i,rest:v.toArray()})}})
 window.pawCounts=candidates.map(x=>x.length)
 window.paws=candidates.map(list=>{if(list.length<3)throw Error('Missing sole candidates');const first=list[0];const far=list.reduce((a,x)=>Math.hypot(x.rest[0]-first.rest[0],x.rest[2]-first.rest[2])>Math.hypot(a.rest[0]-first.rest[0],a.rest[2]-first.rest[2])?x:a);const a=far.rest.map((v,i)=>v-first.rest[i]);const area=x=>{const b=x.rest.map((v,i)=>v-first.rest[i]);return Math.hypot(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])};const third=list.reduce((best,x)=>area(x)>area(best)?x:best);if(area(third)<1e-10)throw Error('Collinear sole triangle');return [first,far,third]})
})
for(const action of ['idle','walk','special']){
 await p.evaluate(action=>window.app.getState().setAction(action),action);await p.waitForTimeout(100)
 q[action+'Support']=await p.evaluate(action=>{
  const s=window.state,root=s.scene.getObjectByName('jinwu_scene'),m=window.mixer,clip=m._actions.find(a=>a.getClip().name===(action==='special'?'alert':action))
  for(const a of m._actions)if(a!==clip)a.stop();clip.reset().setEffectiveWeight(1).play()
  const anchors=[null,null],segments=[],offsets=[0,.5],names=['left','right'];let now=s.clock.elapsedTime
  const render=s.gl.render;s.gl.render=()=>{}
  for(let frame=0;frame<(action==='walk'?384:252);frame++){
   now+=1/60;s.advance(now,true);s.scene.updateMatrixWorld(true);root.traverse(o=>{if(o.skeleton)o.skeleton.update()})
   for(let foot=0;foot<2;foot++){
    if(frame<20)continue
    const rawPhase=(clip.time/clip.getClip().duration+offsets[foot])%1
    const phase=rawPhase<1e-6||rawPhase>1-1e-6?0:rawPhase,planted=action!=='walk'||phase<.70
    const pts=window.paws[foot].map(({o,i})=>{const v=o.position.clone();o.getVertexPosition(i,v);o.localToWorld(v);return v.toArray()})
    if(pts.some(point=>point.some(v=>!Number.isFinite(v))))throw Error('Non-finite actual sole vertex')
    const heading=Math.atan2(pts[1][0]-pts[0][0],pts[1][2]-pts[0][2])
    if(planted){if(!anchors[foot])anchors[foot]={foot:names[foot],beginPhase:phase,first:pts,heading,frames:0,maxXYZ:0,maxXZ:0,maxY:0,maxYawDegrees:0};const a=anchors[foot];a.frames++;for(let i=0;i<pts.length;i++){a.maxXYZ=Math.max(a.maxXYZ,Math.hypot(...pts[i].map((v,k)=>v-a.first[i][k])));a.maxXZ=Math.max(a.maxXZ,Math.hypot(pts[i][0]-a.first[i][0],pts[i][2]-a.first[i][2]));a.maxY=Math.max(a.maxY,Math.abs(pts[i][1]-a.first[i][1]))}const delta=heading-a.heading;a.maxYawDegrees=Math.max(a.maxYawDegrees,Math.abs(Math.atan2(Math.sin(delta),Math.cos(delta)))*180/Math.PI)}
    else if(anchors[foot]){segments.push(anchors[foot]);anchors[foot]=null}
   }
  }
  for(const a of anchors)if(a)segments.push(a);s.gl.render=render
  return {method:'Actual useFrame at 60Hz; three deformed sole vertices per foot over full world-space support phases',candidates:window.pawCounts,maxXYZ:Math.max(...segments.map(x=>x.maxXYZ)),maxXZ:Math.max(...segments.map(x=>x.maxXZ)),maxY:Math.max(...segments.map(x=>x.maxY)),maxYawDegrees:Math.max(...segments.map(x=>x.maxYawDegrees)),segments:segments.map(({first,heading,...x})=>x)}
 },action)
}
await p.evaluate(()=>{window.state.setFrameloop('always');window.app.getState().setAction('idle')})
q.audio=await p.evaluate(async()=>{
 const c=new AudioContext(),buf=await c.decodeAudioData(await(await fetch('/audio/narration/jinwu.mp3')).arrayBuffer());let sum=0,invalid=0;const a=buf.getChannelData(0);for(const x of a){sum+=x*x;if(!Number.isFinite(x))invalid++}
 const e=(await import(window.moduleUrl('/src/systems/audio/AudioEngine.ts'))).audio;await e.unlock()
 const analyser=e.context.createAnalyser();analyser.fftSize=2048;e.sfx.connect(analyser);e.jinwuCall()
 let callPeakRms=0;const data=new Float32Array(analyser.fftSize)
 for(let i=0;i<8;i++){await new Promise(r=>setTimeout(r,90));analyser.getFloatTimeDomainData(data);callPeakRms=Math.max(callPeakRms,Math.sqrt(data.reduce((sum,x)=>sum+x*x,0)/data.length))}
 e.sfx.disconnect(analyser);await c.close()
 return {duration:buf.duration,sampleRate:buf.sampleRate,channels:buf.numberOfChannels,rms:Math.sqrt(sum/a.length),invalid,callPeakRms,contextState:e.context.state,call:'actual invocation and live SFX bus measurement'}
})

if(['idle','walk','special'].some(a=>!Number.isFinite(q[a+'Support'].maxXYZ)||q[a+'Support'].maxXYZ>.0015))throw Error('Sole XYZ failed')
await p.locator('.story-btn').click()
await p.evaluate(async()=>{window.jinwuAudio=(await import(window.moduleUrl('/src/systems/audio/AudioEngine.ts'))).audio})
await p.waitForFunction(()=>window.jinwuAudio.narrationEl?.currentTime>.2&&!window.jinwuAudio.narrationEl.paused)
q.actualNarration=await p.evaluate(()=>{const e=window.jinwuAudio.narrationEl;return {duration:e.duration,currentTime:e.currentTime,paused:e.paused,error:e.error?.message??null}})
if(q.actualNarration.error||q.actualNarration.duration<60)throw Error('Actual narration failed')
await p.screenshot({path:'/tmp/shanhai-check/jinwu-parent-narration.png'})
await p.getByRole('button',{name:'停止评书解说',exact:true}).click()
q.narrationStopped=await p.evaluate(()=>!window.jinwuAudio.narrationEl||window.jinwuAudio.narrationEl.paused)
if(!q.narrationStopped)throw Error('Narration did not stop')
if([q.idle,...q.remount].some(x=>x.nodes!==23||x.meshes!==1||x.outlines!==1||x.roots!==1))throw Error('Jinwu counts changed')
q.errors=errors;await writeFile('/tmp/shanhai-check/jinwu-parent-qa.json',JSON.stringify(q,null,2));console.log(JSON.stringify(q,null,2))
if(errors.length||q.specialReturn!=='idle'||q.remount.some(x=>!x.removed||x.roots!==1||x.invalid.length||x.nodes!==q.idle.nodes)||[q.idle,...q.walk,...q.special].some(x=>x.invalid.length)||['idle','walk','special'].some(a=>q[a+'Support'].maxXZ>.0015||q[a+'Support'].maxY>.0015||q[a+'Support'].maxYawDegrees>.2)||q.audio.invalid||q.audio.rms<=0||q.audio.callPeakRms<=0||q.audio.contextState!=='running')process.exitCode=1
await b.close()
