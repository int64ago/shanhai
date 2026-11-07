// Actual rendered sole XYZ, plane direction, resources, interruption and audio.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'
const [base = 'http://127.0.0.1:5225', output = '/tmp/zhubieyu-new-qa'] = process.argv.slice(2)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(String(error)))
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`) })
const report = { errors, actions: {}, remounts: [], angles: [] }
try {
  let ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready zhubieyu') })
  await page.goto(`${base}/?beast=zhubieyu&action=idle`)
  await ready
  await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const fiber = await import(resources.find(u => u.includes('@react-three_fiber.js')))
    const { useApp } = await import(resources.find(u => new URL(u).pathname === '/src/app/store.ts'))
    window.fishQA = { state: [...fiber._roots.values()][0].store.getState(), useApp }
  })
  async function snapshot() {
    return page.evaluate(() => {
      const { state } = window.fishQA
      state.scene.updateMatrixWorld(true)
      const root = state.scene.getObjectByName('zhubieyu_root')
      const counts = { nodes: 0, meshes: 0, bones: 0, outlines: 0, feet: 0, eyes: 0, pearls: 0, invalid: 0, triangles: 0 }
      root.traverse(n => {
        counts.nodes++
        if (![...n.matrixWorld.elements, ...n.position, ...n.quaternion, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) counts.invalid++
        if (n.isBone) counts.bones++
        if (!n.isMesh || n.userData.watercolorEffect) return
        if (n.userData.inkOutline) { counts.outlines++; return }
        counts.meshes++
        counts.triangles += n.geometry.index ? n.geometry.index.count / 3 : n.geometry.attributes.position.count / 3
        if (n.name.startsWith('zhubieyu_leg_')) counts.feet++
        if (/^zhubieyu_eye_[lr]$/.test(n.name)) counts.eyes++
        if (n.name === 'zhubieyu_pearl') counts.pearls++
        for (const key of ['position', 'normal', 'skinWeight']) {
          const a = n.geometry.attributes[key]
          if (a && !Array.from(a.array).every(Number.isFinite)) counts.invalid++
        }
        if (n.skeleton) {
          n.skeleton.update()
          if (!Array.from(n.skeleton.boneMatrices).every(Number.isFinite)) counts.invalid++
        }
        const q = root.position.clone()
        for (let i = 0; i < n.geometry.attributes.position.count; i++) {
          n.getVertexPosition(i, q)
          if (![...q].every(Number.isFinite)) counts.invalid++
        }
      })
      return counts
    })
  }
  report.baseline = await snapshot()
  for (const [key, expected] of Object.entries({ feet: 6, eyes: 2, pearls: 1, invalid: 0, bones: 21 })) assert.equal(report.baseline[key], expected, key)
  assert.equal(report.baseline.meshes, report.baseline.outlines)
  // Select three noncollinear actual mesh vertices on every rigid sole. Their
  // world displacement and two independent edges constrain the entire plane.
  await page.waitForTimeout(600)
  await page.evaluate(() => {
    const { state } = window.fishQA
    state.scene.updateMatrixWorld(true)
    const root = state.scene.getObjectByName('zhubieyu_root')
    const feet = []
    root.traverse(mesh => {
      if (!mesh.isSkinnedMesh || mesh.userData.inkOutline || !mesh.name.startsWith('zhubieyu_leg_')) return
      mesh.skeleton.update()
      const g = mesh.geometry.attributes
      const candidates = []
      const q = root.position.clone()
      for (let i = 0; i < g.position.count; i++) {
        mesh.getVertexPosition(i, q); mesh.localToWorld(q)
        const bone = mesh.skeleton.bones[g.skinIndex.getX(i)]?.name
        if (q.y < .00008 && g.skinWeight.getX(i) > .99999 && bone?.endsWith('_foot')) candidates.push({ i, point: q.clone() })
      }
      if (candidates.length < 3) throw new Error(`${mesh.name}: insufficient real sole vertices`)
      const a = candidates[0]
      const b = candidates.reduce((best, v) => v.point.distanceToSquared(a.point) > best.point.distanceToSquared(a.point) ? v : best)
      const edge = b.point.clone().sub(a.point)
      const c = candidates.reduce((best, v) => edge.clone().cross(v.point.clone().sub(a.point)).lengthSq() > edge.clone().cross(best.point.clone().sub(a.point)).lengthSq() ? v : best)
      if (edge.clone().cross(c.point.clone().sub(a.point)).lengthSq() < 1e-8) throw new Error(`${mesh.name}: collinear sole vertices`)
      const key = mesh.name.replace('zhubieyu_leg_', '')
      const row = key.startsWith('front') ? 0 : key.startsWith('middle') ? 1 : 2
      const offset = ((row + (key.endsWith('_l') ? 0 : 1)) % 2) * .5
      feet.push({ mesh, key, offset, indices: [a.i, b.i, c.i], candidates: candidates.length })
    })
    window.fishQA.feet = feet
  })
  for (const action of ['idle', 'walk', 'special']) {
    await page.evaluate(a => window.fishQA.useApp.getState().setAction(a), action)
    await page.waitForTimeout(500)
    report.actions[action] = await page.evaluate(async action => {
      const { state, feet } = window.fishQA
      const root = state.scene.getObjectByName('zhubieyu_root')
      const plants = {}
      let cycles = 0, previous = root.userData.animationTime, frames = 0, invalid = 0
      const duration = action === 'walk' ? 7 : action === 'special' ? 3.9 : 2.1
      const ripple = root.getObjectByName('zhubieyu_watercolor_ripples').material
      const rippleStart = ripple.uniforms.time.value
      let ripplePeak = 0
      const start = performance.now()
      while (performance.now() - start < duration * 1000) {
        await new Promise(resolve => requestAnimationFrame(resolve))
        state.scene.updateMatrixWorld(true)
        ripplePeak = Math.max(ripplePeak, ripple.uniforms.strength.value)
        const t = root.userData.animationTime
        if (t < previous - .3) cycles++
        previous = t; frames++
        for (const foot of feet) {
          const phase = t / 2.2 + foot.offset
          const p = phase % 1
          if (action === 'walk' && (p < .05 || p > .62)) continue
          foot.mesh.skeleton.update()
          const positions = foot.indices.map(i => {
            const q = root.position.clone(); foot.mesh.getVertexPosition(i, q); foot.mesh.localToWorld(q)
            if (![...q].every(Number.isFinite)) invalid++
            return q
          })
          const key = `${foot.key}/${action === 'walk' ? cycles + Math.floor(phase) : 0}`
          const entry = plants[key] ??= { foot: foot.key, initial: positions.map(q => q.toArray()), maxDrift: 0, maxDirection: 0, maxNormal: 0, maxY: 0, samples: 0 }
          positions.forEach((q, i) => {
            entry.maxDrift = Math.max(entry.maxDrift, q.distanceTo(root.position.clone().fromArray(entry.initial[i])))
            entry.maxY = Math.max(entry.maxY, Math.abs(q.y))
          })
          const first = entry.initial.map(a => root.position.clone().fromArray(a))
          for (const i of [1, 2]) entry.maxDirection = Math.max(entry.maxDirection, positions[i].clone().sub(positions[0]).angleTo(first[i].clone().sub(first[0])))
          const normal = positions[1].clone().sub(positions[0]).cross(positions[2].clone().sub(positions[0])).normalize()
          entry.maxNormal = Math.max(entry.maxNormal, Math.acos(Math.min(1, Math.abs(normal.y))))
          entry.samples++
        }
      }
      const measured = Object.values(plants).filter(p => p.samples > 5)
      return { frames, invalid, ripple: { elapsed: ripple.uniforms.time.value - rippleStart, peak: ripplePeak, material: ripple.uuid }, feet: feet.length, soleCandidates: feet.map(f => ({ foot: f.key, vertices: f.candidates })), plants: measured,
        maxDrift: Math.max(...measured.map(p => p.maxDrift)), maxDirection: Math.max(...measured.map(p => p.maxDirection)), maxNormal: Math.max(...measured.map(p => p.maxNormal)), maxY: Math.max(...measured.map(p => p.maxY)) }
    }, action)
    const result = report.actions[action]
    assert(result.ripple.elapsed > 1, `${action} updates attached ripple material time`)
    assert(result.ripple.peak > (action === 'special' ? .8 : action === 'walk' ? .15 : .03), `${action} ripple strength`)
    assert.equal(result.feet, 6); assert.equal(result.invalid, 0)
    assert(result.maxDrift < .0007, `${action} actual sole drift ${result.maxDrift}`)
    assert(result.maxDirection < .001, `${action} actual sole direction ${result.maxDirection}`)
    assert(result.maxNormal < .001, `${action} actual sole plane ${result.maxNormal}`)
    assert(result.maxY < .001, `${action} actual sole Y ${result.maxY}`)
  }
  for (const action of ['special', 'walk', 'idle']) {
    await page.evaluate(a => window.fishQA.useApp.getState().setAction(a), action)
    await page.waitForTimeout(90)
    assert.equal((await snapshot()).invalid, 0)
  }
  for (let i = 0; i < 3; i++) {
    await page.evaluate(() => {
      const root = window.fishQA.state.scene.getObjectByName('zhubieyu_root')
      const skeletons = new Set(); root.traverse(n => { if (n.isSkinnedMesh) skeletons.add(n.skeleton) })
      const textures = [...skeletons].map(s => s.boneTexture).filter(Boolean)
      window.fishQA.old = { skeletons: [...skeletons], textures: textures.length, disposed: 0 }
      for (const texture of textures) texture.addEventListener('dispose', () => window.fishQA.old.disposed++)
      const ripple = root.getObjectByName('zhubieyu_watercolor_ripples')
      window.fishQA.old.ripple = { material: ripple.material.uuid, materialDisposals: 0, geometryDisposals: 0 }
      ripple.material.addEventListener('dispose', () => window.fishQA.old.ripple.materialDisposals++)
      ripple.geometry.addEventListener('dispose', () => window.fishQA.old.ripple.geometryDisposals++)
    })
    ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready yayu') })
    await page.evaluate(() => window.fishQA.useApp.getState().select('yayu')); await ready
    await page.waitForFunction(() => window.fishQA.old.ripple.materialDisposals > 0 && window.fishQA.old.ripple.geometryDisposals > 0)
    ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready zhubieyu') })
    await page.evaluate(() => window.fishQA.useApp.getState().select('zhubieyu')); await ready
    const current = await snapshot()
    assert.deepEqual(current, report.baseline)
    const cleanup = await page.evaluate(() => ({ textures: window.fishQA.old.textures, disposed: window.fishQA.old.disposed, live: window.fishQA.old.skeletons.filter(s => s.boneTexture).length,
      ripple: { ...window.fishQA.old.ripple, currentMaterial: window.fishQA.state.scene.getObjectByName('zhubieyu_watercolor_ripples').material.uuid } }))
    assert(cleanup.textures > 0 && cleanup.textures === cleanup.disposed && cleanup.live === 0)
    assert.equal(cleanup.ripple.materialDisposals, 1); assert.equal(cleanup.ripple.geometryDisposals, 1)
    assert.notEqual(cleanup.ripple.material, cleanup.ripple.currentMaterial)
    report.remounts.push({ current, cleanup })
  }
  await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const { audio } = await import(resources.find(u => new URL(u).pathname === '/src/systems/audio/AudioEngine.ts'))
    const original = audio.zhubieyuCall.bind(audio)
    window.fishQA.sound = { calls: 0, stops: 0 }
    audio.zhubieyuCall = pan => {
      window.fishQA.sound.calls++
      const stop = original(pan)
      return () => { window.fishQA.sound.stops++; stop() }
    }
    window.fishQA.useApp.getState().setAction('special')
  })
  await page.waitForTimeout(60)
  await page.evaluate(() => window.fishQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(350)
  assert.equal(await page.evaluate(() => window.fishQA.sound.calls), 0, 'Interrupted special cancels delayed bubble call')
  await page.evaluate(() => window.fishQA.useApp.getState().setAction('special'))
  await page.waitForTimeout(350)
  await page.evaluate(() => window.fishQA.useApp.getState().setAction('idle'))
  await page.waitForTimeout(60)
  report.soundInterruption = await page.evaluate(() => window.fishQA.sound)
  assert.equal(report.soundInterruption.calls, 1); assert.equal(report.soundInterruption.stops, 1)
  await page.evaluate(() => window.fishQA.useApp.getState().setAction('special'))
  await page.waitForFunction(() => window.fishQA.useApp.getState().action === 'idle', null, { timeout: 10000 })
  report.specialReturn = 'idle'
  await page.locator('.story-btn').click(); await page.waitForTimeout(1800)
  report.audio = await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const { audio } = await import(resources.find(u => new URL(u).pathname === '/src/systems/audio/AudioEngine.ts'))
    const el = audio.narrationEl
    const analyser = audio.context.createAnalyser(); analyser.fftSize = 2048; audio.sfx.connect(analyser)
    const samples = new Float32Array(analyser.fftSize)
    const stop = audio.zhubieyuCall(0)
    let peakRMS = 0
    for (let i = 0; i < 24; i++) {
      await new Promise(resolve => setTimeout(resolve, 30)); analyser.getFloatTimeDomainData(samples)
      peakRMS = Math.max(peakRMS, Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length))
    }
    stop(); audio.sfx.disconnect(analyser); analyser.disconnect()
    return { src: el?.src, duration: el?.duration, currentTime: el?.currentTime, error: el?.error, context: audio.context.state, peakRMS }
  })
  assert(report.audio.src.endsWith('/audio/narration/zhubieyu.mp3') && report.audio.currentTime > 0 && report.audio.duration > 50)
  assert.equal(report.audio.error, null); assert(report.audio.peakRMS > .0001)
  await page.locator('.story-btn').click()
  assert(await page.evaluate(() => !window.fishQA.useApp.getState().narrating))
  for (const [name, x, y, z] of [['front', 0, 1.4, 4], ['back', 0, 1.4, -4], ['left', -4, 1.4, 0], ['right', 4, 1.4, 0], ['dorsal', 1.3, 3.8, -1.3]]) {
    await page.evaluate(({ x, y, z }) => {
      const { state } = window.fishQA, root = state.scene.getObjectByName('zhubieyu_root')
      const target = root.position.clone(); target.y = .48
      const offset = root.position.clone().set(x, y, z).applyQuaternion(root.quaternion)
      state.controls.enableDamping = false; state.camera.filmOffset = 0; state.camera.updateProjectionMatrix()
      state.controls.target.copy(target); state.camera.position.copy(target).add(offset); state.controls.update()
    }, { x, y, z })
    await page.waitForTimeout(150)
    const path = join(output, `angle-${name}.png`); await page.screenshot({ path }); report.angles.push(path)
  }
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log(JSON.stringify({ baseline: report.baseline, actions: Object.fromEntries(Object.entries(report.actions).map(([key, value]) => [key, { frames: value.frames, maxDrift: value.maxDrift, maxDirection: value.maxDirection, maxNormal: value.maxNormal, maxY: value.maxY }])), remounts: report.remounts.length, audio: report.audio, errors }, null, 2))
} finally {
  await writeFile(join(output, 'browser-qa.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
