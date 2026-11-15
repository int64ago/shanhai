// Development-stage candidate checks. This does not certify anatomical acceptance.
// node scripts/qa-xixiyu-app.mjs http://127.0.0.1:5203 /tmp/xixiyu-qa
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { launchQABrowser } from './lib/browser.mjs'

const [base = 'http://127.0.0.1:5203', out = '/tmp/xixiyu-qa'] = process.argv.slice(2)
await mkdir(out, { recursive: true })
const report = { candidateOnly: true, passed: false, snapshots: [], errors: [] }
const browser = await launchQABrowser()
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', e => report.errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
  page.on('response', r => { if (r.status() >= 400) report.errors.push(`${r.status()} ${r.url()}`) })
  const ready = id => page.waitForSelector(`[data-stage-beast="${id}"][data-stage-state="ready"]`, { state: 'attached' })
  await page.goto(`${base}/?beast=jingwei&action=idle`)
  await ready('jingwei')
  await page.evaluate(async () => {
    const resources = performance.getEntriesByType('resource').map(r => r.name)
    const url = part => resources.find(u => new URL(u).pathname.includes(part))
    const fiber = await import(url('@react-three_fiber'))
    const { useGLTF } = await import(url('@react-three_drei'))
    const { useApp } = await import(url('/src/app/store.ts'))
    const { BEASTS } = await import(url('/src/app/beasts.ts'))
    const entry = BEASTS.find(b => b.id === 'xixiyu')
    // Preview a pending component only in this isolated browser; never change source readiness.
    const publishedReady = entry.ready
    entry.ready = true
    const cached = []
    for (const path of ['/models/xixiyu/body.glb', '/models/xixiyu/wing.glb']) {
      useGLTF.preload(path)
      let gltf
      for (;;) {
        try { gltf = useGLTF(path); break }
        catch (pending) { if (!pending?.then) throw pending; await pending }
      }
      const snapshot = () => {
        const rows = []
        gltf.scene.traverse(n => rows.push([n.uuid, n.name, n.children.map(c => c.uuid), n.position.toArray(), n.quaternion.toArray(), n.scale.toArray(), n.geometry?.uuid, n.material?.uuid]))
        return JSON.stringify(rows)
      }
      let disposals = 0
      gltf.scene.traverse(n => {
        const resources = [n.geometry, n.skeleton, ...(Array.isArray(n.material) ? n.material : [n.material])].filter(Boolean)
        for (const resource of resources) resource.addEventListener?.('dispose', () => disposals++)
      })
      cached.push({ before: snapshot(), snapshot, disposed: () => disposals })
    }
    const state = [...fiber._roots.values()][0].store.getState()
    window.xixiyuQA = { state, useApp, cached, publishedReady }
    useApp.getState().select('xixiyu')
  })
  await ready('xixiyu')
  async function inspect(label) {
    const s = await page.evaluate(() => {
      const qa = window.xixiyuQA, root = qa.state.scene.getObjectByName('xixiyu_root')
      root.updateWorldMatrix(true, true)
      let invalid = 0, wings = 0, holders = 0, outlines = 0, skinned = 0, maxWeightError = 0
      const tips = []
      root.traverse(n => {
        if (![...n.matrixWorld.elements, ...n.scale].every(Number.isFinite) || Math.min(...n.scale) <= 0) invalid++
        if (n.name.startsWith('xixiyu_wing_holder_')) holders++
        if (n.userData.inkOutline) { outlines++; return }
        if (!n.isSkinnedMesh) return
        skinned++
        if (n.name.startsWith('xixiyu_wing_')) {
          wings++
          const tip = n.skeleton.bones.at(-1)
          tips.push([n.name, ...tip.matrixWorld.elements.slice(12, 15)])
        }
        n.skeleton.update()
        if (!Array.from(n.skeleton.boneMatrices).every(Number.isFinite)) invalid++
        for (const key of ['position', 'normal', 'skinWeight']) {
          const a = n.geometry.attributes[key]
          if (a && !Array.from(a.array ?? a.data?.array ?? []).every(Number.isFinite)) invalid++
        }
        const weights = n.geometry.attributes.skinWeight
        for (let i = 0; i < weights.count; i++) maxWeightError = Math.max(maxWeightError, Math.abs(weights.getX(i) + weights.getY(i) + weights.getZ(i) + weights.getW(i) - 1))
      })
      return { wings, holders, outlines, skinned, invalid, maxWeightError, tips, cacheUnchanged: qa.cached.every(e => e.before === e.snapshot()), sharedDisposals: qa.cached.reduce((sum, e) => sum + e.disposed(), 0), action: qa.useApp.getState().action, publishedReady: qa.publishedReady }
    })
    report.snapshots.push({ label, ...s })
    assert.equal(s.wings, 8, 'Eight modular wings supplement the native folded pair')
    assert.equal(s.holders, 8, 'No StrictMode attachment duplicates')
    assert.equal(s.skinned, 10, 'Eight modular wings plus native body and feather-tip scale surfaces')
    assert.equal(s.outlines, 10)
    assert.equal(s.invalid, 0)
    assert(s.maxWeightError < .0001)
    assert(s.cacheUnchanged)
    assert.equal(s.sharedDisposals, 0)
    return s
  }
  await page.waitForTimeout(500)
  const first = await inspect('idle')
  report.candidateOnly = !first.publishedReady
  await page.screenshot({ path: join(out, 'idle.png') })
  report.walkTransition = await page.evaluate(async () => {
    const qa = window.xixiyuQA, root = qa.state.scene.getObjectByName('xixiyu_root')
    let previous = root.position.clone(), maximumFrameDisplacement = 0
    qa.useApp.getState().setAction('walk')
    for (let i = 0; i < 10; i++) {
      await new Promise(resolve => requestAnimationFrame(resolve))
      maximumFrameDisplacement = Math.max(maximumFrameDisplacement, root.position.distanceTo(previous))
      previous.copy(root.position)
    }
    return { maximumFrameDisplacement }
  })
  assert(report.walkTransition.maximumFrameDisplacement < .065, 'Idle to walk must not teleport to the figure-eight target')
  for (const action of ['walk', 'special', 'idle']) {
    await page.evaluate(a => window.xixiyuQA.useApp.getState().setAction(a), action)
    await page.waitForTimeout(400)
    await inspect(action)
    if (action !== 'idle') await page.screenshot({ path: join(out, `${action}.png`) })
    if (action === 'walk') {
      for (let i = 0; i < 3; i++) {
        await page.screenshot({ path: join(out, `motion-${i}.png`), clip: { x: 520, y: 180, width: 800, height: 480 } })
        await page.waitForTimeout(280)
      }
    }
  }
  const moved = report.snapshots[1].tips.some((tip, i) => tip.slice(1).some((v, j) => Math.abs(v - first.tips[i][j + 1]) > .001))
  assert(moved, 'Wing skeletons must move')
  await page.evaluate(() => window.xixiyuQA.useApp.getState().setAction('special'))
  await page.waitForFunction(() => window.xixiyuQA.useApp.getState().action === 'idle', null, { timeout: 15000 })
  await inspect('special-finished')
  await page.evaluate(() => window.xixiyuQA.useApp.getState().select('jingwei'))
  await ready('jingwei')
  await page.evaluate(() => window.xixiyuQA.useApp.getState().select('xixiyu'))
  await ready('xixiyu')
  await page.waitForTimeout(400)
  await inspect('remounted')
  await page.screenshot({ path: join(out, 'remounted.png') })
  // Isolate the native folded pair for inspection of the hand-modeled scales.
  // These audit images deliberately hide modular holders; action images above
  // retain the complete ten-wing assembly.
  await page.evaluate(() => {
    const { state } = window.xixiyuQA
    state.scene.getObjectByName('xixiyu_root').traverse(n => {
      if (n.name.startsWith('xixiyu_wing_holder_')) n.visible = false
    })
    state.camera.position.set(1.25, 0.66, 0.10)
    state.controls.target.set(0, 0.46, 0)
    state.controls.update()
  })
  await page.waitForTimeout(150)
  await page.screenshot({ path: join(out, 'native-scales-audit.png') })
  assert.deepEqual(report.errors, [])
  report.passed = true
} catch (e) {
  report.failure = String(e.stack || e)
  process.exitCode = 1
} finally {
  await browser.close()
  await writeFile(join(out, 'xixiyu-qa.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
}
