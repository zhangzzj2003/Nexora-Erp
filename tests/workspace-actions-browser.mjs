// 使用独立预览状态检查代表性页面；刷新替身仅记数，不连接或写入正式服务。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const { chromium } = await import(pathToFileURL(process.env.NEXORA_PLAYWRIGHT_MODULE).href)
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
  const errors = []
  page.on('pageerror', error => { errors.push(error.message); console.error(error.message) })
  await page.goto(`${process.env.NEXORA_PLAN_PREVIEW_URL || 'http://127.0.0.1:8791'}/scripts/site-preview/index.html?theme=dark#/workspace/home`)
  await page.waitForSelector('[data-preview="sample-data"]')
  await page.evaluate(async () => {
    const { usePiniaAppStore } = await import('/src/renderer/src/store/app-store.ts')
    const store = usePiniaAppStore()
    window.actionPreviewStore = store
    window.actionPreviewReads = 0
    store.user.permissions.push('customer.assign', 'crm_contact.manage', 'crm_activity.manage', 'crm_opportunity.manage', 'equipment.manage', 'equipment.create')
    store.crmOptions = { customers: [], owners: [], contacts: [], opportunities: [] }
    store.equipmentOverview = { as_of: '2026-10-20T00:00:00Z', equipment: [], plans: [], hour_plans: [], jobs: [], executors: [], materials: [], warehouses: [], work_orders: [] }
    for (const method of ['loadCrm', 'loadEquipment', 'loadSubledger', 'loadSubledgerOrders']) store[method] = async () => { window.actionPreviewReads++; return true }
  })
  for (const [path, selector, refresh, create] of [
    ['customer-relations', '.crm-workspace', '刷新资料', '新建客户跟进'],
    ['equipment-maintenance', '.equipment-workspace', '刷新维护资料', '新建维护工单'],
  ]) {
    await page.evaluate(path => { location.hash = '/workspace/' + path }, path)
    const region = page.locator(selector)
    const toolbar = region.locator('.workspace-table-toolbar').first()
    await toolbar.getByRole('button', { name: refresh, exact: true }).waitFor().catch(async error => { console.error(await region.textContent(), await page.url()); throw error })
    const actions = toolbar.locator('.workspace-table-toolbar-actions')
    const labels = await actions.getByRole('button').allTextContents()
    assert.equal(labels.at(-1), create)
    assert.equal(await region.getByRole('button', { name: refresh, exact: true }).count(), 1)
    const reads = await page.evaluate(() => window.actionPreviewReads)
    await actions.getByRole('button', { name: refresh, exact: true }).click()
    assert.equal(await page.evaluate(() => window.actionPreviewReads), reads + 1)
    for (const width of [1500, 880, 820]) {
      await page.setViewportSize({ width, height: 1000 })
      await page.waitForTimeout(150)
      const bounds = await toolbar.boundingBox()
      for (const button of await actions.getByRole('button').all()) {
        const box = await button.boundingBox()
        assert.ok(box.x >= bounds.x && box.x + box.width <= bounds.x + bounds.width + 1, JSON.stringify({ path, width, box, bounds }))
      }
    }
    await page.setViewportSize({ width: 1500, height: 1000 })
    await page.screenshot({ path: `/private/tmp/nexora-actions-${path}.png` })
  }
  // 多个设备页签都必须带刷新和主操作，不残留顶部重复按钮。
  for (const label of ['设备台账', '日历计划', '运行小时计划']) {
    await page.locator('.equipment-workspace > .equipment-toolbar').getByRole('button', { name: label, exact: true }).click()
    const toolbar = page.locator('.equipment-workspace .workspace-table-toolbar').first()
    assert.equal(await toolbar.getByRole('button', { name: '刷新维护资料', exact: true }).count(), 1)
    assert.equal(await toolbar.getByRole('button').count(), 2)
  }
  await page.evaluate(() => { window.actionPreviewStore.connectionLost = true })
  assert.equal(await page.getByRole('button', { name: '刷新维护资料', exact: true }).isDisabled(), true)
  assert.deepEqual(errors, [])
  console.log('通过：CRM 与设备维护实际操作栏、刷新事件、主操作顺序、全部维护页签、离线禁用和 820–1500px 换行。')
} finally { await browser.close() }
