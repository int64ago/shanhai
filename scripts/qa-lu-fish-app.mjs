// Actual compressed Lu geometry, circular stance, rigid hooves, StrictMode and UI.
// node scripts/qa-lu-fish-app.mjs BASE NEW_OUTPUT MODEL.glb REST_REFERENCE.json
import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const [base, outArg, modelArg, referenceArg] = process.argv.slice(2)
assert(base && outArg && modelArg && referenceArg)
const out = resolve(outArg), bytes = await readFile(resolve(modelArg))
const reference = JSON.parse(await readFile(resolve(referenceArg),'utf8'))
assert.equal(reference.sourceSha256,'367b05b52fb5e3c2f8ffc2e1b556b6f9c2be567bec439b9e214b07108881c9a7')
await mkdir(out,{recursive:false})
const report = { model:resolve(modelArg), sha256:createHash('sha256').update(bytes).digest('hex'), size:bytes.length, errors:[], passed:false }
const publicAsset = resolve(modelArg).endsWith('/public/models/lu_fish/body.glb')
report.publicAsset = publicAsset
if(publicAsset){
  const response=await fetch(new URL('/models/lu_fish/body.glb',base))
  assert.equal(response.status,200)
  const served=Buffer.from(await response.arrayBuffer())
  assert.equal(createHash('sha256').update(served).digest('hex'),report.sha256,'Served public bytes differ')
}
const browser = await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page = await browser.newPage({viewport:{width:1440,height:900}})
if(!publicAsset)await page.route('**/models/lu_fish/body.glb*',r=>r.fulfill({body:bytes,contentType:'model/gltf-binary'}))
page.on('pageerror',e=>report.errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error') report.errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400) report.errors.push(`${r.status()} ${r.url()}`)})
const ready = () => page.waitForSelector('[data-stage-beast="lu_fish"][data-stage-state="ready"]',{state:'attached',timeout:60000})
try {
  await page.goto(`${base}/?beast=lu_fish&action=idle`)
  await ready()
  await page.waitForTimeout(700)
  report.geometry = await page.evaluate(async reference => {
    const resources = performance.getEntriesByType('resource').map(r=>r.name)
    const mod = suffix => {const u=resources.find(u=>new URL(u).pathname.endsWith(suffix));if(!u)throw Error(suffix);return u}
    const T = await import(mod('/three.js'))
    const fiber = await import(mod('/@react-three_fiber.js'))
    const { useGLTF } = await import(mod('/@react-three_drei.js'))
    const { useApp } = await import(mod('/src/app/store.ts'))
    const { clone } = await import(mod('/three_examples_jsm_utils_SkeletonUtils__js.js'))
    const body = useGLTF('/models/lu_fish/body.glb'), scene=clone(body.scene)
    const world = new T.Group(); world.add(scene)
    const mixer = new T.AnimationMixer(scene)
    const clips = Object.fromEntries(body.animations.map(c=>[c.name,mixer.clipAction(c)]))
    if (Object.keys(clips).sort().join()!=='idle,special,walk') throw Error('Three dedicated clips required')
    const meshes=[];scene.traverse(n=>{if(n.isSkinnedMesh)meshes.push(n)})
    world.updateMatrixWorld(true)
    const native = reference.points.map(([x,y,z])=>[x,z,-y]), cell=.001, grid=new Map()
    const key=p=>p.join(',')
    for(let i=0;i<native.length;i++){const k=key(native[i].map(v=>Math.floor(v/cell)));if(!grid.has(k))grid.set(k,[]);grid.get(k).push(i)}
    const nearest=p=>{
      const c=p.map(v=>Math.floor(v/cell));let index=-1,error=Infinity
      for(let x=-1;x<=1;x++)for(let y=-1;y<=1;y++)for(let z=-1;z<=1;z++)for(const j of grid.get(key([c[0]+x,c[1]+y,c[2]+z]))??[]){const d=Math.hypot(...p.map((v,k)=>v-native[j][k]));if(d<error){error=d;index=j}}
      if(index<0||error>.0003)throw Error(`Native rest mismatch ${error}`)
      return {index,error}
    }
    const masks=Object.fromEntries(Object.keys(reference.masks).map(k=>[k,[]]))
    const sets=Object.fromEntries(Object.entries(reference.masks).map(([k,v])=>[k,new Set(v)]))
    const points=[],matches=new Set(),p=new T.Vector3();let maximumRestError=0,triangles=0
    for(const mesh of meshes){
      mesh.skeleton.update();triangles+=mesh.geometry.index.count/3
      for(let i=0;i<mesh.geometry.attributes.position.count;i++){
        mesh.getVertexPosition(i,p);mesh.localToWorld(p)
        const rest=p.toArray(),match=nearest(rest);matches.add(match.index);maximumRestError=Math.max(maximumRestError,match.error)
        const index=points.length;points.push({mesh,index:i,rest,native:match.index})
        for(const [name,set] of Object.entries(sets))if(set.has(match.index))masks[name].push(index)
      }
    }
    // Reverse coverage is independent of the weight and compression index order.
    const compressedGrid=new Map()
    for(const point of points){const k=key(point.rest.map(v=>Math.floor(v/cell)));if(!compressedGrid.has(k))compressedGrid.set(k,[]);compressedGrid.get(k).push(point.rest)}
    let maximumReverseError=0
    for(const p of native){const c=p.map(v=>Math.floor(v/cell));let error=Infinity
      for(let x=-1;x<=1;x++)for(let y=-1;y<=1;y++)for(let z=-1;z<=1;z++)for(const q of compressedGrid.get(key([c[0]+x,c[1]+y,c[2]+z]))??[])error=Math.min(error,Math.hypot(...p.map((v,k)=>v-q[k])))
      if(error>.0003)throw Error(`Missing native anatomy ${error}`);maximumReverseError=Math.max(maximumReverseError,error)
    }
    const state=[...fiber._roots.values()][0].store.getState()
    const snapshot=()=>{const rows=[];body.scene.traverse(n=>rows.push([n.uuid,n.children.map(c=>c.uuid),n.position.toArray(),n.quaternion.toArray(),n.scale.toArray(),n.material?.uuid,n.userData.inkOutline]));return JSON.stringify(rows)}
    let sharedDisposals=0
    const tracked=new Set()
    body.scene.traverse(n=>{for(const r of [n.geometry,n.skeleton,...(Array.isArray(n.material)?n.material:n.material?[n.material]:[])])if(r&&!tracked.has(r)){tracked.add(r);if(r.addEventListener)r.addEventListener('dispose',()=>sharedDisposals++);else if(r.dispose){const dispose=r.dispose.bind(r);r.dispose=()=>{sharedDisposals++;dispose()}}}})
    window.luQA={T,body,world,scene,mixer,clips,points,masks,state,useApp,snapshot,before:snapshot(),sharedDisposals:()=>sharedDisposals,
      sample(name,t,walking=false){mixer.stopAllAction();clips[name].reset().play();mixer.setTime(t)
        const angle=-.16/1.05*t;world.position.set(walking?1.05*Math.cos(angle):0,0,walking?1.05*Math.sin(angle):0);world.rotation.y=walking?Math.PI-angle:0
        world.updateMatrixWorld(true);for(const mesh of meshes)mesh.skeleton.update()
        return points.map(({mesh,index})=>{mesh.getVertexPosition(index,p);mesh.localToWorld(p);return p.toArray()})
      }}
    return {triangles,meshes:meshes.length,vertices:points.length,maximumRestError,maximumReverseError,bones:new Set(meshes.flatMap(m=>m.skeleton.bones)).size,maskCounts:Object.fromEntries(Object.entries(masks).map(([k,v])=>[k,v.length])),clipDurations:Object.fromEntries(body.animations.map(c=>[c.name,c.duration]))}
  },reference)
  assert.equal(report.geometry.triangles,50000)
  assert.equal(report.geometry.bones,35)
  assert(bytes.length<15*1024*1024)
  report.motion = await page.evaluate(()=>{
    const q=window.luQA,legs={back_l:0,front_l:.25,back_r:.5,front_r:.75},duration=1.6,duty=.68
    const distance=(a,b)=>Math.hypot(...a.map((v,k)=>v-b[k]))
    const baseline=q.sample('idle',0)
    let maximumRigidHoofDrift=0,maximumHeadDrift=0,maximumWorldStanceDrift=0,minimumSoleHeight=Infinity,maximumStanceSoleHeight=-Infinity,invalid=0
    const feet=Object.fromEntries(Object.keys(legs).map(leg=>[leg,q.masks['hoof_'+leg]]))
    const anchors=Object.fromEntries(Object.entries(feet).map(([leg,ids])=>[leg,[ids[0],ids[Math.floor(ids.length/2)],ids.at(-1)]]))
    const restDistances=Object.fromEntries(Object.entries(feet).map(([leg,ids])=>[leg,anchors[leg].map(a=>ids.map(i=>distance(baseline[a],baseline[i])))]))
    const head=q.masks.head,headAnchors=[head[0],head[Math.floor(head.length/2)],head.at(-1)]
    const headRest=headAnchors.map(a=>head.map(i=>distance(baseline[a],baseline[i])))
    const plants={},previousPhase={}
    const displacement={}
    for(const name of ['idle','walk','special']){
      let maximum=0
      const seconds=name==='walk'?3.2:4
      for(let frame=0;frame<=Math.round(seconds*120);frame++){
        const t=frame/120,p=q.sample(name,t,name==='walk')
        for(const [leg,ids]of Object.entries(feet)){
          anchors[leg].forEach((a,k)=>ids.forEach((id,i)=>{maximumRigidHoofDrift=Math.max(maximumRigidHoofDrift,Math.abs(distance(p[a],p[id])-restDistances[leg][k][i]))}))
          const phase=(t/duration+legs[leg])%1
          const height=Math.min(...ids.map(i=>p[i][1]));minimumSoleHeight=Math.min(minimumSoleHeight,height)
          if(name==='walk'&&phase>.012&&phase<duty-.012){
            maximumStanceSoleHeight=Math.max(maximumStanceSoleHeight,height)
            const a=p[anchors[leg][0]]
            if(!plants[leg]||phase<previousPhase[leg]||previousPhase[leg]>=duty-.012)plants[leg]=a
            maximumWorldStanceDrift=Math.max(maximumWorldStanceDrift,distance(a,plants[leg]))
          }else plants[leg]=null
          previousPhase[leg]=phase
        }
        if(frame%12===0){
          headAnchors.forEach((a,k)=>head.forEach((id,i)=>{maximumHeadDrift=Math.max(maximumHeadDrift,Math.abs(distance(p[a],p[id])-headRest[k][i]))}))
          for(const point of p)if(!point.every(Number.isFinite))invalid++
          for(const ids of [q.masks.wing_l,q.masks.wing_r,q.masks.tail])for(const id of ids)maximum=Math.max(maximum,distance(p[id],baseline[id]))
        }
      }
      displacement[name]=maximum
    }
    return {maximumRigidHoofDrift,maximumHeadDrift,maximumWorldStanceDrift,minimumSoleHeight,maximumStanceSoleHeight,invalid,displacement,samplingHz:120,walkSeconds:3.2,maskMethod:'Frozen-source geometry; bidirectional spatial matching; all hoof vertices and 3 rigidity anchors'}
  })
  await writeFile(join(out,'report.json'),JSON.stringify(report,null,2)+'\n')
  assert(report.motion.maximumWorldStanceDrift<.003,`World stance ${report.motion.maximumWorldStanceDrift}`)
  assert(report.motion.maximumRigidHoofDrift<.0005,`Rigid hoof ${report.motion.maximumRigidHoofDrift}`)
  assert(report.motion.maximumHeadDrift<.001,`Head rigidity ${report.motion.maximumHeadDrift}`)
  assert(report.motion.minimumSoleHeight>-.003,`Sole penetration ${report.motion.minimumSoleHeight}`)
  assert(report.motion.maximumStanceSoleHeight<.003,`Sole hovering ${report.motion.maximumStanceSoleHeight}`)
  assert.equal(report.motion.invalid,0)
  await page.evaluate(()=>window.luQA.useApp.getState().setAction('walk'))
  report.liveWorldStance=await page.evaluate(()=>new Promise((resolve,reject)=>{
    const q=window.luQA,legs={back_l:0,front_l:.25,back_r:.5,front_r:.75},plants={},previous={}
    let frames=0,maximumDrift=0,elapsed=0,lastTime=null
    const root=q.state.scene.getObjectByName('lu_fish_root'),meshes=[]
    root.traverse(n=>{if(n.isSkinnedMesh&&!n.userData.inkOutline)meshes.push(n)})
    const refs=Object.fromEntries(Object.keys(legs).map(leg=>{
      const point=q.points[q.masks['hoof_'+leg][0]],mesh=meshes.find(m=>m.geometry===point.mesh.geometry)
      if(!mesh)throw Error('Stage geometry differs from measured compressed asset')
      return [leg,{mesh,index:point.index}]
    }))
    const p=new q.T.Vector3(),start=performance.now()
    const sample=()=>{
      try{
        root.updateMatrixWorld(true);for(const mesh of meshes)mesh.skeleton.update()
        const t=root.userData.animationTime??0
        if(lastTime!==null)elapsed+=(t-lastTime+1.6)%1.6
        lastTime=t
        for(const [leg,ref]of Object.entries(refs)){
          const phase=(t/1.6+legs[leg])%1
          ref.mesh.getVertexPosition(ref.index,p);ref.mesh.localToWorld(p)
          if(phase>.02&&phase<.66){
            if(!plants[leg]||phase<previous[leg])plants[leg]=p.clone()
            maximumDrift=Math.max(maximumDrift,p.distanceTo(plants[leg]))
          }else plants[leg]=null
          previous[leg]=phase
        }
        frames++
        if(elapsed>=3.2)return resolve({maximumDrift,frames,animationSeconds:elapsed,source:'Mounted Stage, actual compressed geometry and runtime transform'})
        if(performance.now()-start>20000)throw Error('Runtime walk did not advance')
        requestAnimationFrame(sample)
      }catch(e){reject(e)}
    }
    requestAnimationFrame(sample)
  }))
  assert(report.liveWorldStance.maximumDrift<.004,`Actual runtime stance ${report.liveWorldStance.maximumDrift}`)
  for(const action of ['idle','walk','special']){
    await page.evaluate(a=>window.luQA.useApp.getState().setAction(a),action)
    await page.waitForTimeout(1300)
    await page.screenshot({path:join(out,`${action}.png`)})
  }
  report.strictMode=[]
  for(let i=0;i<3;i++){
    await page.evaluate(()=>window.luQA.useApp.getState().select('jingwei'))
    await page.waitForSelector('[data-stage-beast="jingwei"][data-stage-state="ready"]',{state:'attached',timeout:60000})
    await page.evaluate(()=>window.luQA.useApp.getState().select('lu_fish'))
    await ready()
    const row=await page.evaluate(()=>{const q=window.luQA,root=q.state.scene.getObjectByName('lu_fish_root');let meshes=0,outlines=0,sharedSkeletons=0;const sourceSkeletons=new Set();q.body.scene.traverse(n=>{if(n.isSkinnedMesh)sourceSkeletons.add(n.skeleton)});root.traverse(n=>{if(n.isMesh){if(n.userData.inkOutline)outlines++;else meshes++;if(n.isSkinnedMesh&&sourceSkeletons.has(n.skeleton))sharedSkeletons++}});return {sourceUnchanged:q.before===q.snapshot(),sharedDisposals:q.sharedDisposals(),meshes,outlines,sharedSkeletons}})
    assert(row.sourceUnchanged&&row.sharedDisposals===0&&row.meshes===row.outlines&&row.sharedSkeletons===0)
    report.strictMode.push(row)
  }
  report.ui=[]
  for(const width of [390,700]){
    await page.setViewportSize({width,height:900})
    await page.waitForTimeout(900)
    const row=await page.evaluate(()=>{
      const card=document.querySelector('.card'),source=card.querySelector('.card-source'),design=card.querySelector('.card-inferred')
      const scroller=element=>{for(let n=element;n;n=n.parentElement){const css=getComputedStyle(n);if(/auto|scroll/.test(css.overflowY)&&n.scrollHeight>n.clientHeight+1)return n}return null}
      const sourceScroll=scroller(source),designScroll=scroller(design)
      const access=element=>{const s=scroller(element);if(!s)return {scrollable:false,visible:element.getBoundingClientRect().height>0};s.scrollTop=s.scrollHeight;const reached=s.scrollTop+s.clientHeight>=s.scrollHeight-2;s.scrollTop=0;return {scrollable:true,reached}}
      return {width:innerWidth,noHorizontalOverflow:document.documentElement.scrollWidth<=innerWidth,source:access(source),design:access(design),sourceScroller:sourceScroll?.className,designScroller:designScroll?.className,labels:[...card.querySelectorAll('.card-label')].map(n=>n.textContent),sourceText:source.textContent,designText:design.textContent}
    })
    assert(row.noHorizontalOverflow)
    assert(row.labels.includes('原文')&&row.labels.includes('设计'))
    assert(row.source.reached||row.source.visible)
    assert(row.design.reached||row.design.visible)
    report.ui.push(row)
    await page.screenshot({path:join(out,`ui-${width}.png`)})
    await page.locator('.card-inferred p').last().evaluate(n=>n.scrollIntoView({block:'nearest'}))
    await page.screenshot({path:join(out,`ui-${width}-design-end.png`)})
  }
  assert.deepEqual(report.errors,[])
  report.passed=true
} catch(error) {
  report.failure=String(error)
  await page.screenshot({path:join(out,'failure.png')}).catch(()=>{})
  process.exitCode=1
} finally {
  await writeFile(join(out,'report.json'),JSON.stringify(report,null,2)+'\n')
  await browser.close()
}
console.log(JSON.stringify(report,null,2))
