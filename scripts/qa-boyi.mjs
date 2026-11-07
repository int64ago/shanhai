// Boyi browser QA: source anatomy, live skinning, contact, remounts, audio.
// node scripts/qa-boyi.mjs [http://localhost:5213] [/tmp/boyi-qa]
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const [base='http://localhost:5213', output='/tmp/boyi-qa']=process.argv.slice(2)
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error') errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400) errors.push(`${r.status()} ${r.url()}`)})
const report={actions:{},remounts:[],angles:[],errors}
try {
  const ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready boyi')})
  await page.goto(`${base}/?beast=boyi&action=idle`)
  await ready
  await page.evaluate(async()=>{
    const url=performance.getEntriesByType('resource').map(r=>r.name).find(u=>u.includes('@react-three_fiber.js'))
    const fiber=await import(url)
    const storeUrl=performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/app/store.ts')
    if(!storeUrl) throw new Error('Loaded application store not found')
    const {useApp}=await import(storeUrl)
    window.boyiQA={state:[...fiber._roots.values()][0].store.getState(),useApp}
  })
  async function snapshot(full=false) {
    return page.evaluate(all=>{
      const {state}=window.boyiQA
      const root=state.scene.getObjectByName('boyi_root')
      if(!root) throw new Error('Missing Boyi root')
      root.updateMatrixWorld(true)
      const meshes=[],bones=[],outlines=[]
      let invalid=0,nodes=0
      root.traverse(node=>{
        nodes++
        if(![...node.matrixWorld.elements,...node.position,...node.quaternion,...node.scale].every(Number.isFinite)) invalid++
        if(node.scale.x<=0||node.scale.y<=0||node.scale.z<=0) invalid++
        if(node.isBone) bones.push(node)
        if(!node.isMesh) return
        if(node.userData.inkOutline) {outlines.push(node);return}
        meshes.push(node)
        if(all) for(const key of ['position','normal','skinWeight']) {
          const attr=node.geometry.attributes[key]
          if(attr&&!Array.from(attr.array).every(Number.isFinite)) invalid++
        }
        if(node.skeleton) {
          node.skeleton.update()
          if(!Array.from(node.skeleton.boneMatrices).every(Number.isFinite)) invalid++
        }
      })
      const feet={}
      const p=root.position.clone()
      for(const mesh of meshes) {
        const hoof=mesh.name.startsWith('boyi_hoof_')
        if(!hoof&&!all) continue
        const position=mesh.geometry.attributes.position
        let min=Infinity
        for(let i=0;i<position.count;i++) {
          mesh.getVertexPosition(i,p)
          if(![...p].every(Number.isFinite)) invalid++
          if(hoof) min=Math.min(min,mesh.localToWorld(p).y)
        }
        if(hoof) feet[mesh.name]=min
      }
      return {invalid,nodes,meshes:meshes.length,outlines:outlines.length,bones:bones.length,
        tails:meshes.filter(n=>/^boyi_tail_\d\d$/.test(n.name)).length,
        tailBones:bones.filter(n=>n.name.startsWith('boyi_tail_')).length,
        ears:meshes.filter(n=>n.name.startsWith('boyi_ear_')&&n.name.endsWith('_outer')).length,
        eyes:meshes.filter(n=>n.name.startsWith('boyi_dorsal_')&&n.name.endsWith('_sclera')).length,
        facialEyes:meshes.filter(n=>n.name.includes('face_eye')).length,
        horns:meshes.filter(n=>n.name.includes('horn')).length,
        legs:bones.filter(n=>/^(front|back)_[lr]_foot$/.test(n.name)).length,
        feet}
    },full)
  }
  const baseline=await snapshot(true)
  report.baseline=baseline
  for(const [key,value] of Object.entries({invalid:0,tails:9,tailBones:72,ears:4,eyes:2,facialEyes:0,horns:0,legs:4})) assert.equal(baseline[key],value,key)
  assert.equal(Object.keys(baseline.feet).length,4)
  for(const action of ['idle','walk','special']) {
    await page.evaluate(a=>window.boyiQA.useApp.getState().setAction(a),action)
    const samples=[]
    for(let i=0;i<(action==='special'?43:24);i++) {
      await page.waitForTimeout(120)
      samples.push(await snapshot(i%12===0))
    }
    assert(samples.every(s=>s.invalid===0&&s.tails===9&&s.ears===4&&s.eyes===2))
    // A lifted walk hoof unfolds during the 0.32 s crossfade into a display.
    if(action!=='walk') assert(samples.slice(4).every(s=>Object.values(s.feet).every(y=>Math.abs(y)<.008)),`${action}: hoof contact`)
    if(action==='walk') assert(samples.every(s=>Math.min(...Object.values(s.feet))>-.008&&Math.min(...Object.values(s.feet))<.012),'walk: support contact')
    report.actions[action]=samples
  }
  // Measure actual sole vertices through consecutive planted frames in world space.
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('walk'))
  await page.waitForTimeout(1200)
  report.stance=await page.evaluate(async()=>{
    const root=window.boyiQA.state.scene.getObjectByName('boyi_root')
    const feet=[]
    root.traverse(mesh=>{
      if(!mesh.isMesh||mesh.userData.inkOutline||!mesh.name.startsWith('boyi_hoof_')) return
      const position=mesh.geometry.attributes.position
      let vertex=0
      for(let i=1;i<position.count;i++) if(position.getY(i)<position.getY(vertex)) vertex=i
      feet.push({mesh,vertex,point:root.position.clone(),previous:null,anchor:null,drift:0,samples:0})
    })
    for(let frame=0;frame<180;frame++){
      await new Promise(requestAnimationFrame)
      root.updateWorldMatrix(true,true)
      for(const foot of feet){
        foot.mesh.skeleton.update()
        foot.mesh.getVertexPosition(foot.vertex,foot.point)
        foot.mesh.localToWorld(foot.point)
        const p=foot.point
        if(foot.previous&&Math.abs(p.y)<.006&&Math.abs(p.y-foot.previous.y)<.00002){
          foot.anchor??=p.clone()
          foot.drift=Math.max(foot.drift,Math.hypot(p.x-foot.anchor.x,p.z-foot.anchor.z))
          foot.samples++
        }else foot.anchor=null
        foot.previous=p.clone()
      }
    }
    return feet.map(f=>({name:f.mesh.name,maxStanceDrift:f.drift,samples:f.samples}))
  })
  assert.equal(report.stance.length,4)
  assert(report.stance.every(f=>f.samples>10&&f.maxStanceDrift<.001),JSON.stringify(report.stance))
  // Interrupt a full display, then finish a walk-to-idle transition.
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('special'))
  await page.waitForTimeout(1400)
  const before=await snapshot()
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('walk'))
  await page.waitForTimeout(80)
  const after=await snapshot()
  assert.equal(after.invalid,0)
  await page.waitForTimeout(500)
  await page.evaluate(()=>window.boyiQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(500)
  report.interruption={before,after,settled:await snapshot(true)}
  for(let i=0;i<3;i++) {
    let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready ershu')})
    await page.evaluate(()=>window.boyiQA.useApp.getState().select('ershu'))
    await ready
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready boyi')})
    await page.evaluate(()=>window.boyiQA.useApp.getState().select('boyi'))
    await ready
    const current=await snapshot(true)
    for(const key of ['invalid','nodes','meshes','outlines','bones','tails','tailBones','ears','eyes','facialEyes','horns','legs']) assert.equal(current[key],baseline[key],`remount ${key}`)
    report.remounts.push(current)
  }
  for(const [name,x,y,z] of [['front',0,1,3.6],['back',0,1,-3.6],['left',-3.6,1,0],['right',3.6,1,0],['dorsal',1.2,3.1,-1.2]]) {
    await page.evaluate(({x,y,z})=>{
      const {state}=window.boyiQA
      const root=state.scene.getObjectByName('boyi_root')
      const target=root.position.clone().add({x:0,y:.49,z:0})
      const offset=root.position.clone().set(x,y,z).applyQuaternion(root.quaternion)
      state.controls.enableDamping=false
      state.camera.filmOffset=0
      state.camera.updateProjectionMatrix()
      state.controls.target.copy(target)
      state.camera.position.copy(target).add(offset)
      state.controls.update()
    },{x,y,z})
    await page.waitForTimeout(200)
    const path=join(output,`boyi-angle-${name}.png`)
    await page.screenshot({path})
    report.angles.push(path)
  }
  await page.locator('.story-btn').click()
  await page.waitForTimeout(1800)
  report.audio=await page.evaluate(async()=>{
    const audioUrl=performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts')
    if(!audioUrl) throw new Error('Loaded audio engine not found')
    const {audio}=await import(audioUrl)
    const el=audio.narrationEl
    audio.boyiCall(0)
    return {src:el?.src,duration:el?.duration,currentTime:el?.currentTime,error:el?.error,context:audio.context?.state}
  })
  assert(report.audio.src.endsWith('/audio/narration/boyi.mp3')&&report.audio.currentTime>0&&report.audio.duration>45)
  assert.equal(report.audio.error,null)
  await page.waitForTimeout(1000)
  await page.evaluate(()=>window.boyiQA.useApp.getState().stopNarration())
  assert.equal(errors.length,0,errors.join('\n'))
  console.log(JSON.stringify({baseline,remounts:report.remounts.length,finiteSamples:Object.values(report.actions).reduce((n,a)=>n+a.length,0),stance:report.stance,audio:report.audio,errors},null,2))
} finally {
  await writeFile(join(output,'browser-qa.json'),JSON.stringify(report,null,2))
  await browser.close()
}
