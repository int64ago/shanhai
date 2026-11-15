// Actual Stage / StrictMode assembly, sole contact and serpent support review.
// node scripts/qa-qiangliang.mjs http://localhost:5206 NEW_OUTPUT_DIR
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright-core'

const [base = 'http://localhost:5206', outputArg = 'raw/_build/qiangliang-app-qa'] = process.argv.slice(2)
const output = resolve(outputArg)
await mkdir(output, { recursive: false })
const report = { errors: [], images: [], motions: {}, remounts: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
const shot = async name => { const path = join(output, `${name}.png`); await page.screenshot({ path }); report.images.push(path) }
const action = async name => { await page.evaluate(a => window.qiangliangQA.useApp.getState().setAction(a), name) }
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready qiangliang'), timeout: 60000 })
  await page.goto(`${base}/?beast=qiangliang&action=idle`)
  await ready
  await page.waitForTimeout(700)
  report.anatomy = await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(u => new URL(u).pathname === '/src/app/store.ts'))
    const T = await import(resources.find(u => new URL(u).pathname.endsWith('/three.js')))
    const q = window.qiangliangQA = { T, useApp, state: [...fiber._roots.values()][0].store.getState() }
    q.root = () => q.state.scene.getObjectByName('qiangliang_root')
    q.mesh = () => q.root().getObjectByName('qiangliang_native_body')
    q.snapshot = () => {
      let bodies = 0, serpents = 0, outlines = 0, invalid = 0
      q.root().traverse(n => {
        if (n.isMesh) {
          if (n.userData.inkOutline) outlines++
          else if (n.name === 'qiangliang_supported_serpent') serpents++
          else bodies++
          for (const key of ['position', 'normal', 'skinWeight']) {
            const a = n.geometry.attributes[key]
            if (a && !Array.from(a.array).every(Number.isFinite)) invalid++
          }
        }
        if (!n.matrixWorld.elements.every(Number.isFinite)) invalid++
      })
      let supportDrift = 0
      for (const name of ['mouth_snake', 'held_snake']) {
        const holder = q.root().getObjectByName(name)
        if (!holder || !holder.parent.isBone) throw new Error('Missing serpent support '+name)
        supportDrift = Math.max(supportDrift, holder.getWorldPosition(new T.Vector3()).distanceTo(holder.parent.getWorldPosition(new T.Vector3())))
      }
      return { bodies, serpents, outlines, invalid, supportDrift }
    }
    q.state.scene.updateMatrixWorld(true)
    const mesh = q.mesh(), g = mesh.geometry.attributes
    mesh.skeleton.update()
    const root = mesh.skeleton.bones.find(b => b.name === 'root'), i = mesh.skeleton.bones.indexOf(root)
    const matrix = q.root().matrixWorld.clone().invert().multiply(mesh.matrixWorld).multiply(mesh.bindMatrixInverse)
      .multiply(root.matrixWorld).multiply(mesh.skeleton.boneInverses[i]).multiply(mesh.bindMatrix)
    q.soles = { l: [], r: [] }
    q.feet = { l: [], r: [] }
    let maxFootWeightError = 0
    for (let v = 0; v < g.position.count; v++) {
      const p = new T.Vector3().fromBufferAttribute(g.position, v).applyMatrix4(matrix)
      if (p.y < 1.65 * .105 - .00003) {
        const side = p.x > 0 ? 'l' : 'r'
        q.feet[side].push(v)
        if (p.y < .0029) q.soles[side].push(v)
        let weight = 0
        for (let j = 0; j < 4; j++) if (mesh.skeleton.bones[g.skinIndex.getComponent(v, j)]?.name === `leg_${side}_foot`) weight += g.skinWeight.getComponent(v, j)
        maxFootWeightError = Math.max(maxFootWeightError, 1 - weight)
      }
    }
    q.points = ids => {
      const mesh = q.mesh(), p = new T.Vector3()
      q.state.scene.updateMatrixWorld(true); mesh.skeleton.update()
      return ids.map(i => { mesh.getVertexPosition(i, p); mesh.localToWorld(p); return p.toArray() })
    }
    return { ...q.snapshot(), triangles: mesh.geometry.index.count / 3, bones: mesh.skeleton.bones.length,
      maxFootWeightError, soles: Object.fromEntries(Object.entries(q.soles).map(([s, v]) => [s, v.length])) }
  })
  assert.equal(report.anatomy.bodies, 1)
  assert.equal(report.anatomy.serpents, 2)
  assert.equal(report.anatomy.outlines, 3)
  assert.equal(report.anatomy.invalid, 0)
  assert.equal(report.anatomy.triangles, 50000)
  assert(report.anatomy.maxFootWeightError < .0001)
  assert(Object.values(report.anatomy.soles).every(n => n > 10))
  for (const name of ['idle', 'walk', 'special']) {
    await action('idle'); await page.waitForTimeout(400)
    await action(name); await page.waitForTimeout(450)
    const result = { samples: 0, maxStanceDrift: 0, minSoleHeight: Infinity, maxSupportDrift: 0, cycles: 0 }
    const plants = new Map()
    let previous = null
    for (let sample = 0; sample < (name === 'walk' ? 165 : 26); sample++) {
      const data = await page.evaluate(() => {
        const q = window.qiangliangQA
        return { action: q.useApp.getState().action, time: q.root().userData.animationTime,
          feet: Object.fromEntries(['l', 'r'].map(s => [s, q.points(q.soles[s])])), ...q.snapshot() }
      })
      if (data.action !== name) break
      assert.equal(data.invalid, 0)
      assert.equal(data.serpents, 2)
      assert.equal(data.outlines, 3)
      if (previous !== null && data.time < previous) result.cycles++
      previous = data.time
      result.maxSupportDrift = Math.max(result.maxSupportDrift, data.supportDrift)
      for (const side of ['l', 'r']) {
        const points = data.feet[side]
        result.minSoleHeight = Math.min(result.minSoleHeight, ...points.map(p => p[1]))
        const raw = result.cycles + data.time / 2.4 + (side === 'r' ? .5 : 0)
        if (name === 'walk' && (raw % 1 < .025 || raw % 1 > .635)) continue
        const key = side + '/' + (name === 'walk' ? Math.floor(raw) : 0)
        if (!plants.has(key)) plants.set(key, points)
        const initial = plants.get(key)
        for (let i = 0; i < points.length; i++) result.maxStanceDrift = Math.max(result.maxStanceDrift, Math.hypot(...points[i].map((v, k) => v - initial[i][k])))
      }
      result.samples++
      await page.waitForTimeout(50)
    }
    report.motions[name] = result
    assert(result.maxStanceDrift < .0015, `${name} stance drift ${result.maxStanceDrift}`)
    assert(result.minSoleHeight > -.002, `${name} ground penetration`)
    assert(result.maxSupportDrift < 1e-6)
    if (name === 'walk') assert(result.cycles >= 2)
    if (name === 'special') await page.waitForFunction(() => window.qiangliangQA.useApp.getState().action === 'idle', null, { timeout: 6500 })
  }
  await action('idle'); await page.waitForTimeout(500); await shot('desktop-idle')
  await page.addStyleTag({ content: '.qa-anatomy-only .card,.qa-anatomy-only .story-caption,.qa-anatomy-only .scroll-wrap,.qa-anatomy-only .controls,.qa-anatomy-only .actions,.qa-anatomy-only .title{visibility:hidden!important}' })
  await page.evaluate(() => { const q = window.qiangliangQA, c = q.state.controls; c.target.lerp = function () { return this }; c.minDistance = .2; c.enableDamping = false; document.body.classList.add('qa-anatomy-only') })
  for (const [name, target, direction, distance] of [
    ['front', [0, .85, 0], [0, .1, 1], 3.5],
    ['side', [0, .85, 0], [1, .1, 0], 3.5],
    ['back', [0, .85, 0], [0, .1, -1], 3.5],
    ['mouth', [0, 1.43, .24], [.3, .12, 1], 1.05],
    ['held', [.50, .84, .05], [.5, .2, 1], 1.1],
    ['feet', [0, .13, .05], [.3, .4, 1], 1.2],
  ]) {
    await page.evaluate(({ target, direction, distance }) => {
      const q = window.qiangliangQA, t = new q.T.Vector3(...target).applyMatrix4(q.root().matrixWorld)
      q.state.camera.filmOffset = 0; q.state.camera.updateProjectionMatrix()
      q.state.controls.target.copy(t)
      q.state.camera.position.copy(t).add(new q.T.Vector3(...direction).normalize().multiplyScalar(distance).applyQuaternion(q.root().quaternion))
      q.state.controls.update()
    }, { target, direction, distance })
    await shot('anatomy-' + name)
  }
  await action('idle')
  for (let cycle = 0; cycle < 2; cycle++) {
    const away = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready jiuweihu'), timeout: 30000 })
    await page.evaluate(async () => { const { useApp } = await import('/src/app/store.ts'); useApp.getState().select('jiuweihu') }); await away
    const back = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready qiangliang'), timeout: 30000 })
    await page.evaluate(async () => { const { useApp } = await import('/src/app/store.ts'); useApp.getState().select('qiangliang') }); await back
    await page.waitForTimeout(200)
    const snapshot = await page.evaluate(() => window.qiangliangQA.snapshot())
    report.remounts.push(snapshot)
    assert.equal(snapshot.bodies, 1); assert.equal(snapshot.serpents, 2); assert.equal(snapshot.outlines, 3); assert.equal(snapshot.invalid, 0)
  }
  assert.equal(report.errors.length, 0, report.errors.join('\n'))
  report.passed = true
} finally {
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n')
  await browser.close()
}
console.log(JSON.stringify({ passed: report.passed, report: join(output, 'report.json') }))
