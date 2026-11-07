import {chromium} from 'playwright-core'
import {writeFile} from 'node:fs/promises'
const b=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const p=await b.newPage({viewport:{width:1440,height:900}}),errors=[]
p.on('pageerror',e=>errors.push(String(e)));p.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
await p.addInitScript(()=>{window.__scenes=[];window.__THREE_DEVTOOLS__=new EventTarget();window.__THREE_DEVTOOLS__.addEventListener('observe',e=>{if(e.detail.isScene)window.__scenes.push(e.detail)})})
await p.goto('http://localhost:5215/?beast=screen_peng');await p.waitForFunction(()=>window.__scenes[0]?.getObjectByName('screen_peng_scene'))
await p.evaluate(async()=>{window.app=(await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'))).useApp;window.app.getState().setQuality('high',true);const {AnimationMixer}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/node_modules/.vite/deps/three.js'));const update=AnimationMixer.prototype.update;AnimationMixer.prototype.update=function(dt){if(this.getRoot().name==='screen_peng_scene')window.mixer=this;return update.call(this,dt)}})
await p.waitForFunction(()=>window.mixer);await p.waitForTimeout(700)
const inspect=()=>p.evaluate(()=>{
 const scene=window.__scenes[0],root=scene.getObjectByName('screen_peng_scene');window.__scenes[0].updateMatrixWorld(true)
 let nodes=0,meshes=0,outlines=0;const invalid=[],footMin=[Infinity,Infinity,Infinity,Infinity]
 root.traverse(o=>{nodes++;if(o.userData.inkOutline)outlines++;if(!o.isMesh)return;for(const [name,a] of Object.entries(o.geometry.attributes))for(const v of a.array)if(!Number.isFinite(v))invalid.push(name);if(o.skeleton){o.skeleton.update();for(const x of o.skeleton.boneMatrices)if(!Number.isFinite(x))invalid.push('matrix')};if(o.isSkinnedMesh&&!o.userData.inkOutline){meshes++;const v=o.position.clone();for(let i=0;i<o.geometry.getAttribute('position').count;i++){o.getVertexPosition(i,v);o.localToWorld(v);root.worldToLocal(v);if(![v.x,v.y,v.z].every(Number.isFinite))invalid.push('deformed');if(v.y<.14){const j=(v.z>0?0:2)+(v.x>0?0:1);footMin[j]=Math.min(footMin[j],v.y)}}}})
 const heads=['head_l','head_r'].map(n=>{const bone=root.getObjectByName(n);const v=root.position.clone();bone.getWorldPosition(v);root.worldToLocal(v);return v.toArray()})
 return {nodes,meshes,outlines,invalid,footMin,heads,roots:scene.children.filter(o=>o.getObjectByName('screen_peng_scene')).length}
})
const q={idle:await inspect(),walk:[],special:[],remount:[]}
for(const a of ['walk','special']){await p.evaluate(a=>window.app.getState().setAction(a),a);for(let i=0;i<8;i++){await p.waitForTimeout(a==='walk'?280:500);q[a].push(await inspect())}}
await p.evaluate(()=>window.app.getState().setAction('idle'));await p.waitForTimeout(100);await p.evaluate(()=>window.app.getState().setAction('special'));await p.waitForTimeout(5500)
q.specialReturn=await p.evaluate(()=>window.app.getState().action)
for(let i=0;i<3;i++){await p.evaluate(()=>window.app.getState().select('zheng'));await p.waitForTimeout(650);const removed=await p.evaluate(()=>!window.__scenes[0].getObjectByName('screen_peng_scene'));await p.evaluate(()=>window.app.getState().select('screen_peng'));await p.waitForFunction(()=>window.__scenes[0].getObjectByName('screen_peng_scene'));await p.waitForTimeout(250);q.remount.push({removed,...await inspect()})}
await p.evaluate(()=>{window.state=window.__scenes[0].__r3f.root.getState();window.state.setFrameloop('never')})
// Capture actual deformed paw-pad vertices in beast coordinates while at rest.
await p.evaluate(()=>{
 const root=window.state.scene.getObjectByName('screen_peng_scene'),candidates=[[],[],[],[]];window.__scenes[0].updateMatrixWorld(true)
 root.traverse(o=>{if(!o.isSkinnedMesh||o.userData.inkOutline)return;o.skeleton.update();const v=o.position.clone();for(let i=0;i<o.geometry.getAttribute('position').count;i++){o.getVertexPosition(i,v);o.localToWorld(v);root.worldToLocal(v);if(v.y<.004&&Math.abs(v.x)>.04)candidates[(v.z>0?0:2)+(v.x>0?0:1)].push({o,i,rest:v.toArray()})}})
 window.pawCounts=candidates.map(x=>x.length)
 window.paws=candidates.map(list=>{if(list.length<3)throw Error('Missing paw sole candidates');const first=list[0];const far=list.reduce((a,x)=>Math.hypot(x.rest[0]-first.rest[0],x.rest[2]-first.rest[2])>Math.hypot(a.rest[0]-first.rest[0],a.rest[2]-first.rest[2])?x:a);const a=far.rest.map((v,i)=>v-first.rest[i]);const area=x=>{const b=x.rest.map((v,i)=>v-first.rest[i]);return Math.hypot(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])};const third=list.reduce((best,x)=>area(x)>area(best)?x:best);if(area(third)<1e-10)throw Error('Collinear sole triangle');return [first,far,third]})
})
for(const action of ['idle','walk','special']){
 await p.evaluate(action=>window.app.getState().setAction(action),action);await p.waitForTimeout(100)
 q[action+'Support']=await p.evaluate(action=>{
  const s=window.state,root=s.scene.getObjectByName('screen_peng_scene'),m=window.mixer,clip=m._actions.find(a=>a.getClip().name===(action==='special'?'alert':action))
  for(const a of m._actions)if(a!==clip)a.stop();clip.reset().setEffectiveWeight(1).play()
  const anchors=[null,null,null,null],segments=[],offsets=[.25,.75,0,.5],names=['front_l','front_r','back_l','back_r'];let now=s.clock.elapsedTime
  const render=s.gl.render;s.gl.render=()=>{}
  for(let frame=0;frame<(action==='walk'?432:252);frame++){
   now+=1/60;s.advance(now,true);s.scene.updateMatrixWorld(true);root.traverse(o=>{if(o.skeleton)o.skeleton.update()})
   for(let foot=0;foot<4;foot++){
    if(frame<20)continue
    const phase=(clip.time/1.8+offsets[foot])%1,planted=action!=='walk'||phase<.78
    const pts=window.paws[foot].map(({o,i})=>{const v=o.position.clone();o.getVertexPosition(i,v);o.localToWorld(v);return v.toArray()})
    const heading=Math.atan2(pts[1][0]-pts[0][0],pts[1][2]-pts[0][2])
    if(planted){if(!anchors[foot])anchors[foot]={foot:names[foot],beginPhase:phase,first:pts,heading,frames:0,maxXYZ:0,maxXZ:0,maxYawDegrees:0,maxNormalDegrees:0};const a=anchors[foot];a.frames++;for(let i=0;i<pts.length;i++)a.maxXYZ=Math.max(a.maxXYZ,Math.hypot(...pts[i].map((v,k)=>v-a.first[i][k])));const normal=p=>{const a=p[1].map((v,k)=>v-p[0][k]),b=p[2].map((v,k)=>v-p[0][k]);const n=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],l=Math.hypot(...n);return n.map(v=>v/l)};const n=normal(pts),n0=normal(a.first);a.maxNormalDegrees=Math.max(a.maxNormalDegrees,Math.acos(Math.max(-1,Math.min(1,n.reduce((s,v,k)=>s+v*n0[k],0))))*180/Math.PI);for(let i=0;i<pts.length;i++)a.maxXZ=Math.max(a.maxXZ,Math.hypot(pts[i][0]-a.first[i][0],pts[i][2]-a.first[i][2]));const delta=heading-a.heading;a.maxYawDegrees=Math.max(a.maxYawDegrees,Math.abs(Math.atan2(Math.sin(delta),Math.cos(delta)))*180/Math.PI)}
    else if(anchors[foot]){segments.push(anchors[foot]);anchors[foot]=null}
   }
  }
  for(const a of anchors)if(a)segments.push(a);s.gl.render=render
  return {method:'Actual useFrame frames at 60Hz; three deformed sole vertices per paw; full world XYZ support displacement, paw heading and sole triangle normal',candidates:window.pawCounts,maxXYZ:Math.max(...segments.map(x=>x.maxXYZ)),maxNormalDegrees:Math.max(...segments.map(x=>x.maxNormalDegrees)),maxXZ:Math.max(...segments.map(x=>x.maxXZ)),maxYawDegrees:Math.max(...segments.map(x=>x.maxYawDegrees)),segments:segments.map(({first,heading,...x})=>x)}
 },action)
}
await p.evaluate(()=>{window.state.setFrameloop('always');window.app.getState().setAction('idle')})
q.audio=await p.evaluate(async()=>{const c=new AudioContext(),buf=await c.decodeAudioData(await(await fetch('/audio/narration/screen_peng.mp3')).arrayBuffer());let sum=0,invalid=0;const a=buf.getChannelData(0);for(const x of a){sum+=x*x;if(!Number.isFinite(x))invalid++}const e=(await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'))).audio;await e.unlock();e.screenPengCall();await c.close();return {duration:buf.duration,sampleRate:buf.sampleRate,channels:buf.numberOfChannels,rms:Math.sqrt(sum/a.length),invalid,call:'actual invocation without error'}})

if(['idle','walk','special'].some(a=>!Number.isFinite(q[a+'Support'].maxXYZ)||q[a+'Support'].maxXYZ>.0015||!Number.isFinite(q[a+'Support'].maxNormalDegrees)||q[a+'Support'].maxNormalDegrees>.2))throw Error('Sole XYZ or orientation failed')
await p.locator('.story-btn').click();await p.waitForTimeout(1400)
q.actualNarration=await p.evaluate(async()=>{const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'));const e=audio.narrationEl;return {duration:e.duration,currentTime:e.currentTime,error:e.error,context:audio.context.state}})
if(q.actualNarration.currentTime<=0||q.actualNarration.error||q.actualNarration.duration<60)throw Error('Actual narration failed')
await p.evaluate(()=>window.app.getState().stopNarration())
if([q.idle,...q.remount].some(x=>x.nodes!==48||x.meshes!==5||x.outlines!==5||x.roots!==1))throw Error('ScreenPeng remount counts changed')
q.errors=errors
await writeFile('/tmp/shanhai-check/screen-peng-parent-qa.json',JSON.stringify(q,null,2));console.log(JSON.stringify(q,null,2))
if(errors.length||q.specialReturn!=='idle'||q.remount.some(x=>!x.removed||x.roots!==1||x.invalid.length)||[q.idle,...q.walk,...q.special].some(x=>x.invalid.length)||q.walkSupport.maxXZ>.0015||q.walkSupport.maxYawDegrees>.2||q.specialSupport.maxXZ>.0015||q.specialSupport.maxYawDegrees>.2||q.idleSupport.maxXZ>.0015||q.idleSupport.maxYawDegrees>.2||q.audio.invalid||q.audio.rms<=0)process.exitCode=1
await b.close()
