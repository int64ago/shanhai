// Focused real-browser anatomy, clip, StrictMode cache and remount checks.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { launchQABrowser } from './lib/browser.mjs'

const [base = 'http://localhost:5210', out = '/tmp/shanhai-xiangliu-qa'] = process.argv.slice(2)
await mkdir(out, { recursive: true })
const report = { passed: false, errors: [], actions: [], remounts: [], sourceDesignChecks: [] }
const browser = await launchQABrowser()
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', error => report.errors.push(String(error)))
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()) })
  page.on('response', response => { if (response.status() >= 400) report.errors.push(`${response.status()} ${response.url()}`) })
  const ready = id => page.waitForSelector(`[data-stage-beast="${id}"][data-stage-state="ready"]`, { state: 'attached', timeout: 45000 })
  await page.goto(`${base}/?beast=jingwei&action=idle`)
  await ready('jingwei')
  report.source = await page.evaluate(async () => {
    const resource = needle => performance.getEntriesByType('resource').map(r => r.name).find(name => new URL(name).pathname.includes(needle))
    const { useGLTF } = await import(resource('@react-three_drei'))
    const fiber = await import(resource('@react-three_fiber'))
    const { useApp } = await import(resource('/src/app/store.ts'))
    const { BEASTS } = await import(resource('/src/app/beasts.ts'))
    const entry = BEASTS.find(beast => beast.id === 'xiangliu'), catalogReady = entry.ready
    entry.ready = true // Browser-local candidate controls; source readiness is unchanged.
    const r3fState = [...fiber._roots.values()][0].store.getState()
    const { scene } = r3fState
    let asset
    for (;;) {
      try { asset = useGLTF('/models/xiangliu/body.glb'); break }
      catch (pending) { if (!pending?.then) throw pending; await pending }
    }
    const snapshot = () => {
      const rows = []
      asset.scene.traverse(node => rows.push([node.uuid, node.name, node.children.map(c => c.uuid), node.position.toArray(), node.quaternion.toArray(), node.scale.toArray(), node.material?.uuid, node.skeleton?.uuid]))
      return JSON.stringify(rows)
    }
    const before = snapshot()
    let rigidVertices = 0, invalidFaceWeights = 0, faces = 0
    const textureCoordinates = []
    asset.scene.traverse(mesh => {
      if (mesh.isMesh && mesh.material.map) textureCoordinates.push({ name: mesh.material.name, channel: mesh.material.map.channel, uv: Boolean(mesh.geometry.attributes.uv) })
      if (!mesh.isSkinnedMesh || !mesh.material.name.startsWith('Native_High')) return
      const weights = mesh.geometry.attributes.skinWeight
      const indices = mesh.geometry.attributes.skinIndex
      faces += mesh.geometry.index ? mesh.geometry.index.count / 3 : mesh.geometry.attributes.position.count / 3
      for (let i = 0; i < weights.count; i++) {
        const ws = [weights.getX(i), weights.getY(i), weights.getZ(i), weights.getW(i)]
        const js = [indices.getX(i), indices.getY(i), indices.getZ(i), indices.getW(i)]
        const active = ws.map((w, j) => [w, js[j]]).filter(([w]) => w > 0.00001)
        if (active.length !== 1 || Math.abs(active[0][0] - 1) > 0.0001 || !/^head_\d{2}$/.test(mesh.skeleton.bones[active[0][1]]?.name)) invalidFaceWeights++
        rigidVertices++
      }
    })
    window.__xiangliuQA = { asset, before, snapshot, scene, r3fState, useApp }
    useApp.getState().select('xiangliu')
    return { catalogReady, clips: asset.animations.map(clip => ({ name: clip.name, duration: clip.duration })), rigidVertices, invalidFaceWeights, trianglesInRigidHeads: faces, textureCoordinates }
  })
  assert(report.source.rigidVertices > 0)
  assert.equal(report.source.invalidFaceWeights, 0, 'Complete human faces must have one rigid head influence')
  assert(report.source.textureCoordinates.every(map => map.channel === 0 && map.uv), 'Ink materials require each diffuse map on UV0')
  assert.deepEqual(report.source.clips.map(clip => clip.name).sort(), ['idle', 'special', 'walk'])
  await ready('xiangliu')
  const inspect = () => page.evaluate(() => {
    const qa = window.__xiangliuQA
    const root = qa.scene.getObjectByName('xiangliu_root')
    if (!root) throw new Error('Missing Xiangliu mount')
    root.updateMatrixWorld(true)
    let heads = 0, spine = 0, neck = 0, outlines = 0, meshes = 0, invalid = 0
    const posed = []
    root.traverse(node => {
      if (![...node.matrixWorld.elements].every(Number.isFinite)) invalid++
      if (node.isBone && /^head_\d{2}$/.test(node.name)) { heads++; posed.push([...node.matrixWorld.elements]) }
      if (node.isBone && /^spine_/.test(node.name)) spine++
      if (node.isBone && /^neck_/.test(node.name)) neck++
      if (node.userData.inkOutline) outlines++
      if (node.isMesh && !node.userData.inkOutline) meshes++
    })
    return { heads, spine, neck, outlines, meshes, invalid, sourceUnchanged: qa.before === qa.snapshot(), time: root.userData.animationTime, posed }
  })
  assert.equal(await page.locator('.action-btn').count(), 3, 'All three actual action controls are available')
  for (const action of ['idle', 'walk', 'special']) {
    const label = { idle: '静', walk: '行', special: '神通' }[action]
    await page.getByRole('button', { name: label, exact: true }).click()
    await page.waitForTimeout(350)
    const before = await inspect()
    await page.waitForFunction(time => window.__xiangliuQA.scene.getObjectByName('xiangliu_root')?.userData.animationTime !== time, before.time, { timeout: 15000 })
    const after = await inspect()
    assert.equal(after.heads, 9)
    assert.equal(after.spine, 24)
    assert.equal(after.neck, 63)
    assert.equal(after.invalid, 0)
    assert.equal(after.outlines, after.meshes)
    assert(after.sourceUnchanged)
    assert.notDeepEqual(before.posed, after.posed, `${action} must deform the actual rig`)
    await page.screenshot({ path: join(out, `${action}.png`) })
    report.actions.push({ action, ...after, posed: undefined })
  }
  report.specialReturn = await page.evaluate(async () => {
    const qa = window.__xiangliuQA, state = qa.r3fState, previousLoop = state.frameloop
    // Drive the actual mounted component clock: slow GPU frames are clamped by
    // runtime, so wall-clock waiting does not measure the clip's duration.
    state.setFrameloop('never')
    let steps = 0
    try {
      while (qa.useApp.getState().action === 'special' && steps < 160) {
        state.advance(state.clock.elapsedTime + .05, true)
        steps++
        await new Promise(resolve => setTimeout(resolve, 0))
      }
      return { steps, action: qa.useApp.getState().action }
    } finally { state.setFrameloop(previousLoop) }
  })
  assert.equal(report.specialReturn.action, 'idle', 'Special returns to idle in the actual mounted runtime')
  for (let i = 0; i < 2; i++) {
    await page.evaluate(() => window.__xiangliuQA.useApp.getState().select('jingwei'))
    await ready('jingwei')
    await page.evaluate(() => window.__xiangliuQA.useApp.getState().select('xiangliu'))
    await ready('xiangliu')
    await page.waitForTimeout(300)
    const sample = await inspect()
    assert(sample.sourceUnchanged)
    assert.equal(sample.heads, 9)
    assert.equal(sample.outlines, sample.meshes)
    assert.equal(sample.invalid, 0)
    report.remounts.push({ ...sample, posed: undefined })
  }
  report.cycles = await page.evaluate(async () => {
    const qa = window.__xiangliuQA
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const { AnimationMixer, Group, LoopOnce } = await import(resources.find(url => new URL(url).pathname.endsWith('/three.js')))
    const { clone } = await import(resources.find(url => url.includes('SkeletonUtils')))
    const source = clone(qa.asset.scene), holder = new Group()
    source.position.z -= 1.6; holder.scale.setScalar(.45); holder.rotation.y = -Math.PI / 2; holder.add(source)
    const mixer = new AnimationMixer(source), result = [], posteriorEdges = new Map(), posteriorRest = new Map()
    holder.updateMatrixWorld(true)
    source.traverse(node => {
      if (!node.isSkinnedMesh || !node.material.name.startsWith('Actual_High_body')) return
      const p = node.geometry.attributes.position, v = node.position.clone(), rest = new Float64Array(p.count * 3)
      // Meshopt quantization can fold dequantization into inverse bind matrices.
      // Measure the actual default skin, never distances in normalized storage.
      for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i); node.applyBoneTransform(i, v); v.applyMatrix4(node.matrixWorld); rest.set(v.toArray(), i * 3) }
      posteriorRest.set(node, rest)
    })
    for (const clip of qa.asset.animations) {
      mixer.stopAllAction()
      // Clamp the actual last keyframe: repeating at exactly duration wraps to
      // the first frame and would make a loop-closure check tautological.
      const action = mixer.clipAction(clip).reset().setLoop(LoopOnce, 1)
      action.clampWhenFinished = true
      action.play()
      const samples = []
      for (const fraction of [0, .25, .5, .75, 1]) {
        mixer.setTime(fraction * clip.duration); holder.updateMatrixWorld(true)
        const matrices = [], spines = [], headBounds = new Map()
        let maximumPosteriorEdgeStrain = 0, worstPosteriorEdge
        holder.traverse(node => {
          if (node.isBone && /^head_/.test(node.name)) matrices.push(...node.matrixWorld.elements)
          if (node.isBone && /^spine_/.test(node.name)) spines.push(node.rotation.z)
          if (node.isSkinnedMesh && node.material.name.startsWith('Actual_High_body')) {
            const p = node.geometry.attributes.position, indices = node.geometry.index, v = node.position.clone()
            let edges = posteriorEdges.get(node)
            if (!edges) {
              edges = []; const seen = new Set()
              for (let i = 0; i < indices.count; i += 3) {
                const ids = [indices.getX(i), indices.getX(i + 1), indices.getX(i + 2)]
                for (let j = 0; j < 3; j++) {
                  const a = Math.min(ids[j], ids[(j + 1) % 3]), b = Math.max(ids[j], ids[(j + 1) % 3]), key = `${a},${b}`
                  if (seen.has(key)) continue; seen.add(key)
                  const rest = posteriorRest.get(node)
                  const length = Math.hypot(rest[a * 3] - rest[b * 3], rest[a * 3 + 1] - rest[b * 3 + 1], rest[a * 3 + 2] - rest[b * 3 + 2])
                  if (length >= .005) edges.push([a, b, length])
                }
              }
              posteriorEdges.set(node, edges)
            }
            const posed = new Float64Array(p.count * 3)
            for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i); node.applyBoneTransform(i, v); v.applyMatrix4(node.matrixWorld); posed.set(v.toArray(), i * 3) }
            for (const [a, b, rest] of edges) {
              const length = Math.hypot(posed[a * 3] - posed[b * 3], posed[a * 3 + 1] - posed[b * 3 + 1], posed[a * 3 + 2] - posed[b * 3 + 2])
              const strain = Math.abs(length / rest - 1)
              if (strain > maximumPosteriorEdgeStrain) {
                maximumPosteriorEdgeStrain = strain
                const joints = node.geometry.attributes.skinIndex, ws = node.geometry.attributes.skinWeight
                worstPosteriorEdge = { rest, length, vertices: [a, b].map(i => ({ position: [p.getX(i), p.getY(i), p.getZ(i)], posed: Array.from(posed.slice(i * 3, i * 3 + 3)), weights: [ws.getX(i), ws.getY(i), ws.getZ(i), ws.getW(i)], bones: [joints.getX(i), joints.getY(i), joints.getZ(i), joints.getW(i)].map(j => node.skeleton.bones[j].name) })) }
              }
            }
          }
          if (!node.isSkinnedMesh || !node.material.name.startsWith('Native_High')) return
          const p = node.geometry.attributes.position, joints = node.geometry.attributes.skinIndex, v = node.position.clone()
          for (let i = 0; i < p.count; i++) {
            const name = node.skeleton.bones[joints.getX(i)].name
            let b = headBounds.get(name)
            if (!b) { b = [[Infinity, Infinity, Infinity], [-Infinity, -Infinity, -Infinity]]; headBounds.set(name, b) }
            v.fromBufferAttribute(p, i); node.applyBoneTransform(i, v); v.applyMatrix4(node.matrixWorld)
            for (let k = 0; k < 3; k++) { b[0][k] = Math.min(b[0][k], v.getComponent(k)); b[1][k] = Math.max(b[1][k], v.getComponent(k)) }
          }
        })
        const bounds = [...headBounds.values()]; let minimumHeadBoxGap = Infinity
        for (let i = 0; i < bounds.length; i++) for (let j = i + 1; j < bounds.length; j++) {
          const a = bounds[i], b = bounds[j]
          const distance = Math.hypot(...[0, 1, 2].map(k => Math.max(0, a[0][k] - b[1][k], b[0][k] - a[1][k])))
          minimumHeadBoxGap = Math.min(minimumHeadBoxGap, distance)
        }
        samples.push({ fraction, matrices, spines, minimumHeadBoxGap, maximumPosteriorEdgeStrain, worstPosteriorEdge })
      }
      const loopError = Math.max(...samples[0].matrices.map((value, i) => Math.abs(value - samples[4].matrices[i])))
      const headMotion = Math.max(...samples[0].matrices.map((value, i) => Math.abs(value - samples[2].matrices[i])))
      result.push({ action: clip.name, duration: clip.duration, loopError, headMotion, samples: samples.map(({ matrices, ...rest }) => rest) })
    }
    mixer.stopAllAction(); mixer.uncacheRoot(source)
    const skeletons = new Set(); source.traverse(node => { if (node.isSkinnedMesh) skeletons.add(node.skeleton) }); for (const skeleton of skeletons) skeleton.dispose()
    return result
  })
  for (const cycle of report.cycles) {
    assert(cycle.loopError < .0001, `${cycle.action} loop must close`)
    assert(cycle.headMotion > .001, `${cycle.action} must animate actual head transforms`)
    assert(cycle.samples.every(sample => sample.minimumHeadBoxGap > .02), `${cycle.action} native head bounds must remain separate`)
    assert(cycle.samples.every(sample => sample.maximumPosteriorEdgeStrain < .2), `${cycle.action} posterior edges over 5mm must not kink`)
  }
  for (const [name, width, height] of [['tablet', 768, 1024], ['narrow-tablet', 700, 1000], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height }); await page.waitForTimeout(250)
    await page.screenshot({ path: join(out, `${name}.png`) })
    if (width === 700 || width === 390) {
      const card = page.locator('.card[data-beast="xiangliu"]')
      const sources = await card.locator('.card-source').allTextContents()
      assert.equal(sources.length, 2, 'Both classical versions must remain separately quoted')
      assert(sources[0].includes('相柳者，九首人面，蛇身而青。'))
      assert(sources[1].includes('共工臣名曰相繇，九首蛇身，自環，食于九土。'))
      await card.hover()
      await page.mouse.wheel(0, 600)
      await page.waitForFunction(() => document.querySelector('.card[data-beast="xiangliu"]').scrollTop > 0)
      const result = await card.evaluate(element => {
        const design = element.querySelector('.card-inferred'), label = design.querySelector('.card-label')
        const bounds = element.getBoundingClientRect(), d = design.getBoundingClientRect(), style = getComputedStyle(design)
        return { scrollTop: element.scrollTop, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, writingMode: getComputedStyle(element).writingMode, designDisplay: style.display, designBorder: style.borderTopColor, designLabel: label.textContent, designVisible: d.top >= bounds.top && d.bottom <= bounds.bottom, cardInsideViewport: bounds.left >= 0 && bounds.right <= innerWidth && bounds.top >= 0 && bounds.bottom <= innerHeight }
      })
      assert.equal(result.writingMode, 'horizontal-tb')
      assert.notEqual(result.designDisplay, 'none', 'Design inference must remain available on mobile')
      assert.equal(result.designLabel, '设计')
      assert(result.designVisible && result.cardInsideViewport, 'Scrolled design panel must fit inside its card and viewport')
      report.sourceDesignChecks.push({ width, height, sources, ...result })
      await page.screenshot({ path: join(out, `${name}-source-design.png`) })
      await card.evaluate(element => { element.scrollTop = 0 })
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(150)
  for (const view of ['roots', 'single-side', 'single-nape']) {
    await page.evaluate(view => {
      const qa = window.__xiangliuQA, { camera, controls } = qa.r3fState
      const root = qa.scene.getObjectByName('xiangliu_root'); root.updateMatrixWorld(true)
      const target = camera.position.clone()
      if (view === 'roots') {
        target.set(.95, .57, 0); camera.position.copy(target).add(camera.position.clone().set(2.8, 1.8, 3.4)); camera.fov = 25
      } else {
        const head = root.getObjectByName('head_05'); head.getWorldPosition(target); target.y += .09
        camera.position.copy(target).add(camera.position.clone().set(view === 'single-nape' ? -2 : 0, .04, view === 'single-side' ? 2 : 0)); camera.fov = 15
      }
      camera.filmOffset = 0; controls.target.copy(target); camera.updateProjectionMatrix(); controls.update()
    }, view)
    await page.waitForTimeout(250)
    await page.screenshot({ path: join(out, `ink-${view}.png`), clip: { x: 480, y: 140, width: 840, height: 580 } })
  }
  assert.deepEqual(report.errors, [])
  report.passed = true
} catch (error) {
  report.failure = error.stack || String(error)
  process.exitCode = 1
} finally {
  await browser.close()
  await writeFile(join(out, 'qa.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
}
