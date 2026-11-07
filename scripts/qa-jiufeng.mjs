import {chromium} from 'playwright-core'
import {writeFile} from 'node:fs/promises'
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']}),page=await browser.newPage({viewport:{width:1440,height:900}}),logs=[]
page.on('pageerror',e=>logs.push({type:'pageerror',text:String(e)}));page.on('console',m=>{if(['error','warning'].includes(m.type()))logs.push({type:m.type(),text:m.text()})})
await page.goto('http://localhost:5215/?beast=jiufeng');await page.waitForTimeout(1400)
async function select(beast,action='idle'){
 await page.evaluate(async([beast,action])=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));useApp.getState().select(beast);useApp.getState().setAction(action)},[beast,action]);await page.waitForTimeout(550)
}
async function snapshot(){return page.evaluate(async()=>{
 const {_roots}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/node_modules/.vite/deps/@react-three_fiber.js')),scene=_roots.get(document.querySelector('canvas')).store.getState().scene,root=scene.getObjectByName('jiufeng_torso'),bones=[],holders=[],humans=[],geometry=new Set()
 scene.updateMatrixWorld(true)
 let torsos=0,meshes=0,outlines=0,wings=0,feet=0,mounts=0,chains=0,invalid=0,negative=0,cpuVertices=0
 scene.traverse(o=>{if(o.name==='jiufeng_torso')torsos++})
 root.traverse(o=>{
  if(/^jiufeng_human_\d$/.test(o.name))humans.push(o.uuid)
  if(/^jiufeng_holder_\d$/.test(o.name))holders.push({name:o.name,children:o.children.length})
  if(o.isBone){bones.push(o.uuid);if(/^human_mount_\d$/.test(o.name))mounts++;if(/^neck_\d_0$/.test(o.name))chains++;if(/^wing_[lr]_1$/.test(o.name))wings++;if(/^foot_[lr]$/.test(o.name))feet++}
  if(!o.matrixWorld.elements.every(Number.isFinite))invalid++
  if(o.isMesh){
   if(o.userData.inkOutline){outlines++;return}meshes++
   if(o.scale.x<=0||o.scale.y<=0||o.scale.z<=0)negative++
   if(!geometry.has(o.geometry)){
    geometry.add(o.geometry);const n=o.geometry.attributes.normal
    for(let i=0;i<n.count;i++)if(!Number.isFinite(n.getX(i)+n.getY(i)+n.getZ(i)))invalid++
   }
   if(o.isSkinnedMesh)o.skeleton.update()
   const p=o.position.clone()
   for(let i=0;i<o.geometry.attributes.position.count;i++){o.getVertexPosition(i,p).applyMatrix4(o.matrixWorld);cpuVertices++;if(!Number.isFinite(p.x+p.y+p.z))invalid++}
  }
 })
 return {torsos,humans:humans.length,uniqueHumans:new Set(humans).size,holders,mounts,chains,wings,feet,bones:bones.length,uniqueBones:new Set(bones).size,meshes,outlines,invalid,negative,cpuVertices}
})}
const remounts=[await snapshot()]
for(const other of ['gudiao','qitu','kaiming','qingniao','min_bird','jingwei']){await select(other);await select('jiufeng');remounts.push(await snapshot())}
const support=[]
for(const action of ['idle','walk','special']){
 await select('jiufeng','idle');await page.waitForTimeout(250)
 await page.evaluate(async action=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));useApp.getState().setAction(action)},action);await page.waitForTimeout(320)
 support.push(await page.evaluate(async action=>{
  const {_roots}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/node_modules/.vite/deps/@react-three_fiber.js')),state=_roots.get(document.querySelector('canvas')).store.getState(),root=state.scene.getObjectByName('jiufeng_torso'),meshes=[]
  root.traverse(o=>{if(o.isSkinnedMesh&&!o.userData.inkOutline&&o.geometry.index.count/3>30000)meshes.push(o)})
  const mesh=meshes[0],feet=['l','r'].map(s=>root.getObjectByName(`foot_${s}`)),mounts=Array.from({length:9},(_,i)=>root.getObjectByName(`human_mount_${i}`)),firstQuats=mounts.map(b=>b.quaternion.clone()),movements=mounts.map(()=>0),frames=[]
  state.scene.updateMatrixWorld(true);mesh.skeleton.update()
  const candidates=[[],[]]
  for(let i=0;i<mesh.geometry.attributes.position.count;i++){
   const p=mesh.position.clone();mesh.getVertexPosition(i,p).applyMatrix4(mesh.matrixWorld);root.worldToLocal(p)
   if(p.y<.02&&Math.abs(p.x)>.06)candidates[p.x>0?0:1].push({i,p})
  }
  const indices=candidates.map(rows=>{
   rows.sort((a,b)=>a.p.y-b.p.y);const low=rows[0]
   const far=rows.filter(r=>r.p.y<low.p.y+.012).sort((a,b)=>b.p.distanceToSquared(low.p)-a.p.distanceToSquared(low.p))[0]
   return [low.i,far.i]
  })
  let invalid=0,maxMountOffset=0
  for(let f=0;f<155;f++){
   await new Promise(requestAnimationFrame);state.scene.updateMatrixWorld(true);mesh.skeleton.update()
   const soles=indices.map(pair=>pair.map(i=>{const p=mesh.position.clone();mesh.getVertexPosition(i,p).applyMatrix4(mesh.matrixWorld);if(!Number.isFinite(p.x+p.y+p.z))invalid++;return p}))
   const directions=soles.map(([a,b])=>b.clone().sub(a).normalize().toArray())
   for(let i=0;i<9;i++){
    movements[i]=Math.max(movements[i],mounts[i].quaternion.angleTo(firstQuats[i]))
    const head=root.getObjectByName(`jiufeng_human_${i}`),p=head.getWorldPosition(head.position.clone());mounts[i].worldToLocal(p);maxMountOffset=Math.max(maxMountOffset,p.length())
   }
   frames.push({feet:feet.map(b=>b.getWorldPosition(b.position.clone()).toArray()),soles:soles.map(([a])=>a.toArray()),directions,rootPosition:root.parent.position.toArray(),rootYaw:root.parent.rotation.y})
  }
  const floor=Math.min(...frames.flatMap(f=>f.feet.map(p=>p[1])));let segment=[],segments=[]
  for(const f of frames){if(action!=='walk'||f.feet.every(p=>Math.abs(p[1]-floor)<.0001))segment.push(f);else if(segment.length){segments.push(segment);segment=[]}}
  if(segment.length)segments.push(segment)
  const planted=segments.filter(s=>s.length>=3).map(s=>{
   let maxDisplacement3D=0,maxDirectionAngle=0;const axisRange=[0,0,0]
   for(const f of s)for(let foot=0;foot<2;foot++){
    const d=f.soles[foot].map((v,j)=>v-s[0].soles[foot][j]);maxDisplacement3D=Math.max(maxDisplacement3D,Math.hypot(...d));d.forEach((v,j)=>axisRange[j]=Math.max(axisRange[j],Math.abs(v)))
    const a=f.directions[foot],b=s[0].directions[foot],dot=a.reduce((sum,v,j)=>sum+v*b[j],0);maxDirectionAngle=Math.max(maxDirectionAngle,Math.acos(Math.max(-1,Math.min(1,dot))))
   }
   return {frames:s.length,maxDisplacement3D,maxDirectionAngle,axisRange,soleMinY:Math.min(...s.flatMap(f=>f.soles.map(p=>p[1]))),soleMaxY:Math.max(...s.flatMap(f=>f.soles.map(p=>p[1])))}
  })
  return {action,frames:frames.length,indices,invalid,maxMountOffset,movements,planted,rootStart:frames[0].rootPosition,rootEnd:frames.at(-1).rootPosition,yawStart:frames[0].rootYaw,yawEnd:frames.at(-1).rootYaw}
 },action))
}
await page.locator('.story-btn').click();await page.waitForTimeout(1100)
const narration=await page.evaluate(async()=>{const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')),el=audio.narrationEl;return {src:el?.getAttribute('src'),duration:el?.duration,currentTime:el?.currentTime,paused:el?.paused,error:el?.error,context:audio.context?.state}})
const narrationLayout=await page.locator('.story-caption').evaluate(el=>({collapsed:!el.open,height:el.getBoundingClientRect().height,bottom:el.getBoundingClientRect().bottom}))
if(!narrationLayout.collapsed||narrationLayout.height>80)throw Error('Narration should start compact')
await page.screenshot({path:'/tmp/shanhai-check/jiufeng-parent-jiufeng-narration.png'})
await page.locator('.story-caption summary').click()
if(!await page.locator('.story-caption p').isVisible())throw Error('Transcript did not expand')
await page.screenshot({path:'/tmp/shanhai-check/jiufeng-parent-transcript-expanded.png'})
await page.locator('.story-caption summary').click()
await page.getByRole('button',{name:'停止评书解说',exact:true}).click()
await page.evaluate(async()=>{
 const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')),{useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts')),ctx=audio.context,original=audio.jiufengCall.bind(audio),make=ctx.createOscillator.bind(ctx)
 window.jiufengAudio={calls:0,oscillators:[]}
 audio.jiufengCall=()=>{window.jiufengAudio.calls++;ctx.createOscillator=(...args)=>{const osc=make(...args);window.jiufengAudio.oscillators.push(osc);return osc};try{original()}finally{ctx.createOscillator=make}}
 window.jiufengAnalyser=ctx.createAnalyser();audio.sfx.connect(window.jiufengAnalyser);useApp.getState().setAction('idle')
});await page.waitForTimeout(300)
await page.evaluate(async()=>{const {useApp}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts'));window.jiufengApp=useApp;useApp.getState().setAction('special')})
const call=await page.evaluate(async()=>{
 let maxRms=0;const a=window.jiufengAnalyser,buffer=new Float32Array(a.fftSize)
 for(let i=0;i<115;i++){await new Promise(requestAnimationFrame);a.getFloatTimeDomainData(buffer);maxRms=Math.max(maxRms,Math.sqrt(buffer.reduce((s,v)=>s+v*v,0)/buffer.length))}
 const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'));audio.sfx.disconnect(a)
 return {calls:window.jiufengAudio.calls,oscillators:window.jiufengAudio.oscillators.length,maxRms,narrationStopped:!audio.narrationEl||audio.narrationEl.paused}
})
await page.waitForFunction(()=>window.jiufengApp.getState().action==='idle',null,{timeout:20000})
const returnAction=await page.evaluate(()=>window.jiufengApp.getState().action)
const result={strictRemountCycles:6,remounts,support,narration,narrationLayout,call,specialReturnsTo:returnAction,logs};await writeFile('/tmp/shanhai-check/jiufeng-parent-browser-qa.json',JSON.stringify(result,null,2))
console.log(JSON.stringify({remounts:remounts.length,counts:remounts.map(r=>[r.humans,r.bones,r.meshes,r.outlines,r.invalid]),support:support.map(s=>({action:s.action,planted:s.planted,movements:s.movements,maxMountOffset:s.maxMountOffset})),narration,call,specialReturnsTo:returnAction,logs}));await browser.close()
if(remounts.some(r=>r.torsos!==1||r.humans!==9||r.uniqueHumans!==9||r.holders.length!==9||r.holders.some(h=>h.children!==1)||r.mounts!==9||r.chains!==9||r.wings!==2||r.feet!==2||r.bones!==55||r.uniqueBones!==55||r.meshes!==20||r.outlines!==20||r.invalid||r.negative)||support.some(s=>s.invalid||s.maxMountOffset>.00001||s.movements.some(m=>m<.001)||!s.planted.length||s.planted.some(p=>p.maxDisplacement3D>.002||p.maxDirectionAngle>.005))||!(narration.currentTime>.2)||narration.duration<80||narration.paused||narration.error||call.calls!==1||call.oscillators!==9||call.maxRms<.0001||!call.narrationStopped||returnAction!=='idle'||logs.some(l=>['error','pageerror'].includes(l.type)))throw Error('Strict remount/world support/audio QA failure')
