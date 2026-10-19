// 用真实仓库页面和公共组件检查标题、对齐、按钮、预览竞态及失败草稿；不访问正式服务。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import Icons from 'unplugin-icons/vite'
const modulePath = process.env.NEXORA_PLAYWRIGHT_MODULE
if (!modulePath) throw Error('请设置 NEXORA_PLAYWRIGHT_MODULE 为已安装的 playwright 入口。')
const { chromium } = await import(pathToFileURL(modulePath).href)
const fixture = `
import {createApp,h,ref} from 'vue';
import {NConfigProvider,NMessageProvider,darkTheme} from 'naive-ui';
import {createPinia} from 'pinia';
import WarehousesView from '/src/renderer/src/views/workspace/catalog/WarehousesView.vue';
import {usePiniaAppStore} from '/src/renderer/src/store/app-store';
import {naiveThemeOverrides} from '/src/renderer/src/utils/app-theme';
import '/src/renderer/src/style.css';
import '/src/renderer/src/light-theme.css';
import '/src/renderer/src/dark-theme.css';
const pinia=createPinia(),store=usePiniaAppStore(pinia);
store.$patch({user:{id:1,username:'测试管理员',roles:['admin'],permissions:['warehouse.manage','inventory.view']},
 server:{id:'fixture',fingerprint:'fixture'},connectionLost:false,
 warehouses:[{id:1,code:'MAIN',name:'主仓库',version:1,material_count:3},{id:2,code:'DC',name:'东仓',version:1,material_count:0}]});
const theme=ref('light');
window.fixture={store,theme,calls:[],pending:{},hold:false,failSave:false,failPreview:false,saved:[]};
window.nexora={callApi:async(action,payload)=>{
 window.fixture.calls.push([action,payload]);
 if(action==='warehouseDetail')return {...store.warehouses.find(item=>item.id===payload.id)};
 if(action==='previewWarehouseCode'){
  if(window.fixture.failPreview)throw Error('模拟预览失败');
  if(window.fixture.hold)return new Promise(resolve=>window.fixture.pending[payload.name]=resolve);
  return {code:payload.name==='原材料仓库'?'YCLCK':'DC-2'};
 }
 throw Error('未预期接口 '+action);
}};
store.saveWarehouse=async(data,id)=>{window.fixture.saved.push({data:{...data},id});return !window.fixture.failSave};
createApp({setup:()=>()=>h(NConfigProvider,{theme:theme.value==='dark'?darkTheme:null,themeOverrides:naiveThemeOverrides},
 {default:()=>h(NMessageProvider,null,{default:()=>h(WarehousesView)})})}).use(pinia).mount('#app');
`
const server = await createServer({ configFile: false, plugins: [vue(), tailwindcss(), Icons({ compiler: 'vue3' }), {
  name: 'warehouse-catalog-browser',
  resolveId: id => id === '/warehouse-fixture.js' ? '\0warehouse-fixture' : undefined,
  load: id => id === '\0warehouse-fixture' ? fixture : undefined,
  configureServer(server) { server.middlewares.use((req, res, next) => {
    if (req.url?.split('?')[0] !== '/') return next()
    res.setHeader('content-type', 'text/html')
    res.end('<html><head><meta charset="utf-8"></head><body style="padding:32px"><div id="app"></div><script type="module" src="/warehouse-fixture.js"></script></body></html>')
  }) }
}], server: { host: '127.0.0.1', port: 0, hmr: false, ws: false } })
let browser
const errors = [], evidence = process.env.NEXORA_BROWSER_EVIDENCE_DIR
try {
  await server.listen()
  browser = await chromium.launch({ channel: process.env.NEXORA_BROWSER_CHANNEL || 'chrome', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(server.resolvedUrls.local[0])
  const add = page.getByRole('button', { name: '新增仓库', exact: true })
  await add.waitFor()
  await page.getByText('物料种数', { exact: true }).waitFor()
  assert.equal(await page.locator('[title="当前库存大于零的不同物料数量"]').allTextContents().then(rows => rows.map(value => value.trim())).then(rows => rows.join(',')), '3,0')
  for (const label of ['编辑', '删除']) {
    const button = page.getByRole('button', { name: label, exact: true }).first()
    assert.ok((await button.getAttribute('class')).includes('app-button--secondary'))
    assert.ok((await button.boundingBox()).height >= 33)
  }
  assert.equal(await page.getByRole('button', { name: '删除', exact: true }).first().isDisabled(), true)
  if (evidence) await mkdir(evidence, { recursive: true })
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; window.fixture.theme.value = theme }, theme)
    await add.click()
    const modal = page.locator('.app-modal[data-dialog-phase="open"]')
    await modal.waitFor()
    assert.equal((await modal.locator('.n-card-header__main').innerText()).trim(), '新增仓库')
    assert.equal(await modal.locator('h3').count(), 0)
    const name = modal.getByLabel('仓库名称', { exact: true }), code = modal.locator('input[readonly]')
    await name.fill('原材料仓库')
    await page.waitForFunction(() => document.querySelector('.warehouse-editor input[readonly]')?.value === 'YCLCK')
    const save = modal.getByRole('button', { name: '保存', exact: true }), cancel = modal.getByRole('button', { name: '取消', exact: true })
    const saveBox = await save.boundingBox(), cancelBox = await cancel.boundingBox(), formBox = await modal.locator('form').boundingBox()
    assert.ok(Math.abs(saveBox.y - cancelBox.y) < 1)
    assert.ok(Math.abs(saveBox.x + saveBox.width - formBox.x - formBox.width) < 2)
    assert.ok(saveBox.x - cancelBox.x - cancelBox.width >= 10 && saveBox.x - cancelBox.x - cancelBox.width <= 14)
    if (evidence) await page.screenshot({ path: `${evidence}/${theme}-create.png` })
    await cancel.click()
    await page.waitForFunction(() => !document.querySelector('.app-modal'))
    assert.equal(await page.evaluate(() => window.fixture.saved.length), 0)
  }
  // 同一名称的早期响应不能覆盖后输入名称，关闭后也不能重开或污染下次表单。
  await page.evaluate(() => { window.fixture.hold = true })
  await add.click()
  let modal = page.locator('.app-modal[data-dialog-phase="open"]')
  await modal.waitFor()
  let name = modal.getByLabel('仓库名称', { exact: true })
  await name.fill('旧名称')
  await page.waitForFunction(() => !!window.fixture.pending['旧名称'])
  await name.fill('新名称')
  await page.waitForFunction(() => !!window.fixture.pending['新名称'])
  await page.evaluate(() => { window.fixture.pending['新名称']({code:'NEW'}); window.fixture.pending['旧名称']({code:'OLD'}) })
  await page.waitForFunction(() => document.querySelector('.warehouse-editor input[readonly]')?.value === 'NEW')
  await name.fill('关闭中')
  await page.waitForFunction(() => !!window.fixture.pending['关闭中'])
  await modal.getByRole('button', { name: '取消', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.app-modal'))
  await page.evaluate(() => { window.fixture.pending['关闭中']({code:'LATE'}); window.fixture.hold = false; window.fixture.failPreview = true })
  await add.click()
  modal = page.locator('.app-modal[data-dialog-phase="open"]')
  await modal.waitFor()
  name = modal.getByLabel('仓库名称', { exact: true })
  assert.equal(await name.inputValue(), '')
  assert.equal(await modal.locator('input[readonly]').inputValue(), '')
  await name.fill('保留草稿')
  await modal.getByRole('alert').waitFor()
  await page.evaluate(() => { window.fixture.failSave = true })
  await modal.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal(await name.inputValue(), '保留草稿')
  await page.evaluate(() => { window.fixture.failSave = false })
  await modal.getByRole('button', { name: '保存', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.app-modal'))
  // 编辑主仓库改名保持 MAIN，且修改原因仍是必填项。
  const previewCalls = await page.evaluate(() => window.fixture.calls.filter(([action]) => action === 'previewWarehouseCode').length)
  await page.getByRole('button', { name: '编辑', exact: true }).first().click()
  modal = page.locator('.app-modal[data-dialog-phase="open"]')
  await modal.waitFor()
  assert.equal((await modal.locator('.n-card-header__main').innerText()).trim(), '编辑仓库')
  await modal.getByLabel('仓库名称', { exact: true }).fill('新的主仓库名称')
  assert.equal(await modal.locator('input[readonly]').inputValue(), 'MAIN')
  assert.equal(await modal.getByLabel('修改原因', { exact: true }).evaluate(el => el.required), true)
  await modal.getByRole('button', { name: '取消', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.app-modal'))
  assert.equal(await page.evaluate(() => window.fixture.calls.filter(([action]) => action === 'previewWarehouseCode').length), previewCalls)
  // 旧服务缺失统计显示未知，占位不能冒充真实零库存。
  await page.evaluate(() => { delete window.fixture.store.warehouses[0].material_count })
  assert.equal((await page.locator('[title="请升级服务端后查看物料种数"]').innerText()).trim(), '—')
  await page.setViewportSize({width:390,height:844})
  await add.click()
  modal = page.locator('.app-modal[data-dialog-phase="open"]')
  await modal.waitFor()
  const mobile = await modal.boundingBox()
  assert.ok(mobile.x >= 0 && mobile.x + mobile.width <= 391)
  assert.equal(await modal.locator('.form-grid').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length), 1)
  if (evidence) await page.screenshot({ path: `${evidence}/mobile-create.png` })
  assert.deepEqual(errors, [])
  console.log('PASS: 仓库标题、明暗主题、右侧按钮、物料种数、编码预览竞态、失败保留、编辑保码及窄屏布局')
} finally { await browser?.close(); await server.close() }
