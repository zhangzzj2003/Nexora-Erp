import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { createSSRApp, h, effectScope } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { materialUseOptions, materialUseIssue } from '../src/renderer/src/utils/material-use.ts'
import { validateMaterialUses } from '../src/shared/material-uses.ts'
import { validateMaterialChoiceResult } from '../src/shared/material-choice-validation.ts'

const materials = [
  { id: 1, sku: 'NET-8890', name: '网络款', unit: '台', can_sell: true, can_purchase: false, can_produce: true },
  { id: 2, sku: 'RAW', name: '原料', unit: '个', can_sell: false, can_purchase: true, can_produce: false },
  { id: 3, sku: 'LEGACY', name: '旧服务物料', unit: '件' }
]
const options = [{ value: 0, label: '请选择', disabled: true }, ...materials.map(row => ({value: row.id, label: row.name}))]

test('三项用途独立过滤；旧草稿禁用项保留，历史和旧服务资料不丢失', () => {
  for (const [use, expected] of [['can_purchase', [0, 2, 3]], ['can_sell', [0, 1, 3]], ['can_produce', [0, 1, 3]]]) {
    assert.deepEqual(materialUseOptions(options, materials, use, 0).map(row => row.value), expected)
  }
  const retained = materialUseOptions(options, materials, 'can_purchase', 1).find(row => row.value === 1)
  assert.equal(retained.disabled, true)
  assert.match(retained.label, /不可采购.*重新选择/)
  assert.equal(materialUseOptions(options, materials, undefined, 1), options)
  assert.match(materialUseIssue([{material_id: 1}], materials, 'can_purchase'), /NET-8890.*未允许采购/)
  assert.equal(materialUseIssue([{material_id: 1}], materials, 'can_sell'), '')
  assert.equal(materialUseIssue([{material_id: 3}], materials, 'can_purchase'), '')
  assert.equal(materials.length, 3)
})

test('网络用途字段严格核验，字符串 false 不得变成可用候选', () => {
  for (const key of ['can_sell', 'can_purchase', 'can_produce']) {
    for (const value of ['false', 0, null, {}, []]) {
      assert.throws(() => validateMaterialUses({[key]: value}), /用途/)
      assert.throws(() => validateMaterialChoiceResult('crmOptions', {materials: [{...materials[0], [key]: value}]}), /用途/)
    }
  }
  validateMaterialUses({})
  validateMaterialUses(materials[0])
})

test('真实公共选择器只向菜单传入可用候选，失效当前值仍显示资料', async t => {
  // 只替换菜单外壳以读取候选；业务过滤、资料组件及 Vue 响应式均运行真实实现。
  const server = await createServer({configFile: false, plugins: [{name: 'capture-use-options', enforce: 'pre',
    resolveId(id) { if (id.endsWith('/WorkspaceSelect.vue')) return '\0use-menu' },
    load(id) { if (id === '\0use-menu') return `import {h} from 'vue';export default {props:['options'],setup(p){return()=>h('pre',JSON.stringify(p.options))}}` }
  }, vue()], optimizeDeps: {noDiscovery: true, include: []}, server: {middlewareMode: true, hmr: false, ws: false}})
  t.after(() => server.close())
  const {default: Select} = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceMaterialSelect.vue')
  const render = (use, modelValue) => renderToString(createSSRApp({render: () => h(Select, {materials, options, use, modelValue, compact: true})}))
  const fresh = await render('can_purchase', 0)
  assert.doesNotMatch(fresh, /网络款|NET-8890/)
  assert.match(fresh, /原料/)
  const old = await render('can_purchase', 1)
  assert.match(old, /不可采购.*重新选择/)
  assert.match(old, /label&quot;:&quot;NET-8890 · 网络款（不可采购，请重新选择）/ )
  assert.match(old, /aria-label="物料资料"/)
  assert.match(await render(undefined, 0), /网络款/)
})

test('所有新采购与销售选料入口显式接入用途，售后维修耗材保持原规则', async () => {
  // 防止实际页面忘记传业务用途，公共组件单测通过却仍展示全量物料。
  for (const [name, use] of [['purchase/PurchaseRequestsView','can_purchase'], ['purchase/PurchaseOrdersView','can_purchase'],
    ['sales/SalesOrdersView','can_sell'], ['sales/CrmEditor','can_sell']]) {
    const source = await readFile(new URL(`../src/renderer/src/views/workspace/${name}.vue`, import.meta.url), 'utf8')
    assert.match(source, new RegExp(`<WorkspaceMaterialSelect use="${use}"`))
  }
  const after = await readFile(new URL('../src/renderer/src/views/workspace/sales/AfterSalesEditor.vue', import.meta.url), 'utf8')
  assert.match(after, /<WorkspaceMaterialSelect use="can_sell"[^>]*v-model="form.replacement_material_id"/)
  assert.match(after, /<WorkspaceMaterialSelect :materials=[^>]*v-model="line.material_id"/)
})

