// Browser QA for Ershu: real rendered skinning, remounts, interruptions, angles.
// Usage: node scripts/qa-ershu.mjs [http://localhost:5213] [/tmp/ershu-qa]
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import { chromium } from 'playwright-core'

const [base = 'http://localhost:5213', output = '/tmp/ershu-qa'] = process.argv.slice(2)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (error) => errors.push(String(error)))
page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
page.on('response', (response) => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`) })
const report = { actions: {}, remounts: [], angles: [], errors }
try {
  const ready = page.waitForEvent('console', { predicate: (m) => m.text().includes('[beast] ready ershu') })
  await page.goto(`${base}/?beast=ershu&action=idle`)
  await ready
  await page.evaluate(async () => {
    const url = performance.getEntriesByType('resource').map((r) => r.name).find((u) => u.includes('@react-three_fiber.js'))
    const fiber = await import(url)
    // Reuse the exact URL loaded by Vite, including its HMR timestamp. A bare
    // dynamic import can create a second Zustand store after integration edits.
    const storeUrl = performance.getEntriesByType('resource').map((r) => r.name).find((u) => new URL(u).pathname === '/src/app/store.ts')
    if (!storeUrl) throw new Error('Loaded application store not found')
    const { useApp } = await import(storeUrl)
    const state = [...fiber._roots.values()][0].store.getState()
    window.ershuQA = { state, useApp }
  })

  async function snapshot(full = false) {
    return page.evaluate((all) => {
      const { state } = window.ershuQA
      const root = state.scene.getObjectByName('ershu_root')
      if (!root) throw new Error('Missing Ershu root')
      root.updateMatrixWorld(true)
      const nodes = [], surfaces = [], outlines = [], bones = []
      let invalid = 0
      root.traverse((node) => {
        nodes.push(node)
        if (![...node.matrixWorld.elements, ...node.position, ...node.quaternion, ...node.scale].every(Number.isFinite)) invalid++
        if (node.isBone) bones.push(node)
        if (!node.isMesh) return
        if (node.userData.inkOutline) { outlines.push(node); return }
        surfaces.push(node)
        for (const attribute of ['position', 'normal', 'skinWeight']) {
          if (node.geometry.attributes[attribute] && !Array.from(node.geometry.attributes[attribute].array).every(Number.isFinite)) invalid++
        }
        if (node.skeleton) {
          node.skeleton.update()
          if (!Array.from(node.skeleton.boneMatrices).every(Number.isFinite)) invalid++
        }
      })
      const body = surfaces.find((node) => node.name === 'ershu_high_deer_body')
      const feet = { front_l: Infinity, front_r: Infinity, back_l: Infinity, back_r: Infinity }
      const position = body.geometry.attributes.position
      const point = root.position.clone()
      for (let i = 0; i < position.count; i++) {
        if (!all && position.getY(i) > 0.035) continue
        point.fromBufferAttribute(position, i)
        body.applyBoneTransform(i, point)
        if (![...point].every(Number.isFinite)) invalid++
        if (position.getY(i) <= 0.035) {
          const leg = `${position.getZ(i) > -0.11 ? 'front' : 'back'}_${position.getX(i) > 0 ? 'l' : 'r'}`
          body.localToWorld(point)
          feet[leg] = Math.min(feet[leg], point.y)
        }
      }
      return {
        invalid,
        nodes: nodes.length,
        meshes: surfaces.length,
        outlines: outlines.length,
        bones: bones.length,
        tails: surfaces.filter((n) => n.name === 'ershu_tail').length,
        tailBones: bones.filter((n) => n.name.startsWith('ershu_tail_')).length,
        ears: surfaces.filter((n) => n.name.startsWith('ershu_ear_') && n.name.endsWith('_outer')).length,
        eyes: surfaces.filter((n) => n.name.startsWith('ershu_eye_')).length,
        legs: bones.filter((n) => /^(front|back)_[lr]_foot$/.test(n.name)).length,
        height: state.scene.getObjectByName('ershu_flight').position.y,
        action: window.ershuQA.useApp.getState().action,
        feet,
      }
    }, full)
  }

  const baseline = await snapshot(true)
  assert.equal(baseline.invalid, 0)
  assert.equal(baseline.tails, 1)
  assert.equal(baseline.tailBones, 10)
  assert.equal(baseline.ears, 2)
  assert.equal(baseline.eyes, 2)
  assert.equal(baseline.legs, 4)
  report.baseline = baseline

  for (const action of ['idle', 'walk', 'special']) {
    await page.evaluate((a) => window.ershuQA.useApp.getState().setAction(a), action)
    const samples = []
    // Runtime caps frame delta; wall time can exceed clip time on a busy GPU.
    // Observe the complete special action rather than assuming 5.5s wall time.
    for (let i = 0; i < (action === 'special' ? 240 : 24); i++) {
      await page.waitForTimeout(120)
      const sample = await snapshot(i % 8 === 0)
      samples.push(sample)
      if (action === 'special' && sample.action === 'idle') break
    }
    report.actions[action] = samples
    assert(samples.every((s) => s.invalid === 0 && s.tails === 1 && s.ears === 2 && s.legs === 4))
    if (action === 'idle') assert(samples.every((s) => Object.values(s.feet).every((y) => Math.abs(y) < 0.005)))
    if (action === 'walk') assert(samples.every((s) => Math.min(...Object.values(s.feet)) > -0.006 && Math.min(...Object.values(s.feet)) < 0.01))
    if (action === 'special') {
      assert(Math.max(...samples.map((s) => s.height)) > 0.35)
      assert.equal(samples.at(-1).action, 'idle', 'Full flight did not finish')
    }
  }

  await page.evaluate(() => window.ershuQA.useApp.getState().setAction('special'))
  let before
  for (let i = 0; i < 240; i++) {
    await page.waitForTimeout(120)
    before = await snapshot()
    if (before.height > 0.35) break
  }
  await page.evaluate(() => window.ershuQA.useApp.getState().setAction('walk'))
  await page.waitForTimeout(40)
  const after = await snapshot()
  assert(before.height > 0.3 && after.height > 0.2, 'Interrupted flight teleported to ground')
  let landed
  for (let i = 0; i < 240; i++) {
    await page.waitForTimeout(120)
    landed = await snapshot()
    if (landed.height < 0.001) break
  }
  assert(landed.height < 0.001, 'Interrupted flight did not land')
  report.interruption = { before, after, landed }

  for (let i = 0; i < 3; i++) {
    let ready = page.waitForEvent('console', { predicate: (m) => m.text().includes('[beast] ready tianma') })
    await page.evaluate(() => window.ershuQA.useApp.getState().select('tianma'))
    await ready
    ready = page.waitForEvent('console', { predicate: (m) => m.text().includes('[beast] ready ershu') })
    await page.evaluate(() => window.ershuQA.useApp.getState().select('ershu'))
    await ready
    await page.waitForTimeout(350)
    const remount = await snapshot(true)
    for (const key of ['invalid', 'nodes', 'meshes', 'outlines', 'bones', 'tails', 'tailBones', 'ears', 'eyes', 'legs', 'height']) {
      assert.equal(remount[key], baseline[key], `Remount changed ${key}`)
    }
    // Idle breathing has a different phase after remount; compare contact with tolerance.
    assert(Object.values(remount.feet).every((height) => Math.abs(height) < 0.005))
    report.remounts.push(remount)
  }

  for (const [name, x, z] of [['front', 0, 3.9], ['back', 0, -3.9], ['left', -3.9, 0], ['right', 3.9, 0]]) {
    await page.evaluate(({ x, z }) => {
      const { state } = window.ershuQA
      const root = state.scene.getObjectByName('ershu_root')
      const target = root.position.clone().add({ x: 0, y: 0.60, z: 0 })
      const offset = root.position.clone().set(x, 0.7, z).applyQuaternion(root.quaternion)
      state.controls.enableDamping = false
      state.camera.filmOffset = 0
      state.camera.updateProjectionMatrix()
      state.controls.target.copy(target)
      state.camera.position.copy(target).add(offset)
      state.controls.update()
    }, { x, z })
    await page.waitForTimeout(250)
    const path = join(output, `ershu-angle-${name}.png`)
    await page.screenshot({ path })
    report.angles.push(path)
  }
  await page.locator('.story-btn').click()
  await page.waitForTimeout(1800)
  report.narration = await page.evaluate(async () => {
    const audioUrl = performance.getEntriesByType('resource').map((r) => r.name).find((u) => new URL(u).pathname === '/src/systems/audio/AudioEngine.ts')
    if (!audioUrl) throw new Error('Loaded audio engine not found')
    const { audio } = await import(audioUrl)
    const element = audio.narrationEl
    return { src: element?.src, duration: element?.duration, currentTime: element?.currentTime, error: element?.error, context: audio.context?.state }
  })
  assert(report.narration.src.endsWith('/audio/narration/ershu.mp3'))
  assert(report.narration.duration > 50 && report.narration.currentTime > 0)
  assert.equal(report.narration.error, null)
  await page.evaluate(() => window.ershuQA.useApp.getState().stopNarration())
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log(JSON.stringify({ baseline, interruption: report.interruption, narration: report.narration, remounts: report.remounts.length, finiteSamples: Object.values(report.actions).reduce((n, a) => n + a.length, 0), errors }, null, 2))
} finally {
  await writeFile(join(output, 'browser-qa.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
