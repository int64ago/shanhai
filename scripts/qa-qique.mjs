// Byte-bound real-browser Qique QA: cache before mount, three remounts,
// CPU skinning, complete sole contacts including startup/switches, real audio.
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { chromium } from 'playwright-core'
const [base='http://localhost:5236',out='/tmp/qique-remake/qa',mode='full']=process.argv.slice(2)
const targeted=mode==='contacts'
await mkdir(out,{recursive:true})
const hash=b=>createHash('sha256').update(b).digest('hex'),bytes=await readFile(new URL('../public/models/qique/body.glb',import.meta.url))
const q={scope:targeted?'targeted contacts only':'full lifecycle/contact/audio/multiview',asset:{bytes:bytes.length,sha256:hash(bytes)},loads:[],remounts:[],contact:{},images:[],errors:[]},jobs=[]
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
page.on('pageerror',e=>q.errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')q.errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400)q.errors.push(`${r.status()} ${r.url()}`);if(new URL(r.url()).pathname==='/models/qique/body.glb')jobs.push(r.body().then(b=>q.loads.push({url:r.url(),bytes:b.length,sha256:hash(b)})))})
try {
  let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei')})
  await page.goto(`${base}/?beast=jingwei&action=idle`);await ready
  await page.evaluate(async()=>{
    const url=p=>performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname===p)?.name
    const {useGLTF}=await import(url('/node_modules/.vite/deps/@react-three_drei.js'))
    const {AnimationMixer}=await import(url('/node_modules/.vite/deps/three.js'))
    const fiber=await import(url('/node_modules/.vite/deps/@react-three_fiber.js'))
    const {useApp}=await import(url('/src/app/store.ts'))
    useApp.getState().setQuality('high',true)
    const update=AnimationMixer.prototype.update
    AnimationMixer.prototype.update=function(dt){if(this.getRoot().name==='qique_scene')window.qi.mixer=this;return update.call(this,dt)}
    useGLTF.preload('/models/qique/body.glb');let cached
    for(;;){try{cached=useGLTF('/models/qique/body.glb');break}catch(p){if(!p?.then)throw p;await p}}
    const source=cached.scene,resources=new Map()
    source.traverse(n=>{if(n.geometry)resources.set(n.geometry,{id:n.geometry.uuid,type:'geometry',count:0});if(n.skeleton)resources.set(n.skeleton,{id:n.skeleton.uuid,type:'skeleton',count:0});for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){resources.set(m,{id:m.uuid,type:'material',count:0});for(const v of Object.values(m))if(v?.isTexture)resources.set(v,{id:v.uuid,type:'texture',count:0})}})
    for(const [r,row]of resources)r.addEventListener?.('dispose',()=>row.count++)
    const digest=a=>{let h=2166136261;for(const b of new Uint8Array(a.buffer,a.byteOffset,a.byteLength))h=Math.imul(h^b,16777619);return h>>>0}
    const snapshot=()=>{
      const nodes=[];source.traverse(n=>nodes.push({id:n.uuid,name:n.name,parent:n.parent?.uuid,children:n.children.map(c=>c.uuid),p:n.position.toArray(),q:n.quaternion.toArray(),s:n.scale.toArray(),geometry:n.geometry?.uuid,skeleton:n.skeleton?.uuid,boneTexture:n.skeleton?.boneTexture?.uuid,frustum:n.frustumCulled,outline:!!n.userData.inkOutline,materials:(Array.isArray(n.material)?n.material:n.material?[n.material]:[]).map(m=>({id:m.uuid,type:m.type,map:m.map?.uuid,color:m.color?.getHexString(),side:m.side,data:JSON.stringify(m.userData)}))}))
      return JSON.stringify({nodes,geometry:[...resources].filter(([,r])=>r.type==='geometry').map(([g])=>({id:g.uuid,index:g.index?digest(g.index.array):null,attributes:Object.fromEntries(Object.entries(g.attributes).map(([k,a])=>[k,digest(a.array??a.data.array)]))}))})
    }
    window.qi={source,resources,snapshot,before:snapshot(),state:[...fiber._roots.values()][0].store.getState(),useApp}
  })
  const select=async id=>{const ready=page.waitForEvent('console',{predicate:m=>m.text().includes(`[beast] ready ${id}`)});await page.evaluate(id=>window.qi.useApp.getState().select(id),id);await ready}
  await select('qique');await page.waitForFunction(()=>window.qi.mixer);await page.waitForTimeout(250)
  q.baseline=await page.evaluate(()=>{
    const w=window.qi,root=w.state.scene.getObjectByName('qique_root'),sourceNodes=new Set(),sourceSkels=new Set();w.source.traverse(n=>{sourceNodes.add(n);if(n.skeleton)sourceSkels.add(n.skeleton)})
    let meshes=0,outlines=0,bones=0,invalid=0,owned=true,sharedGeometry=true,sharedTexture=true
    root.traverse(n=>{if(sourceNodes.has(n))owned=false;if(n.isBone)bones++;if(!n.isMesh)return;if(n.userData.inkOutline){outlines++;return}meshes++;if(sourceSkels.has(n.skeleton)||n.skeleton.bones.some(b=>sourceNodes.has(b)))owned=false
      const original=w.source.getObjectByName(n.name);sharedGeometry&&=n.geometry===original.geometry;sharedTexture&&=n.material.uniforms.uMap.value===original.material.map
      for(const a of Object.values(n.geometry.attributes))if(!Array.from(a.array??a.data.array).every(Number.isFinite))invalid++
    })
    return {meshes,outlines,bones,invalid,owned,sharedGeometry,sharedTexture,cacheUnchanged:w.before===w.snapshot(),actions:w.mixer._actions.map(a=>a.getClip().name)}
  })
  await Promise.all(jobs)
  assert(q.loads.length&&q.loads.every(r=>r.bytes===q.asset.bytes&&r.sha256===q.asset.sha256),'actual fetched candidate bytes')
  assert.equal(q.baseline.meshes,4);assert.equal(q.baseline.outlines,4);assert.equal(q.baseline.bones,18)
  assert(q.baseline.owned&&q.baseline.sharedGeometry&&q.baseline.sharedTexture&&q.baseline.cacheUnchanged&&!q.baseline.invalid)
  q.footOwnership=await page.evaluate(()=>{
    const w=window.qi,root=w.state.scene.getObjectByName('qique_root'),rows=[]
    root.updateWorldMatrix(true,true)
    root.traverse(mesh=>{
      if(!mesh.isSkinnedMesh||mesh.userData.inkOutline)return
      const original=w.source.getObjectByName(mesh.name),name=original.material.name
      if(!['qique_skin','qique_claw'].includes(name))return
      const a=mesh.geometry.attributes,count=a.position.count,parent=Array.from({length:count},(_,i)=>i),positions=new Map()
      const find=i=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i]}return i},union=(i,j)=>{parent[find(j)]=find(i)}
      for(let i=0;i<count;i++){
        const key=[a.position.getX(i),a.position.getY(i),a.position.getZ(i)].join(',')
        if(positions.has(key))union(i,positions.get(key));else positions.set(key,i)
      }
      const index=mesh.geometry.index,at=i=>index?index.getX(i):i
      for(let i=0;i<(index?.count??count);i+=3){union(at(i),at(i+1));union(at(i),at(i+2))}
      const components=new Map()
      for(let i=0;i<count;i++){const key=find(i);if(!components.has(key))components.set(key,[]);components.get(key).push(i)}
      mesh.skeleton.update()
      for(const ids of components.values()){
        let x=0;const bones=new Set();let rigid=true
        for(const i of ids){
          const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);root.worldToLocal(p);x+=p.x
          const weights=[a.skinWeight.getX(i),a.skinWeight.getY(i),a.skinWeight.getZ(i),a.skinWeight.getW(i)],indices=[a.skinIndex.getX(i),a.skinIndex.getY(i),a.skinIndex.getZ(i),a.skinIndex.getW(i)]
          rigid&&=Math.max(...weights)>.999
          weights.forEach((v,j)=>{if(v>1e-5)bones.add(mesh.skeleton.bones[indices[j]].name)})
        }
        const side=x>0?'l':'r',names=[...bones]
        rows.push({material:name,vertices:ids.length,meanX:x/ids.length,side,bones:names,rigid,consistent:names.every(n=>n===`foot_${side}`||n===`leg_${side}_upper`||n===`leg_${side}_lower`)})
      }
    });return rows
  })
  assert(q.footOwnership.every(c=>c.consistent),'complete skin/claw component belongs to one foot')
  for(const side of ['l','r']){
    const claws=q.footOwnership.filter(c=>c.material==='qique_claw'&&c.side===side),skin=q.footOwnership.filter(c=>c.material==='qique_skin'&&c.side===side)
    assert(claws.length===5&&claws.every(c=>c.rigid&&c.bones.length===1&&c.bones[0]===`foot_${side}`)&&skin.length===1,'five complete rigid claws and one continuous skin surface per foot')
  }
  const seen=new Set()
  for(let cycle=0;cycle<(targeted?0:3);cycle++){
    await page.evaluate(()=>{
      const w=window.qi,root=w.state.scene.getObjectByName('qique_root'),skels=new Set(),mats=new Map(),originals=new Map()
      root.traverse(n=>{if(n.isSkinnedMesh)skels.add(n.skeleton);if(n.isMesh){for(const m of Array.isArray(n.material)?n.material:[n.material])mats.set(m,{id:m.uuid,count:0});if(!n.userData.inkOutline)originals.set(n,w.source.getObjectByName(n.name).material)}})
      const skeletons=new Map([...skels].map(s=>[s,{id:s.uuid,count:0}])),textures=new Map([...skels].map(s=>[s.boneTexture,{id:s.boneTexture?.uuid,count:0}]))
      for(const [s,row]of skeletons){const dispose=s.dispose.bind(s);s.dispose=()=>{row.count++;dispose()}}
      for(const [m,row]of mats)m.addEventListener('dispose',()=>row.count++)
      for(const [t,row]of textures){if(!t)throw Error('Rendered skeleton has no bone texture');t.addEventListener('dispose',()=>row.count++)}
      w.old={root,mixer:w.mixer,skeletons,textures,mats,originals}
    })
    await select('jingwei');await page.waitForTimeout(80)
    const disposed=await page.evaluate(()=>{
      const w=window.qi,o=w.old;let outlines=0;o.root.traverse(n=>{if(n.userData.inkOutline)outlines++})
      return {root:o.root.uuid,removed:o.root.parent===null,materials:[...o.mats.values()],skeletons:[...o.skeletons.values()],textures:[...o.textures.values()],texturesCleared:[...o.skeletons.keys()].every(s=>s.boneTexture===null),restored:[...o.originals].every(([n,m])=>n.material===m),outlines,actions:o.mixer._actions.length,bindings:o.mixer._bindings.length,cache:w.before===w.snapshot(),shared:[...w.resources.values()]}
    })
    assert(disposed.removed&&disposed.materials.length===8&&disposed.materials.every(r=>r.count===1))
    assert(disposed.skeletons.length===4&&disposed.skeletons.every(r=>r.count===1)&&disposed.textures.every(r=>r.count===1))
    assert(disposed.texturesCleared&&disposed.restored&&!disposed.outlines&&!disposed.actions&&!disposed.bindings&&disposed.cache&&disposed.shared.every(r=>r.count===0))
    await select('qique');await page.waitForTimeout(200)
    const fresh=await page.evaluate(()=>{
      const w=window.qi,root=w.state.scene.getObjectByName('qique_root'),skels=new Set(),textures=new Set(),probes={head:[],neck:[],wing_l:[],wing_r:[]}
      root.traverse(mesh=>{if(!mesh.isSkinnedMesh||mesh.userData.inkOutline)return;skels.add(mesh.skeleton.uuid);textures.add(mesh.skeleton.boneTexture?.uuid);const a=mesh.geometry.attributes
        for(let i=0;i<a.position.count;i++){const weights=[a.skinWeight.getX(i),a.skinWeight.getY(i),a.skinWeight.getZ(i),a.skinWeight.getW(i)],indices=[a.skinIndex.getX(i),a.skinIndex.getY(i),a.skinIndex.getZ(i),a.skinIndex.getW(i)],slot=weights.indexOf(Math.max(...weights)),bone=mesh.skeleton.bones[indices[slot]]?.name,key=Object.keys(probes).find(k=>bone===k||bone?.startsWith(k+'_'));if(key&&weights[slot]>.5&&probes[key].length<8)probes[key].push({mesh,i})}
      })
      w.cpu=()=>{w.state.scene.updateMatrixWorld(true);root.traverse(n=>{if(n.skeleton)n.skeleton.update()});return Object.fromEntries(Object.entries(probes).map(([k,list])=>[k,list.map(({mesh,i})=>{const p=root.position.clone();mesh.getVertexPosition(i,p);mesh.localToWorld(p);root.worldToLocal(p);return p.toArray()})]))}
      return {root:root.uuid,skeletons:[...skels],textures:[...textures],probeCounts:Object.fromEntries(Object.entries(probes).map(([k,v])=>[k,v.length])),registered:w.mixer.getRoot()===root.getObjectByName('qique_scene')&&w.mixer._actions.length===3&&w.mixer._actions.every(a=>w.mixer.existingAction(a.getClip())===a)}
    })
    assert(fresh.registered&&Object.values(fresh.probeCounts).every(n=>n===8))
    for(const id of [fresh.root,...fresh.skeletons,...fresh.textures]){assert(id&&!seen.has(id));seen.add(id)}
    assert(!fresh.skeletons.some(id=>disposed.skeletons.some(r=>r.id===id))&&!fresh.textures.some(id=>disposed.textures.some(r=>r.id===id)))
    const clips=[]
    for(const action of ['idle','walk','special']){
      await page.evaluate(a=>window.qi.useApp.getState().setAction(a),action);await page.waitForTimeout(70)
      const sample=()=>page.evaluate(a=>({time:window.qi.mixer._actions.find(c=>c.getClip().name===(a==='special'?'alert':a)).time,vertices:window.qi.cpu()}),action)
      const before=await sample();await page.waitForTimeout(260);const after=await sample()
      const motion=Object.fromEntries(Object.entries(before.vertices).map(([key,vertices])=>[key,Math.max(...vertices.map((p,i)=>Math.hypot(...p.map((v,k)=>after.vertices[key][i][k]-v))))]))
      assert(after.time>before.time+.02&&Object.values(motion).every(v=>v>1e-7),`${action} actual clip/CPU motion after remount`);clips.push({action,beforeTime:before.time,afterTime:after.time,motion})
    }
    q.remounts.push({cycle,disposed,fresh,clips});await page.evaluate(()=>window.qi.useApp.getState().setAction('idle'));await page.waitForTimeout(220)
  }
  await page.evaluate(()=>{
    const w=window.qi,{state}=w,root=state.scene.getObjectByName('qique_root');state.setFrameloop('never');state.scene.updateMatrixWorld(true)
    const candidates={l:[],r:[]},digits={l:[[],[],[],[],[]],r:[[],[],[],[],[]]},debug=[]
    root.traverse(mesh=>{if(!mesh.isSkinnedMesh||mesh.userData.inkOutline)return;mesh.skeleton.update();const a=mesh.geometry.attributes,original=w.source.getObjectByName(mesh.name)
      for(let i=0;i<a.position.count;i++){
        const weights=[a.skinWeight.getX(i),a.skinWeight.getY(i),a.skinWeight.getZ(i),a.skinWeight.getW(i)],indices=[a.skinIndex.getX(i),a.skinIndex.getY(i),a.skinIndex.getZ(i),a.skinIndex.getW(i)],slot=weights.indexOf(Math.max(...weights)),bone=mesh.skeleton.bones[indices[slot]]?.name
        if(!/^foot_[lr]$/.test(bone)||weights[slot]<.999)continue
        // Quantized storage also folds decode transforms into skin bindings.
        // Select anatomical regions on the actual CPU-skinned rendered clone.
        const side=bone.at(-1),rest=root.position.clone()
        mesh.getVertexPosition(i,rest);mesh.localToWorld(rest);const restWorld=rest.toArray();root.worldToLocal(rest)
        const v={mesh,i,p:rest.toArray(),world:restWorld}
        candidates[side].push(v)
        const x=(side==='l'?1:-1)*.101,pivot=root.position.clone();mesh.skeleton.bones[indices[slot]].getWorldPosition(pivot);root.worldToLocal(pivot)
        // Remove the current rigid stance translation only for assigning the
        // five authored digit regions. Measurement always uses actual world XYZ.
        const px=v.p[0]-(pivot.x-x),pz=v.p[2]-(pivot.z-.145)
        if(original.material.name!=='qique_skin'||pz<.24)continue
        const lengths=[.058,.106,.132,.117,.086],roots=[.202,.218,.226,.222,.210]
        const distances=lengths.map((length,k)=>{const spread=(k-2)*.019,sx=x+spread*.76,sz=roots[k],ex=x+spread*1.90,ez=sz+length,dx=ex-sx,dz=ez-sz,t=Math.max(.35,Math.min(1,((px-sx)*dx+(pz-sz)*dz)/(dx*dx+dz*dz)));return Math.hypot(px-sx-dx*t,pz-sz-dz*t)})
        const d=distances.indexOf(Math.min(...distances));if(distances[d]<.012)digits[side][d].push(v)
      }
    })
    w.soles={};w.toes={};w.candidateCounts={};w.soleAreas={}
    for(const side of ['l','r']){
      w.toes[side]=digits[side].map(list=>{if(!list.length)throw Error('Missing actual digit skin sample '+JSON.stringify({side,counts:digits[side].map(v=>v.length),debug}));return list.reduce((best,p)=>p.p[1]<best.p[1]?p:best)})
      // Use an actual near-ground plantar patch. The very lowest quantized
      // layer can be only an edge; choose the widest noncollinear triangle on
      // a real surface layer within 0.5mm of it. Never reshape the anatomy.
      const lowest=Math.min(...candidates[side].map(v=>v.p[1])),layers=[]
      for(const v of candidates[side].filter(v=>v.p[1]<lowest+.0005).sort((a,b)=>a.p[1]-b.p[1])){
        let layer=layers.find(g=>Math.abs(g[0].p[1]-v.p[1])<.00002)
        if(!layer){layer=[];layers.push(layer)}layer.push(v)
      }
      let best=null
      for(const list of layers){
        if(list.length<3)continue
        const a=list[0],v=root.position.clone().fromArray(a.p),b=list.reduce((best,p)=>v.distanceToSquared(v.clone().fromArray(p.p))>v.distanceToSquared(v.clone().fromArray(best.p))?p:best),edge=v.clone().fromArray(b.p).sub(v),area=p=>v.clone().fromArray(p.p).sub(v).cross(edge).length(),c=list.reduce((best,p)=>area(p)>area(best)?p:best),score=area(c)
        if(score>1e-9&&(!best||score>best.score))best={p:[a,b,c],score}
      }
      if(!best)throw Error('No noncollinear actual plantar surface')
      w.soles[side]=best.p;w.soleAreas[side]=best.score/2;w.candidateCounts[side]=candidates[side].length
      if(w.soleAreas[side]<1e-6)throw Error('Plantar triangle spans less than one square millimetre')
    }
    w.positions=items=>{state.scene.updateMatrixWorld(true);root.traverse(n=>{if(n.skeleton)n.skeleton.update()});return Object.fromEntries(Object.entries(items).map(([side,list])=>[side,list.map(({mesh,i})=>{const v=root.position.clone();mesh.getVertexPosition(i,v);mesh.localToWorld(v);return v.toArray()})]))}
    w.now=state.clock.elapsedTime
  })
  async function contact(action,frames){
    const before=await page.evaluate(()=>{
      const w=window.qi,root=w.state.scene.getObjectByName('qique_root')
      return {positions:w.positions(w.soles),action:w.useApp.getState().action,walkPhase:root.userData.walkPhase,displayTime:w.mixer._actions.find(a=>a.getClip().name==='alert').time,debug:root.userData.contactDebug}
    })
    const pre=before.positions
    await page.evaluate(a=>window.qi.useApp.getState().setAction(a),action);await page.waitForTimeout(70)
    const effect=await page.evaluate(()=>window.qi.positions(window.qi.soles))
    const result=await page.evaluate(({action,frames,before})=>{
      const w=window.qi,{state}=w,root=state.scene.getObjectByName('qique_root'),anchors={},segments=[],render=state.gl.render;state.gl.render=()=>{}
      const normal=p=>{const v=p.map(p=>root.position.clone().fromArray(p));return v[1].sub(v[0]).cross(v[2].sub(v[0])).normalize()},degrees=(a,b)=>Math.acos(Math.max(-1,Math.min(1,a.dot(root.position.clone().fromArray(b)))))*180/Math.PI
      // Masks are declared from the authored schedule, independently of the
      // helper's planted flags. A departing swing remains airborne during the
      // fixed 180ms crossfade; every frame/foot is still sampled, including dt0.
      const scheduled=(a,phase,t,index)=>a==='walk'?((phase+[0,.5][index])%1<=.65+1e-8):a==='special'?(index===1||t<=.95+1e-8||t>=2.8-1e-8):true
      const oldSupport=[0,1].map(i=>scheduled(before.action,before.walkPhase,before.displayTime,i))
      let zero,phaseZeroSamples=0,minY=Infinity,maxLift=0,invalid=0,unplantedGroundFrames=0;const samples=[]
      for(let f=0;f<=frames;f++){
        if(f)w.now+=1/120;state.advance(w.now,true)
        const soles=w.positions(w.soles),toes=w.positions(w.toes),phase=root.userData.walkPhase
        if(!f)zero=soles;if(phase<1e-7||phase>1-1e-7)phaseZeroSamples++
        for(const [index,side]of ['l','r'].entries()){
          const points=soles[side],n=normal(points),direction=root.position.clone().fromArray(points[1]).sub(root.position.clone().fromArray(points[0])).normalize(),display=w.mixer._actions.find(a=>a.getClip().name==='alert').time,
            planted=scheduled(action,phase,display,index)&&(f/120>=.18||oldSupport[index])
          for(const p of [...points,...toes[side]])if(!p.every(Number.isFinite))invalid++
          minY=Math.min(minY,...points.map(p=>p[1]));maxLift=Math.max(maxLift,...points.map(p=>p[1]))
          if(!planted){if(points.every(p=>Math.abs(p[1])<.0001))unplantedGroundFrames++;if(anchors[side]){segments.push(anchors[side]);delete anchors[side]}continue}
          const a=anchors[side]??={side,first:points,toes:toes[side],normal:n.toArray(),direction:direction.toArray(),frames:0,beginFrame:f,beginPhase:phase,maxXYZ:0,maxToeXYZ:0,maxNormal:0,maxDirection:0,maxGroundTilt:0,minY:Infinity,maxY:-Infinity}
          a.frames++;a.endFrame=f;a.endPhase=phase
          for(let i=0;i<3;i++){a.maxXYZ=Math.max(a.maxXYZ,Math.hypot(...points[i].map((v,k)=>v-a.first[i][k])));a.minY=Math.min(a.minY,points[i][1]);a.maxY=Math.max(a.maxY,points[i][1])}
          for(let i=0;i<5;i++)a.maxToeXYZ=Math.max(a.maxToeXYZ,Math.hypot(...toes[side][i].map((v,k)=>v-a.toes[i][k])))
          a.maxNormal=Math.max(a.maxNormal,degrees(n,a.normal));a.maxDirection=Math.max(a.maxDirection,degrees(direction,a.direction));a.maxGroundTilt=Math.max(a.maxGroundTilt,Math.acos(Math.min(1,Math.abs(n.y)))*180/Math.PI);anchors[side]=a
        }
        if(f<=24||f===frames||f%48===0)samples.push({frame:f,phase,planted:[...root.userData.planted],debug:root.userData.contactDebug,soles,toes})
      }
      segments.push(...Object.values(anchors));state.gl.render=render
      return {action,supportMask:'walk: phase offsets [0,.5], 0..0.65 inclusive; special: right full, left 0..0.95 and2.8..4.2 inclusive; idle: both; departing swing retained only through fixed180ms blend, allfeet sampled everyframe',outgoing:before,frames:frames+1,hz:120,phaseZeroSamples,invalid,minY,maxLift,unplantedGroundFrames,zero,samples,candidateCounts:w.candidateCounts,soleAreasMetersSquared:w.soleAreas,soleVertices:Object.fromEntries(Object.entries(w.soles).map(([s,list])=>[s,list.map(v=>({mesh:v.mesh.name,index:v.i,restRoot:v.p,restWorld:v.world}))])),toeVertices:Object.fromEntries(Object.entries(w.toes).map(([s,list])=>[s,list.map(v=>({mesh:v.mesh.name,index:v.i,restRoot:v.p,restWorld:v.world}))])),maxXYZ:Math.max(...segments.map(a=>a.maxXYZ)),maxToeXYZ:Math.max(...segments.map(a=>a.maxToeXYZ)),maxNormal:Math.max(...segments.map(a=>a.maxNormal)),maxDirection:Math.max(...segments.map(a=>a.maxDirection)),maxGroundTilt:Math.max(...segments.map(a=>a.maxGroundTilt)),segments:segments.map(({first,toes,normal,direction,...a})=>a)}
    },{action,frames,before})
    const jumps=p=>Object.fromEntries(Object.entries(pre).map(([side,points])=>[side,Math.max(...points.map((v,i)=>Math.hypot(...v.map((x,k)=>p[side][i][k]-x))))]))
    result.effectJump=jumps(effect);result.zeroDtJump=jumps(result.zero);delete result.zero
    const early=result.samples.filter(s=>s.frame<=24)
    result.positiveDtSteps=early.slice(1).map((s,i)=>({frame:s.frame,seconds:s.frame/120,
      maxXYZ:Math.max(...['l','r'].flatMap(side=>s.soles[side].map((p,j)=>Math.hypot(...p.map((v,k)=>v-early[i].soles[side][j][k])))))}))
    result.maxPositiveDtStep=Math.max(...result.positiveDtSteps.map(s=>s.maxXYZ))
    return result
  }
  q.contact.idle=await contact('idle',240)
  q.contact.idleToWalkStartup=await contact('walk',864)
  q.contact.walkToIdle=await contact('idle',90)
  q.contact.idleToSpecial=await contact('special',180)
  q.contact.specialToWalk=await contact('walk',240)
  q.contact.walkToSpecial=await contact('special',180)
  q.contact.specialToIdle=await contact('idle',90)
  q.contact.fullDisplay=await contact('special',504)
  for(const [name,c]of Object.entries(q.contact)){
    assert(!c.invalid&&c.segments.length&&c.maxXYZ<.0015&&c.maxToeXYZ<.0015,`${name} full stance XYZ ${c.maxXYZ}/${c.maxToeXYZ}`)
    assert(c.maxNormal<.2&&c.maxDirection<.2&&c.maxGroundTilt<.2,`${name} direction/relative normal/absolute tilt`)
    assert(c.minY>-.002,`${name} ground penetration`)
    assert(c.maxPositiveDtStep<.015,`${name} smooth positive-delta landing after zero frame`)
    assert(Object.values(c.effectJump).every(v=>v<.0015)&&Object.values(c.zeroDtJump).every(v=>v<.0015),`${name} switch pre/effect/dt0 jump`)
    assert(c.segments.every(s=>s.minY>-.002&&s.maxY<.002),`${name} anchored sole at actual ground`)
  }
  assert(q.contact.idleToWalkStartup.phaseZeroSamples>=4,'phase zero/start/end included without frame trimming')
  assert(q.contact.fullDisplay.maxLift>.07,'display actually raises a foot')
  // Multiviews use actual useFrame; rendering is the only suppressed operation
  // while stepping. The GLB response hash above applies to all captures here.
  if(!targeted){
  const hidden=await page.addStyleTag({content:'.card,.actions,.scroll-wrap,.controls,.title{visibility:hidden!important}'})
  for(const action of ['idle','walk','special']){
    await page.evaluate(a=>window.qi.useApp.getState().setAction(a),action);await page.waitForTimeout(70)
    await page.evaluate(()=>{const w=window.qi,r=w.state.gl.render;w.state.gl.render=()=>{};for(let i=0;i<180;i++){w.now+=1/120;w.state.advance(w.now,true)}w.state.gl.render=r})
    for(const [view,offset]of [['front',[0,.15,1.75]],['side',[1.75,.15,0]],['back',[0,.2,-1.75]],['34',[1.25,.30,1.25]]]){
      await page.evaluate(offset=>{const w=window.qi,s=w.state,root=s.scene.getObjectByName('qique_root'),center=root.position.clone().add({x:0,y:.46,z:0}),v=root.position.clone().fromArray(offset).applyAxisAngle({x:0,y:1,z:0},root.rotation.y);s.camera.position.copy(center).add(v);s.camera.filmOffset=0;s.camera.updateProjectionMatrix();s.camera.lookAt(center);s.camera.updateMatrixWorld();s.scene.updateMatrixWorld(true);s.gl.render(s.scene,s.camera)},offset)
      const file=join(out,`${action}-${view}.png`);await page.screenshot({path:file});q.images.push({file,assetSha256:q.asset.sha256})
    }
    if(action!=='walk')for(const detail of ['feet','feet-side','wing-root']){
      await page.evaluate(detail=>{
        const w=window.qi,s=w.state,root=s.scene.getObjectByName('qique_root'),center=root.position.clone(),offset=root.position.clone()
        if(detail.startsWith('feet')){
          const left=root.getObjectByName('foot_l'),right=root.getObjectByName('foot_r');left.getWorldPosition(center);right.getWorldPosition(offset);center.add(offset).multiplyScalar(.5)
          offset.set(0,-.025,.10).applyAxisAngle({x:0,y:1,z:0},root.rotation.y);center.add(offset)
          offset.fromArray(detail==='feet'?[.55,.18,.65]:[.82,.10,0])
        }else{offset.set(.10,.55,.12).applyAxisAngle({x:0,y:1,z:0},root.rotation.y);center.add(offset);offset.set(.65,.24,-.65)}
        offset.applyAxisAngle({x:0,y:1,z:0},root.rotation.y);s.camera.position.copy(center).add(offset);s.camera.filmOffset=0;s.camera.updateProjectionMatrix();s.camera.lookAt(center);s.camera.updateMatrixWorld();s.gl.render(s.scene,s.camera)
      },detail)
      const file=join(out,`${action}-${detail}.png`);await page.screenshot({path:file});q.images.push({file,assetSha256:q.asset.sha256})
    }
  }
  await hidden.evaluate(e=>e.remove())
  await page.evaluate(()=>{window.qi.state.setFrameloop('always');window.qi.useApp.getState().setAction('idle')});await page.waitForTimeout(300)
  await page.locator('.story-btn').click();await page.waitForTimeout(700)
  q.audio=await page.evaluate(async()=>{
    const url=performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname==='/src/systems/audio/AudioEngine.ts').name,{audio}=await import(url);window.qi.audio=audio
    const c=new AudioContext(),buffer=await c.decodeAudioData(await(await fetch('/audio/narration/qique.mp3')).arrayBuffer()),samples=buffer.getChannelData(0);let sum=0,invalid=0
    for(const v of samples){sum+=v*v;if(!Number.isFinite(v))invalid++}
    const playback={time:audio.narrationEl.currentTime,duration:audio.narrationEl.duration,paused:audio.narrationEl.paused,error:audio.narrationEl.error,context:audio.context.state}
    const analyser=audio.context.createAnalyser();analyser.fftSize=2048;audio.sfx.connect(analyser);audio.qiqueCall();audio.footstep(0,.24)
    let sfxRms=0;for(let i=0;i<8;i++){await new Promise(r=>setTimeout(r,80));const a=new Float32Array(2048);analyser.getFloatTimeDomainData(a);sfxRms=Math.max(sfxRms,Math.sqrt(a.reduce((s,v)=>s+v*v,0)/a.length))}
    audio.sfx.disconnect(analyser);window.qi.narration=audio.narrationEl;await c.close();return {decoded:{duration:buffer.duration,rate:buffer.sampleRate,rms:Math.sqrt(sum/samples.length),invalid},playback,sfxRms}
  })
  assert(!q.audio.decoded.invalid&&q.audio.decoded.rms>0&&q.audio.playback.time>0&&!q.audio.playback.paused&&!q.audio.playback.error&&q.audio.sfxRms>0)
  await page.evaluate(()=>window.qi.useApp.getState().stopNarration());await page.waitForTimeout(120)
  q.audio.stopped=await page.evaluate(()=>({paused:window.qi.narration.paused,time:window.qi.narration.currentTime,detached:window.qi.audio.narrationEl===null}))
  assert(q.audio.stopped.paused&&q.audio.stopped.time===0&&q.audio.stopped.detached)
  await page.evaluate(()=>{const w=window.qi,a=w.audio,call=a.qiqueCall.bind(a);w.calls=0;a.qiqueCall=()=>{w.calls++;call()};w.useApp.getState().setAction('special')});await page.waitForTimeout(80)
  await page.evaluate(()=>window.qi.useApp.getState().setAction('idle'));await page.waitForTimeout(750)
  q.cancelledCalls=await page.evaluate(()=>window.qi.calls);assert.equal(q.cancelledCalls,0)
  await page.evaluate(()=>window.qi.useApp.getState().setAction('special'));await page.waitForTimeout(4600)
  q.specialReturn=await page.evaluate(()=>window.qi.useApp.getState().action);assert.equal(q.specialReturn,'idle')
  q.buttons=[]
  for(const [label,expected]of [['行','walk'],['神通','special'],['静','idle']]){
    await page.getByRole('button',{name:label,exact:true}).click();await page.waitForTimeout(70)
    const actual=await page.evaluate(()=>window.qi.useApp.getState().action);q.buttons.push({label,expected,actual});assert.equal(actual,expected)
  }
  }
  q.finalCache=await page.evaluate(()=>({unchanged:window.qi.before===window.qi.snapshot(),resources:[...window.qi.resources.values()]}));assert(q.finalCache.unchanged&&q.finalCache.resources.every(r=>r.count===0))
  assert.deepEqual(q.errors,[]);assert.equal(hash(await readFile(new URL('../public/models/qique/body.glb',import.meta.url))),q.asset.sha256)
  q.passed=true
} catch(error){q.passed=false;q.failure=String(error);process.exitCode=1}
finally {await writeFile(join(out,'qa.json'),JSON.stringify(q,null,2));console.log(JSON.stringify(q,null,2));await browser.close()}
