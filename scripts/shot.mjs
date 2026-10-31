// 开发用截图：用本机 Chrome 打开页面，等神兽挂载（控制台出现 ready 标记）后再截图。
// 用法：node scripts/shot.mjs <url> <out.png> [宽x高] [额外等待毫秒]
import { chromium } from 'playwright-core'

const [url, out, size = '1440x900', extra = '2500'] = process.argv.slice(2)
const [width, height] = size.split('x').map(Number)
const browser = await chromium.launch({
  channel: 'chrome',
  args: ['--use-angle=metal', '--enable-gpu', '--hide-scrollbars'],
})
const page = await browser.newPage({ viewport: { width, height } })
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
const ready = page.waitForEvent('console', { predicate: (m) => m.text().includes('[beast] ready'), timeout: 30000 })
await page.goto(url)
await ready.catch(() => errors.push('等待 [beast] ready 超时'))
await page.waitForTimeout(Number(extra))
await page.screenshot({ path: out })
await browser.close()
console.log(errors.length ? `截图完成，有错误：\n${errors.join('\n')}` : `截图完成 ${out}`)
