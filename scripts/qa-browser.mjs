// Key end-to-end browser QA against the built production bundle (dist/ via vite preview).
// Usage: node scripts/qa-browser.mjs [baseUrl] [outDir]
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { launchQABrowser, measurePngSpread, withViteServer } from './lib/browser.mjs'

const [explicitUrl, outDir = process.env.QA_OUT_DIR || '/tmp/shanhai-qa-browser'] = process.argv.slice(2)
await mkdir(outDir, { recursive: true })

const report = {
  mode: 'production-preview',
  initialGlbs: [],
  initialRender: null,
  archetypes: [],
  placeholder: null,
  actions: [],
  retryRecovered: false,
  uiFlows: {},
  mobile: null,
  unexpectedErrors: [],
  passed: false,
}

async function waitStageState(page, id, state = 'ready', timeout = 45_000) {
  await page.waitForSelector(`[data-stage-beast="${id}"][data-stage-state="${state}"]`, {
    state: 'attached',
    timeout,
  })
  if (state === 'ready') {
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
  }
}

try {
  await withViteServer('preview', explicitUrl, async (base) => {
    const browser = await launchQABrowser()
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
      const glbRequests = []
      let ignoreExpectedAbort = false

      page.on('pageerror', (err) => {
        const text = String(err)
        if (ignoreExpectedAbort && text.includes('/models/taotie/body.glb')) return
        report.unexpectedErrors.push(`pageerror: ${text}`)
      })
      page.on('console', (msg) => {
        if (msg.type() !== 'error') return
        const text = msg.text()
        if (ignoreExpectedAbort && text.includes('ERR_FAILED')) return
        report.unexpectedErrors.push(`console.error: ${text}`)
      })
      page.on('response', (res) => {
        if (res.status() >= 400) {
          report.unexpectedErrors.push(`http ${res.status()}: ${res.url()}`)
        }
      })
      page.on('request', (req) => {
        const pathname = new URL(req.url()).pathname
        if (pathname.endsWith('.glb')) glbRequests.push(pathname)
      })
      page.on('requestfailed', (req) => {
        const pathname = new URL(req.url()).pathname
        if (ignoreExpectedAbort && pathname === '/models/taotie/body.glb') return
        report.unexpectedErrors.push(`requestfailed: ${pathname} (${req.failure()?.errorText || 'unknown'})`)
      })

      // 1. Initial homepage load + lazy-load GLB budget + rendered WebGL pixels + philology card
      await page.goto(`${base}/`, { waitUntil: 'domcontentloaded' })
      await waitStageState(page, 'jiuweihu', 'ready')
      await page.waitForLoadState('networkidle')

      assert.equal(await page.locator('.stage-loading').count(), 0, 'loading banner hidden once ready')
      assert.equal(await page.locator('.stage-error').count(), 0, 'error banner absent on healthy load')

      report.initialGlbs = [...glbRequests].sort()
      assert.deepEqual(
        report.initialGlbs,
        ['/models/jiuweihu/body.glb', '/models/jiuweihu/tail.glb'],
        `initial homepage must only fetch jiuweihu GLBs, got: ${JSON.stringify(report.initialGlbs)}`,
      )

      const canvasBox = await page.locator('canvas').boundingBox()
      assert(canvasBox && canvasBox.width >= 800 && canvasBox.height >= 500, 'WebGL canvas must fill viewport')

      const webglOk = await page.evaluate(() => {
        const c = document.createElement('canvas')
        return Boolean(c.getContext('webgl2') || c.getContext('webgl'))
      })
      assert(webglOk, 'WebGL context must be available')

      const centerShot = await page.screenshot({
        clip: { x: 480, y: 180, width: 480, height: 480 },
      })
      const spread = measurePngSpread(centerShot)
      report.initialRender = spread
      assert(spread.spread >= 40, `WebGL center crop looks blank/uniform: ${JSON.stringify(spread)}`)

      assert.equal(await page.locator('.card-name').innerText(), '九尾狐')
      assert((await page.locator('.card-source').first().innerText()).includes('原文'))
      assert((await page.locator('.card-inferred').innerText()).includes('设计'))

      // Snapshot the catalog before filtering; completed beasts need no placeholder.
      const expectedAllCount = await page.locator('.scroll-item').count()
      const expectedReadyNames = await page.locator('.scroll-item.is-ready').allTextContents()
      assert(expectedAllCount >= 62, `unexpected catalog size: ${expectedAllCount}`)
      assert(expectedReadyNames.length >= 40, `unexpected ready count: ${expectedReadyNames.length}`)

      // 2. Switch across all 5 archetypes + shared Quadruped + custom Ershu + cache hit
      const switches = [
        { id: 'dijiang', name: '帝江', archetype: 'sac', parts: 3 },
        { id: 'qitu', name: '鵸鵌', archetype: 'avian', parts: 3 },
        { id: 'changyou', name: '长右', archetype: 'biped', parts: 1 },
        { id: 'feiyi_snake', name: '肥遗', archetype: 'serpentine', parts: 1 },
        { id: 'lushu', name: '鹿蜀', archetype: 'quadruped-shared', parts: 1 },
        { id: 'ershu', name: '耳鼠', archetype: 'quadruped-custom', parts: 1 },
      ]

      for (const item of switches) {
        const t0 = Date.now()
        await page.locator('.scroll-item', { hasText: item.name }).click()
        await waitStageState(page, item.id, 'ready')
        assert.equal(await page.locator('.stage-error').count(), 0, `${item.id}: unexpected error banner`)
        assert.equal(await page.locator('.card-name').innerText(), item.name)
        report.archetypes.push({ ...item, ms: Date.now() - t0 })
      }

      const pending = page.locator('.scroll-item.is-pending').first()
      if (await pending.count()) {
        const name = (await pending.innerText()).trim()
        await pending.click()
        await page.waitForFunction((name) => document.querySelector('.card-name')?.textContent?.trim() === name, name)
        const id = await page.locator('[data-beast]').getAttribute('data-beast')
        assert(id, 'pending beast card exposes its ID')
        await waitStageState(page, id, 'ready')
        assert(await page.locator('.card-note').isVisible(), 'unready beast shows pending note')
        assert(glbRequests.includes('/models/_placeholder/fox.glb'), 'placeholder loads fox.glb on demand')
        report.placeholder = { id, name }
      }

      const glbCountBeforeCacheHit = glbRequests.length
      await page.locator('.scroll-item', { hasText: '九尾狐' }).click()
      await waitStageState(page, 'jiuweihu', 'ready')
      assert.equal(glbRequests.length, glbCountBeforeCacheHit, 'switching back to cached jiuweihu must not re-fetch GLBs')

      // 3. Action switching (idle / walk / special) & URL query routing
      for (const label of ['行', '神通', '静']) {
        await page.locator('.actions .action-btn', { hasText: label }).click()
        assert.equal(await page.locator('.actions .action-btn.is-active').innerText(), label)
        await page.waitForTimeout(220)
        report.actions.push(label)
      }

      await page.goto(`${base}/?beast=bifang&action=walk`, { waitUntil: 'domcontentloaded' })
      await waitStageState(page, 'bifang', 'ready')
      assert.equal(await page.locator('.card-name').innerText(), '毕方')
      assert.equal(await page.locator('.actions .action-btn.is-active').innerText(), '行')

      // 4. ErrorBoundary isolation + retry recovery
      let abortTaotie = true
      await page.route('**/models/taotie/body.glb', (route) => {
        if (abortTaotie) {
          abortTaotie = false
          return route.abort('failed')
        }
        return route.continue()
      })

      ignoreExpectedAbort = true
      await page.locator('.scroll-item', { hasText: '饕餮' }).click()
      await waitStageState(page, 'taotie', 'error')
      ignoreExpectedAbort = false

      const errText = (await page.locator('.stage-error').innerText()).replace(/\s+/g, ' ').trim()
      assert(errText.includes('神兽现世受阻') && errText.includes('重试加载'), `unexpected error banner text: ${errText}`)
      assert.equal(await page.locator('canvas').count(), 1, 'stage canvas stays mounted during model load error')

      await page.getByRole('button', { name: '重试加载' }).click()
      await waitStageState(page, 'taotie', 'ready')
      assert.equal(await page.locator('.stage-error').count(), 0, 'error banner clears after retry')
      report.retryRecovered = true

      // 5. Region tabs, catalog modal search, narration & controls
      await page.locator('.scroll-tab', { hasText: '已现' }).click()
      const readyScrollCount = await page.locator('.scroll-item').count()
      assert.deepEqual(await page.locator('.scroll-item').allTextContents(), expectedReadyNames, 'ready filter lists exactly the ready beasts')
      assert.equal(await page.locator('.scroll-item.is-pending').count(), 0, 'ready filter excludes pending beasts')
      await page.locator('.scroll-tab', { hasText: '全卷' }).click()
      const allScrollCount = await page.locator('.scroll-item').count()
      assert.equal(allScrollCount, expectedAllCount, 'full scroll restores the complete catalog')

      await page.locator('.catalog-trigger').click()
      await page.locator('.catalog-panel').waitFor({ state: 'visible' })
      await page.locator('.catalog-search').fill('帝江')
      assert.equal(await page.locator('.beast-card').count(), 1, 'catalog search narrows to Dijiang')
      await page.keyboard.press('Escape')
      assert.equal(await page.locator('.catalog-panel').count(), 0, 'Escape closes catalog modal')

      await page.getByRole('button', { name: '播放评书解说' }).click()
      await page.locator('.story-caption').waitFor({ state: 'visible' })
      await page.getByRole('button', { name: '停止评书解说' }).click()
      assert.equal(await page.locator('.story-caption').count(), 0)

      const qualityBtn = page.getByRole('button', { name: '切换画质' })
      const nextQuality = { 画高: '画中', 画中: '画低', 画低: '画高' }
      // First click locks quality (disabling PerformanceMonitor auto-stepping) before asserting the cycle
      await qualityBtn.click()
      const q1 = await qualityBtn.innerText()
      assert(Object.hasOwn(nextQuality, q1), `unexpected quality label: ${q1}`)
      await qualityBtn.click()
      const q2 = await qualityBtn.innerText()
      assert.equal(q2, nextQuality[q1])
      await qualityBtn.click()
      const q3 = await qualityBtn.innerText()
      assert.equal(q3, nextQuality[q2])
      await qualityBtn.click()
      assert.equal(await qualityBtn.innerText(), nextQuality[q3])

      report.uiFlows = { readyScrollCount, allScrollCount, catalogSearchPassed: true, narrationToggled: true, qualityCycled: true }

      // Release the desktop WebGL context before the independent mobile check.
      await page.close()

      // 6. Mobile viewport smoke check
      const mobilePage = await browser.newPage({ viewport: { width: 390, height: 844 } })
      mobilePage.on('pageerror', (err) => report.unexpectedErrors.push(`mobile pageerror: ${String(err)}`))
      mobilePage.on('console', (msg) => {
        if (msg.type() === 'error') report.unexpectedErrors.push(`mobile console.error: ${msg.text()}`)
      })
      mobilePage.on('response', (res) => {
        if (res.status() >= 400) report.unexpectedErrors.push(`mobile http ${res.status()}: ${res.url()}`)
      })
      await mobilePage.goto(`${base}/?beast=jiuweihu`, { waitUntil: 'domcontentloaded' })
      await waitStageState(mobilePage, 'jiuweihu', 'ready')
      const mobileBox = await mobilePage.locator('canvas').boundingBox()
      assert(mobileBox && mobileBox.width >= 350 && mobileBox.height >= 700, 'mobile canvas fills viewport')
      report.mobile = { width: Math.round(mobileBox.width), height: Math.round(mobileBox.height) }
      await mobilePage.close()

      assert.deepEqual(report.unexpectedErrors, [], `Unexpected browser errors: ${report.unexpectedErrors.join('; ')}`)
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
  await writeFile(join(outDir, 'browser-qa.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
}