test('采购新建、编辑和转单在用途变化后拒绝写入并保留草稿，重新允许后恢复', async t => {
  const server = await createServer({configFile:false, optimizeDeps:{noDiscovery:true,include:[]}, server:{middlewareMode:true,hmr:false,ws:false}})
  t.after(() => server.close())
  const {createPurchaseActions} = await server.ssrLoadModule('/src/renderer/src/store/modules/purchase-actions.ts')
  const {createAppState} = await server.ssrLoadModule('/src/renderer/src/store/state.ts')
  const state = createAppState(), calls = []
  const original = globalThis.window
  t.after(() => {globalThis.window = original})
  globalThis.window = {nexora:{callApi:async (action, payload) => {calls.push([action, payload])}}}
  const actions = createPurchaseActions(state, async run => {try {await run()} catch (error) {state.error.value = error.message}})
  state.materials.value = structuredClone(materials)
  const line = {material_id:1, quantity:'2', pricing_mode:'unit_price', unit_price:'3', line_total:'6'}
  for (const requestId of [null, 7]) {
    state.purchaseRequestForm.value = {requestId,reference:'保留',note:'说明',lines:[{...line}]}
    const before = JSON.stringify(state.purchaseRequestForm.value)
    await actions.savePurchaseRequest()
    assert.equal(JSON.stringify(state.purchaseRequestForm.value), before)
  }
  state.purchaseForm.value = {supplier_id:1,reference:'订单',lines:[{...line}]}
  await actions.createPurchaseOrder()
  assert.equal(state.purchaseForm.value.reference, '订单')
  state.requestConversionForm.value = {requestId:7,supplier_id:1,reference:'转单',lines:[{...line,purchase_request_line_id:8}]}
  await actions.convertPurchaseRequest()
  assert.equal(state.requestConversionForm.value.requestId, 7)
  assert.equal(calls.length, 0)
  assert.match(state.error.value, /未允许采购/)
  state.materials.value[0].can_purchase = true
  await actions.savePurchaseRequest()
  assert.equal(calls[0][0], 'updatePurchaseRequest')
  assert.equal(state.purchaseRequestForm.value.lines[0].material_id, 0)
})


// 实际业务动作也要拦截，避免程序触发保存或切换页面后绕过选择器。
test('销售订单、报价、售后换货和设备采购动作拒绝受限物料并保留输入', async t => {
  const server = await createServer({configFile:false, optimizeDeps:{noDiscovery:true,include:[]}, server:{middlewareMode:true,hmr:false,ws:false}})
  t.after(() => server.close())
  const {createAppState} = await server.ssrLoadModule('/src/renderer/src/store/state.ts')
  const state = createAppState(), calls = [], scope = effectScope()
  const previous = globalThis.window
  t.after(() => {scope.stop(); globalThis.window = previous})
  globalThis.window = {nexora:{callApi:async (...args) => {calls.push(args); return {id:1}}}}
  state.user.value = {id:1, roles:[], permissions:['sales_order.create','crm.view','crm_quote.create','after_sales.create','equipment.view','purchase_request.view','purchase_request.create']}
  const actions = {}
  for (const [file, factory] of [['sales','createSalesActions'],['crm','createCrmActions'],['after-sales','createAfterSalesActions'],['equipment','createEquipmentActions']]) {
    const module = await server.ssrLoadModule(`/src/renderer/src/store/modules/${file}-actions.ts`)
    Object.assign(actions, scope.run(() => module[factory](state, async run => {try {await run()} catch (error) {state.error.value = error.message}})))
  }
  state.materials.value = structuredClone(materials)
  state.crmOptions.value = {materials:structuredClone(materials)}
  state.afterSalesOverview.value = {materials:structuredClone(materials)}
  state.equipmentOverview.value = {materials:structuredClone(materials)}
  state.salesForm.value.lines = [{material_id:2,quantity:'1',unit_price:'3'}]
  const sales = state.salesForm.value
  await actions.createSalesOrder()
  assert.equal(state.salesForm.value, sales);assert.match(state.error.value, /未允许销售/)
  state.crmForms.value.quote.lines = [{material_id:2,quantity:'1',unit_price:'3'}]
  const quote = state.crmForms.value.quote
  assert.equal(await actions.saveCrm('quote'), false)
  assert.equal(state.crmForms.value.quote, quote)
  state.afterSalesForm.value.kind = 'exchange';state.afterSalesForm.value.replacement_material_id = 2
  const after = state.afterSalesForm.value
  assert.equal(await actions.saveAfterSalesCase(), false)
  assert.equal(state.afterSalesForm.value, after)
  assert.equal(await actions.createMaintenancePurchaseRequest({parts:[{material_id:1,quantity:'1'}]}), false)
  assert.match(state.error.value, /未允许采购/)
  assert.equal(calls.length, 0)
})
