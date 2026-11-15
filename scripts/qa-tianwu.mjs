// Actual Stage QA: compressed geometry soles, support phase, remount and actions.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { launchQABrowser } from './lib/browser.mjs'

const [base = 'http://localhost:5208', out = '/tmp/shanhai-tianwu-qa'] = process.argv.slice(2)
await mkdir(out, { recursive: true })
const layoutOnly=process.argv.includes('--layout-only')
const report = { passed: false, mode:layoutOnly?'layout-clearance':'complete', errors: [], actions: {}, support: [], remounts: [] }
const browser = await launchQABrowser()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
const sample = (name, time, locomotion = false) => page.evaluate(({ name, time, locomotion }) => window.tianwuQA.sample(name, time, locomotion), { name, time, locomotion })
async function ready() {
  await page.waitForFunction(() => !!window.tianwuQA)
  await page.waitForSelector('[data-stage-beast="tianwu"][data-stage-state="ready"]', { state: 'attached' })
}
try {
  await page.goto(`${base}/?beast=tianwu&action=idle`, { waitUntil: 'networkidle' })
  await ready()
  if(!layoutOnly) {
  const rest = await sample('idle', 0)
  for (const [name, t] of [['idle', 1.1], ['walk', 1.0], ['special', 2.5]]) {
    const s = await sample(name, t)
    assert.deepEqual(s.clips.sort(), ['idle', 'special', 'walk'])
    assert.equal(s.skins, 28)
    assert.equal(s.outlines, 28, 'StrictMode must leave one outline per visible native skin')
    assert.deepEqual(s.sharing,{headGeometries:1,tailGeometries:1,legGeometries:2,skeletons:28})
    assert.equal(s.feet.length, 8)
    assert(s.feet.every(f => f.count >= 5), 'All eight real geometric sole masks must be nonempty')
    assert(s.feet.every(f => f.points.flat().every(Number.isFinite)))
    let headDistanceDrift = 0
    for (const head of s.heads) {
      assert(head.points.length >= 12, `Missing complete face sample ${head.head}`)
      const original = rest.heads[head.head].points
      for (let i = 0; i < head.points.length; i++) for (let j = 0; j < i; j++) {
        const length = (p, q) => Math.hypot(...p.map((v, k) => v - q[k]))
        headDistanceDrift = Math.max(headDistanceDrift, Math.abs(length(head.points[i], head.points[j]) - length(original[i], original[j])))
      }
    }
    assert(headDistanceDrift < .001, `Human faces stretch by ${headDistanceDrift}m`)
    let pawDistanceDrift=0
    for(const foot of s.feet) {
      assert(foot.anchorVertexIds.length>=4,'Four actual palm edge anchors must be distinct')
      assert(foot.pawCount>foot.count,'Complete low paw mask must extend beyond sole contact points')
      const original=rest.feet.find(f=>f.foot===foot.foot).pawPoints
      for(let i=0;i<foot.pawPoints.length;i++)for(let j=0;j<i;j++) {
        const distance=(p,q)=>Math.hypot(...p.map((v,k)=>v-q[k]))
        pawDistanceDrift=Math.max(pawDistanceDrift,Math.abs(distance(foot.pawPoints[i],foot.pawPoints[j])-distance(original[i],original[j])))
      }
    }
    assert(pawDistanceDrift<.0001,`Native palm deforms by ${pawDistanceDrift}m`)
    report.actions[name] = { ...s, maximumHeadDistanceDriftM: headDistanceDrift, maximumPalmDistanceDriftM:pawDistanceDrift, image: join(out, `${name}.png`) }
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
    await page.screenshot({ path: report.actions[name].image })
  }
  // Actual circular locomotion: local targets compensate world position AND
  // yaw. Test the same compressed sole vertices after multiple full turns.
  const duty = .68
  for (let pair = 0; pair < 4; pair++) for (let side = 0; side < 2; side++) {
    const foot = pair * 2 + side, phase = (pair * .25 + (side ? .5 : 0)) % 1
    for (const cycle of [0, 10, 22, 45, 86]) for (const supportPhase of [.06, .24, .46, .56]) {
      const start = cycle * 4 + (supportPhase - phase + 1) % 1 * 4
      const a = await sample('walk', start, true)
      const b = await sample('walk', start + .32, true)
      const aa = a.feet.find(f => f.foot === foot).points
      const bb = b.feet.find(f => f.foot === foot).points
      assert(((start / 4 + phase) % 1) < duty)
      const drift = Math.max(...aa.map((p, i) => Math.hypot(...p.map((v, k) => bb[i][k] - v))))
      const groundSpread = Math.max(...aa.map(p => p[1]), ...bb.map(p => p[1])) - Math.min(...aa.map(p => p[1]), ...bb.map(p => p[1]))
      const verticalDrift = Math.max(...aa.map((p, i) => Math.abs(bb[i][1] - p[1])))
      report.support.push({ foot, cycle, supportPhase, start, elapsed: .32, maximumWorldSoleDriftM: drift, maximumVerticalDriftM: verticalDrift, nativeSoleHeightSpreadM: groundSpread })
      assert(drift < .0025, `Foot ${foot} slips ${drift}m during support`)
      assert(verticalDrift < .0015, `Foot ${foot} tips out of its initial ground plane`)
    }
  }
  report.route = []
  for (const fraction of [0, .125, .25, .375, .5, .625, .75, .875, 1, 1.5, 2]) {
    const t = fraction * rest.route.period
    const s = await sample('walk', t, true)
    const bounds = s.screenBounds
    report.route.push({ time: t, fraction, ...bounds })
    assert(bounds.minX > -.98 && bounds.maxX < .98 && bounds.minY > -.98 && bounds.maxY < .98, `Route leaves stage at turn ${fraction}: ${JSON.stringify(bounds)}`)
    if ([0, .25, .5, .75, 2].includes(fraction)) {
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
      await page.screenshot({ path: join(out, `turn-${fraction}.png`) })
    }
  }
  // A repeat selection exercises effect cleanup and prevents cached scene mutation.
  for (let i = 0; i < 2; i++) {
    await page.locator('.scroll-item', { hasText: '九尾狐' }).click()
    await page.waitForFunction(() => !window.tianwuQA)
    await page.locator('.scroll-item', { hasText: '天吴' }).click()
    await ready()
    const s = await sample('idle', .5)
    assert.equal(s.outlines, 28)
    assert.equal(s.skins, 28)
    report.remounts.push({ skins: s.skins, outlines: s.outlines })
  }
  await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
  report.inspectionCamera={before:await page.evaluate(()=>window.tianwuQA.cameraState())}
  assert(report.inspectionCamera.before.target.every((v,i)=>Math.abs(v-[0,.6,0][i])<1e-9),'Remount must restore Tianwu fixed camera target')
  report.details=[]
  for(const name of ['idle','walk','special']) for(const view of ['face','shoulder','hips','tails']) {
    await sample(name,name==='special'?2.5:1.1)
    await page.evaluate(view=>window.tianwuQA.view(view),view)
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
    const image=join(out,`${name}-${view}.png`);await page.screenshot({path:image});report.details.push({name,view,image})
  }
  await page.evaluate(()=>window.tianwuQA.view('restore'))
  await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
  report.inspectionCamera.after=await page.evaluate(()=>window.tianwuQA.cameraState())
  for(const key of ['position','quaternion','target'])assert(report.inspectionCamera.before[key].every((v,i)=>Math.abs(v-report.inspectionCamera.after[key][i])<1e-9),`Inspection changed shared camera ${key}`)
  for(const key of ['zoom','filmOffset','fov'])assert.equal(report.inspectionCamera.after[key],report.inspectionCamera.before[key],`Inspection changed shared camera ${key}`)
  }
  // Optionally test the coordinator's live shared stylesheet together with this
  // worktree's Tianwu-specific card extension, without changing shared sources.
  const sharedBase=process.env.TIANWU_SHARED_UI_BASE
  if(sharedBase) {
    const url=new URL('/src/app/global.css?direct',sharedBase).href
    const response=await fetch(url)
    assert(response.ok&&response.headers.get('content-type')?.includes('text/css'),'Shared UI stylesheet must be real CSS')
    await page.addStyleTag({content:await response.text()})
    report.sharedStylesheet=url
  }
  report.geometryClearance=[]
  for(const width of [1440,390,700]) {
    await page.setViewportSize({width,height:width===390?844:900})
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
    const rects=[]
    for(const selector of ['.card[data-beast="tianwu"]','.actions','.controls','.title','.scroll-wrap']) {
      const box=await page.locator(selector).boundingBox();assert(box,`Missing real UI ${selector}`)
      rects.push({name:selector,...box})
    }
    const period=(await sample('idle',0)).route.period
    for(const action of ['idle','walk','special'])for(let phase=0;phase<=32;phase++) {
      const time=phase/32*period
      let result=await page.evaluate(({action,time,rects})=>window.tianwuQA.clearance(action,time,rects,113),{action,time,rects})
      if(result.minimumPx<24)result=await page.evaluate(({action,time,rects})=>window.tianwuQA.clearance(action,time,rects,1),{action,time,rects})
      report.geometryClearance.push({width,action,phase:phase/32,time,...result})
    }
  }
  const narrowest=report.geometryClearance.reduce((a,b)=>a.minimumPx<b.minimumPx?a:b)
  assert(narrowest.minimumPx>=8,`Actual deformed geometry overlaps UI margin: ${JSON.stringify(narrowest)}`)
  report.responsive=[]
  for(const width of [390,700]) {
    await page.setViewportSize({width,height:width===390?844:900})
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
    for(const [name,label] of [['walk','行'],['special','神通'],['idle','静']]) {
      await page.evaluate(()=>window.tianwuQA.resume())
      await page.locator('.actions').getByRole('button',{name:label,exact:true}).click()
      await page.waitForFunction(name=>window.tianwuQA.useApp.getState().action===name,name)
      const before=await page.evaluate(()=>window.tianwuQA.observe())
      await page.waitForFunction(({before,name})=>{
        const after=window.tianwuQA.observe()
        return after.clock>before.clock&&after.head.some((v,i)=>Math.abs(v-before.head[i])>1e-8)&&(name!=='walk'||after.walkTime>before.walkTime)
      },{before,name},{timeout:30000})
      const after=await page.evaluate(()=>window.tianwuQA.observe())
      assert(after.clock>before.clock,`Real ${name} frame clock must advance`)
      assert(after.head.some((v,i)=>Math.abs(v-before.head[i])>1e-8),`Real ${name} native face must move`)
      if(name==='walk')assert(after.walkTime>before.walkTime,'Real walk route must advance')
    }
    const initial=await sample('idle',.5)
    const card=page.locator('.card[data-beast="tianwu"]'),box=await card.boundingBox()
    assert(box&&box.x>=0&&box.x+box.width<=width,'Source card fits viewport')
    const layout=await card.evaluate(el=>({scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,writingMode:getComputedStyle(el).writingMode,design:getComputedStyle(el.querySelector('.card-inferred')).display,source:el.querySelector('.card-source').textContent}))
    assert.equal(layout.writingMode,'horizontal-tb')
    assert.notEqual(layout.design,'none','Design disclosure remains available on mobile')
    assert(layout.source.includes('八首人面，八足八尾，背青黃。'))
    assert(layout.scrollHeight>layout.clientHeight,'Long source/design content scrolls')
    await card.evaluate(el=>{el.scrollTop=0})
    await page.mouse.move(box.x+100,box.y+100);await page.mouse.wheel(0,500)
    await page.waitForFunction(()=>document.querySelector('.card[data-beast="tianwu"]').scrollTop>0)
    const sourceWheel=await card.evaluate(el=>el.scrollTop)
    const design=await card.locator('.card-inferred').boundingBox()
    assert(design&&design.y<box.y+box.height&&design.y+design.height>box.y,'Wheel reveals design block')
    await page.mouse.move(design.x+30,Math.min(box.y+box.height-12,Math.max(box.y+12,design.y+30)));await page.mouse.wheel(0,-80)
    await page.waitForFunction(before=>document.querySelector('.card[data-beast="tianwu"]').scrollTop<before,sourceWheel)
    const designWheel=await card.evaluate(el=>el.scrollTop),after=await sample('idle',.5)
    assert(Math.abs(initial.screenBounds.minX-after.screenBounds.minX)<.0001,'Card wheel must not zoom the animal')
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal page overflow')
    await page.screenshot({path:join(out,`width-${width}.png`)})
    const controls=await page.locator('.controls').boundingBox(),actions=await page.locator('.actions').boundingBox(),selector=await page.locator('.scroll-wrap').boundingBox()
    assert(controls&&actions&&selector&&controls.y+controls.height<=selector.y&&actions.y+actions.height<=selector.y,'Controls/actions remain above the selector')
    report.responsive.push({width,...layout,sourceWheel,designWheel,coordinatorFinalPositionCompatibility:true,controls,actions,selector})
  }
  assert.equal(report.errors.length, 0, report.errors.join('\n'))
  report.passed = true
} catch (e) {
  report.failure = String(e)
  await page.screenshot({ path: join(out, 'failure.png') }).catch(() => {})
  throw e
} finally {
  await writeFile(join(out, 'report.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
console.log(JSON.stringify({ passed: report.passed, support: report.support, remounts: report.remounts }))
