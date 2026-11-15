// Actual stage QA: four supported yellow serpents, complete feet and StrictMode.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright-core'

const [base = 'http://localhost:5206', directory = 'raw/_build/kuafu-stage-qa'] = process.argv.slice(2)
const output = resolve(directory)
await mkdir(output, { recursive: false })
const report = { errors: [], images: [], motions: {}, remounts: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
const action = name => page.evaluate(a => window.kuafuQA.useApp.getState().setAction(a), name)
const shot = async name => { const path = join(output, name + '.png'); await page.screenshot({ path }); report.images.push(path) }
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready kuafu'), timeout: 60000 })
  await page.goto(`${base}/?beast=kuafu&action=idle`)
  await ready
  await page.waitForTimeout(700)
  report.anatomy = await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import('/src/app/store.ts')
    const T = await import(resources.find(u => new URL(u).pathname.endsWith('/three.js')))
    const q = window.kuafuQA = { T, useApp, state: [...fiber._roots.values()][0].store.getState() }
    q.root = () => q.state.scene.getObjectByName('kuafu_root')
    q.meshes = () => { const list = []; q.root().traverse(n => { if (n.isMesh && !n.userData.inkOutline) list.push(n) }); return list }
    q.snapshot = () => {
      let outlines = 0, invalid = 0
      const held = new Set(), ears = new Set()
      q.root().traverse(n => {
        if (n.isMesh) {
          if (n.userData.inkOutline) outlines++
          else if (n.parent?.name.startsWith('kuafu_held_snake_')) held.add(n.parent.name)
          else if (n.name === 'kuafu_ear_snake') ears.add(n.uuid)
          for (const key of ['position', 'normal', 'skinWeight']) {
            const a = n.geometry.attributes[key]
            if (a && !Array.from(a.array).every(Number.isFinite)) invalid++
          }
        }
        if (!n.matrixWorld.elements.every(Number.isFinite)) invalid++
      })
      let supportDrift = 0
      for (const side of ['l', 'r']) {
        const holder = q.root().getObjectByName(`ear_${side}_snake_holder`)
        if (!holder?.parent.isBone) throw new Error('Missing supported ear serpent')
        supportDrift = Math.max(supportDrift, holder.getWorldPosition(new T.Vector3()).distanceTo(holder.parent.getWorldPosition(new T.Vector3())))
      }
      return { held: held.size, ears: ears.size, outlines, invalid, supportDrift, meshes: q.meshes().length }
    }
    q.state.scene.updateMatrixWorld(true)
    q.soles = { l: [], r: [] }
    q.grips = []
    let maxFootWeightError = 0, footVertices = 0, bodyTriangles = 0
    for (const mesh of q.meshes()) {
      if (!mesh.isSkinnedMesh) throw new Error('Unskinned anatomy ' + mesh.name)
      const g = mesh.geometry.attributes
      mesh.skeleton.update()
      const root = mesh.skeleton.bones.find(b => b.name === 'root')
      if (!root) continue
      const index = mesh.skeleton.bones.indexOf(root)
      const matrix = q.root().matrixWorld.clone().invert().multiply(mesh.matrixWorld).multiply(mesh.bindMatrixInverse)
        .multiply(root.matrixWorld).multiply(mesh.skeleton.boneInverses[index]).multiply(mesh.bindMatrix)
      const body = mesh.parent?.name === 'kuafu_native_body'
      if (body) bodyTriangles += mesh.geometry.index.count / 3
      const serpent = mesh.parent?.name.match(/^kuafu_held_snake_([lr])/)
      for (let v = 0; v < g.position.count; v++) {
        const p = new T.Vector3().fromBufferAttribute(g.position, v).applyMatrix4(matrix)
        if (body && p.y < 1.9 * .068 - .00003) {
          const side = p.x > 0 ? 'l' : 'r'
          footVertices++
          if (p.y < .0034) q.soles[side].push({ mesh, v })
          let weight = 0
          for (let j = 0; j < 4; j++) if (mesh.skeleton.bones[g.skinIndex.getComponent(v, j)]?.name === `leg_${side}_foot`) weight += g.skinWeight.getComponent(v, j)
          maxFootWeightError = Math.max(maxFootWeightError, 1 - weight)
        }
        if (serpent) {
          const side = serpent[1], bone = mesh.skeleton.bones.find(b => b.name === `arm_${side}_hand`)
          let weight = 0
          for (let j = 0; j < 4; j++) if (mesh.skeleton.bones[g.skinIndex.getComponent(v, j)]?.name === `held_${side}_root`) weight += g.skinWeight.getComponent(v, j)
          if (weight > .9999 && v % 8 === 0) {
            const world = mesh.localToWorld(mesh.getVertexPosition(v, new T.Vector3()))
            q.grips.push({ mesh, v, bone, initial: bone.worldToLocal(world).toArray() })
          }
        }
      }
    }
    q.points = entries => entries.map(({ mesh, v }) => {
      mesh.skeleton.update()
      return mesh.localToWorld(mesh.getVertexPosition(v, new T.Vector3())).toArray()
    })
    q.gripDrift = () => {
      let maximum = 0
      for (const { mesh, v, bone, initial } of q.grips) {
        mesh.skeleton.update()
        const p = bone.worldToLocal(mesh.localToWorld(mesh.getVertexPosition(v, new T.Vector3())))
        maximum = Math.max(maximum, p.distanceTo(new T.Vector3(...initial)))
      }
      return maximum
    }
    return { ...q.snapshot(), meshNames: q.meshes().map(m => [m.name, m.parent.name]), bodyTriangles, footVertices, maxFootWeightError, gripVertices: q.grips.length,
      soleVertices: Object.fromEntries(Object.entries(q.soles).map(([s, a]) => [s, a.length])) }
  })
  assert.equal(report.anatomy.held, 2)
  assert.equal(report.anatomy.ears, 2)
  assert.equal(report.anatomy.invalid, 0)
  assert(report.anatomy.outlines >= 5)
  assert(report.anatomy.bodyTriangles > 100000)
  assert(report.anatomy.maxFootWeightError < .0001)
  assert(report.anatomy.gripVertices > 20)
  assert(Object.values(report.anatomy.soleVertices).every(n => n > 10))
  for (const name of ['idle', 'walk', 'special']) {
    await action('idle'); await page.waitForTimeout(500)
    await action(name); await page.waitForTimeout(450)
    const result = { samples: 0, cycles: 0, maxStanceDrift: 0, minSoleHeight: Infinity, maxGripDrift: 0, maxSupportDrift: 0 }
    const plants = new Map()
    let previous = null
    for (let sample = 0; sample < (name === 'walk' ? 150 : 26); sample++) {
      const data = await page.evaluate(() => {
        const q = window.kuafuQA
        q.state.scene.updateMatrixWorld(true)
        return { action: q.useApp.getState().action, time: q.root().userData.animationTime,
          feet: Object.fromEntries(['l', 'r'].map(s => [s, q.points(q.soles[s])])), gripDrift: q.gripDrift(), ...q.snapshot() }
      })
      if (data.action !== name) break
      assert.equal(data.invalid, 0); assert.equal(data.held, 2); assert.equal(data.ears, 2)
      assert.equal(data.outlines, report.anatomy.outlines)
      if (previous !== null && data.time < previous) result.cycles++
      previous = data.time
      result.maxGripDrift = Math.max(result.maxGripDrift, data.gripDrift)
      result.maxSupportDrift = Math.max(result.maxSupportDrift, data.supportDrift)
      for (const side of ['l', 'r']) {
        const points = data.feet[side]
        result.minSoleHeight = Math.min(result.minSoleHeight, ...points.map(p => p[1]))
        const raw = result.cycles + data.time / 2.6 + (side === 'r' ? .5 : 0)
        if (name === 'walk' && (raw % 1 < .025 || raw % 1 > .645)) continue
        const key = side + '/' + (name === 'walk' ? Math.floor(raw) : 0)
        if (!plants.has(key)) plants.set(key, points)
        const initial = plants.get(key)
        for (let i = 0; i < points.length; i++) result.maxStanceDrift = Math.max(result.maxStanceDrift, Math.hypot(...points[i].map((v, k) => v - initial[i][k])))
      }
      result.samples++
      await page.waitForTimeout(60)
    }
    report.motions[name] = result
    assert(result.maxStanceDrift < .0015, `${name} sliding ${result.maxStanceDrift}`)
    assert(result.minSoleHeight > -.002)
    assert(result.maxGripDrift < .0001, `${name} grip drift ${result.maxGripDrift}`)
    assert(result.maxSupportDrift < 1e-6)
    if (name === 'walk') assert(result.cycles >= 2)
    if (name === 'special') await page.waitForFunction(() => window.kuafuQA.useApp.getState().action === 'idle', null, { timeout: 6500 })
  }
  // Drive the real R3F clock at 20 Hz for 80 simulated seconds per viewport.
  // This covers a full circular walk, including the closest and farthest camera
  // distances, while projecting actual deformed surface vertices against UI.
  report.framing = {}
  for (const [label, width, height] of [['desktop', 1440, 900], ['phone', 390, 844]]) {
    await page.setViewportSize({ width, height })
    await action('idle'); await page.waitForTimeout(500)
    await page.evaluate(() => {
      const q = window.kuafuQA
      q.state.camera.position.set(3.2, 1.3, 3.8)
      q.state.controls.target.set(0, .6, 0)
      q.state.controls.update()
      q.state.setFrameloop('never')
      q.frameTime = 0
      q.step = count => {
        for (let i = 0; i < count; i++) q.state.advance(q.frameTime += .05, false)
      }
      q.frameBounds = () => {
        q.state.scene.updateMatrixWorld(true)
        const padding = 8, width = innerWidth, height = innerHeight
        const overlays = [...document.querySelectorAll('.card,.scroll-wrap,.actions,.controls,.title')]
          .filter(e => getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden')
          .map(e => { const r = e.getBoundingClientRect(); return { name: e.className, left: r.left, top: r.top, right: r.right, bottom: r.bottom } })
        const bounds = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity }
        const feet = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity }
        let violations = 0
        const examples = []
        for (const mesh of q.meshes()) {
          mesh.skeleton.update()
          const g = mesh.geometry.attributes
          const body = mesh.parent?.name === 'kuafu_native_body'
          for (let v = 0; v < g.position.count; v++) {
            const p = mesh.localToWorld(mesh.getVertexPosition(v, new q.T.Vector3()))
            const foot = body && p.y < .20
            p.project(q.state.camera)
            const x = (p.x + 1) * width / 2, y = (1 - p.y) * height / 2
            bounds.left = Math.min(bounds.left, x); bounds.right = Math.max(bounds.right, x)
            bounds.top = Math.min(bounds.top, y); bounds.bottom = Math.max(bounds.bottom, y)
            if (foot) {
              feet.left = Math.min(feet.left, x); feet.right = Math.max(feet.right, x)
              feet.top = Math.min(feet.top, y); feet.bottom = Math.max(feet.bottom, y)
            }
            const hit = overlays.find(r => x > r.left - padding && x < r.right + padding && y > r.top - padding && y < r.bottom + padding)
            if (hit || x < padding || x > width - padding || y < padding || y > height - padding || Math.abs(p.z) > 1) {
              violations++
              if (examples.length < 3) examples.push({ mesh: mesh.name, x, y, overlay: hit?.name ?? 'viewport' })
            }
          }
        }
        return { bounds, feet, overlays, violations, examples, angle: Math.atan2(q.root().position.z, q.root().position.x) }
      }
      q.step(100)
    })
    const result = { width, height, simulatedWalkSeconds: 80, walkRadians: 0, samples: 0, maxViolations: 0, frames: [], extremes: {} }
    for (const name of ['idle', 'walk', 'special']) {
      await action(name); await page.waitForTimeout(30)
      let previous = null
      const batches = name === 'walk' ? 80 : 8
      for (let batch = 0; batch < batches; batch++) {
        const data = await page.evaluate(count => { const q = window.kuafuQA; q.step(count); return q.frameBounds() }, name === 'walk' ? 20 : 10)
        if (name === 'walk' && previous !== null) {
          let delta = data.angle - previous
          if (delta < -Math.PI) delta += Math.PI * 2
          if (delta > Math.PI) delta -= Math.PI * 2
          result.walkRadians += Math.abs(delta)
        }
        previous = data.angle
        result.samples++
        result.maxViolations = Math.max(result.maxViolations, data.violations)
        result.frames.push({ action: name, batch, ...data })
        for (const [key, value, better] of [
          ['highest-head', data.bounds.top, (a, b) => a < b],
          ['lowest-feet', data.feet.bottom, (a, b) => a > b],
        ]) {
          if (!result.extremes[key] || better(value, result.extremes[key].value)) {
            await shot(`${label}-${key}`)
            result.extremes[key] = { value, action: name, batch, image: join(output, `${label}-${key}.png`), ...data }
          }
        }
        assert.equal(data.violations, 0, `${label}/${name}/${batch} UI occlusion: ${JSON.stringify(data.examples)}`)
        if (name === 'walk' && batch % 20 === 19) await shot(`${label}-circle-${(batch + 1) / 20}`)
        if (batch === (name === 'walk' ? 1 : 3)) await shot(`${label}-${name}`)
      }
    }
    assert(result.walkRadians > Math.PI * 2, `${label} did not cover a complete circle`)
    report.framing[label] = result
    await page.evaluate(() => window.kuafuQA.state.setFrameloop('always'))
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await action('idle'); await page.waitForTimeout(500); await shot('desktop-idle')
  await page.addStyleTag({ content: '.qa-anatomy-only .card,.qa-anatomy-only .story-caption,.qa-anatomy-only .scroll-wrap,.qa-anatomy-only .controls,.qa-anatomy-only .actions,.qa-anatomy-only .title{visibility:hidden!important}' })
  await page.evaluate(() => { const q = window.kuafuQA, c = q.state.controls; c.target.lerp = function () { return this }; c.minDistance = .15; c.enableDamping = false; document.body.classList.add('qa-anatomy-only') })
  for (const [name, target, direction, distance] of [
    ['front', [0, .98, 0], [0, .1, 1], 3.7], ['side', [0, .98, 0], [1, .1, 0], 3.7], ['back', [0, .98, 0], [0, .1, -1], 3.7],
    ['hand-l', [.44, 1.18, .145], [.3, .15, 1], .72], ['hand-r', [-.45, 1.18, .137], [-.3, .15, 1], .72],
    ['grip-side', [.44, 1.18, .145], [1, .1, -.2], .72],
    ['ear-l', [.122, 1.73, -.046], [1, .1, .2], .56], ['ear-r', [-.122, 1.73, -.046], [-1, .1, .2], .56],
    ['feet', [0, .13, -.05], [.3, .35, 1], 1.2],
  ]) {
    await page.evaluate(({ target, direction, distance }) => {
      const q = window.kuafuQA, t = new q.T.Vector3(...target).applyMatrix4(q.root().matrixWorld)
      q.state.camera.filmOffset = 0; q.state.camera.updateProjectionMatrix(); q.state.controls.target.copy(t)
      q.state.camera.position.copy(t).add(new q.T.Vector3(...direction).normalize().multiplyScalar(distance).applyQuaternion(q.root().quaternion))
      q.state.controls.update()
    }, { target, direction, distance })
    await shot('anatomy-' + name)
  }
  for (let cycle = 0; cycle < 2; cycle++) {
    const away = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready jiuweihu'), timeout: 30000 })
    await page.evaluate(async () => { const { useApp } = await import('/src/app/store.ts'); useApp.getState().select('jiuweihu') }); await away
    const back = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready kuafu'), timeout: 30000 })
    await page.evaluate(async () => { const { useApp } = await import('/src/app/store.ts'); useApp.getState().select('kuafu') }); await back
    await page.waitForTimeout(200)
    const snapshot = await page.evaluate(() => window.kuafuQA.snapshot())
    report.remounts.push(snapshot)
    assert.equal(snapshot.held, 2); assert.equal(snapshot.ears, 2); assert.equal(snapshot.outlines, report.anatomy.outlines); assert.equal(snapshot.invalid, 0)
  }
  assert.equal(report.errors.length, 0, report.errors.join('\n'))
  report.passed = true
} finally {
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n')
  await browser.close()
}
console.log(JSON.stringify({ passed: report.passed, report: join(output, 'report.json') }))
