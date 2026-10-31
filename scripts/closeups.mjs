// 开发用：拉近镜头，按时间序列截几张特写，检查动作和局部细节。
// 用法：node scripts/closeups.mjs <url> <输出前缀> [张数] [间隔毫秒] [裁剪 x,y,w,h]
import { chromium } from 'playwright-core'

const [url, prefix, n = '4', gap = '600', clip] = process.argv.slice(2)
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const ready = page.waitForEvent('console', { predicate: (m) => m.text().includes('[beast] ready'), timeout: 30000 })
await page.goto(url)
await ready
await page.waitForTimeout(1500)
const [x, y, width, height] = (clip ?? '0,0,1440,900').split(',').map(Number)
for (let i = 0; i < Number(n); i++) {
  await page.screenshot({ path: `${prefix}${i}.png`, clip: { x, y, width, height } })
  await page.waitForTimeout(Number(gap))
}
await browser.close()
