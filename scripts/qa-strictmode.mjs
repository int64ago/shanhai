// React 19 StrictMode + useGLTF cache-isolation, disposal, remount & skinning QA (via vite dev).
// Usage: node scripts/qa-strictmode.mjs [baseUrl] [outDir]
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { launchQABrowser, withViteServer } from './lib/browser.mjs'

const [explicitUrl, outDir = process.env.QA_OUT_DIR || '/tmp/shanhai-qa-browser'] = process.argv.slice(2)
await mkdir(outDir, { recursive: true })

const TARGETS = [
  { id: 'jiuweihu', glbs: ['/models/jiuweihu/body.glb', '/models/jiuweihu/tail.glb'], cloned: false },
  { id: 'dijiang', glbs: ['/models/dijiang/body.glb', '/models/dijiang/wing.glb', '/models/dijiang/leg.glb'], cloned: false },
  { id: 'qitu', glbs: ['/models/qitu/body.glb', '/models/qitu/head.glb', '/models/qitu/tail.glb'], cloned: false },
  { id: 'ershu', glbs: ['/models/ershu/body.glb'], cloned: true },
  { id: 'changyou', glbs: ['/models/changyou/body.glb'], cloned: true },
  { id: 'feiyi_snake', glbs: ['/models/feiyi_snake/body.glb'], cloned: true },
]

const report = {
  mode: 'strictmode-dev',
  beasts: [],
  unexpectedErrors: [],
  passed: false,
}

async function waitStageReady(page, id, timeout = 45_000) {
  await page.waitForSelector(`[data-stage-beast="${id}"][data-stage-state="ready"]`, {
    state: 'attached',
    timeout,
  })
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
}

