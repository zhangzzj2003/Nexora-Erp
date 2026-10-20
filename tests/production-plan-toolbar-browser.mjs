// 使用真实页面和隔离内存样例，验证按钮位置与草稿保留，不访问正式服务。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const modulePath = process.env.NEXORA_PLAYWRIGHT_MODULE
if (!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 Playwright 入口。')
const { chromium } = await import(pathToFileURL(modulePath).href)
const origin = process.env.NEXORA_PLAN_PREVIEW_URL || 'http://127.0.0.1:8791'
const browser = await chromium.launch({ headless: true, channel: process.env.NEXORA_CHROMIUM_CHANNEL || 'chrome' })
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1100 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`${origin}/scripts/site-preview/index.html?qa=productionPlans&theme=dark#/workspace/production-plans`)
  const toolbar = page.locator('.production-plans > .workspace-table > .workspace-table-toolbar')
  const actions = toolbar.locator('.workspace-table-toolbar-actions')
  await actions.getByRole('button', { name: '新建生产计划', exact: true }).waitFor()
  await page.waitForTimeout(300)
  assert.deepEqual(await actions.getByRole('button').allTextContents(), ['刷新计划', '物料需求计划', '生产工单', '新建生产计划'])
  assert.equal(await page.locator('#workspace-page-summary .summary-filter').count(), 5)
  assert.equal(await page.locator('.production-plans > .plan-toolbar, .production-plans > .workspace-summary').count(), 0)
  const search = toolbar.getByRole('searchbox', { name: '搜索计划', exact: true })
  const reset = toolbar.getByRole('button', { name: '重置', exact: true })
  assert.equal(await reset.isDisabled(), true)
  const searchBox = await search.boundingBox(), createBox = await actions.getByRole('button', { name: '新建生产计划', exact: true }).boundingBox()
  assert.ok(Math.abs(searchBox.y + searchBox.height - createBox.y - createBox.height) < 2)
  await page.screenshot({ path: '/private/tmp/nexora-production-plan-toolbar-dark.png' })
  await actions.getByRole('button', { name: '新建生产计划', exact: true }).click()
  const reference = page.getByPlaceholder('例如：十月第三周生产安排')
  await reference.fill('按钮区域验收草稿')
  await page.getByRole('button', { name: '收起', exact: true }).click()
  await actions.getByRole('button', { name: '继续编制计划', exact: true }).waitFor()
  await search.fill('不会匹配任何计划')
  await page.locator('#workspace-page-summary').getByRole('button', { name: /^延期计划/ }).click()
  await page.locator('.workspace-table-empty-copy:visible').filter({ hasText: '没有匹配的生产计划。' }).first().waitFor()
  await reset.click()
  assert.equal(await search.inputValue(), '')
  assert.equal(await page.locator('#workspace-page-summary').getByRole('button', { name: /^全部计划/ }).getAttribute('aria-pressed'), 'true')
  await actions.getByRole('button', { name: '继续编制计划', exact: true }).click()
  assert.equal(await reference.inputValue(), '按钮区域验收草稿')
  await page.getByRole('button', { name: '收起', exact: true }).click()
  // 草稿按钮会增加操作区长度；覆盖中等窗口及主进程规定的 820px 最小桌面宽度。
  for (const width of [1100, 880, 820]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.waitForTimeout(100)
    const bounds = await toolbar.boundingBox()
    for (const button of await actions.getByRole('button').all()) {
      const box = await button.boundingBox()
      assert.ok(box.x >= bounds.x && box.x + box.width <= bounds.x + bounds.width + 1,
        JSON.stringify({ width, label: await button.textContent(), box, bounds }))
    }
  }
  await actions.getByRole('button', { name: '清空未保存输入', exact: true }).click()
  await actions.getByRole('button', { name: '新建生产计划', exact: true }).waitFor()
  await page.waitForTimeout(300)
  // 切换页面后旧统计应卸载，不遗留上一页卡片。
  await actions.getByRole('button', { name: '生产工单', exact: true }).click()
  await page.waitForURL('**/workspace/work-orders')
  assert.equal(await page.locator('#workspace-page-summary').getByRole('button', { name: /^全部计划/ }).count(), 0)
  await page.setViewportSize({ width: 1920, height: 1100 })
  await page.goto(`${origin}/scripts/site-preview/index.html?qa=productionPlans&theme=light#/workspace/production-plans`)
  await actions.getByRole('button', { name: '新建生产计划', exact: true }).waitFor()
  await page.screenshot({ path: '/private/tmp/nexora-production-plan-toolbar-light.png' })
  assert.deepEqual(errors, [])
  console.log('通过：标题统计、筛选栏按钮顺序与对齐、重置保留草稿、清空草稿、窄窗口换行、导航卸载统计及明暗主题。')
} finally {
  await browser.close()
}
