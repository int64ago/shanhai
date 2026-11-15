// Real Stage eye closeups and raycast UV/rest-surface probes; no scene/material edits.
// node scripts/review-lingyu-eyes.mjs BASE NEW_OUTPUT [CANDIDATE.glb] [PREPARATION.json]
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright-core'
const [base, outArg, modelArg, preparationArg = 'raw/_build/lingyu-runtime-v1/lingyu-preparation.json'] = process.argv.slice(2)
assert(base && outArg)
const preparation = JSON.parse(await readFile(resolve(preparationArg), 'utf8'))
const out = resolve(outArg)
await mkdir(out, { recursive: false })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
try {
 const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
 if (modelArg) { const bytes = await readFile(resolve(modelArg)); await page.route('**/models/lingyu/body.glb*', r => r.fulfill({ body: bytes, contentType: 'model/gltf-binary' })) }
 const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready lingyu'), timeout: 60000 })
 await page.goto(`${base}/?beast=lingyu&action=idle`); await ready
 await page.addStyleTag({ content: '.card,.story-caption,.scroll-wrap,.controls,.actions,.title{visibility:hidden!important}' })
 const setup = await page.evaluate(async reference => {
  const resources = performance.getEntriesByType('resource').map(r => r.name), module = suffix => resources.find(u => new URL(u).pathname.endsWith(suffix))
  const T = await import(module('/three.js')), fiber = await import(module('/@react-three_fiber.js')), { useApp } = await import(module('/src/app/store.ts')), { useGLTF } = await import(module('/@react-three_drei.js'))
  const state = [...fiber._roots.values()][0].store.getState(), root = state.scene.getObjectByName('lingyu_root'), meshes = [], sources = [], source = useGLTF('/models/lingyu/body.glb').scene
  root.traverse(n => { if (n.isMesh && !n.userData.inkOutline) meshes.push(n) }); source.updateMatrixWorld(true); source.traverse(n => { if (n.isMesh) { n.skeleton.update(); sources.push(n) } })
  const target = new T.Vector3(), p = new T.Vector3(); let count = 0
  for (const [index, m] of meshes.entries()) for (let i = 0; i < m.geometry.attributes.position.count; i++) { const s = sources[index]; s.getVertexPosition(i, p); s.localToWorld(p); const raw = p.clone().sub(new T.Vector3(0, reference.elevationM, 0)).divideScalar(reference.uniformScale).add(new T.Vector3(...reference.rawOrigin)); if (raw.z > .65) { m.getVertexPosition(i, p); target.add(m.localToWorld(p)); count++ } }
  target.divideScalar(count)
  const c = state.controls; c.target.lerp = function () { return this }; c.minDistance = .1; c.minPolarAngle = 0; c.maxPolarAngle = Math.PI; c.enableDamping = false; c.target.copy(target)
  state.camera.filmOffset = 0; state.camera.fov = 38; state.camera.updateProjectionMatrix(); state.camera.position.copy(target).add(new T.Vector3(0, .1, 1).normalize().multiplyScalar(1.1)); c.update()
  window.lingyuEyeReview = { T, state, meshes, sources, useApp, reference }
  return { target: target.toArray(), reference }
 }, preparation)
 await page.waitForTimeout(300)
 await page.screenshot({ path: join(out, 'idle-face.png') })
 const probes = await page.evaluate(() => {
  const { T, state, meshes, sources, reference } = window.lingyuEyeReview, ray = new T.Raycaster(), result = []
  for (let y = 250; y <= 550; y += 10) for (let x = 400; x <= 1000; x += 10) {
   ray.setFromCamera(new T.Vector2(x / innerWidth * 2 - 1, 1 - y / innerHeight * 2), state.camera)
   const h = ray.intersectObjects(meshes, false)[0]; if (!h) continue
   const m = h.object, local = m.worldToLocal(h.point.clone()), ids = [h.face.a, h.face.b, h.face.c], posed = ids.map(i => m.getVertexPosition(i, new T.Vector3())), b = T.Triangle.getBarycoord(local, ...posed, new T.Vector3()), rest = new T.Vector3()
   const s = sources[meshes.indexOf(m)]
   ids.forEach((i, j) => rest.addScaledVector(s.localToWorld(s.getVertexPosition(i, new T.Vector3())), b.getComponent(j)))
   const raw = rest.sub(new T.Vector3(0, reference.elevationM, 0)).divideScalar(reference.uniformScale).add(new T.Vector3(...reference.rawOrigin))
   result.push({ screen: [x, y], uv: h.uv?.toArray(), raw: raw.toArray() })
  }
  return result
 })
 await writeFile(join(out, 'eye-probes.json'), JSON.stringify({ setup, probes }, null, 2) + '\n')
 for (const action of ['walk', 'special']) { await page.evaluate(a => window.lingyuEyeReview.useApp.getState().setAction(a), action); await page.waitForTimeout(1000); await page.screenshot({ path: join(out, `${action}-face.png`) }) }
 console.log(out)
} finally { await browser.close() }
