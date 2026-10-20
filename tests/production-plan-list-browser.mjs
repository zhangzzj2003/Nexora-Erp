// 真实页面使用隔离样例，覆盖编号入口、详情读取失败与公共状态标签，不访问正式业务数据。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const { chromium } = await import(pathToFileURL(process.env.NEXORA_PLAYWRIGHT_MODULE).href)
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
const origin = process.env.NEXORA_PLAN_PREVIEW_URL || 'http://127.0.0.1:8791'
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1280 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/scripts/site-preview/production-plan-fixtures.mjs*', async route => {
    const response = await route.fetch()
    const body = (await response.text()).replace('const options = planOptionsFixture()', `
records.splice(0, records.length, ...[
  ['draft', 'unreleased'], ['submitted', 'unreleased'], ['approved', 'unreleased'],
  ['rejected', 'unreleased'], ['withdrawn', 'unreleased'], ['executed', 'released'],
  ['executed', 'in_progress'], ['executed', 'completed'], ['executed', 'completed', 'cancelled']
].map(([approval, progress, status = 'draft'], index) => ({...planFixture(), id: index + 10,
  document_no: 'SCJH-20261020-' + String(index + 10).padStart(6, '0'), reference: '十月生产安排 ' + (index + 1),
  approval: planApproval(approval), progress, status,
  lines: ['normal','high','urgent'].map((priority, i) => ({...planFixture().lines[0], id:i + 1, sku:'CTRL-00'+(i+1), name:'智能控制器 '+(i+1), priority, plan_id: index + 10, quantity:i===1?'20.000':'100.000', unreleased_quantity:i===2?'0.000':i===1?'20.000':'100.000', released_quantity:i===2?'100.000':'0.000'}))})))
const options = planOptionsFixture()`)
    await route.fulfill({ response, body })
  })
  const number = page.getByRole('button', { name: '查看生产计划 SCJH-20261020-000010 详情', exact: true })
  const table = page.locator('.production-plans > .workspace-table')
  for (const theme of ['dark', 'light']) {
    await page.goto(`${origin}/scripts/site-preview/index.html?qa=productionPlans&theme=${theme}#/workspace/production-plans`)
    await number.waitFor()
    await page.waitForTimeout(300)
    const headers = await table.locator('.vxe-header--column .vxe-cell').allTextContents()
    assert.deepEqual(headers.slice(0, 2).map(text => text.trim()), ['计划编号', '计划名称'])
    assert.deepEqual(headers.slice(4, 6).map(text => text.trim()), ['审批状态', '执行状态'])
    assert.equal(await table.getByRole('button',{name:'单据审批',exact:true}).count(),0)
    const rows = table.locator('.vxe-body--row')
    assert.equal(await rows.count(), 9)
    const numberCell = number.locator('xpath=ancestor::td[1]')
    assert.doesNotMatch(await numberCell.textContent(), /十月生产安排/)
    const nameCell = rows.first().locator('td').nth(1)
    assert.equal((await nameCell.textContent()).trim(), '十月生产安排 1')
    for (const [index, tones] of [['pending','pending'], ['info','pending'], ['ready','pending'],
      ['danger','pending'], ['neutral','pending'], ['ready','ready'], ['ready','info'], ['ready','success'], ['neutral']].entries()) {
      const tags = rows.nth(index).locator('.app-status-tag')
      assert.equal(await tags.count(), tones.length)
      for (const [position, tone] of tones.entries()) assert.match(await tags.nth(position).getAttribute('class'), new RegExp('app-status-tag--' + tone))
    }
    await page.screenshot({ path: `/private/tmp/nexora-plan-list-${theme}.png` })
  }
  await page.evaluate(() => {
    const base = window.nexora.callApi
    window.planDetailReads = []
    window.nexora.callApi = async (operation, payload) => {
      if (operation === 'productionPlanDetail') {
        window.planDetailReads.push(payload.id)
        if (window.failPlanDetail) throw Error('验收样例：计划详情暂时不可用')
      }
      return base(operation, payload)
    }
  })
  // 编号支持键盘打开，关闭后回到同一入口；原详情按钮读取同一计划。
  await number.focus(); await number.press('Enter')
  const dialog = page.locator('.workspace-document-dialog:visible')
  await dialog.getByText('十月生产安排 1', { exact: true }).waitFor()
  assert.deepEqual(await page.evaluate(() => window.planDetailReads), [10])
  assert.equal(await dialog.locator('.document-basic .app-status-tag').count(), 2)
  assert.equal(await dialog.locator('.document-detail-field').filter({ hasText: '审批状态' }).locator('.app-status-tag').count(), 1)
  assert.equal(await dialog.locator('.document-detail-field').filter({ hasText: '执行状态' }).locator('.app-status-tag').count(), 1)
  const detailHeaders = await dialog.locator('.document-lines .vxe-header--column .vxe-cell').allTextContents()
  assert.deepEqual(detailHeaders.map(text => text.trim()), ['产品编号','产品名称','排期','优先级','计划产量','已下达 / 未下达','报工 / 合格 / 不合格'])
  const priorityTags = dialog.locator('.document-lines .vxe-body--row .app-status-tag')
  for (const [i,tone] of ['neutral','pending','danger'].entries()) assert.match(await priorityTags.nth(i).getAttribute('class'), new RegExp('app-status-tag--'+tone))
  // 详情审批直接定位当前单据；关闭审批保留底层详情，焦点返回详情窗口。
  const approvalButton = dialog.getByRole('button', {name:'单据审批',exact:true})
  await approvalButton.click()
  const approval = page.locator('.document-approval-dialog:visible')
  await approval.getByText('十月生产安排 1', {exact:true}).waitFor()
  assert.match(await approval.textContent(), /SCJH-20261020-000010/)
  assert.deepEqual((await approval.locator('.document-lines .vxe-header--column .vxe-cell').allTextContents()).map(text=>text.trim()),
    ['产品编号','产品名称','BOM 版本','计划产量','排期','完工仓库','优先级'])
  assert.equal(await approval.locator('.document-lines .vxe-body--row').count(),3)
  assert.equal(await approval.getByRole('button',{name:'查看资料',exact:true}).count(),3)
  assert.match(await approval.locator('.document-lines .vxe-body--row').first().textContent(),/智能控制器 1/)
  assert.equal(await approval.locator('.document-basic').getByText('智能控制器 1',{exact:true}).count(),0)
  await page.waitForTimeout(400)
  await page.screenshot({path:'/private/tmp/nexora-plan-approval-light.png'})
  await approval.getByRole('button', {name:'关闭',exact:true}).click()
  await approval.waitFor({state:'hidden'})
  assert.equal(await dialog.isVisible(), true)
  await page.waitForFunction(el => el === document.activeElement, await approvalButton.elementHandle())
  await page.screenshot({path:'/private/tmp/nexora-plan-detail-light.png'})
  await dialog.locator('.document-footer').getByRole('button', { name: '关闭', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(await number.evaluate(el => el === document.activeElement), true)
  await table.locator('.vxe-body--row').first().getByRole('button', { name: '计划详情', exact: true }).click()
  await dialog.getByText('十月生产安排 1', { exact: true }).waitFor()
  assert.deepEqual(await page.evaluate(() => window.planDetailReads), [10, 10, 10])
  await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
  // 读取失败时展示错误，不能把上一份详情冒充新计划；重新打开可恢复。
  await page.evaluate(() => { window.failPlanDetail = true })
  await number.click()
  await page.getByText(/验收样例：计划详情暂时不可用/).first().waitFor()
  assert.equal(await dialog.getByText('十月生产安排 1', { exact: true }).count(), 0)
  await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
  await page.evaluate(() => { window.failPlanDetail = false })
  await number.click(); await dialog.getByText('十月生产安排 1', { exact: true }).waitFor()
  await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
  // 表头下达可切换剩余产品，完成行不进入候选，提交正确行且保留已填写依据。
  await page.getByRole('button', {name:'查看生产计划 SCJH-20261020-000012 详情',exact:true}).click()
  await dialog.getByText('十月生产安排 3', {exact:true}).waitFor()
  await dialog.getByRole('button', {name:'分批下达',exact:true}).click()
  const command = page.getByRole('dialog').filter({hasText:'分批下达生产计划'})
  await command.getByLabel('操作依据', {exact:true}).fill('优先交付第二款产品')
  await command.getByLabel('选择下达产品', {exact:true}).click()
  await page.locator('.n-base-select-option').first().waitFor()
  assert.equal(await page.locator('.n-base-select-option').count(), 2)
  await page.locator('.n-base-select-option').filter({hasText:'CTRL-002'}).click()
  assert.equal(await command.getByLabel('本批下达数量', {exact:true}).inputValue(), '20.000')
  assert.equal(await command.getByLabel('操作依据', {exact:true}).inputValue(), '优先交付第二款产品')
  await command.getByLabel('本批下达数量', {exact:true}).fill('5')
  await command.getByRole('button', {name:'生成工单草稿',exact:true}).click()
  await command.waitFor({state:'hidden'})
  await dialog.getByText('优先交付第二款产品',{exact:true}).first().waitFor()
  assert.match(await dialog.locator('.document-lines .vxe-body--row').nth(1).textContent(), /5.000 \/ 15.000/)
  await dialog.locator('.document-footer').getByRole('button',{name:'关闭',exact:true}).click()
  await dialog.waitFor({state:'hidden'})
  await page.setViewportSize({ width: 820, height: 1000 })
  await page.waitForTimeout(200)
  await number.click(); await dialog.getByText('十月生产安排 1', { exact: true }).waitFor()
  await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' })
  await page.setViewportSize({width:1920,height:1280})
  await page.goto(`${origin}/scripts/site-preview/index.html?qa=productionPlans&theme=dark#/workspace/production-plans`)
  await number.click(); await dialog.getByText('十月生产安排 1',{exact:true}).waitFor()
  await dialog.getByRole('button',{name:'单据审批',exact:true}).click()
  await approval.getByText('十月生产安排 1',{exact:true}).waitFor()
  await page.waitForTimeout(400)
  await page.screenshot({path:'/private/tmp/nexora-plan-approval-dark.png'})
  await page.setViewportSize({width:820,height:1000})
  await approval.locator('.document-lines').scrollIntoViewIfNeeded()
  assert.equal(await approval.getByRole('button',{name:'关闭',exact:true}).isVisible(),true)
  await approval.getByRole('button',{name:'关闭',exact:true}).click()
  await approval.waitFor({state:'hidden'})
  await dialog.locator('.document-footer').getByRole('button',{name:'关闭',exact:true}).click()
  assert.deepEqual(errors, [])
  console.log('通过：编号名称独立列、键盘与鼠标详情入口、关闭回焦、读取失败恢复、九种状态独立列、详情审批及回焦、优先级标签、多产品分批下达、明暗主题及窄窗口。')
} finally { await browser.close() }
