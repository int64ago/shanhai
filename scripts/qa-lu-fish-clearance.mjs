// Project every actual compressed skinned vertex against real DOM rectangles.
// Walk uses the mounted runtime for a complete circle. Idle/special are also
// sampled at 72 recorded world/camera headings, across each complete clip.
// node scripts/qa-lu-fish-clearance.mjs BASE NEW_OUTPUT
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright-core'

const [base, outArg] = process.argv.slice(2)
assert(base && outArg)
const out = resolve(outArg)
await mkdir(out,{recursive:false})
const report = { requiredClearancePixels:9, note:'9px surface clearance reserves 1px for the ink outline; minimum requested DOM gap is 8px', viewports:[], errors:[], passed:false }
const browser = await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
try{
  for(const [width,height] of [[390,900],[700,900],[1440,900]]){
    const page = await browser.newPage({viewport:{width,height}})
    page.on('pageerror',e=>report.errors.push(String(e)))
    await page.goto(`${base}/?beast=lu_fish&action=idle`)
    await page.waitForSelector('[data-stage-beast="lu_fish"][data-stage-state="ready"]',{state:'attached',timeout:60000})
    await page.waitForTimeout(1000)
    await page.screenshot({path:join(out,`${width}-initial.png`)})
    await page.evaluate(async()=>{
      const urls=performance.getEntriesByType('resource').map(r=>r.name)
      const mod=suffix=>urls.find(u=>new URL(u).pathname.endsWith(suffix))
      const T=await import(mod('/three.js'))
      const fiber=await import(mod('/@react-three_fiber.js'))
      const {useGLTF}=await import(mod('/@react-three_drei.js'))
      const {useApp}=await import(mod('/src/app/store.ts'))
      const state=[...fiber._roots.values()][0].store.getState()
      const root=state.scene.getObjectByName('lu_fish_root'),source=root.children[0]
      const meshes=[];root.traverse(n=>{if(n.isSkinnedMesh&&!n.userData.inkOutline)meshes.push(n)})
      state.setFrameloop('never')
      const render=state.gl.render.bind(state.gl)
      state.gl.render=()=>{}
      window.clearQA={T,state,root,source,meshes,useApp,body:useGLTF('/models/lu_fish/body.glb'),render}
    })
    await page.evaluate(()=>window.clearQA.useApp.getState().setAction('walk'))
    await page.waitForTimeout(100)
    const result=await page.evaluate(()=>{
      const q=window.clearQA,{T,state,root,source,meshes}=q
      const dom={}
      for(const [name,selector]of Object.entries({card:'.card',actions:'.actions',controls:'.controls',scroll:'.scroll-wrap'})){
        const element=document.querySelector(selector)
        if(!element)throw Error(`Missing real DOM ${selector}`)
        const r=element.getBoundingClientRect();dom[name]={left:r.left,top:r.top,right:r.right,bottom:r.bottom}
      }
      const domEntries=Object.entries(dom)
      const minimum=Object.fromEntries(Object.keys(dom).map(k=>[k,{pixels:Infinity}]))
      minimum.viewport={pixels:Infinity}
      const counts={walk:0,idle:0,special:0},headingSnapshots=[]
      let vertexSamples=0,worst=null
      const p=new T.Vector3(),projection=new T.Matrix4()
      const camera=state.camera
      const pose=(action,time)=>({action,time,rootPosition:root.position.toArray(),rootQuaternion:root.quaternion.toArray(),cameraPosition:camera.position.toArray(),cameraQuaternion:camera.quaternion.toArray()})
      const measure=(action,time)=>{
        root.updateMatrixWorld(true);camera.updateMatrixWorld(true)
        for(const mesh of meshes){
          mesh.skeleton.update()
          projection.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse).multiply(mesh.matrixWorld)
          for(let i=0;i<mesh.geometry.attributes.position.count;i++){
            mesh.getVertexPosition(i,p);p.applyMatrix4(projection)
            const x=(p.x+1)*innerWidth/2,y=(1-p.y)*innerHeight/2
            const edge=Math.min(x,y,innerWidth-x,innerHeight-y)
            if(edge<minimum.viewport.pixels)minimum.viewport={pixels:edge,x,y,...pose(action,time)}
            for(const [name,r]of domEntries){
              const dx=Math.max(r.left-x,0,x-r.right),dy=Math.max(r.top-y,0,y-r.bottom)
              const distance=Math.hypot(dx,dy)
              if(distance<minimum[name].pixels){
                minimum[name]={pixels:distance,x,y,vertex:i,...pose(action,time)}
                if(!worst||distance<worst.pixels)worst={...minimum[name],region:name}
              }
            }
            vertexSamples++
          }
        }
        counts[action]++
      }
      const circleSeconds=2*Math.PI*1.05/.16,frames=Math.ceil(circleSeconds/.05)
      let seconds=state.clock.elapsedTime
      const startYaw=root.rotation.y
      for(let i=0;i<=frames;i++){
        if(i>0){seconds+=circleSeconds/frames;state.advance(seconds,true)}
        measure('walk',root.userData.animationTime??0)
        if(headingSnapshots.length<72&&i>=headingSnapshots.length*frames/72)headingSnapshots.push(pose('walk',root.userData.animationTime??0))
      }
      const actualWalkYawSpan=root.rotation.y-startYaw
      if(Math.abs(actualWalkYawSpan-2*Math.PI)>.001)throw Error(`Runtime did not complete the full circle: ${actualWalkYawSpan}`)
      // Restore the cached GLB bind defaults before creating a second mixer.
      // Optimized clips may omit channels whose value equals the rest pose.
      source.traverse(node=>{if(node.isBone){const rest=q.body.scene.getObjectByName(node.name);if(!rest)throw Error('Missing bind bone');node.position.copy(rest.position);node.quaternion.copy(rest.quaternion);node.scale.copy(rest.scale)}})
      const mixer=new T.AnimationMixer(source)
      const clips=Object.fromEntries(q.body.animations.map(c=>[c.name,mixer.clipAction(c)]))
      for(const snapshot of headingSnapshots){
        root.position.fromArray(snapshot.rootPosition);root.quaternion.fromArray(snapshot.rootQuaternion)
        camera.position.fromArray(snapshot.cameraPosition);camera.quaternion.fromArray(snapshot.cameraQuaternion)
        for(const name of ['idle','special'])for(let step=0;step<=8;step++){
          const time=4*step/8
          mixer.stopAllAction();clips[name].reset().setLoop(T.LoopOnce,1);clips[name].clampWhenFinished=true;clips[name].play();mixer.setTime(time)
          measure(name,time)
        }
      }
      q.worst=worst;q.mixer=mixer;q.clips=clips
      if(worst){
        root.position.fromArray(worst.rootPosition);root.quaternion.fromArray(worst.rootQuaternion)
        camera.position.fromArray(worst.cameraPosition);camera.quaternion.fromArray(worst.cameraQuaternion)
        mixer.stopAllAction();clips[worst.action].reset().play();mixer.setTime(worst.time)
        root.updateMatrixWorld(true);camera.updateMatrixWorld(true)
        state.gl.render=q.render;q.render(state.scene,camera)
      }
      return {width:innerWidth,height:innerHeight,dom,minimum,counts,vertexSamples,walkCircleSeconds:circleSeconds,actualWalkYawSpan,walkFrameStepSeconds:circleSeconds/frames,standingHeadings:headingSnapshots.length,standingClipStepSeconds:.5,passed:Object.values(minimum).every(r=>r.pixels>=9)}
    })
    report.viewports.push(result)
    await page.screenshot({path:join(out,`${width}-worst.png`)})
    console.log(JSON.stringify({width,passed:result.passed,gaps:Object.fromEntries(Object.entries(result.minimum).map(([k,v])=>[k,v.pixels]))}))
    await writeFile(join(out,'report.json'),JSON.stringify(report,null,2)+'\n')
    await page.close()
  }
  report.passed=report.viewports.every(v=>v.passed)&&report.errors.length===0
  if(!report.passed)process.exitCode=1
}catch(error){report.failure=String(error);process.exitCode=1}
finally{await writeFile(join(out,'report.json'),JSON.stringify(report,null,2)+'\n');await browser.close()}
console.log(JSON.stringify({passed:report.passed,failure:report.failure,errors:report.errors}))
