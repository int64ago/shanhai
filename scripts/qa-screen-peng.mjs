// Actual StrictMode cache isolation, remount animation, full-stance sole motion,
// independent neck deformation, multiview render, narration and SFX checks.
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { chromium } from 'playwright-core'
const [base='http://localhost:5234',out='/tmp/screen-peng-qa']=process.argv.slice(2)
await mkdir(out,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const assetBytes=await readFile(new URL('../public/models/screen_peng/body.glb',import.meta.url))
const q={asset:{bytes:assetBytes.length,sha256:createHash('sha256').update(assetBytes).digest('hex')},assetLoads:[],remounts:[],contact:{},images:[],errors:[]}
const responseJobs=[]
page.on('pageerror',e=>q.errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')q.errors.push(m.text())})
page.on('response',r=>{
  if(r.status()>=400)q.errors.push(`${r.status()} ${r.url()}`)
  if(new URL(r.url()).pathname==='/models/screen_peng/body.glb')responseJobs.push(r.body().then(bytes=>q.assetLoads.push({url:r.url(),bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')})))
})
try {
  let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei')})
  await page.goto(`${base}/?beast=jingwei&action=idle`);await ready
  await page.evaluate(async()=>{
    const url=path=>performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname===path)?.name
    const {useGLTF}=await import(url('/node_modules/.vite/deps/@react-three_drei.js'))
    const {AnimationMixer}=await import(url('/node_modules/.vite/deps/three.js'))
    const fiber=await import(url('/node_modules/.vite/deps/@react-three_fiber.js'))
    const {useApp}=await import(url('/src/app/store.ts'))
    const update=AnimationMixer.prototype.update
    AnimationMixer.prototype.update=function(dt){if(this.getRoot().name==='screen_peng_scene')window.peng.mixer=this;return update.call(this,dt)}
    useGLTF.preload('/models/screen_peng/body.glb')
    let source
    for(;;){try{source=useGLTF('/models/screen_peng/body.glb').scene;break}catch(pending){if(!pending?.then)throw pending;await pending}}
    const resources=new Map()
    source.traverse(n=>{if(n.geometry)resources.set(n.geometry,{uuid:n.geometry.uuid,type:'geometry',disposals:0});if(n.skeleton)resources.set(n.skeleton,{uuid:n.skeleton.uuid,type:'skeleton',disposals:0});for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){resources.set(m,{uuid:m.uuid,type:'material',disposals:0});for(const value of Object.values(m))if(value?.isTexture)resources.set(value,{uuid:value.uuid,type:'texture',disposals:0})}})
    for(const [resource,row]of resources)if(resource.addEventListener)resource.addEventListener('dispose',()=>row.disposals++)
    const hash=array=>{let h=2166136261;for(const byte of new Uint8Array(array.buffer,array.byteOffset,array.byteLength))h=Math.imul(h^byte,16777619);return h>>>0}
    const snapshot=()=>{
      const nodes=[]
      source.traverse(n=>nodes.push({uuid:n.uuid,name:n.name,children:n.children.map(c=>c.uuid),position:n.position.toArray(),quaternion:n.quaternion.toArray(),scale:n.scale.toArray(),outline:!!n.userData.inkOutline,geometry:n.geometry?.uuid,skeleton:n.skeleton?.uuid,boneTexture:n.skeleton?.boneTexture?.uuid,materials:(Array.isArray(n.material)?n.material:n.material?[n.material]:[]).map(m=>({uuid:m.uuid,type:m.type,map:m.map?.uuid,normalMap:m.normalMap?.uuid,color:m.color?.getHexString(),side:m.side,userData:JSON.stringify(m.userData)}))}))
      return JSON.stringify({nodes,geometry:[...resources].filter(([,r])=>r.type==='geometry').map(([g])=>({uuid:g.uuid,index:g.index?hash(g.index.array):null,attributes:Object.fromEntries(Object.entries(g.attributes).map(([k,a])=>[k,hash(a.isInterleavedBufferAttribute?a.data.array:a.array)]))}))})
    }
    window.peng={source,resources,snapshot,before:snapshot(),state:[...fiber._roots.values()][0].store.getState(),useApp}
  })
  const select=async id=>{
    const ready=page.waitForEvent('console',{predicate:m=>m.text().includes(`[beast] ready ${id}`)})
    await page.evaluate(id=>window.peng.useApp.getState().select(id),id);await ready
  }
  await select('screen_peng');await page.waitForFunction(()=>window.peng.mixer)
  await page.waitForTimeout(350)
  q.baseline=await page.evaluate(()=>{
    const root=window.peng.state.scene.getObjectByName('screen_peng_root');let invalid=0,meshes=0,outlines=0,bones=0
    root.traverse(n=>{if(![...n.position,...n.quaternion,...n.scale,...n.matrixWorld.elements].every(Number.isFinite))invalid++;if(n.isBone)bones++;if(!n.isMesh)return;if(n.userData.inkOutline){outlines++;return}meshes++;for(const attr of Object.values(n.geometry.attributes))if(!Array.from(attr.array??attr.data.array).every(Number.isFinite))invalid++;if(n.skeleton&&!Array.from(n.skeleton.boneMatrices).every(Number.isFinite))invalid++})
    return {invalid,meshes,outlines,bones,cacheUnchanged:window.peng.before===window.peng.snapshot(),actions:window.peng.mixer._actions.map(a=>a.getClip().name)}
  })
  await Promise.all(responseJobs)
  assert(q.assetLoads.length>0&&q.assetLoads.every(a=>a.bytes===q.asset.bytes&&a.sha256===q.asset.sha256),'actual browser GLB response matches candidate bytes')
  assert.equal(q.baseline.invalid,0);assert.equal(q.baseline.meshes,5);assert.equal(q.baseline.outlines,5);assert.equal(q.baseline.bones,39);assert(q.baseline.cacheUnchanged)
  // Three actual unmount/remount cycles: exact resource disposal, new IDs,
  // active mixer-owned actions advancing AND CPU-skinned vertices moving.
  const seenSkeletons=new Set(),seenTextures=new Set()
  for(let cycle=0;cycle<3;cycle++){
    await page.waitForFunction(()=>{
      const skeletons=new Set();window.peng.state.scene.getObjectByName('screen_peng_root').traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton)})
      return [...skeletons].every(s=>s.boneTexture!==null)
    })
    await page.evaluate(()=>{
      const {state,mixer}=window.peng,root=state.scene.getObjectByName('screen_peng_root'),skeletons=new Set(),materials=new Map(),originals=new Map()
      root.traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton);if(n.isMesh){for(const m of Array.isArray(n.material)?n.material:[n.material])materials.set(m,{id:m.uuid,count:0});if(!n.userData.inkOutline)originals.set(n,window.peng.source.getObjectByName(n.name)?.material)}})
      const skeletonRows=new Map([...skeletons].map(s=>[s,{id:s.uuid,count:0}])),textures=new Map([...skeletons].map(s=>[s.boneTexture,{id:s.boneTexture.uuid,count:0}]))
      for(const [s,row]of skeletonRows){const dispose=s.dispose.bind(s);s.dispose=()=>{row.count++;dispose()}}
      for(const [m,row]of materials)m.addEventListener('dispose',()=>row.count++)
      for(const [t,row]of textures)t.addEventListener('dispose',()=>row.count++)
      window.peng.old={root,mixer,materials,textures,skeletonRows,originals}
    })
    await select('jingwei');await page.waitForTimeout(120)
    const disposal=await page.evaluate(()=>{
      const {old}=window.peng
      return {materials:[...old.materials.values()],textures:[...old.textures.values()],skeletons:[...old.skeletonRows.values()],liveTextures:[...old.skeletonRows.keys()].filter(s=>s.boneTexture!==null).length,restored:[...old.originals].every(([n,m])=>n.material===m),outlines:(()=>{let n=0;old.root.traverse(o=>{if(o.userData.inkOutline)n++});return n})(),mixerActions:old.mixer._actions.length,cacheUnchanged:window.peng.before===window.peng.snapshot(),shared:[...window.peng.resources.values()]}
    })
    assert(disposal.materials.length===10&&disposal.materials.every(r=>r.count===1),'every owned ink/outline material disposed once')
    assert(disposal.textures.every(r=>r.count===1)&&disposal.skeletons.every(r=>r.count===1),'each unique skeleton and bone texture disposed once')
    assert(disposal.restored&&disposal.outlines===0&&disposal.liveTextures===0&&disposal.mixerActions===0&&disposal.cacheUnchanged)
    assert(disposal.shared.every(r=>r.disposals===0),'no shared resource disposed')
    await select('screen_peng');await page.waitForTimeout(150)
    const before=await page.evaluate(()=>{
      const {state,mixer}=window.peng,root=state.scene.getObjectByName('screen_peng_root');state.scene.updateMatrixWorld(true)
      const meshes=[],probes={head_l:[],head_r:[],neck_l:[],neck_r:[]}
      root.traverse(n=>{if(n.isSkinnedMesh&&!n.userData.inkOutline){n.skeleton.update();meshes.push(n)}})
      for(const mesh of meshes){const a=mesh.geometry.attributes;for(let i=0;i<a.position.count;i++){
        const weights=[a.skinWeight.getX(i),a.skinWeight.getY(i),a.skinWeight.getZ(i),a.skinWeight.getW(i)],indices=[a.skinIndex.getX(i),a.skinIndex.getY(i),a.skinIndex.getZ(i),a.skinIndex.getW(i)],slot=weights.indexOf(Math.max(...weights))
        const bone=mesh.skeleton.bones[indices[slot]]?.name
        const key=Object.keys(probes).find(key=>bone===key||bone?.startsWith(key+'_'))
        if(key&&probes[key].length<8&&weights[slot]>.5)probes[key].push({mesh,i})
      }}
      window.peng.probes=probes
      window.peng.probePositions=()=>{
        state.scene.updateMatrixWorld(true);root.traverse(n=>{if(n.skeleton)n.skeleton.update()})
        return Object.fromEntries(Object.entries(probes).map(([key,list])=>[key,list.map(({mesh,i})=>{const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);root.worldToLocal(p);return p.toArray()})]))
      }
      return {rootId:root.uuid,mixerOwned:mixer.getRoot()===root.getObjectByName('screen_peng_scene'),skeletons:[...new Set(meshes.map(n=>n.skeleton.uuid))],textures:[...new Set(meshes.map(n=>n.skeleton.boneTexture?.uuid))],registered:mixer._actions.every(a=>mixer.existingAction(a.getClip())===a),actions:mixer._actions.length,probeCounts:Object.fromEntries(Object.entries(probes).map(([k,v])=>[k,v.length]))}
    })
    const clips=[]
    for(const action of ['idle','walk','special']){
      await page.evaluate(a=>window.peng.useApp.getState().setAction(a),action);await page.waitForTimeout(70)
      const first=await page.evaluate(a=>({time:window.peng.mixer._actions.find(c=>c.getClip().name===(a==='special'?'alert':a)).time,vertices:window.peng.probePositions()}),action)
      await page.waitForTimeout(350)
      const after=await page.evaluate(a=>({time:window.peng.mixer._actions.find(c=>c.getClip().name===(a==='special'?'alert':a)).time,vertices:window.peng.probePositions()}),action)
      const movement=Object.fromEntries(Object.entries(first.vertices).map(([key,vertices])=>[key,Math.max(...vertices.map((p,i)=>Math.hypot(...p.map((v,k)=>after.vertices[key][i][k]-v))))]))
      assert(after.time>first.time+.02&&Object.values(movement).every(v=>v>1e-7),`${action}: actual clip and both head/neck CPU vertices move after remount`)
      clips.push({action,beforeTime:first.time,afterTime:after.time,cpuMovement:movement})
    }
    assert(before.mixerOwned&&before.registered&&before.actions===3&&Object.values(before.probeCounts).every(n=>n===8),'fresh mixer-owned actions and actual skin probes')
    for(const id of before.skeletons){assert(!seenSkeletons.has(id)&&!disposal.skeletons.some(r=>r.id===id));seenSkeletons.add(id)}
    for(const id of before.textures){assert(id&&!seenTextures.has(id)&&!disposal.textures.some(r=>r.id===id));seenTextures.add(id)}
    q.remounts.push({cycle,disposal,before,clips})
    await page.evaluate(()=>window.peng.useApp.getState().setAction('idle'));await page.waitForTimeout(250)
  }
  // Select three noncollinear, genuinely CPU-skinned rigid sole vertices for
  // each paw. All measurements below run actual useFrame including contacts.
  await page.evaluate(()=>{
    const {state}=window.peng,root=state.scene.getObjectByName('screen_peng_root');state.setFrameloop('never');state.scene.updateMatrixWorld(true)
    const lists=Object.fromEntries(['front_l','front_r','back_l','back_r'].map(n=>[n,[]]))
    root.traverse(mesh=>{if(!mesh.isSkinnedMesh||mesh.userData.inkOutline)return;mesh.skeleton.update();const g=mesh.geometry.attributes,p=root.position.clone();for(let i=0;i<g.position.count;i++){
      const weights=[g.skinWeight.getX(i),g.skinWeight.getY(i),g.skinWeight.getZ(i),g.skinWeight.getW(i)],indices=[g.skinIndex.getX(i),g.skinIndex.getY(i),g.skinIndex.getZ(i),g.skinIndex.getW(i)],slot=weights.indexOf(Math.max(...weights))
      const bone=mesh.skeleton.bones[indices[slot]]?.name;if(!bone?.endsWith('_foot')||weights[slot]<.999)continue
      mesh.getVertexPosition(i,p);mesh.localToWorld(p);if(Math.abs(p.y)>.004)continue
      const name=bone.replace(/_foot$/,'');lists[name]?.push({mesh,i,p:p.toArray()})
    }})
    const paws={}
    for(const [name,candidates]of Object.entries(lists)){
      const minY=Math.min(...candidates.map(v=>v.p[1])),list=candidates.filter(v=>v.p[1]<minY+.0001)
      if(list.length<3)throw Error(`${name} missing sole vertices`)
      const a=list[0],v=root.position.clone().fromArray(a.p)
      const b=list.reduce((best,p)=>v.distanceToSquared(v.clone().fromArray(p.p))>v.distanceToSquared(v.clone().fromArray(best.p))?p:best)
      const edge=v.clone().fromArray(b.p).sub(v),area=p=>v.clone().fromArray(p.p).sub(v).cross(edge).lengthSq()
      const c=list.reduce((best,p)=>area(p)>area(best)?p:best)
      if(area(c)<1e-10)throw Error('Collinear sole triangle')
      paws[name]=[a,b,c]
    }
    window.peng.paws=paws;window.peng.now=state.clock.elapsedTime
    window.peng.solePositions=()=>{
      state.scene.updateMatrixWorld(true);root.traverse(n=>{if(n.skeleton)n.skeleton.update()})
      return Object.fromEntries(Object.entries(paws).map(([name,vertices])=>[name,vertices.map(({mesh,i})=>{const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);return p.toArray()})]))
    }
  })
  async function contact(action,frames){
    const switchBefore=await page.evaluate(()=>window.peng.solePositions())
    await page.evaluate(a=>window.peng.useApp.getState().setAction(a),action);await page.waitForTimeout(70)
    const effectAfter=await page.evaluate(()=>window.peng.solePositions())
    const result=await page.evaluate(({action,frames})=>{
      const w=window.peng,{state,paws}=w,root=state.scene.getObjectByName('screen_peng_root'),anchors={},segments=[],offsets={front_l:.25,front_r:.75,back_l:0,back_r:.5}
      const render=state.gl.render;state.gl.render=()=>{}
      const normal=points=>{const [a,b,c]=points.map(p=>root.position.clone().fromArray(p));return b.sub(a).cross(c.sub(a)).normalize()}
      let phaseZeroSamples=0,invalid=0,zeroFramePositions
      for(let frame=0;frame<=frames;frame++){
        if(frame){w.now+=1/120;state.advance(w.now,true)}else state.advance(w.now,true)
        state.scene.updateMatrixWorld(true);root.traverse(n=>{if(n.skeleton)n.skeleton.update()})
        if(frame===0)zeroFramePositions=w.solePositions()
        const phase=w.mixer._actions.find(a=>a.getClip().name==='walk').time/1.8%1
        if(phase<1e-7||phase>1-1e-7)phaseZeroSamples++
        for(const [name,vertices]of Object.entries(paws)){
          const planted=!root.userData.walkingContact||(phase+offsets[name])%1<.78
          const points=vertices.map(({mesh,i})=>{const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);if(![...p].every(Number.isFinite))invalid++;return p.toArray()})
          const n=normal(points),direction=root.position.clone().fromArray(points[1]).sub(root.position.clone().fromArray(points[0])).normalize()
          if(!planted){if(anchors[name]){segments.push(anchors[name]);delete anchors[name]}continue}
          const a=anchors[name]??={name,first:points,normal:n.toArray(),direction:direction.toArray(),frames:0,beginPhase:(phase+offsets[name])%1,maxXYZ:0,maxDirectionDegrees:0,maxNormalDegrees:0,maxGroundTiltDegrees:0,minY:Infinity,maxY:-Infinity}
          a.frames++;for(let i=0;i<points.length;i++){a.maxXYZ=Math.max(a.maxXYZ,Math.hypot(...points[i].map((v,k)=>v-a.first[i][k])));a.minY=Math.min(a.minY,points[i][1]);a.maxY=Math.max(a.maxY,points[i][1])}
          const degrees=(v,b)=>Math.acos(Math.max(-1,Math.min(1,v.dot(root.position.clone().fromArray(b)))))*180/Math.PI
          a.maxGroundTiltDegrees=Math.max(a.maxGroundTiltDegrees,Math.acos(Math.min(1,Math.abs(n.y)))*180/Math.PI)
          a.maxNormalDegrees=Math.max(a.maxNormalDegrees,degrees(n,a.normal));a.maxDirectionDegrees=Math.max(a.maxDirectionDegrees,degrees(direction,a.direction));anchors[name]=a
        }
      }
      segments.push(...Object.values(anchors));state.gl.render=render
      return {action,frames:frames+1,hz:120,phaseZeroSamples,invalid,zeroFramePositions,maxXYZ:Math.max(...segments.map(s=>s.maxXYZ)),maxNormalDegrees:Math.max(...segments.map(s=>s.maxNormalDegrees)),maxGroundTiltDegrees:Math.max(...segments.map(s=>s.maxGroundTiltDegrees)),maxDirectionDegrees:Math.max(...segments.map(s=>s.maxDirectionDegrees)),segments:segments.map(({first,normal,direction,...s})=>s)}
    },{action,frames})
    const drift=positions=>Object.fromEntries(Object.entries(switchBefore).map(([name,points])=>[name,Math.max(...points.map((p,i)=>Math.hypot(...p.map((v,k)=>positions[name][i][k]-v))))]))
    result.switchEffectJump=drift(effectAfter);result.switchZeroDtJump=drift(result.zeroFramePositions)
    delete result.zeroFramePositions
    result.switchPassed=Object.values(result.switchEffectJump).every(v=>v<.0015)&&Object.values(result.switchZeroDtJump).every(v=>v<.0015)
    return result
  }
  q.contact.idle=await contact('idle',240)
  q.contact.walkStartupAndFullStances=await contact('walk',864)
  q.contact.walkToIdle=await contact('idle',90)
  q.contact.special=await contact('special',240)
  q.contact.specialToWalk=await contact('walk',216)
  q.contact.walkToSpecial=await contact('special',90)
  q.contact.specialToIdle=await contact('idle',90)
  for(const [name,m]of Object.entries(q.contact)){assert.equal(m.invalid,0);assert(m.maxXYZ<.0015,`${name} XYZ drift ${m.maxXYZ}`);assert(m.maxNormalDegrees<.2&&m.maxDirectionDegrees<.2&&m.maxGroundTiltDegrees<.2,`${name} sole direction/normal/absolute ground tilt`);assert(m.switchPassed,`${name}: pre-switch effect/dt=0 sole jump`)}
  assert(q.contact.walkStartupAndFullStances.phaseZeroSamples>=4,'phase zero explicitly included, no trimmed stance intervals')
  // Real runtime multiviews and a full neck-motion sequence, independent of
  // aggregate stats. The script writes images for mandatory human/Read review.
  for(const action of ['idle','walk','special']){
    await page.evaluate(a=>window.peng.useApp.getState().setAction(a),action);await page.waitForTimeout(70)
    for(let frame=0;frame<180;frame++)await page.evaluate(()=>{window.peng.now+=1/120;window.peng.state.advance(window.peng.now,true)})
    const views=action==='idle'?['front','back','side','34']:action==='special'?['front','back','back34','backHigh']:['front','back','side']
    for(const view of views){
      await page.evaluate(view=>{
        const {state}=window.peng,root=state.scene.getObjectByName('screen_peng_root'),center=root.position.clone().add({x:0,y:.72,z:0})
        const offsets={front:[0,.10,1.65],back:[0,.13,-1.65],side:[1.65,.12,0],'34':[1.15,.20,1.25],back34:[1.10,.35,-1.25],backHigh:[0,.90,-1.30]},offset=root.position.clone().fromArray(offsets[view]).applyAxisAngle({x:0,y:1,z:0},root.rotation.y)
        state.camera.position.copy(center).add(offset);state.camera.lookAt(center);state.camera.updateMatrixWorld();state.scene.updateMatrixWorld(true);state.gl.render(state.scene,state.camera)
      },view)
      const file=join(out,`${action}-${view}.png`);await page.screenshot({path:file});q.images.push(file)
    }
  }
  await page.evaluate(()=>window.peng.useApp.getState().setAction('idle'));await page.waitForTimeout(70)
  await page.evaluate(()=>window.peng.useApp.getState().setAction('special'));await page.waitForTimeout(70)
  q.neckMotion=[]
  for(let index=0;index<9;index++){
    const row=await page.evaluate(index=>{
      const {state}=window.peng,root=state.scene.getObjectByName('screen_peng_root'),render=state.gl.render
      state.gl.render=()=>{}
      for(let i=0;i<(index?60:1);i++){window.peng.now+=1/120;state.advance(window.peng.now,true)}
      state.gl.render=render
      const center=root.position.clone().add({x:0,y:.83,z:0}),offset=root.position.clone().set(.75,.50,-1.05).applyAxisAngle({x:0,y:1,z:0},root.rotation.y)
      state.camera.position.copy(center).add(offset);state.camera.lookAt(center);state.camera.updateMatrixWorld();state.scene.updateMatrixWorld(true);state.gl.render(state.scene,state.camera)
      return {time:window.peng.mixer._actions.find(a=>a.getClip().name==='alert').time,vertices:window.peng.probePositions(),rotations:Object.fromEntries(['l','r'].map(side=>[side,['neck_'+side,'neck_'+side+'_mid','neck_'+side+'_tip','head_'+side].map(n=>root.getObjectByName(n).quaternion.toArray())]))}
    },index)
    const file=join(out,`neck-motion-${index}.png`);await page.screenshot({path:file});q.images.push(file);q.neckMotion.push(row)
  }
  q.neckCpuDisplacement=Object.fromEntries(Object.entries(q.neckMotion[0].vertices).map(([key,vertices])=>[key,Math.max(...q.neckMotion.flatMap(row=>vertices.map((p,i)=>Math.hypot(...p.map((v,k)=>row.vertices[key][i][k]-v)))))]))
  assert(Object.values(q.neckCpuDisplacement).every(v=>v>1e-5),'actual CPU-skinned head and neck tissue moves on both independent chains')
  assert(q.neckMotion.some(row=>JSON.stringify(row.rotations.l)!==JSON.stringify(row.rotations.r)),'independent head/neck motion')
  await page.evaluate(()=>{window.peng.state.setFrameloop('always');window.peng.useApp.getState().setAction('idle')});await page.waitForTimeout(400)
  await page.locator('.story-btn').click();await page.waitForTimeout(900)
  q.audio=await page.evaluate(async()=>{
    const url=performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname==='/src/systems/audio/AudioEngine.ts').name
    const {audio}=await import(url);window.peng.audio=audio
    const c=new AudioContext(),buffer=await c.decodeAudioData(await(await fetch('/audio/narration/screen_peng.mp3')).arrayBuffer()),samples=buffer.getChannelData(0)
    let sum=0;for(const value of samples)sum+=value*value
    const playback={time:audio.narrationEl.currentTime,duration:audio.narrationEl.duration,paused:audio.narrationEl.paused,error:audio.narrationEl.error,context:audio.context.state}
    let starts=0;const start=OscillatorNode.prototype.start;OscillatorNode.prototype.start=function(...args){starts++;return start.apply(this,args)}
    const analyser=audio.context.createAnalyser();analyser.fftSize=2048;audio.sfx.connect(analyser)
    audio.screenPengCall();audio.footstep(0,.35);OscillatorNode.prototype.start=start
    await new Promise(r=>setTimeout(r,200));const signal=new Float32Array(2048);analyser.getFloatTimeDomainData(signal);audio.sfx.disconnect(analyser)
    const sfxRms=Math.sqrt(signal.reduce((s,v)=>s+v*v,0)/signal.length)
    window.peng.narration=audio.narrationEl;await c.close()
    return {decoded:{duration:buffer.duration,rate:buffer.sampleRate,channels:buffer.numberOfChannels,rms:Math.sqrt(sum/samples.length)},playback,sfxOscillatorsStarted:starts,sfxRms}
  })
  assert(q.audio.decoded.rms>0&&q.audio.playback.time>0&&!q.audio.playback.paused&&!q.audio.playback.error&&q.audio.sfxOscillatorsStarted>0&&q.audio.sfxRms>0)
  await page.evaluate(()=>window.peng.useApp.getState().stopNarration());await page.waitForTimeout(150)
  q.audio.stopped=await page.evaluate(()=>({paused:window.peng.narration.paused,time:window.peng.narration.currentTime,detached:window.peng.audio.narrationEl===null}))
  assert(q.audio.stopped.paused)
  await page.evaluate(()=>{window.peng.calls=0;const audio=window.peng.audio,call=audio.screenPengCall.bind(audio);audio.screenPengCall=()=>{window.peng.calls++;call()};window.peng.useApp.getState().setAction('special')});await page.waitForTimeout(80)
  await page.evaluate(()=>window.peng.useApp.getState().setAction('idle'));await page.waitForTimeout(1100)
  q.cancelledSpecialCalls=await page.evaluate(()=>window.peng.calls);assert.equal(q.cancelledSpecialCalls,0)
  await page.evaluate(()=>window.peng.useApp.getState().setAction('special'));await page.waitForTimeout(5000)
  q.specialReturn=await page.evaluate(()=>window.peng.useApp.getState().action);assert.equal(q.specialReturn,'idle')
  q.finalCache=await page.evaluate(()=>({unchanged:window.peng.before===window.peng.snapshot(),shared:[...window.peng.resources.values()]}));assert(q.finalCache.unchanged&&q.finalCache.shared.every(r=>r.disposals===0))
  assert.deepEqual(q.errors,[])
  assert.equal(createHash('sha256').update(await readFile(new URL('../public/models/screen_peng/body.glb',import.meta.url))).digest('hex'),q.asset.sha256,'candidate remains byte-locked through capture')
  q.captureAssetSha256=q.asset.sha256
  q.passed=true
} catch(error) {
  q.passed=false;q.failure=String(error);process.exitCode=1
} finally {
  await writeFile(join(out,'qa.json'),JSON.stringify(q,null,2));console.log(JSON.stringify(q,null,2));await browser.close()
}
