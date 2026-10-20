// 只在隔离预览中替换内存样例，验证真实选择器与生产计划联动，不连接正式服务。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const modulePath = process.env.NEXORA_PLAYWRIGHT_MODULE
if (!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 Playwright 入口。')
const { chromium } = await import(pathToFileURL(modulePath).href)
const origin = process.env.NEXORA_PLAN_PREVIEW_URL || 'http://127.0.0.1:8791'
const browser = await chromium.launch({ headless: true, channel: process.env.NEXORA_CHROMIUM_CHANNEL || 'chrome' })
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/scripts/site-preview/production-plan-fixtures.mjs*', async route => {
    const response = await route.fetch()
    const body = (await response.text()).replace('export const productionPlanPreviewOperations', `
options.materials[0] = {...options.materials[0], sku:'CP-HYDY-000001', name:'智能控制器 · 网络版',
  specification:'FR-4 / 80 × 60 × 1.6mm / 双层 / 裸板 / 网络通信与远程控制扩展模块',
  package:'工业外壳', brand:'示例品牌', manufacturer_part_number:'NET-8890-PRO-EXTENDED-LONG-PART-NUMBER'}
for(let id=2;id<=18;id++){
  options.materials.push({id,sku:'QA-'+String(id).padStart(3,'0'),name:'备选生产产品 '+id,unit:'台',can_produce:id!==18})
  options.boms.push({...options.boms[0],id,material_id:id,version:id})
}
export const productionPlanPreviewOperations`)
    await route.fulfill({ response, body })
  })
  const input = page.getByRole('textbox', { name: '计划生产产品', exact: true })
  const menu = page.locator('.workspace-material-table:visible')
  const open = async () => { await input.click(); await menu.waitFor(); await page.waitForTimeout(250) }
  await page.goto(`${origin}/scripts/site-preview/index.html?qa=productionPlans&theme=dark#/workspace/production-plans`)
  await page.getByRole('button', { name: '新建生产计划', exact: true }).click()
  await open()
  assert.equal(await menu.locator('.workspace-material-table__row').count(), 17)
  assert.equal(await menu.getByText('QA-018', { exact: true }).count(), 0)
  const first = menu.locator('.workspace-material-table__row').first()
  assert.equal(await first.locator('.workspace-material-table__sku').textContent(), 'CP-HYDY-000001')
  assert.equal(await first.locator('.workspace-material-table__name').textContent(), '智能控制器 · 网络版')
  assert.match(await first.locator('.workspace-material-table__details').textContent(), /NET-8890-PRO-EXTENDED-LONG-PART-NUMBER/)
  // 表头与数据列对齐，菜单显著宽于触发框，长规格必须完整换行而非省略。
  const layout = await menu.evaluate(el => {
    const header = el.querySelector('.workspace-material-table__header').children
    const row = el.querySelector('.workspace-material-table__row').children
    const detail = el.querySelector('.workspace-material-table__details')
    return { width: el.getBoundingClientRect().width,
      aligned: [...header].every((cell, index) => Math.abs(cell.getBoundingClientRect().left - row[index].getBoundingClientRect().left) < 1),
      detailHeight: detail.clientHeight, lineHeight: parseFloat(getComputedStyle(detail).lineHeight),
      fits: detail.scrollWidth <= detail.clientWidth + 1 }
  })
  assert.ok(layout.width >= 630 && layout.aligned && layout.fits, JSON.stringify(layout))
  assert.ok(layout.detailHeight > layout.lineHeight, JSON.stringify(layout))
  await page.screenshot({ path: '/private/tmp/nexora-production-product-table-dark.png' })
  await first.click()
  await menu.waitFor({ state: 'hidden' })
  assert.match(await page.locator('.plan-product').textContent(), /BOM V2/)
  // 选择销售来源后重选产品，应仍由原页面清空来源并切到对应 BOM。
  await page.getByRole('textbox', { name: '计划销售来源', exact: true }).click()
  await page.locator('.n-base-select-option').filter({ hasText: '客户交付批次' }).click()
  await open()
  await input.fill('QA-002')
  assert.equal(await menu.locator('.workspace-material-table__row').count(), 1)
  assert.match(await menu.textContent(), /详细资料暂不可用/)
  await input.press('ArrowDown')
  await input.press('Enter')
  await menu.waitFor({ state: 'hidden' })
  assert.match(await page.locator('.plan-product').textContent(), /QA-002/)
  assert.match(await page.locator('.plan-product').textContent(), /BOM V2/)
  assert.match(await page.locator('.n-base-selection').filter({ has: page.getByRole('textbox', { name: '计划销售来源', exact: true }) }).textContent(), /自主备货/)
  await open()
  await input.fill('不存在的候选')
  await menu.getByText('暂无可选项', { exact: true }).waitFor()
  await input.press('Escape')
  await menu.waitFor({ state: 'hidden' })
  // 窄窗口下菜单仍完整处于视口内，滚动候选时固定表头不跟随内容消失。
  await page.setViewportSize({ width: 540, height: 900 })
  await open()
  const box = await menu.boundingBox()
  assert.ok(box.x >= 0 && box.x + box.width <= 541, JSON.stringify(box))
  const headerTop = (await menu.locator('.workspace-material-table__header').boundingBox()).y
  await menu.locator('.n-scrollbar-container').evaluate(el => { el.scrollTop = el.scrollHeight })
  assert.equal((await menu.locator('.workspace-material-table__header').boundingBox()).y, headerTop)
  await menu.getByText('QA-017', { exact: true }).click()
  assert.match(await page.locator('.plan-product').textContent(), /BOM V17/)
  await open()
  await page.getByText('基础信息', { exact: true }).click()
  await menu.waitFor({ state: 'hidden' })
  // 浅色主题使用相同表格，不依赖深色弹窗的局部样式。
  await page.setViewportSize({ width: 1600, height: 1100 })
  await page.goto(`${origin}/scripts/site-preview/index.html?qa=productionPlans&theme=light#/workspace/production-plans`)
  await page.getByRole('button', { name: '新建生产计划', exact: true }).click()
  await open()
  assert.equal(await menu.locator('.workspace-material-table__row').count(), 17)
  await page.screenshot({ path: '/private/tmp/nexora-production-product-table-light.png' })
  assert.deepEqual(errors, [])
  console.log('通过：两列对齐、完整详情、用途过滤、键盘搜索选择、空状态、BOM/销售来源联动、滚动、窄窗口与明暗主题。')
} finally {
  await browser.close()
}
