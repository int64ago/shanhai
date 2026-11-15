// Actual runtime full-circle UI clearance. No mesh/animation/camera overrides.
// node scripts/qa-longzhi-orbit.mjs BASE NEW_EVIDENCE_DIR
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright-core'
const [base = 'http://127.0.0.1:5207', outArg] = process.argv.slice(2)
assert(outArg)
const out = resolve(outArg)
await mkdir(out, { recursive: false })
const report = { passed: false, safetyPx: 8, dtSeconds: .05, sampleEverySteps: 23, method: 'Actual R3F manual clock; all skin vertices, no bbox collisions; painted overlay boxes and title text ranges only; 1.15s samples (<1 degree), non-aliased 48 gait phases, through >=2pi', errors: [], viewports: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
try {
  for (const size of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 700, height: 900 }]) {
    const page = await browser.newPage({ viewport: size })
    page.on('pageerror', e => report.errors.push(String(e)))
    page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
    const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready longzhi'), timeout: 60000 })
    await page.goto(`${base}/?beast=longzhi&action=idle`); await ready; await page.waitForTimeout(900)
    let cardScroll
    if (size.width === 390) {
      await page.screenshot({ path: join(out, '390-source-top.png') })
      cardScroll = await page.evaluate(() => {
        const card = document.querySelector('.card'), items = []
        for (const el of card.querySelectorAll('.card-source,.card-inferred')) {
          const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
          while (walker.nextNode()) { const node = walker.currentNode; for (let i = 0; i < node.length; i++) if (node.textContent[i].trim()) items.push({ node, i, seen: false }) }
        }
        const maxScroll = card.scrollHeight - card.clientHeight
        for (let y = 0; y < maxScroll + card.clientHeight; y += Math.max(1, card.clientHeight / 3)) {
          card.scrollTop = Math.min(y, maxScroll)
          const clip = card.getBoundingClientRect()
          for (const item of items) {
            const range = document.createRange(); range.setStart(item.node, item.i); range.setEnd(item.node, item.i + 1)
            const r = range.getBoundingClientRect()
            if (r.top >= clip.top + 1 && r.bottom <= clip.bottom - 1 && r.left >= clip.left + 1 && r.right <= clip.right - 1) item.seen = true
          }
        }
        card.scrollTop = maxScroll
        return { overflowY: getComputedStyle(card).overflowY, maxScroll, characters: items.length, readableCharacters: items.filter(i => i.seen).length, source: card.querySelector('.card-source').textContent, inferredParagraphs: card.querySelectorAll('.card-inferred p').length }
      })
      await page.screenshot({ path: join(out, '390-design-bottom.png') })
      assert.equal(cardScroll.readableCharacters, cardScroll.characters)
      assert.equal(cardScroll.inferredParagraphs, 4)
      assert(cardScroll.maxScroll > 0)
      await page.evaluate(() => { document.querySelector('.card').scrollTop = 0 })
    }
    const setup = await page.evaluate(async () => {
      const resources = performance.getEntriesByType('resource').map(r => r.name)
      const url = suffix => resources.find(u => new URL(u).pathname.endsWith(suffix))
      const fiber = await import(url('/@react-three_fiber.js')), T = await import(url('/three.js'))
      const state = [...fiber._roots.values()][0].store.getState()
      state.setFrameloop('never')
      const root = state.scene.getObjectByName('longzhi_root'), mesh = root.getObjectByProperty('isSkinnedMesh', true)
      const q = window.orbitQA = { state, root, mesh, T, now: state.clock.elapsedTime, render: state.gl.render, frame: 0, initialAngle: root.rotation.y }
      // Only suppress redundant drawing between samples; all frame subscribers still run.
      state.gl.render = () => {}
      for (let i = 0; i < 40; i++) { q.now += .05; state.advance(q.now, true) }
      const painted = '.card,.actions button,.controls button,.scroll-tab,.catalog-trigger,.scroll-rod,.scroll-arrow,.scroll-paper,.story-caption'
      const visible = el => { const s = getComputedStyle(el), r = el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0 && r.width > 0 && r.height > 0 }
      const rect = (r, label) => ({ left: Math.max(0, r.left), top: Math.max(0, r.top), right: Math.min(innerWidth, r.right), bottom: Math.min(innerHeight, r.bottom), label })
      q.blockers = [...document.querySelectorAll(painted)].filter(visible).map(el => rect(el.getBoundingClientRect(), el.className))
      const title = document.querySelector('.title')
      if (title && visible(title)) {
        const walker = document.createTreeWalker(title, NodeFilter.SHOW_TEXT)
        while (walker.nextNode()) { const node = walker.currentNode; if (!node.textContent.trim()) continue; const range = document.createRange(); range.selectNodeContents(node); for (const r of range.getClientRects()) q.blockers.push(rect(r, 'title text')) }
        for (const el of title.querySelectorAll('.seal')) q.blockers.push(rect(el.getBoundingClientRect(), 'title seal'))
      }
      q.blockers = q.blockers.filter(r => r.left < r.right && r.top < r.bottom)
      const a = mesh.geometry.attributes, n = a.position.count
      q.positions = new Float64Array(n * 3); q.weights = new Float64Array(n * 4); q.joints = new Uint16Array(n * 4)
      for (let i = 0; i < n; i++) {
        for (let k = 0; k < 3; k++) q.positions[i * 3 + k] = a.position.getComponent(i, k)
        for (let k = 0; k < 4; k++) { q.weights[i * 4 + k] = a.skinWeight.getComponent(i, k); q.joints[i * 4 + k] = a.skinIndex.getComponent(i, k) }
      }
      q.sample = () => {
        state.scene.updateMatrixWorld(true); state.camera.updateMatrixWorld(true); mesh.skeleton.update()
        const m = new T.Matrix4().multiplyMatrices(state.camera.projectionMatrix, state.camera.matrixWorldInverse).multiply(mesh.matrixWorld).multiply(mesh.bindMatrixInverse)
        const palette = [], b = new T.Matrix4()
        for (let i = 0; i < mesh.skeleton.bones.length; i++) palette.push(new T.Matrix4().multiplyMatrices(m, b.fromArray(mesh.skeleton.boneMatrices, i * 16)).multiply(mesh.bindMatrix).elements)
        let minimumPx = Infinity, danger = null, coveredVertices = 0, unsafeVertices = 0, clippedVertices = 0, invalidVertices = 0
        const low = [Infinity, Infinity], high = [-Infinity, -Infinity]
        for (let i = 0; i < n; i++) {
          const x = q.positions[i * 3], y = q.positions[i * 3 + 1], z = q.positions[i * 3 + 2]
          let cx = 0, cy = 0, cz = 0, cw = 0
          for (let k = 0; k < 4; k++) {
            const weight = q.weights[i * 4 + k]; if (!weight) continue
            const e = palette[q.joints[i * 4 + k]]
            cx += weight * (e[0] * x + e[4] * y + e[8] * z + e[12]); cy += weight * (e[1] * x + e[5] * y + e[9] * z + e[13])
            cz += weight * (e[2] * x + e[6] * y + e[10] * z + e[14]); cw += weight * (e[3] * x + e[7] * y + e[11] * z + e[15])
          }
          const sx = (cx / cw + 1) * innerWidth / 2, sy = (1 - cy / cw) * innerHeight / 2
          if (!Number.isFinite(sx + sy + cz + cw)) invalidVertices++
          if (cw <= 0 || Math.abs(cz / cw) > 1) clippedVertices++
          low[0] = Math.min(low[0], sx); low[1] = Math.min(low[1], sy); high[0] = Math.max(high[0], sx); high[1] = Math.max(high[1], sy)
          let distance = Math.min(sx, sy, innerWidth - sx, innerHeight - sy), label = 'viewport', covered = false
          for (const r of q.blockers) {
            const dx = Math.max(r.left - sx, 0, sx - r.right), dy = Math.max(r.top - sy, 0, sy - r.bottom)
            let d
            if (dx || dy) { if (distance >= 0 && (dx > distance || dy > distance)) continue; d = Math.hypot(dx, dy) }
            else { d = -Math.min(sx - r.left, r.right - sx, sy - r.top, r.bottom - sy); covered = true }
            if (d < distance) { distance = d; label = r.label }
          }
          if (covered) coveredVertices++
          if (distance < 8) unsafeVertices++
          if (distance < minimumPx) { minimumPx = distance; danger = { vertex: i, screen: [sx, sy], overlay: label } }
        }
        // Independent Three.js implementation checks the optimized projection.
        let projectionErrorPx = 0
        for (let i = 0; i < n; i += Math.max(1, Math.floor(n / 100))) {
          const p = new T.Vector3(); mesh.getVertexPosition(i, p); mesh.localToWorld(p); p.project(state.camera)
          const x = q.positions[i * 3], y = q.positions[i * 3 + 1], z = q.positions[i * 3 + 2]; let cx = 0, cy = 0, cw = 0
          for (let k = 0; k < 4; k++) { const w = q.weights[i * 4 + k], e = palette[q.joints[i * 4 + k]]; cx += w * (e[0]*x+e[4]*y+e[8]*z+e[12]); cy += w * (e[1]*x+e[5]*y+e[9]*z+e[13]); cw += w * (e[3]*x+e[7]*y+e[11]*z+e[15]) }
          projectionErrorPx = Math.max(projectionErrorPx, Math.hypot((cx/cw-p.x)*innerWidth/2, (cy/cw-p.y)*innerHeight/2))
        }
        return { frame: q.frame, seconds: q.frame * .05, angle: root.rotation.y, clipTime: root.userData.animationTime, root: root.position.toArray(), camera: state.camera.position.toArray(), target: state.controls.target.toArray(), fov: state.camera.fov, filmOffset: state.camera.filmOffset, minimumPx, danger, coveredVertices, unsafeVertices, clippedVertices, invalidVertices, projectionErrorPx, low, high }
      }
      q.advance = steps => { for (let i = 0; i < steps; i++) { q.now += .05; state.advance(q.now, true); q.frame++ } }
      return { vertices: n, initialAngle: q.initialAngle, blockers: q.blockers, rootScale: root.scale.toArray() }
    })
    await page.getByRole('toolbar', { name: '动作' }).getByRole('button', { name: '行', exact: true }).click()
    await page.waitForTimeout(50)
    const result = { size, setup, cardScroll, samples: [], minimumPx: Infinity, maximumCoveredVertices: 0, maximumUnsafeVertices: 0, maximumClippedVertices: 0, maximumProjectionErrorPx: 0 }
    const count = Math.ceil(2 * Math.PI * 3 / (.07 / (.68 * 2.4)) / (.05 * report.sampleEverySteps))
    for (let i = 0; i <= count; i++) {
      const sample = await page.evaluate(steps => { const q = window.orbitQA; q.advance(steps); return q.sample() }, i ? report.sampleEverySteps : 0)
      result.samples.push(sample)
      result.maximumCoveredVertices = Math.max(result.maximumCoveredVertices, sample.coveredVertices)
      result.maximumUnsafeVertices = Math.max(result.maximumUnsafeVertices, sample.unsafeVertices)
      result.maximumClippedVertices = Math.max(result.maximumClippedVertices, sample.clippedVertices)
      result.maximumProjectionErrorPx = Math.max(result.maximumProjectionErrorPx, sample.projectionErrorPx)
      assert.equal(sample.invalidVertices, 0)
      if (sample.minimumPx < result.minimumPx) {
        result.minimumPx = sample.minimumPx; result.worst = sample
        await page.evaluate(() => { const q = window.orbitQA; q.state.gl.render = q.render; q.state.advance(q.now, true); q.state.gl.render = () => {} })
        result.worstImage = join(out, `${size.width}-worst.png`); await page.screenshot({ path: result.worstImage })
      }
    }
    result.angleCovered = result.samples.at(-1).angle - result.samples[0].angle
    result.passed = result.angleCovered >= 2 * Math.PI && result.minimumPx >= 8 && !result.maximumClippedVertices && result.maximumProjectionErrorPx < .001
    report.viewports.push(result)
    await writeFile(join(out, 'report.json'), JSON.stringify(report, null, 2) + '\n')
    console.log(JSON.stringify({ size, passed: result.passed, samples: result.samples.length, angleCovered: result.angleCovered, minimumPx: result.minimumPx, worst: result.worst }))
    await page.close()
  }
  report.passed = report.viewports.every(v => v.passed) && !report.errors.length
} finally {
  await writeFile(join(out, 'report.json'), JSON.stringify(report, null, 2) + '\n'); await browser.close()
}
console.log(JSON.stringify({ passed: report.passed, report: join(out, 'report.json') }))
if (!report.passed) process.exitCode = 1
