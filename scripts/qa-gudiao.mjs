import {chromium} from 'playwright-core'
import {writeFile} from 'node:fs/promises'
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']}),page=await browser.newPage({viewport:{width:1440,height:900}}),logs=[]
page.on('pageerror',e=>logs.push({type:'pageerror',text:String(e)}));page.on('console',m=>{if(['error','warning'].includes(m.type()))logs.push({type:m.type(),text:m.text()})})
await page.goto('http://localhost:5215/?beast=gudiao');await page.waitForTimeout(1300)
const remounts=[]
for(const [beast,action] of [['gudiao','idle'],['gudiao','walk'],['gudiao','special'],['qitu','idle'],['gudiao','idle'],['qingniao','idle'],['gudiao','special'],['min_bird','idle'],['gudiao','walk']]){
 await page.evaluate(async([beast,action])=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));useApp.getState().select(beast);useApp.getState().setAction(action)},[beast,action]);await page.waitForTimeout(450)
 if(beast!=='gudiao')continue
 remounts.push(await page.evaluate(async()=>{
  const {_roots}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/node_modules/.vite/deps/@react-three_fiber.js')),scene=_roots.get(document.querySelector('canvas')).store.getState().scene,root=scene.getObjectByName('gudiao_individual'),bones=[],skeletons=new Set()
  let individuals=0,heads=0,wings=0,legs=0,horns=0,meshes=0,outlines=0,invalid=0,negative=0
  scene.traverse(o=>{if(o.name==='gudiao_individual')individuals++})
  root.traverse(o=>{
   if(o.isBone){bones.push(o.uuid);if(o.name==='head')heads++;if(/^wing_[lr]_1$/.test(o.name))wings++;if(/^foot_[lr]$/.test(o.name))legs++}
   if(!o.matrixWorld.elements.every(Number.isFinite))invalid++
   if(o.isMesh){
    if(o.userData.inkOutline)outlines++;else if(o.isSkinnedMesh){meshes++;skeletons.add(o.skeleton);if(o.geometry.index.count/3<2000)horns++}
    if(o.scale.x<=0||o.scale.y<=0||o.scale.z<=0)negative++
    const n=o.geometry.attributes.normal;for(let i=0;i<n.count;i++)if(!Number.isFinite(n.getX(i)+n.getY(i)+n.getZ(i)))invalid++
   }
  })
  return {individuals,heads,wings,legs,horns,meshes,skeletons:skeletons.size,bones:bones.length,uniqueBones:new Set(bones).size,outlines,invalid,negative}
 }))
}
const support=[]
for(const action of ['idle','walk','special']){
 await page.evaluate(async()=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));useApp.getState().setAction('idle')});await page.waitForTimeout(250)
 await page.evaluate(async action=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));useApp.getState().setAction(action)},action);await page.waitForTimeout(300)
 support.push(await page.evaluate(async action=>{
  const {_roots}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/node_modules/.vite/deps/@react-three_fiber.js')),state=_roots.get(document.querySelector('canvas')).store.getState(),root=state.scene.getObjectByName('gudiao_individual'),frames=[],bone=root.getObjectByName('head')
  const horn=[];root.traverse(o=>{if(o.isSkinnedMesh&&!o.userData.inkOutline&&o.geometry.index.count/3<2000)horn.push(o)})
  const body=[];root.traverse(o=>{if(o.isSkinnedMesh&&!o.userData.inkOutline&&o.geometry.index.count/3>2000)body.push(o)})
  const mesh=body[0];state.scene.updateMatrixWorld(true);mesh.skeleton.update()
  const soleIndices=[1,-1].flatMap(sign=>{
   let lowest=Infinity;const candidates=[]
   for(let i=0;i<mesh.geometry.attributes.position.count;i++){
    const p=mesh.position.clone();mesh.getVertexPosition(i,p).applyMatrix4(mesh.matrixWorld);root.worldToLocal(p)
    if(p.x*sign>.06){lowest=Math.min(lowest,p.y);candidates.push({index:i,p:p.clone()})}
   }
   const low=candidates.filter(c=>c.p.y<lowest+.003),first=low[0]
   const second=low.reduce((a,b)=>b.p.distanceToSquared(first.p)>a.p.distanceToSquared(first.p)?b:a)
   const axis=second.p.clone().sub(first.p)
   const third=low.reduce((a,b)=>axis.clone().cross(b.p.clone().sub(first.p)).lengthSq()>axis.clone().cross(a.p.clone().sub(first.p)).lengthSq()?b:a)
   if(axis.clone().cross(third.p.clone().sub(first.p)).lengthSq()<1e-10)throw Error('Missing noncollinear sole markers')
   return [first.index,second.index,third.index]
  })
  const soleFrames=[]
  const initial=bone.quaternion.clone();let headMotion=0,invalid=0,hornRootRest=null,maxHornRootDrift=0
  for(let i=0;i<145;i++){
   await new Promise(requestAnimationFrame);state.scene.updateMatrixWorld(true)
   frames.push(['l','r'].map(s=>{const b=root.getObjectByName(`foot_${s}`);return b.getWorldPosition(b.position.clone()).toArray()}))
   mesh.skeleton.update();soleFrames.push(soleIndices.map(index=>{const p=mesh.position.clone();mesh.getVertexPosition(index,p).applyMatrix4(mesh.matrixWorld);if(!Number.isFinite(p.x+p.y+p.z))invalid++;return p.toArray()}))
   headMotion=Math.max(headMotion,bone.quaternion.angleTo(initial))
   for(const mesh of horn){
    mesh.skeleton.update();const p=mesh.position.clone();mesh.getVertexPosition(0,p).applyMatrix4(mesh.matrixWorld);bone.worldToLocal(p)
    if(!Number.isFinite(p.x+p.y+p.z))invalid++
    if(!hornRootRest)hornRootRest=p.clone();maxHornRootDrift=Math.max(maxHornRootDrift,p.distanceTo(hornRootRest))
   }
  }
  const floor=Math.min(...frames.flatMap(f=>f.map(p=>p[1])));let segment=[],segments=[]
  for(const f of frames){if(action!=='walk'||f.every(p=>Math.abs(p[1]-floor)<.0001))segment.push(f);else if(segment.length){segments.push(segment);segment=[]}}
  if(segment.length)segments.push(segment)
  return {action,frames:frames.length,floor,headMotion,maxHornRootDrift,invalid,soleVertexIndices:soleIndices,planted:segments.filter(s=>s.length>=3).map(s=>{
   const soles=s.map(f=>soleFrames[frames.indexOf(f)])
   const direction=(f,offset)=>{const a=mesh.position.clone().fromArray(f[offset]),b=mesh.position.clone().fromArray(f[offset+1]),c=mesh.position.clone().fromArray(f[offset+2]);return [b.clone().sub(a).normalize(),b.clone().sub(a).cross(c.clone().sub(a)).normalize()]}
   const initial=[direction(soles[0],0),direction(soles[0],3)]
   const maxSoleRotation=Math.max(...soles.flatMap(f=>[0,1].flatMap(side=>direction(f,side*3).map((v,k)=>v.angleTo(initial[side][k])))))
   return {frames:s.length,maxSoleRotation,maxDrift:Math.max(...s.flatMap(f=>f.map((p,i)=>Math.hypot(p[0]-s[0][i][0],p[2]-s[0][i][2])))),maxSoleDrift:Math.max(...soles.flatMap(f=>f.map((p,i)=>Math.hypot(p[0]-soles[0][i][0],p[2]-soles[0][i][2]))))}
  })}
 },action))
}
await page.locator('.story-btn').click();await page.waitForTimeout(1100)
const narration=await page.evaluate(async()=>{const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')),el=audio.narrationEl;return {src:el?.getAttribute('src'),duration:el?.duration,currentTime:el?.currentTime,paused:el?.paused,error:el?.error,context:audio.context?.state}})
await page.screenshot({path:'/tmp/shanhai-check/gudiao-parent-gudiao-narration.png'});await page.getByRole('button',{name:'停止评书解说',exact:true}).click()
await page.evaluate(async()=>{
 const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')),{useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts')),ctx=audio.context,original=audio.gudiaoCry.bind(audio)
 window.gudiaoCryOscillators=[];window.gudiaoCryCalls=0
 const make=ctx.createOscillator.bind(ctx)
 audio.gudiaoCry=()=>{window.gudiaoCryCalls++;ctx.createOscillator=(...args)=>{const osc=make(...args);window.gudiaoCryOscillators.push(osc);return osc};try{original()}finally{ctx.createOscillator=make}}
 window.gudiaoAnalyser=ctx.createAnalyser();window.gudiaoAnalyser.fftSize=2048;audio.sfx.connect(window.gudiaoAnalyser)
 useApp.getState().setAction('idle')
});await page.waitForTimeout(300)
await page.evaluate(async()=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));window.gudiaoApp=useApp;useApp.getState().setAction('special')})
const cry=await page.evaluate(async()=>{
 let maxRms=0;const analyser=window.gudiaoAnalyser,buf=new Float32Array(analyser.fftSize)
 for(let i=0;i<130;i++){await new Promise(requestAnimationFrame);analyser.getFloatTimeDomainData(buf);maxRms=Math.max(maxRms,Math.sqrt(buf.reduce((sum,v)=>sum+v*v,0)/buf.length))}
 const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'));audio.sfx.disconnect(analyser)
 return {calls:window.gudiaoCryCalls,oscillators:window.gudiaoCryOscillators.length,types:window.gudiaoCryOscillators.map(o=>o.type),maxRms,narrationStopped:!audio.narrationEl||audio.narrationEl.paused}
})
await page.waitForFunction(()=>window.gudiaoApp.getState().action==='idle',null,{timeout:20000})
const returnAction=await page.evaluate(()=>window.gudiaoApp.getState().action)
const result={remounts,support,narration,cry,specialReturnsTo:returnAction,logs};await writeFile('/tmp/shanhai-check/gudiao-parent-browser-qa.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));await browser.close()
if(remounts.some(r=>r.individuals!==1||r.heads!==1||r.wings!==2||r.legs!==2||r.horns!==1||r.meshes!==2||r.skeletons!==2||r.bones!==19||r.uniqueBones!==19||r.outlines!==2||r.invalid||r.negative)||support.some(s=>s.invalid||s.headMotion<.001||s.maxHornRootDrift>.00001||!s.planted.length||s.planted.some(p=>p.maxDrift>.002||p.maxSoleDrift>.002||p.maxSoleRotation>.03))||narration.paused||narration.error||narration.currentTime<=0||narration.duration<80||cry.oscillators!==6||cry.calls!==1||cry.maxRms<.0001||!cry.narrationStopped||returnAction!=='idle'||logs.some(l=>['error','pageerror'].includes(l.type)))throw Error('Browser QA failure')
