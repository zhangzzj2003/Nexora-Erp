// 浏览器使用隔离内存样例，验证汇总、差异提醒、来源选择与部分生成，不触碰业务数据库。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const { chromium } = await import(pathToFileURL(process.env.NEXORA_PLAYWRIGHT_MODULE).href)
const browser = await chromium.launch({ headless: true, channel: 'chrome' })
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await page.route('**/scripts/site-preview/production-plan-fixtures.mjs*', async route => {
    const response = await route.fetch()
    const body = (await response.text()).replace('const options = planOptionsFixture()', `
      records[0].lines[0].production_requirements = '甲公司 Logo；黑色；中性包装';
      records[1].approval = planApproval(); records[1].lines[0].production_requirements = '甲公司 Logo；黑色；中性包装';
      const third = structuredClone(records[0]); third.id = 3; third.document_no = 'SCJH-20261019-000003';
      third.lines[0].id = 3; third.lines[0].plan_id = 3; third.lines[0].production_requirements = '乙公司 Logo；白色；礼盒包装'; records.push(third);
      const fourth = structuredClone(third); fourth.id = 4; fourth.document_no = 'SCJH-20261019-000004';
      fourth.lines[0].id = 4; fourth.lines[0].plan_id = 4; fourth.lines[0].production_requirements = ''; records.push(fourth);
      const options = planOptionsFixture()`)
    await route.fulfill({ response, body })
  })
  for (const theme of ['dark', 'light']) {
    await page.goto(`http://127.0.0.1:8791/scripts/site-preview/index.html?qa=productionPlans&theme=${theme}#/workspace/work-orders`)
    const entry = page.getByRole('button', { name: '从生产计划生成，1 种机型待生成' })
    await entry.waitFor()
    assert.equal(await page.locator('.production-demand-badge').innerText(), '1')
    await entry.click()
    const dialog = page.getByRole('dialog').filter({ hasText: '从生产计划生成工单' })
    await dialog.waitFor()
    await dialog.getByText('待生成 400.000 台', { exact: true }).waitFor()
    assert.equal(await dialog.locator('.demand-model').count(), 1)
    assert.equal(await dialog.locator('.demand-variant').count(), 3)
    await dialog.getByText('生产要求：未填写，需核对 Logo、颜色、包装等要求', { exact: true }).waitFor()
    const same = dialog.locator('.demand-variant').filter({ hasText: '甲公司 Logo；黑色；中性包装' })
    await same.getByText('200.000 台', { exact: true }).waitFor()
    assert.equal(await same.getByRole('button', { name: '选择生成', exact: true }).count(), 2)
    // 等待公共弹窗入场完成再截图，避免把过渡帧当作界面验收。
    await page.waitForFunction(() => document.querySelector('[data-app-modal-id][data-dialog-phase="open"]'))
    await page.screenshot({ path: `/private/tmp/nexora-production-demands-${theme}.png` })
    await same.getByRole('button', { name: '选择生成', exact: true }).first().click()
    const form = dialog.locator('.demand-selection')
    await form.getByText(/本批来源：SCJH-20261019-000001/).waitFor()
    await form.getByRole('spinbutton').fill('40')
    await form.getByRole('textbox').fill('核对甲公司黑色款，首批四十台')
    assert.equal(await form.getByRole('button', { name: '生成工单草稿', exact: true }).isDisabled(), true)
    await form.getByRole('checkbox').check()
    await form.getByRole('button', { name: '生成工单草稿', exact: true }).click()
    await dialog.getByText('待生成 360.000 台', { exact: true }).waitFor()
    assert.equal(await dialog.locator('.demand-selection').count(), 0)
    await dialog.getByRole('button', { name: '关闭', exact: true }).click()
    assert.match(page.url(), /work-orders/)
  }
  assert.deepEqual(errors, [])
  console.log('通过：机型角标、跨计划汇总、Logo/颜色/包装分组、未知要求提醒、按来源部分生成、生成后余额刷新及明暗主题。')
} finally { await browser.close() }