try {
  await withViteServer('dev', explicitUrl, async (base) => {
    const browser = await launchQABrowser()
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
      page.on('pageerror', (err) => report.unexpectedErrors.push(`pageerror: ${String(err)}`))
      page.on('console', (msg) => {
        if (msg.type() === 'error') report.unexpectedErrors.push(`console.error: ${msg.text()}`)
      })
      page.on('response', (res) => {
        if (res.status() >= 400) report.unexpectedErrors.push(`http ${res.status()}: ${res.url()}`)
      })

      await page.goto(`${base}/?beast=jingwei&action=idle`, { waitUntil: 'domcontentloaded' })
      await waitStageReady(page, 'jingwei')

      await page.evaluate(async () => {
        const findModule = (match) =>
          performance
            .getEntriesByType('resource')
            .map((r) => r.name)
            .find((u) => match(new URL(u).pathname))

        const dreiUrl = findModule((p) => p.includes('@react-three_drei'))
        const fiberUrl = findModule((p) => p.includes('@react-three_fiber'))
        const storeUrl = findModule((p) => p === '/src/app/store.ts')
        if (!dreiUrl || !fiberUrl || !storeUrl) {
          throw new Error(`Missing Vite dev module handles: drei=${dreiUrl} fiber=${fiberUrl} store=${storeUrl}`)
        }

        const { useGLTF } = await import(dreiUrl)
        const fiber = await import(fiberUrl)
        const { useApp } = await import(storeUrl)
        const r3fState = [...fiber._roots.values()][0].store.getState()

        window.__strictQA = { useGLTF, r3fState, useApp, tracked: new Map() }
      })

      for (const target of TARGETS) {
        // 1. Preload & snapshot raw cached useGLTF scene before StrictMode mount
        await page.evaluate(async ({ id, glbs }) => {
          const qa = window.__strictQA
          const entries = []

          for (const url of glbs) {
            qa.useGLTF.preload(url)
            let gltf
            for (;;) {
              try {
                gltf = qa.useGLTF(url)
                break
              } catch (pending) {
                if (!pending?.then) throw pending
                await pending
              }
            }
            const source = gltf.scene
            const sharedResources = new Map()
            source.traverse((n) => {
              if (n.geometry) sharedResources.set(n.geometry, { type: 'geometry', disposals: 0 })
              if (n.skeleton) sharedResources.set(n.skeleton, { type: 'skeleton', disposals: 0 })
              const mats = Array.isArray(n.material) ? n.material : n.material ? [n.material] : []
              for (const m of mats) {
                sharedResources.set(m, { type: 'material', disposals: 0 })
                for (const v of Object.values(m)) {
                  if (v?.isTexture) sharedResources.set(v, { type: 'texture', disposals: 0 })
                }
              }
            })
            for (const [res, row] of sharedResources) {
              res.addEventListener?.('dispose', () => row.disposals++)
            }

            const snapshot = () => {
              const rows = []
              source.traverse((n) =>
                rows.push({
                  uuid: n.uuid,
                  name: n.name,
                  children: n.children.map((c) => c.uuid),
                  p: n.position.toArray(),
                  q: n.quaternion.toArray(),
                  s: n.scale.toArray(),
                  geometry: n.geometry?.uuid,
                  skeleton: n.skeleton?.uuid,
                  outline: !!n.userData.inkOutline,
                  materials: (Array.isArray(n.material) ? n.material : n.material ? [n.material] : []).map((m) => ({
                    uuid: m.uuid,
                    type: m.type,
                    side: m.side,
                    userData: JSON.stringify(m.userData),
                  })),
                }),
              )
              return JSON.stringify(rows)
            }

            entries.push({ url, before: snapshot(), snapshot, sharedResources })
          }

          qa.tracked.set(id, entries)
        }, target)

        // 2. First StrictMode mount
        await page.evaluate((id) => window.__strictQA.useApp.getState().select(id), target.id)
        await waitStageReady(page, target.id)

        const mountCheck = await page.evaluate((id) => {
          const qa = window.__strictQA
          const { scene } = qa.r3fState
          scene.updateMatrixWorld(true)

          let invalid = 0
          let outlines = 0
          let skinnedMeshes = 0
          let bones = 0
          let tailHolders = 0

          scene.traverse((n) => {
            if (![...n.matrixWorld.elements, ...n.position, ...n.quaternion, ...n.scale].every(Number.isFinite)) {
              invalid++
            }
            if ((n.isSkinnedMesh || n.isBone || n.userData?.inkOutline) && Math.min(...n.scale) <= 0) invalid++
            if (n.name === 'tail_holder') tailHolders++
            if (n.isBone) bones++
            if (!n.isMesh) return
            if (n.userData.inkOutline) {
              outlines++
              return
            }
            if (n.isSkinnedMesh) {
              skinnedMeshes++
              if (n.skeleton) {
                n.skeleton.update()
                if (!Array.from(n.skeleton.boneMatrices).every(Number.isFinite)) invalid++
              }
              for (const attrName of ['position', 'normal', 'skinWeight']) {
                const attr = n.geometry.attributes[attrName]
                if (attr && !Array.from(attr.array ?? attr.data?.array ?? []).every(Number.isFinite)) invalid++
              }
            }
          })

          const entries = qa.tracked.get(id)
          const cacheUnchanged = entries.every((e) => e.before === e.snapshot())
          const sharedDisposals = entries.reduce(
            (sum, e) => sum + [...e.sharedResources.values()].reduce((s, r) => s + r.disposals, 0),
            0,
          )
          return { invalid, outlines, skinnedMeshes, bones, tailHolders, cacheUnchanged, sharedDisposals }
        }, target.id)

        assert.equal(mountCheck.invalid, 0, `${target.id} mount had non-finite transforms/weights/bones`)
        assert(mountCheck.outlines > 0, `${target.id} must have ink outline meshes`)
        assert(mountCheck.skinnedMeshes > 0, `${target.id} must have skinned meshes`)
        if (target.id === 'jiuweihu') {
          assert.equal(mountCheck.tailHolders, 1, 'StrictMode must attach tail_holder exactly once')
        }
        if (target.cloned) {
          assert(mountCheck.cacheUnchanged, `${target.id} mutated shared useGLTF cache on StrictMode mount`)
        }
        assert.equal(mountCheck.sharedDisposals, 0, `${target.id} disposed shared useGLTF resource on mount`)

        // 3. Unmount by switching to jingwei -> verify zero shared disposals (& unchanged cache for cloned)
        await page.evaluate(() => window.__strictQA.useApp.getState().select('jingwei'))
        await waitStageReady(page, 'jingwei')

        const unmountCheck = await page.evaluate((id) => {
          const entries = window.__strictQA.tracked.get(id)
          const cacheUnchanged = entries.every((e) => e.before === e.snapshot())
          const sharedDisposals = entries.reduce(
            (sum, e) => sum + [...e.sharedResources.values()].reduce((s, r) => s + r.disposals, 0),
            0,
          )
          return { cacheUnchanged, sharedDisposals }
        }, target.id)

        if (target.cloned) {
          assert(unmountCheck.cacheUnchanged, `${target.id} cache changed after unmount`)
        }
        assert.equal(unmountCheck.sharedDisposals, 0, `${target.id} disposed shared useGLTF resource on unmount`)

        // 4. Remount -> verify walk & special run cleanly without NaN or cache mutation
        await page.evaluate((id) => window.__strictQA.useApp.getState().select(id), target.id)
        await waitStageReady(page, target.id)

        for (const action of ['walk', 'special', 'idle']) {
          await page.evaluate((a) => window.__strictQA.useApp.getState().setAction(a), action)
          await page.waitForTimeout(260)
          const invalidAfterAction = await page.evaluate(() => {
            const { scene } = window.__strictQA.r3fState
            scene.updateMatrixWorld(true)
            let invalid = 0
            scene.traverse((n) => {
              if (![...n.matrixWorld.elements, ...n.position, ...n.quaternion, ...n.scale].every(Number.isFinite)) {
                invalid++
              }
              if (n.isSkinnedMesh && n.skeleton) {
                n.skeleton.update()
                if (!Array.from(n.skeleton.boneMatrices).every(Number.isFinite)) invalid++
              }
            })
            return invalid
          })
          assert.equal(invalidAfterAction, 0, `${target.id} remount ${action} produced non-finite matrices`)
        }

        const finalCheck = await page.evaluate((id) => {
          const entries = window.__strictQA.tracked.get(id)
          return {
            cacheUnchanged: entries.every((e) => e.before === e.snapshot()),
            zeroDisposals: entries.every((e) => [...e.sharedResources.values()].every((r) => r.disposals === 0)),
          }
        }, target.id)
        if (target.cloned) {
          assert(finalCheck.cacheUnchanged, `${target.id} shared cache mutated after remount actions`)
        }
        assert(finalCheck.zeroDisposals, `${target.id} shared resource disposed after remount actions`)

        report.beasts.push({
          id: target.id,
          cloned: target.cloned,
          ...mountCheck,
          remountPassed: true,
        })
      }

      assert.deepEqual(report.unexpectedErrors, [], `Unexpected errors: ${report.unexpectedErrors.join('; ')}`)
      report.passed = true
    } finally {
      await browser.close()
    }
  })
} catch (err) {
  report.passed = false
  report.failure = err instanceof Error ? err.stack || err.message : String(err)
  process.exitCode = 1
} finally {
  await writeFile(join(outDir, 'strictmode-qa.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
}
