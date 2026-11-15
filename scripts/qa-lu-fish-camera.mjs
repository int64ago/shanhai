// Exercise Lu's real useFrame/cleanup; two independent full circles + quarter
// circles ensure the unmount test has a nonzero follow translation to undo.
// node scripts/qa-lu-fish-camera.mjs BASE NEW_OUTPUT
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright-core'
const [base,outArg]=process.argv.slice(2)
assert(base&&outArg)
const out=resolve(outArg);await mkdir(out,{recursive:false})
const report={viewports:[],errors:[],passed:false}
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
try{
  for(const width of [390,700,1440]){
    const page=await browser.newPage({viewport:{width,height:900}})
    page.on('pageerror',e=>report.errors.push(String(e)))
    const ready=id=>page.waitForSelector(`[data-stage-beast="${id}"][data-stage-state="ready"]`,{state:'attached',timeout:60000})
    await page.goto(`${base}/?beast=lushu&action=idle`);await ready('lushu')
    await page.evaluate(async()=>{
      const urls=performance.getEntriesByType('resource').map(r=>r.name),mod=s=>urls.find(u=>new URL(u).pathname.endsWith(s))
      const fiber=await import(mod('/@react-three_fiber.js')),{useApp}=await import(mod('/src/app/store.ts'))
      const state=[...fiber._roots.values()][0].store.getState();state.setFrameloop('never')
      const render=state.gl.render.bind(state.gl);state.gl.render=()=>{}
      const q=window.cameraQA={state,useApp,render,step(seconds){let t=state.clock.elapsedTime;const n=Math.ceil(seconds/.05);for(let i=0;i<n;i++){t+=seconds/n;state.advance(t,true)}},snapshot(){return {camera:state.camera.position.toArray(),target:state.controls.target.toArray()}}}
      q.step(8);q.baseline=q.snapshot()
    })
    const rows=[]
    for(let trial=0;trial<2;trial++){
      await page.evaluate(()=>{const s=window.cameraQA.useApp.getState();s.select('lu_fish');s.setAction('idle')});await ready('lu_fish')
      await page.evaluate(()=>{const q=window.cameraQA;q.step(8);q.entry=q.snapshot()})
      await page.evaluate(()=>window.cameraQA.useApp.getState().setAction('walk'));await page.waitForTimeout(50)
      const walked=await page.evaluate(()=>{
        const q=window.cameraQA,root=q.state.scene.getObjectByName('lu_fish_root'),yaw=root.rotation.y
        const circle=2*Math.PI*1.05/.16;q.step(circle)
        const fullCircleYawSpan=root.rotation.y-yaw
        q.step(circle/4)
        const after=q.snapshot(),translation=after.camera.map((v,i)=>v-q.entry.camera[i]),position=root.position.toArray()
        return {fullCircleYawSpan,additionalQuarterCircle:true,translation,rootPosition:position,followError:Math.hypot(...translation.map((v,i)=>v-position[i])),translationMagnitude:Math.hypot(...translation),allFinite:[...after.camera,...after.target].every(Number.isFinite)}
      })
      assert(Math.abs(walked.fullCircleYawSpan-2*Math.PI)<.00001)
      assert(walked.translationMagnitude>1&&walked.followError<.000001&&walked.allFinite)
      await page.evaluate(()=>{const s=window.cameraQA.useApp.getState();s.select('lushu');s.setAction('idle')});await ready('lushu')
      const cleanup=await page.evaluate(()=>{const q=window.cameraQA;q.step(8);const after=q.snapshot(),baseline=q.baseline;return {baseline,after,cameraError:Math.hypot(...after.camera.map((v,i)=>v-baseline.camera[i])),targetError:Math.hypot(...after.target.map((v,i)=>v-baseline.target[i])),allFinite:[...after.camera,...after.target].every(Number.isFinite)}})
      assert(cleanup.cameraError<.000001&&cleanup.targetError<.000001&&cleanup.allFinite)
      rows.push({trial:trial+1,walked,cleanup})
    }
    report.viewports.push({width,trials:rows})
    await page.close()
  }
  assert.deepEqual(report.errors,[]);report.passed=true
}catch(error){report.failure=String(error);process.exitCode=1}
finally{await writeFile(join(out,'report.json'),JSON.stringify(report,null,2)+'\n');await browser.close()}
console.log(JSON.stringify(report,null,2))
