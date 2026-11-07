// Qitu integration QA: count all modules, real sole vertices, remounts and audio.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'
const [base='http://localhost:5215', output='/tmp/shanhai-check/qitu-integrated']=process.argv.slice(2)
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[],report={errors,remounts:[]}
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)})
try {
  const ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready qitu')})
  await page.goto(`${base}/?beast=qitu&action=idle`);await ready
  await page.evaluate(async()=>{
    const resources=performance.getEntriesByType('resource').map(r=>r.name)
    const loaded=path=>resources.find(u=>new URL(u).pathname===path)
    const fiber=await import(resources.find(u=>u.includes('@react-three_fiber.js')))
    const {useApp}=await import(loaded('/src/app/store.ts'))
    window.qituQA={state:[...fiber._roots.values()][0].store.getState(),useApp,loaded}
  })
  const inspect=()=>page.evaluate(()=>{
    const scene=window.qituQA.state.scene,torso=scene.getObjectByName('qitu_torso')
    scene.updateMatrixWorld(true)
    const counts={heads:0,tails:0,bones:0,meshes:0,outlines:0,holders:0,invalid:0,skeletons:0},skeletons=new Set()
    torso.traverse(o=>{
      if(/^qitu_head_\d$/.test(o.name))counts.heads++
      if(/^qitu_tail_\d$/.test(o.name))counts.tails++
      if(/^qitu_(head|tail)_holder_/.test(o.name)){counts.holders++;if(o.children.length!==1)counts.invalid++}
      if(o.isBone)counts.bones++
      if(![...o.matrixWorld.elements,...o.position,...o.quaternion,...o.scale].every(Number.isFinite)||Math.min(...o.scale)<=0)counts.invalid++
      if(o.userData.inkOutline){counts.outlines++;return}
      if(!o.isSkinnedMesh)return
      counts.meshes++;skeletons.add(o.skeleton);o.skeleton.update()
      if(!Array.from(o.skeleton.boneMatrices).every(Number.isFinite))counts.invalid++
      for(const a of Object.values(o.geometry.attributes))if(!Array.from(a.array).every(Number.isFinite))counts.invalid++
      const v=o.position.clone()
      for(let i=0;i<o.geometry.attributes.position.count;i++){o.getVertexPosition(i,v);if(![...v].every(Number.isFinite))counts.invalid++}
    })
    counts.skeletons=skeletons.size
    return counts
  })
  report.baseline=await inspect()
  assert.deepEqual(report.baseline,{heads:3,tails:6,bones:54,meshes:10,outlines:10,holders:9,invalid:0,skeletons:10})
  report.actions={}
  for(const action of ['walk','special']){
    await page.evaluate(a=>window.qituQA.useApp.getState().setAction(a),action)
    report.actions[action]=[]
    for(let i=0;i<8;i++){await page.waitForTimeout(200);const counts=await inspect();assert.equal(counts.invalid,0);report.actions[action].push(counts)}
  }
  await page.waitForFunction(()=>window.qituQA.useApp.getState().action==='idle',null,{timeout:20000})
  report.specialReturnedIdle=true
  await page.evaluate(()=>window.qituQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(350)
  await page.evaluate(()=>{
    const qa=window.qituQA,torso=qa.state.scene.getObjectByName('qitu_torso')
    qa.state.scene.updateMatrixWorld(true)
    let body
    torso.traverse(o=>{if(o.isSkinnedMesh&&!o.userData.inkOutline&&o.skeleton.bones.some(b=>b.name==='foot_l'))body=o})
    body.skeleton.update()
    const feet=['l','r'].map(side=>({name:side,bone:torso.getObjectByName(`foot_${side}`),markers:[]})),p=body.position.clone()
    for(let i=0;i<body.geometry.attributes.position.count;i++){
      body.getVertexPosition(i,p);body.localToWorld(p)
      if(p.y>.006)continue
      const nearest=feet.reduce((a,b)=>p.distanceToSquared(a.bone.getWorldPosition(body.position.clone()))<p.distanceToSquared(b.bone.getWorldPosition(body.position.clone()))?a:b)
      nearest.markers.push(i)
    }
    if(feet.some(f=>f.markers.length<3))throw new Error('Missing Qitu toe markers')
    qa.body=body;qa.feet=feet;qa.useApp.getState().setAction('walk')
  })
  await page.waitForTimeout(400)
  report.motion=await page.evaluate(async()=>{
    const qa=window.qituQA,torso=qa.state.scene.getObjectByName('qitu_torso'),body=qa.body
    const feet=qa.feet.map(f=>({...f,anchor:null,flat:null,previousY:null,maxDrift:0,maxRotation:0,samples:0}))
    const modules=[...[0,1,2].map(i=>torso.getObjectByName(`qitu_head_${i}`)),...[0,1,2,3,4,5].map(i=>torso.getObjectByName(`qitu_tail_${i}`))]
    const moduleSamples=modules.map(()=>[])
    for(let frame=0;frame<210;frame++){
      await new Promise(requestAnimationFrame);qa.state.scene.updateMatrixWorld(true);body.skeleton.update()
      for(const foot of feet){
        const points=foot.markers.map(index=>{const v=body.position.clone();body.getVertexPosition(index,v);return body.localToWorld(v)})
        const y=Math.min(...points.map(p=>p.y))
        const planted=Math.max(...points.map(p=>p.y))<.007&&y>-.004&&foot.previousY!==null&&Math.abs(y-foot.previousY)<.00002
        foot.previousY=y
        if(!planted){foot.anchor=null;continue}
        const q=foot.bone.getWorldQuaternion(body.quaternion.clone()).normalize()
        if(!foot.anchor){foot.anchor=points;foot.flat=q}
        foot.samples++
        for(let j=0;j<points.length;j++)foot.maxDrift=Math.max(foot.maxDrift,Math.hypot(points[j].x-foot.anchor[j].x,points[j].z-foot.anchor[j].z))
        foot.maxRotation=Math.max(foot.maxRotation,q.angleTo(foot.flat))
      }
      for(const [i,m]of modules.entries())moduleSamples[i].push(m.getObjectByName(i<3?'head_chain_1':'tail_chain_1').quaternion.toArray())
    }
    return {feet:feet.map(f=>({name:f.name,vertices:f.markers.length,maxDrift:f.maxDrift,maxRotation:f.maxRotation,samples:f.samples})),modules:modules.map((m,i)=>({name:m.name,range:Math.max(...[0,1,2,3].map(k=>Math.max(...moduleSamples[i].map(q=>q[k]))-Math.min(...moduleSamples[i].map(q=>q[k]))))}))}
  })
  assert(report.motion.feet.every(f=>f.samples>10&&f.maxDrift<.002&&f.maxRotation<.03),JSON.stringify(report.motion.feet))
  assert(report.motion.modules.every(m=>m.range>.001))
  for(const other of ['min_bird','qingniao','jingwei']){
    let ready=page.waitForEvent('console',{predicate:m=>m.text().includes(`[beast] ready ${other}`)})
    await page.evaluate(id=>window.qituQA.useApp.getState().select(id),other);await ready
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready qitu')})
    await page.evaluate(()=>window.qituQA.useApp.getState().select('qitu'));await ready
    const counts=await inspect();assert.deepEqual(counts,report.baseline);report.remounts.push(counts)
  }
  await page.locator('.story-btn').click();await page.waitForTimeout(1300)
  report.audio=await page.evaluate(async()=>{
    const {audio}=await import(window.qituQA.loaded('/src/systems/audio/AudioEngine.ts'))
    const el=audio.narrationEl,ctx=audio.context,create=ctx.createOscillator.bind(ctx),types=[]
    ctx.createOscillator=(...args)=>{const osc=create(...args);types.push(osc);return osc}
    audio.qituLaugh();await new Promise(r=>setTimeout(r,1300));ctx.createOscillator=create
    return {duration:el.duration,currentTime:el.currentTime,error:el.error,context:ctx.state,oscillators:types.length,types:types.map(o=>o.type)}
  })
  assert(report.audio.currentTime>0&&report.audio.duration>90)
  assert.equal(report.audio.error,null);assert.equal(report.audio.context,'running');assert.equal(report.audio.oscillators,12)
  await page.evaluate(()=>window.qituQA.useApp.getState().stopNarration())
  await page.evaluate(()=>{
    const s=window.qituQA.state,root=s.scene.getObjectByName('qitu_torso').parent
    s.camera.filmOffset=0;s.camera.updateProjectionMatrix();s.controls.enableDamping=false;s.controls.minPolarAngle=.1
    const offset=root.position.clone().set(0,3.2,-3.8).applyAxisAngle(root.position.clone().set(0,1,0),root.rotation.y)
    s.camera.position.copy(root.position).add(offset);s.controls.target.copy(root.position).setY(.48);s.controls.update()
    window.qituQA.useApp.getState().setAction('special')
  })
  await page.waitForTimeout(500)
  for(let i=0;i<3;i++){await page.screenshot({path:join(output,`six-tails-${i}.png`)});await page.waitForTimeout(300)}
  assert.deepEqual(errors,[])
  console.log(JSON.stringify(report,null,2))
}finally{await writeFile(join(output,'browser-qa.json'),JSON.stringify(report,null,2));await browser.close()}
