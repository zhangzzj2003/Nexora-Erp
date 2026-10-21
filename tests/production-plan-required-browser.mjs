// 回环预览只注入内存样例，验证工单执行页不能手工建单，来源能直达生产计划详情。
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
const { chromium } = await import(pathToFileURL(process.env.NEXORA_PLAYWRIGHT_MODULE).href)
const browser = await chromium.launch({headless:true, channel:'chrome'})
try {
  const page = await browser.newPage({viewport:{width:1920,height:1280}})
  const errors=[]; page.on('pageerror', error=>errors.push(error.message))
  await page.route('**/scripts/site-preview/main.mjs*', async route=>{
    const response=await route.fetch()
    const order={id:8,document_no:'SCGD-20261020-000008',status:'draft',product_name:'控制器',product_sku:'CTRL-001',
      bom_version:1,warehouse_id:1,warehouse_name:'成品仓',product_unit:'台',target_quantity:'10.000',
      reported_quantity:'0.000',accepted_quantity:'0.000',rejected_quantity:'0.000',remaining_output_quantity:'10.000',
      created_at:'2026-10-20 00:00:00',created_by_name:'计划员',reference:'按计划第一批',note:'',lines:[],
      production_schedule:{production_plan_id:1,production_plan_document_no:'SCJH-20261019-000001',
        start_date:'2026-10-20',end_date:'2026-10-25',priority:'normal'}}
    const body=(await response.text()).replace('workOrders: dialogQa ?',
      `workOrders: productionPlanQa ? ${JSON.stringify([order,{...order,id:9,document_no:'SCGD-20261020-000009',production_schedule:undefined}])} : dialogQa ?`)
    await route.fulfill({response,body})
  })
  for (const theme of ['dark','light']) {
    await page.goto(`http://127.0.0.1:8791/scripts/site-preview/index.html?qa=productionPlans&theme=${theme}#/workspace/work-orders?create_from_bom=1`)
    const view=page.locator('.production-work-orders')
    await view.getByRole('button',{name:/^从生产计划生成/}).waitFor()
    assert.equal(await view.getByRole('button',{name:'新建生产工单',exact:true}).count(),0)
    await view.getByText('历史工单（无生产计划关联）',{exact:true}).waitFor()
    await page.screenshot({path:`/private/tmp/nexora-plan-required-orders-${theme}.png`})
    await view.getByRole('button',{name:'SCJH-20261019-000001',exact:true}).click()
    const detail=page.getByRole('dialog').filter({hasText:'产品排期与进度'})
    await detail.waitFor(); await detail.getByRole('button',{name:'生成生产工单',exact:true}).waitFor()
    assert.match(page.url(),/production-plans/)
    await detail.locator('.document-footer').getByRole('button',{name:'关闭',exact:true}).click()
  }
  assert.deepEqual(errors,[])
  console.log('通过：工单仅从计划生成、旧 BOM 地址无建单表单、来源计划跳转、历史提示及明暗主题。')
} finally { await browser.close() }
