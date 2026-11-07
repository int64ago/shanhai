// Actual CPU-skinned sole planes, tail curvature, ground clearance and GPU cleanup.
// node scripts/qa-zouwu.mjs [base URL] [output directory]
import assert from 'node:assert/strict'
import {mkdir,writeFile} from 'node:fs/promises'
import {chromium} from 'playwright-core'
const [base='http://localhost:5232',output='/tmp/shanhai-zouwu-fix']=process.argv.slice(2)
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
const report={errors,actions:{},remounts:[]}
try {
 let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready zouwu')})
 await page.goto(`${base}/?beast=zouwu&action=idle`);await ready
 await page.evaluate(async()=>{
  const urls=performance.getEntriesByType('resource').map(r=>r.name)
  const fiber=await import(urls.find(u=>u.includes('@react-three_fiber.js')))
  const {useApp}=await import(urls.find(u=>new URL(u).pathname==='/src/app/store.ts'))
  window.qa={s:[...fiber._roots.values()][0].store.getState(),app:useApp}
 })
 await page.waitForTimeout(500)
 const snapshot=()=>page.evaluate(()=>{
  const {s}=window.qa,root=s.scene.getObjectByName('zouwu_root'),tail=root.getObjectByName('zouwu_single_tail')
  s.scene.updateMatrixWorld(true)
  let nodes=0,invalid=0,minTail=Infinity
  root.traverse(o=>{nodes++;if(![...o.matrixWorld.elements,...o.scale].every(Number.isFinite)||Math.min(...o.scale)<=0)invalid++;if(o.skeleton)o.skeleton.update();if(o.isMesh)for(const a of Object.values(o.geometry.attributes))for(const x of a.array)if(!Number.isFinite(x))invalid++})
  const p=tail.position.clone(),points=tail.skeleton.bones.map(b=>b.getWorldPosition(p).toArray())
  const angles=[]
  for(let i=1;i<points.length-1;i++){const a=p.clone().fromArray(points[i]).sub(p.clone().fromArray(points[i-1])),b=p.clone().fromArray(points[i+1]).sub(p.clone().fromArray(points[i]));angles.push(a.angleTo(b))}
  const rings=new Map([0,4,8,68,72,76,128,132,136].map(i=>[i,{sum:[0,0,0],count:0}]))
  const positions=tail.geometry.attributes.position
  let restLength=0
  for(let i=0;i<positions.count;i++)restLength=Math.max(restLength,positions.getX(i))
  for(let i=0;i<positions.count;i++){
   tail.getVertexPosition(i,p);tail.localToWorld(p);minTail=Math.min(minTail,p.y);if(![...p].every(Number.isFinite))invalid++
   const ring=rings.get(Math.round(positions.getX(i)/restLength*144))
   if(ring){ring.sum=ring.sum.map((v,j)=>v+p.getComponent(j));ring.count++}
  }
  const centres=[...rings.values()].map(r=>p.clone().fromArray(r.sum.map(v=>v/r.count)))
  const surfaceAngles=[0,3,6].map(i=>centres[i+1].clone().sub(centres[i]).angleTo(centres[i+2].clone().sub(centres[i+1])))
  const arc=points.slice(1).reduce((sum,x,i)=>sum+Math.hypot(...x.map((v,j)=>v-points[i][j])),0)
  const feet={};for(const n of ['front_l','front_r','back_l','back_r'])feet[n]=root.getObjectByName(n+'_foot').getWorldPosition(p).toArray()
  return {nodes,invalid,minTail,arc,angles,surfaceAngles,feet,holders:root.getObjectsByProperty('name','zouwu_tail_holder').length,tails:root.getObjectsByProperty('name','zouwu_single_tail').length,animationTime:root.userData.animationTime}
 })
 report.baseline=await snapshot()
 for(const action of ['idle','walk','special']){
  await page.evaluate(a=>window.qa.app.getState().setAction(a),action)
  const samples=[]
  for(let i=0;i<(action==='special'?42:action==='idle'?64:36);i++){await page.waitForTimeout(110);samples.push(await snapshot())}
  report.actions[action]=samples
 }
 // Select actual rest sole vertices per paw, then measure their full XYZ,
 // heading and plane normal through several complete support phases.
 await page.evaluate(()=>window.qa.app.getState().setAction('idle'));await page.waitForTimeout(400)
 report.contact=await page.evaluate(async()=>{
  const {s,app}=window.qa,root=s.scene.getObjectByName('zouwu_root'),body=root.getObjectByName('body'),points={}
  const p=body.position.clone();s.scene.updateMatrixWorld(true);body.skeleton.update()
  for(let i=0;i<body.geometry.attributes.position.count;i++){
   body.getVertexPosition(i,p);body.localToWorld(p)
   if(p.y>.002)continue
   const a=body.geometry.attributes,foot=body.skeleton.bones[a.skinIndex.getX(i)].name
   if(!foot.endsWith('_foot')||a.skinWeight.getX(i)<.999)continue
   ;(points[foot]??=[]).push(i)
  }
  window.qa.soles=points
  const offsets={back_l_foot:0,front_l_foot:.25,back_r_foot:.5,front_r_foot:.75},plants={}
  app.getState().setAction('walk');await new Promise(r=>setTimeout(r,400))
  const begin=performance.now();let frames=0,cycle=0,previous=root.userData.animationTime
  while(performance.now()-begin<5600){
   await new Promise(r=>requestAnimationFrame(r));frames++;s.scene.updateMatrixWorld(true);body.skeleton.update()
   const time=root.userData.animationTime;if(time<previous-.5)cycle++;previous=time
   for(const [foot,ids]of Object.entries(points)){
    const phase=time/1.6+offsets[foot],u=phase%1;if(u<.04||u>.61)continue
    const key=`${foot}/${cycle+Math.floor(phase)}`
    const xyz=ids.map(i=>{body.getVertexPosition(i,p);body.localToWorld(p);return p.toArray()})
    const plant=plants[key]??={foot,initial:xyz,maxXYZ:0,maxDirection:0,samples:0,minY:Infinity,maxY:-Infinity}
    for(let i=0;i<xyz.length;i++){
     plant.maxXYZ=Math.max(plant.maxXYZ,Math.hypot(...xyz[i].map((v,j)=>v-plant.initial[i][j])))
     plant.minY=Math.min(plant.minY,xyz[i][1]);plant.maxY=Math.max(plant.maxY,xyz[i][1])
     const a=xyz[i].map((v,j)=>v-xyz[0][j]),b=plant.initial[i].map((v,j)=>v-plant.initial[0][j]),d=Math.hypot(...a)*Math.hypot(...b)
     if(d>1e-8)plant.maxDirection=Math.max(plant.maxDirection,Math.acos(Math.max(-1,Math.min(1,a.reduce((v,x,j)=>v+x*b[j],0)/d))))
    }
    plant.samples++;plants[key]=plant
   }
  }
  const valid=Object.values(plants).filter(p=>p.samples>8)
  return {frames,pointsPerFoot:Object.fromEntries(Object.entries(points).map(([k,v])=>[k,v.length])),plants:valid.map(({initial,...p})=>p),maxXYZ:Math.max(...valid.map(p=>p.maxXYZ)),maxDirection:Math.max(...valid.map(p=>p.maxDirection))}
 })
 report.transitions=await page.evaluate(async()=>{
  const {s,app,soles}=window.qa,root=s.scene.getObjectByName('zouwu_root'),body=root.getObjectByName('body'),p=body.position.clone()
  const anchors={},segments=[],schedule=[['idle',650],['walk',1100],['idle',750],['special',2100],['idle',650],['walk',950],['special',3600],['idle',500]]
  function normal(pts,ids){const a=pts[ids[1]].map((v,j)=>v-pts[ids[0]][j]),b=pts[ids[2]].map((v,j)=>v-pts[ids[0]][j]);const n=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],l=Math.hypot(...n);return n.map(x=>x/l)}
  let frames=0
  for(const [action,ms]of schedule){
   app.getState().setAction(action);const start=performance.now()
   while(performance.now()-start<ms){
    await new Promise(r=>requestAnimationFrame(r));frames++;s.scene.updateMatrixWorld(true);body.skeleton.update()
    for(const [foot,ids]of Object.entries(soles)){
     if(!root.getObjectByName(foot).userData.planted){if(anchors[foot]){segments.push(anchors[foot]);delete anchors[foot]}continue}
     const xyz=ids.map(i=>{body.getVertexPosition(i,p);body.localToWorld(p);return p.toArray()})
     if(!anchors[foot]){
      let far=1,third=2,area=0
      for(let i=1;i<xyz.length;i++)if(Math.hypot(...xyz[i].map((v,j)=>v-xyz[0][j]))>Math.hypot(...xyz[far].map((v,j)=>v-xyz[0][j])))far=i
      const a=xyz[far].map((v,j)=>v-xyz[0][j])
      for(let i=1;i<xyz.length;i++){const b=xyz[i].map((v,j)=>v-xyz[0][j]),x=Math.hypot(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]);if(x>area){area=x;third=i}}
      if(area<1e-8)throw Error('Collinear sole samples')
      const plane=[0,far,third];anchors[foot]={foot,initial:xyz,plane,normal:normal(xyz,plane),frames:0,maxXYZ:0,maxNormal:0,maxHeading:0}
     }
     const a=anchors[foot];a.frames++
     for(let i=0;i<xyz.length;i++)a.maxXYZ=Math.max(a.maxXYZ,Math.hypot(...xyz[i].map((v,j)=>v-a.initial[i][j])))
     const n=normal(xyz,a.plane);a.maxNormal=Math.max(a.maxNormal,Math.acos(Math.max(-1,Math.min(1,n.reduce((v,x,j)=>v+x*a.normal[j],0)))))
     const i=a.plane[1],heading=Math.atan2(xyz[i][0]-xyz[0][0],xyz[i][2]-xyz[0][2]),initial=Math.atan2(a.initial[i][0]-a.initial[0][0],a.initial[i][2]-a.initial[0][2]),d=heading-initial
     a.maxHeading=Math.max(a.maxHeading,Math.abs(Math.atan2(Math.sin(d),Math.cos(d))))
    }
   }
  }
  segments.push(...Object.values(anchors))
  const valid=segments.filter(s=>s.frames>4)
  return {frames,schedule,segments:valid.map(({initial,plane,normal,...a})=>a),maxXYZ:Math.max(...valid.map(a=>a.maxXYZ)),maxNormalDegrees:Math.max(...valid.map(a=>a.maxNormal))*180/Math.PI,maxHeadingDegrees:Math.max(...valid.map(a=>a.maxHeading))*180/Math.PI}
 })
 await page.evaluate(()=>window.qa.app.getState().setAction('special'))
 await page.waitForFunction(()=>window.qa.app.getState().action==='idle',null,{timeout:15000})
 report.specialReturn='idle'
 for(let i=0;i<3;i++){
  await page.evaluate(()=>{
   const root=window.qa.s.scene.getObjectByName('zouwu_root'),sk=new Set();root.traverse(o=>{if(o.skeleton)sk.add(o.skeleton)})
   const textures=[...sk].map(s=>s.boneTexture).filter(Boolean)
   const materials=new Set();root.traverse(o=>{if(o.isMesh)materials.add(o.material)})
   window.qa.old={sk:[...sk],textures,disposed:0,materials:materials.size,materialsDisposed:0,geometryDisposed:0}
   for(const t of textures)t.addEventListener('dispose',()=>window.qa.old.disposed++)
   for(const m of materials)m.addEventListener('dispose',()=>window.qa.old.materialsDisposed++)
   root.getObjectByName('zouwu_single_tail').geometry.addEventListener('dispose',()=>window.qa.old.geometryDisposed++)
  })
  ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready boyi')})
  await page.evaluate(()=>window.qa.app.getState().select('boyi'));await ready
  const cleanup=await page.evaluate(()=>({textures:window.qa.old.textures.length,disposed:window.qa.old.disposed,materials:window.qa.old.materials,materialsDisposed:window.qa.old.materialsDisposed,geometryDisposed:window.qa.old.geometryDisposed,live:window.qa.old.sk.filter(s=>s.boneTexture).length,rootLeft:!!window.qa.s.scene.getObjectByName('zouwu_root')}))
  ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready zouwu')})
  await page.evaluate(()=>window.qa.app.getState().select('zouwu'));await ready;await page.waitForTimeout(250)
  report.remounts.push({cleanup,...await snapshot()})
 }
 await page.addStyleTag({content:'.title,.card,.actions,.controls,.scroll-wrap{visibility:hidden!important}'})
 for(const action of ['idle','walk','special'])for(const view of ['side','back']){
  await page.evaluate(({action,view})=>{
   const {s,app}=window.qa;app.getState().setAction(action)
   const root=s.scene.getObjectByName('zouwu_root'),target=root.position.clone().setY(.40)
   target.add(root.position.clone().set(0,0,-.55).applyQuaternion(root.quaternion))
   const offset=root.position.clone().set(...(view==='side'?[4,1,0]:[-1,1.7,-4.5])).applyQuaternion(root.quaternion)
   s.controls.enableDamping=false;s.camera.filmOffset=0;s.camera.updateProjectionMatrix();s.controls.target.copy(target);s.camera.position.copy(target).add(offset);s.controls.update()
  },{action,view})
  if(action==='special')await page.waitForTimeout(1400)
  for(let frame=0;frame<(action==='special'?5:3);frame++){await page.waitForTimeout(action==='special'?250:330);await page.screenshot({path:`${output}/${action}-${view}-${frame}.png`})}
 }
 assert.equal(report.baseline.invalid,0)
 assert(Object.values(report.actions).flat().every(s=>s.invalid===0&&s.minTail>.015&&s.arc>.98156),'Finite skinning, tail longer than body and no ground penetration')
 report.curvature=Object.fromEntries(Object.entries(report.actions).map(([action,samples])=>[action,[0,1,2].map(i=>({part:['root','middle','tip'][i],min:Math.min(...samples.map(s=>s.surfaceAngles[i])),max:Math.max(...samples.map(s=>s.surfaceAngles[i]))}))]))
 for(const parts of Object.values(report.curvature))for(const part of parts)assert(part.max-part.min>.001,`Surface curvature changes at ${part.part}`)
 assert(report.transitions.maxXYZ<.0006,`Transition sole drift ${report.transitions.maxXYZ}`)
 assert(report.transitions.maxNormalDegrees<.05,'Transition sole plane normal')
 assert(report.transitions.maxHeadingDegrees<.05,'Transition sole heading')
 assert.equal(Object.keys(report.contact.pointsPerFoot).length,4,'Four sole planes')
 assert(report.contact.maxXYZ<.0015,`Sole XYZ drift ${report.contact.maxXYZ}`)
 assert(report.contact.maxDirection<Math.PI/900,`Sole direction drift ${report.contact.maxDirection}`)
 for(const m of report.remounts){assert.equal(m.nodes,report.baseline.nodes);assert.equal(m.holders,1);assert.equal(m.tails,1);assert.equal(m.cleanup.disposed,m.cleanup.textures);assert.equal(m.cleanup.materialsDisposed,m.cleanup.materials);assert.equal(m.cleanup.geometryDisposed,1);assert.equal(m.cleanup.live,0);assert(!m.cleanup.rootLeft)}
 assert.equal(errors.length,0)
} finally {
 await writeFile(`${output}/qa.json`,JSON.stringify(report,null,2))
 console.log(JSON.stringify({errors,baseline:report.baseline,contact:report.contact,remounts:report.remounts.map(r=>r.cleanup)},null,2))
 await browser.close()
}
