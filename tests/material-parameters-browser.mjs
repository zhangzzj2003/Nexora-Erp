// 用真实公共单据弹窗、VXE 表格和按钮验证摘要宽度、两级展开及键盘焦点，不访问业务服务。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const modulePath = process.env.NEXORA_PLAYWRIGHT_MODULE
if (!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 playwright 入口。')
const { chromium } = await import(pathToFileURL(modulePath).href)
const fixture = `
import {createApp,h,ref} from 'vue';
import {NMessageProvider} from 'naive-ui';
import WorkspaceDocumentDialog from '/src/renderer/src/components/workspace/WorkspaceDocumentDialog.vue';
import WorkspaceMaterialParameters from '/src/renderer/src/components/workspace/WorkspaceMaterialParameters.vue';
import '/src/renderer/src/style.css';
import '/src/renderer/src/dark-theme.css';
const material={id:1,sku:'EL-CN-000001',name:'示例 · 2.54mm 排针 8P',unit:'条',category_name:'电子类 / 连接器',
 specification:'单排 / 8P / 间距 2.54mm',package:'直插',brand:'Nexora 示例制造商',manufacturer_part_number:'DEMO-CONN254-8P',
 electrical_value:'8P',notes:'很长的只读备注：'.repeat(30),
 spec_values:[{field_id:1,name:'含铅',status:'filled',value:false,unit:'',historical:false}],extra_attributes:[{name:'工艺',value:'镀金',unit:''}]};
const data=ref([{...material,quantity:'1000'}, {...material,id:2,sku:'EL-CN-000002',name:'示例 · 接线端子 2P',quantity:'2000'}]);
window.materialFixture={data};window.submits=0;window.rowClicks=0;
const columns=[{key:'sku',title:'物料编码',width:180},{key:'name',title:'物料名称',width:240},
 {key:'quantity',title:'单据数量',width:110},{key:'received',title:'已入库',width:110},
 {key:'remaining',title:'待入库',width:110},{key:'unit',title:'单位',width:70}];
createApp({setup:()=>()=>h(NMessageProvider,null,{default:()=>h(WorkspaceDocumentDialog,
 {show:true,title:'其他入库详情 · 展示验收',data:data.value,columns,readOnly:true,minTableWidth:820,onSubmit:()=>window.submits++},
 {basicInfo:()=>h('p','主仓库 · 已入库'),
 'cell-sku':({row})=>h('strong',row.sku),
 'cell-name':({row})=>h('div',{'data-material':row.id,onClick:()=>window.rowClicks++},[
  h('strong',row.name),h(WorkspaceMaterialParameters,{material:row,currentReference:true})]),
 'cell-quantity':({row})=>row.quantity,'cell-received':({row})=>row.quantity,'cell-remaining':()=>0,'cell-unit':({row})=>row.unit})})}).mount('#app');
`
const server = await createServer({ configFile: false, plugins: [vue(), tailwindcss(), {
  name: 'material-parameters-browser',
  resolveId: id => id === '/material-fixture.js' ? '\0material-fixture' : undefined,
  load: id => id === '\0material-fixture' ? fixture : undefined,
  configureServer(server) { server.middlewares.use((req, res, next) => {
    if (req.url !== '/') return next()
    res.setHeader('content-type', 'text/html')
    res.end('<html><head><meta charset="utf-8"></head><body><div id="app"></div><script type="module" src="/material-fixture.js"></script></body></html>')
  }) }
}], server: { host: '127.0.0.1', port: 0, hmr: false, ws: false } })
let browser
const errors = []
const businessRequests = []
const evidenceDir = process.env.NEXORA_BROWSER_EVIDENCE_DIR
try {
  await server.listen()
  browser = await chromium.launch({ channel: process.env.NEXORA_BROWSER_CHANNEL || 'chrome', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) businessRequests.push(request.url()) })
  await page.goto(server.resolvedUrls.local[0])
  const first = page.locator('[data-material="1"]'), second = page.locator('[data-material="2"]')
  await first.getByRole('button', { name: '查看资料', exact: true }).waitFor()
  const baseline = (await first.boundingBox()).height
  assert.ok(baseline < 70, `名称与摘要应紧凑，实际高度 ${baseline}`)
  assert.equal(await first.locator('dl').count(), 0)
  const summary = await first.locator('.material-parameters-summary-text').evaluate(el => ({
    clipped: el.scrollWidth > el.clientWidth, nowrap: getComputedStyle(el).whiteSpace,
    ellipsis: getComputedStyle(el).textOverflow
  }))
  assert.deepEqual(summary, { clipped: true, nowrap: 'nowrap', ellipsis: 'ellipsis' })
  if (evidenceDir) {
    await mkdir(evidenceDir, { recursive: true })
    await page.screenshot({ path: `${evidenceDir}/01-collapsed.png` })
  }
  // 键盘查看后焦点应停留在对应收起按钮，不触发表单提交或父行点击。
  await first.getByRole('button', { name: '查看资料', exact: true }).focus()
  await page.keyboard.press('Enter')
  const collapse = first.getByRole('button', { name: '收起资料', exact: true })
  await collapse.waitFor()
  assert.equal(await collapse.evaluate(el => el === document.activeElement), true)
  assert.equal(await first.getByText('当前档案参数', { exact: true }).count(), 1)
  assert.equal(await first.getByText('备注', { exact: true }).count(), 0)
  assert.equal(await second.getByRole('button', { name: '查看资料', exact: true }).count(), 1)
  assert.ok((await first.boundingBox()).height > baseline)
  const card = await first.locator('.material-parameters-card').evaluate(el => ({ width: el.clientWidth, scroll: el.scrollWidth,
    columns: getComputedStyle(el.querySelector('dl')).gridTemplateColumns.split(' ').length }))
  assert.equal(card.columns, 2); assert.ok(card.scroll <= card.width + 1)
  if (evidenceDir) await page.screenshot({ path: `${evidenceDir}/02-info-card.png` })
  await first.getByRole('button', { name: '展开详情', exact: true }).click()
  await first.getByText('备注', { exact: true }).waitFor()
  assert.equal(await first.getByText('否', { exact: true }).count(), 1)
  assert.equal(await first.getByText('镀金', { exact: true }).count(), 1)
  await first.getByRole('button', { name: '收起详情', exact: true }).click()
  assert.equal(await first.getByText('备注', { exact: true }).count(), 0)
  await collapse.click()
  assert.equal(await first.getByRole('button', { name: '查看资料', exact: true }).evaluate(el => el === document.activeElement), true)
  assert.ok(Math.abs((await first.boundingBox()).height - baseline) < 1)
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme)
    await page.setViewportSize({ width: 760, height: 900 })
    await first.getByRole('button', { name: '查看资料', exact: true }).click()
    const size = await first.locator('.material-parameters-card').evaluate(el => [el.clientWidth, el.scrollWidth])
    assert.ok(size[1] <= size[0] + 1, `${theme} 窄屏资料卡不能撑宽单元格`)
    await first.getByRole('button', { name: '收起资料', exact: true }).click()
  }
  assert.deepEqual(await page.evaluate(() => [window.submits, window.rowClicks]), [0, 0])
  assert.deepEqual(errors, [])
  assert.deepEqual(businessRequests, [])
  console.log('浏览器验收通过：摘要省略、两列资料卡、两级展开收起、独立行状态、键盘焦点、明暗主题窄屏，无误提交或业务请求。')
} finally {
  await browser?.close()
  await server.close()
}
