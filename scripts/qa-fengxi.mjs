// Integrated Fengxi QA: actual runtime skinning, sole contacts, transitions and audio.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const [base = 'http://localhost:5215', output = '/tmp/shanhai-check/fengxi-integrated'] = process.argv.slice(2)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = [], report = { errors }
page.on('pageerror', e => errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`) })
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready fengxi') })
  await page.goto(`${base}/?beast=fengxi&action=idle`)
  await ready
  await page.evaluate(async () => {
    const loaded = path => performance.getEntriesByType('resource').map(r => r.name).find(u => new URL(u).pathname === path)
    const fiberUrl = performance.getEntriesByType('resource').map(r => r.name).find(u => u.includes('@react-three_fiber.js'))
    const fiber = await import(fiberUrl)
    const { useApp } = await import(loaded('/src/app/store.ts'))
    const { AnimationMixer } = await import(loaded('/node_modules/.vite/deps/three.js'))
    const original = AnimationMixer.prototype.update
    AnimationMixer.prototype.update = function (dt) {
      if (this.getRoot().name === 'Fengxi_CachedScene') window.fengxiQA.mixer = this
      return original.call(this, dt)
    }
    window.fengxiQA = { useApp, state: [...fiber._roots.values()][0].store.getState(), loaded }
  })
  await page.waitForFunction(() => window.fengxiQA.mixer)
  const inspect = () => page.evaluate(() => {
    const root = window.fengxiQA.state.scene.getObjectByName('Fengxi')
    const result = { bodies: 0, outlines: 0, washes: 0, bones: 0, nodes: 0, invalid: 0 }
    window.fengxiQA.state.scene.updateMatrixWorld(true)
    root.traverse(o => {
      result.nodes++
      if (![...o.matrixWorld.elements, ...o.position, ...o.quaternion, ...o.scale].every(Number.isFinite) || Math.min(...o.scale) <= 0) result.invalid++
      if (o.isBone) result.bones++
      if (o.userData.inkOutline) { result.outlines++; return }
      if (o.name === 'Fengxi_PearlWash') result.washes++
      if (!o.isSkinnedMesh) return
      result.bodies++
      for (const a of Object.values(o.geometry.attributes)) if (!Array.from(a.array).every(Number.isFinite)) result.invalid++
      o.skeleton.update()
      if (!Array.from(o.skeleton.boneMatrices).every(Number.isFinite)) result.invalid++
      const v = o.position.clone()
      for (let i = 0; i < o.geometry.attributes.position.count; i++) {
        o.getVertexPosition(i, v)
        if (![...v].every(Number.isFinite)) result.invalid++
      }
    })
    return result
  })
  report.baseline = await inspect()
  assert.equal(report.baseline.bodies, 3)
  assert.equal(report.baseline.outlines, 3)
  assert.equal(report.baseline.washes, 0)
  assert.equal(report.baseline.bones, 20)
  assert.equal(report.baseline.invalid, 0)
  report.actions = {}
  for (const action of ['walk', 'special']) {
    await page.evaluate(a => window.fengxiQA.useApp.getState().setAction(a), action)
    report.actions[action] = []
    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(180)
      const stats = await inspect()
      assert.equal(stats.invalid, 0)
      report.actions[action].push(stats)
    }
    if (action === 'special') await page.screenshot({ path: join(output, 'special-peak.png') })
  }
  await page.waitForFunction(() => window.fengxiQA.useApp.getState().action === 'idle', { timeout: 20000 })
  report.specialReturnedIdle = true
  await page.evaluate(() => {
    const qa = window.fengxiQA
    qa.useApp.getState().setAction('idle')
    qa.state.setFrameloop('never')
  })
  await page.waitForTimeout(100)
  await page.evaluate(() => {
    const qa = window.fengxiQA, s = qa.state, root = s.scene.getObjectByName('Fengxi')
    const mixer = qa.mixer
    for (const a of mixer._actions) a.stop()
    const idle = mixer._actions.find(a => a.getClip().name === 'idle')
    idle.reset().setEffectiveWeight(1).play()
    mixer.update(0)
    root.updateWorldMatrix(true, true)
    const names = ['back_l', 'front_l', 'back_r', 'front_r']
    const feet = names.map(name => ({ name, bone: root.getObjectByName(`${name}_foot`), markers: [] }))
    const p = root.position.clone()
    root.traverse(mesh => {
      if (!mesh.isSkinnedMesh || mesh.userData.inkOutline) return
      mesh.skeleton.update()
      for (let i = 0; i < mesh.geometry.attributes.position.count; i++) {
        mesh.getVertexPosition(i, p); mesh.localToWorld(p)
        if (p.y > .004) continue
        const nearest = feet.reduce((a, b) => p.distanceToSquared(a.bone.getWorldPosition(root.position.clone())) < p.distanceToSquared(b.bone.getWorldPosition(root.position.clone())) ? a : b)
        nearest.markers.push({ mesh, index: i })
      }
    })
    if (feet.some(f => f.markers.length < 3)) throw new Error('Missing hoof sole vertices')
    qa.feet = feet
    qa.useApp.getState().setAction('walk')
  })
  await page.waitForTimeout(100)
  report.stance = await page.evaluate(() => {
    const qa = window.fengxiQA, s = qa.state, root = s.scene.getObjectByName('Fengxi')
    const walk = qa.mixer._actions.find(a => a.getClip().name === 'walk')
    for (const a of qa.mixer._actions) if (a !== walk) a.stop()
    walk.reset().setEffectiveWeight(1).play()
    const feet = qa.feet.map(f => ({ ...f, anchor: null, flat: null, boneAnchor: null, boneDrift: 0, worst: null, cycle: -1, displacement: 0, rotation: 0, samples: 0 }))
    let now = s.clock.elapsedTime
    const render = s.gl.render
    s.gl.render = () => {}
    try {
      for (let frame = 0; frame < 600; frame++) {
        now += 1 / 60; s.advance(now, true)
        // SkinnedMesh.updateMatrixWorld refreshes attached bindMatrixInverse;
        // updateWorldMatrix alone skips that override when rendering is paused.
        s.scene.updateMatrixWorld(true)
        root.traverse(o => { if (o.skeleton) o.skeleton.update() })
        const phase = walk.time / walk.getClip().duration
        for (const [i, foot] of feet.entries()) {
          const p = (phase + i / 4) % 1, cycle = Math.floor(phase + i / 4)
          if (frame < 30 || p < .04 || p > .64) { foot.anchor = null; continue }
          const points = foot.markers.map(({ mesh, index }) => {
            const v = root.position.clone(); mesh.getVertexPosition(index, v); return mesh.localToWorld(v)
          })
          const q = foot.bone.getWorldQuaternion(root.quaternion.clone()).normalize()
          const bonePoint = foot.bone.getWorldPosition(root.position.clone())
          if (!foot.anchor || foot.cycle !== cycle) { foot.anchor = points; foot.flat = q; foot.cycle = cycle; foot.boneAnchor = bonePoint }
          foot.boneDrift = Math.max(foot.boneDrift, bonePoint.distanceTo(foot.boneAnchor))
          foot.samples++
          for (let j = 0; j < points.length; j++) {
            const distance = points[j].distanceTo(foot.anchor[j])
            if (distance > foot.displacement) {
              foot.displacement = distance
              const { mesh, index } = foot.markers[j], skin = mesh.geometry.attributes.skinIndex, weights = mesh.geometry.attributes.skinWeight
              foot.worst = { phase: p, frame, index, first: foot.anchor[j].toArray(), last: points[j].toArray(), bones: [0, 1, 2, 3].map(k => ({ name: mesh.skeleton.bones[skin.getComponent(index, k)]?.name, weight: weights.getComponent(index, k) })) }
            }
          }
          foot.rotation = Math.max(foot.rotation, q.angleTo(foot.flat))
        }
      }
    } finally { s.gl.render = render }
    return feet.map(f => ({ name: f.name, soleVertices: f.markers.length, samples: f.samples, maxStanceDisplacement: f.displacement, maxStanceRotation: f.rotation, boneDrift: f.boneDrift, worst: f.worst }))
  })
  assert(report.stance.every(f => f.samples > 100 && f.maxStanceDisplacement < .001 && f.maxStanceRotation < .002), JSON.stringify(report.stance))
  await page.evaluate(() => { window.fengxiQA.state.setFrameloop('always'); window.fengxiQA.useApp.getState().setAction('idle') })
  await page.waitForTimeout(400)
  const before = await page.evaluate(() => {
    const root = window.fengxiQA.state.scene.getObjectByName('Fengxi')
    return { p: root.position.toArray(), yaw: root.rotation.y }
  })
  await page.evaluate(() => window.fengxiQA.useApp.getState().setAction('walk'))
  await page.waitForTimeout(70)
  const after = await page.evaluate(() => {
    const root = window.fengxiQA.state.scene.getObjectByName('Fengxi')
    return { p: root.position.toArray(), yaw: root.rotation.y }
  })
  report.walkReentry = { before, after }
  assert(Math.hypot(...after.p.map((x, i) => x - before.p[i])) < .08)
  assert(Math.abs(after.yaw - before.yaw) < .08)
  report.remounts = []
  for (let i = 0; i < 3; i++) {
    let ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready lili') })
    await page.evaluate(() => window.fengxiQA.useApp.getState().select('lili')); await ready
    ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready fengxi') })
    await page.evaluate(() => window.fengxiQA.useApp.getState().select('fengxi')); await ready
    const stats = await inspect()
    assert.deepEqual(stats, report.baseline)
    report.remounts.push(stats)
  }
  await page.locator('.story-btn').click()
  await page.waitForTimeout(1400)
  report.audio = await page.evaluate(async () => {
    const { audio } = await import(window.fengxiQA.loaded('/src/systems/audio/AudioEngine.ts'))
    audio.fengxiCall(0)
    const el = audio.narrationEl
    const bytes = await (await fetch('/audio/narration/fengxi.mp3')).arrayBuffer()
    const context = new AudioContext()
    const buffer = await context.decodeAudioData(bytes)
    let energy = 0
    for (const value of buffer.getChannelData(0)) energy += value * value
    await context.close()
    return { duration: el.duration, currentTime: el.currentTime, error: el.error, context: audio.context?.state, rms: Math.sqrt(energy / buffer.length) }
  })
  assert(report.audio.currentTime > 0 && report.audio.duration > 20 && report.audio.rms > .01)
  assert.equal(report.audio.error, null)
  assert.equal(report.audio.context, 'running')
  await page.evaluate(() => window.fengxiQA.useApp.getState().stopNarration())
  assert.deepEqual(errors, [])
  console.log(JSON.stringify(report, null, 2))
} finally {
  await writeFile(join(output, 'browser-qa.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
