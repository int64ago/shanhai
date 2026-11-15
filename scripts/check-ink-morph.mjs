// Local renderer regression for corrective shapes; no downloaded or production assets.
// Compare actual shader GPU silhouettes to CPU-evaluated morph + skin positions.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { chromium } from 'playwright-core'
const [base, outArg] = process.argv.slice(2)
assert(base && outArg, 'Usage: node scripts/check-ink-morph.mjs <vite-url> <new-output-dir>')
const output = resolve(outArg)
await mkdir(output, { recursive: false })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 900, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready jimeng'), timeout: 60000 })
  await page.goto(`${base}/?beast=jimeng&action=idle`)
  await ready
  const result = await page.evaluate(async () => {
    const urls = performance.getEntriesByType('resource').map(e => e.name)
    const T = await import(urls.find(u => new URL(u).pathname.endsWith('/three.js')))
    const fiber = await import(urls.find(u => u.includes('@react-three_fiber.js')))
    const { createInkMaterial } = await import('/src/systems/ink/inkMaterial.ts')
    const { createOutline } = await import('/src/systems/ink/inkify.ts')
    const store = [...fiber._roots.values()][0].store, state = store.getState()
    state.setFrameloop('never')
    const geometry = new T.SphereGeometry(.5, 40, 28)
    geometry.translate(0, .8, 0)
    const p = geometry.attributes.position, n = geometry.attributes.normal
    const dp = new Float32Array(p.count * 3), dn = new Float32Array(p.count * 3)
    const joints = new Uint16Array(p.count * 4), weights = new Float32Array(p.count * 4)
    for (let i = 0; i < p.count; i++) {
      dp.set([.65 * p.getX(i), .22 * (p.getY(i) - .8), -.3 * p.getZ(i)], i * 3)
      const targetNormal = new T.Vector3(n.getX(i) / 1.65, n.getY(i) / 1.22, n.getZ(i) / .7).normalize()
      dn.set([targetNormal.x - n.getX(i), targetNormal.y - n.getY(i), targetNormal.z - n.getZ(i)], i * 3)
      const w = T.MathUtils.clamp((p.getY(i) - .45) / .6, 0, 1)
      joints.set([0, 1, 0, 0], i * 4); weights.set([1 - w, w, 0, 0], i * 4)
    }
    geometry.morphTargetsRelative = true
    geometry.morphAttributes.position = [new T.BufferAttribute(dp, 3)]
    geometry.morphAttributes.normal = [new T.BufferAttribute(dn, 3)]
    geometry.setAttribute('skinIndex', new T.BufferAttribute(joints, 4))
    geometry.setAttribute('skinWeight', new T.BufferAttribute(weights, 4))
    const material = createInkMaterial({ map: null, tint: '#789b9c' })
    const mesh = new T.SkinnedMesh(geometry, material), root = new T.Bone(), upper = new T.Bone()
    upper.position.y = .7; root.add(upper); mesh.add(root)
    mesh.bind(new T.Skeleton([root, upper])); mesh.frustumCulled = false
    const outline = createOutline(mesh, .018)
    const fixture = new T.Group(); fixture.add(mesh, outline)
    // Exercise AnimationMixer's weights binding instead of assigning only a test copy.
    const mixer = new T.AnimationMixer(mesh)
    const clip = new T.AnimationClip('corrective', 1, [new T.NumberKeyframeTrack('.morphTargetInfluences[0]', [0, 1], [0, 1])])
    const action = mixer.clipAction(clip).setLoop(T.LoopOnce, 1); action.clampWhenFinished = true; action.play()
    const testScene = new T.Scene(); testScene.add(fixture)
    const camera = new T.PerspectiveCamera(35, 1, .01, 20)
    camera.position.set(.8, 1.1, 3.4); camera.lookAt(0, .8, 0); camera.updateMatrixWorld(true)
    const target = new T.WebGLRenderTarget(384, 384)
    const renderer = state.gl, previousTarget = renderer.getRenderTarget()
    const previousColor = renderer.getClearColor(new T.Color()), previousAlpha = renderer.getClearAlpha()
    const white = 'void main(){ gl_FragColor = vec4(1.0); }'
    const originalFragment = material.fragmentShader
    material.fragmentShader = white; material.needsUpdate = true
    const outlineFragment = outline.material.fragmentShader
    outline.material.fragmentShader = white; outline.material.side = T.FrontSide
    outline.material.uniforms.uWidth.value = 0; outline.material.uniforms.uDepthBias.value = 0; outline.material.needsUpdate = true
    const readMask = () => {
      renderer.setRenderTarget(target); renderer.setClearColor(0, 1); renderer.clear(); renderer.render(testScene, camera)
      const bytes = new Uint8Array(384 * 384 * 4); renderer.readRenderTargetPixels(target, 0, 0, 384, 384, bytes)
      return bytes
    }
    const comparison = (a, b) => {
      let difference = 0, foreground = 0
      for (let i = 0; i < a.length; i += 4) { const aa = a[i] > 127, bb = b[i] > 127; if (aa || bb) foreground++; if (aa !== bb) difference++ }
      return { differentPixels: difference, foregroundPixels: foreground, fraction: difference / Math.max(1, foreground) }
    }
    const samples = []
    for (const weight of [0, .5, 1]) {
      action.reset().play(); mixer.setTime(weight); root.position.x = .04; upper.rotation.z = .35
      fixture.updateMatrixWorld(true); mesh.skeleton.update()
      const evaluated = geometry.clone(); evaluated.morphAttributes = {}; evaluated.deleteAttribute('skinIndex'); evaluated.deleteAttribute('skinWeight')
      const xyz = new Float32Array(p.count * 3), normals = new Float32Array(p.count * 3), v = new T.Vector3()
      const matrices = [0, 1].map(i => new T.Matrix4().fromArray(mesh.skeleton.boneMatrices, i * 16))
      for (let i = 0; i < p.count; i++) {
        mesh.getVertexPosition(i, v); xyz.set(v.toArray(), i * 3)
        const skin = new T.Matrix4(); skin.elements.fill(0)
        for (let k = 0; k < 16; k++) skin.elements[k] = matrices[0].elements[k] * weights[i * 4] + matrices[1].elements[k] * weights[i * 4 + 1]
        skin.premultiply(mesh.bindMatrixInverse).multiply(mesh.bindMatrix)
        v.set(n.getX(i) + weight * dn[i * 3], n.getY(i) + weight * dn[i * 3 + 1], n.getZ(i) + weight * dn[i * 3 + 2])
        v.applyMatrix3(new T.Matrix3().setFromMatrix4(skin)); normals.set(v.toArray(), i * 3)
      }
      evaluated.setAttribute('position', new T.BufferAttribute(xyz, 3)); evaluated.setAttribute('normal', new T.BufferAttribute(normals, 3)); evaluated.computeBoundingSphere()
      const referenceMaterial = createInkMaterial({ map: null }); referenceMaterial.fragmentShader = white
      const reference = new T.Mesh(evaluated, referenceMaterial); reference.frustumCulled = false
      mesh.visible = false; outline.visible = false; testScene.add(reference); const cpu = readMask(); testScene.remove(reference)
      mesh.visible = true; const ink = readMask(); mesh.visible = false; outline.visible = true; const line = readMask()
      const normalFragment = 'varying vec3 vN; void main(){ gl_FragColor = vec4(normalize(vN) * .5 + .5, 1.0); }'
      material.fragmentShader = referenceMaterial.fragmentShader = normalFragment; material.needsUpdate = referenceMaterial.needsUpdate = true
      outline.visible = false; testScene.add(reference); const cpuNormals = readMask(); testScene.remove(reference)
      mesh.visible = true; const gpuNormals = readMask(); mesh.visible = false
      let normalMaxDelta8bit = 0, normalSum = 0, normalChannels = 0
      for (let i = 0; i < cpu.length; i += 4) {
        if (cpu[i] < 128 || ink[i] < 128) continue
        for (let k = 0; k < 3; k++) { const d = Math.abs(cpuNormals[i + k] - gpuNormals[i + k]); normalMaxDelta8bit = Math.max(normalMaxDelta8bit, d); normalSum += d; normalChannels++ }
      }
      material.fragmentShader = white; material.needsUpdate = true
      samples.push({ weight, actualMeshWeight: mesh.morphTargetInfluences[0], actualOutlineWeight: outline.morphTargetInfluences?.[0], ink: comparison(cpu, ink), outline: comparison(cpu, line), normalMaxDelta8bit, normalMeanDelta8bit: normalSum / normalChannels })
      evaluated.dispose(); reference.material.dispose()
    }
    renderer.setRenderTarget(previousTarget); renderer.setClearColor(previousColor, previousAlpha); target.dispose()
    material.fragmentShader = originalFragment; material.needsUpdate = true
    outline.material.fragmentShader = outlineFragment; outline.material.side = T.BackSide
    outline.material.uniforms.uWidth.value = .018; outline.material.uniforms.uDepthBias.value = .0012; outline.material.needsUpdate = true
    mesh.visible = outline.visible = true
    state.scene.getObjectByName('jimeng_root').visible = false; state.controls.enabled = false
    fixture.position.set(0, .1, 1); state.scene.add(fixture)
    const fixedCamera = camera.clone(); fixedCamera.position.z += 1; fixedCamera.position.y += .1
    fixedCamera.lookAt(0, .9, 1); fixedCamera.updateMatrixWorld(true)
    state.internal.subscribe({ current: () => { state.camera.copy(fixedCamera); state.camera.updateMatrixWorld(true) } }, 0, store)
    const style = document.createElement('style'); style.textContent = 'body * {visibility:hidden!important} canvas,#morph-test-label {visibility:visible!important}'; document.head.append(style)
    const label = document.createElement('div'); label.id = 'morph-test-label'
    Object.assign(label.style, { position: 'fixed', top: '16px', left: '16px', padding: '12px', background: '#efe6d2', color: '#54392e', zIndex: 999 })
    document.body.append(label)
    window.inkMorphTest = {
      set(weight) { action.reset().play(); mixer.setTime(weight); fixture.updateMatrixWorld(true); mesh.skeleton.update(); label.textContent = `水墨 morph + skin / ${weight} · 独立渲染诊断，非整兽验收`; for (let i = 0; i < 3; i++) fiber.advance(1, true); return { meshWeight: mesh.morphTargetInfluences[0], outlineWeight: outline.morphTargetInfluences?.[0] } },
    }
    return { samples, outlineSharesInfluences: outline.morphTargetInfluences === mesh.morphTargetInfluences, outlineSharesDictionary: outline.morphTargetDictionary === mesh.morphTargetDictionary, restNoisePreserved: material.vertexShader.includes('vObj = position;'), widthPositiveForVisualReview: outline.material.uniforms.uWidth.value }
  })
  for (const weight of [0, .5, 1]) {
    const actual = await page.evaluate(w => window.inkMorphTest.set(w), weight)
    assert.equal(actual.meshWeight, weight); assert.equal(actual.outlineWeight, weight)
    await page.screenshot({ path: join(output, `morph-${weight}.png`) })
  }
  await writeFile(join(output, 'report.json'), JSON.stringify({ ...result, errors, visualReview: 'PENDING_READ', wholeBeastAccepted: false }, null, 2) + '\n')
  console.log(JSON.stringify({ output, ...result, errors }))
  assert.equal(errors.length, 0, errors.join('\n'))
  assert(result.outlineSharesInfluences && result.outlineSharesDictionary, 'Outline must follow animated mesh morph weights')
  assert(result.restNoisePreserved)
  for (const sample of result.samples) {
    assert.equal(sample.actualMeshWeight, sample.weight)
    assert.equal(sample.actualOutlineWeight, sample.weight)
    assert(sample.ink.fraction < .002 && sample.outline.fraction < .002, `GPU silhouette differs from CPU morph+skin at ${sample.weight}`)
    assert(sample.normalMaxDelta8bit <= 2, `GPU normals differ from CPU morph+skin at ${sample.weight}`)
  }
} finally { await browser.close() }
