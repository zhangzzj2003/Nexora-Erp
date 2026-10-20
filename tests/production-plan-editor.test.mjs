import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { planOptionsFixture, planInputFixture } from './production-plan-fixture.mjs'

test('计划产品与 BOM 独立分列，版本候选、销售联动和禁用约束保持一致', async t => {
  // 保留真实编辑器和行数据，只替换浏览器控件；候选与保存仍来自编辑器实际绑定。
  const server = await createServer({ configFile: false, plugins: [{
    name: 'plan-editor-columns', enforce: 'pre',
    resolveId(id, importer) {
      if (!importer?.includes('/src/renderer/')) return
      if (id.endsWith('/store/app-store')) return '\0plan-editor-store'
      if (id.endsWith('/WorkspaceDocumentDialog.vue')) return '\0plan-editor-dialog'
      if (id.endsWith('/WorkspaceSelect.vue')) return '\0plan-editor-select'
      if (id.endsWith('.vue')) return '\0plan-editor-empty'
    },
    load(id) {
      if (id === '\0plan-editor-empty') return 'export default {render:()=>null}'
      if (id === '\0plan-editor-dialog') return `import {h} from 'vue';export default {props:['columns','data'],setup:(p,{slots})=>()=>h('section',p.data.flatMap(row=>p.columns.map(col=>h('div',{'data-column':col.key},[h('span',col.title),slots['cell-'+col.key]?.({row})]))))}`
      if (id === '\0plan-editor-select') return `import {h} from 'vue';export const controls=[];export default {props:['options','disabled','modelValue'],setup(p,{attrs}){controls.push({props:p,attrs});return()=>h('select',{'aria-label':attrs['aria-label'],disabled:p.disabled},p.options.map(o=>h('option',{value:o.value},o.label)))}}`
      if (id === '\0plan-editor-store') return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const saves=[];
        export const usePiniaAppStore=defineStore('plan-editor-columns',()=>{const s=createAppState();return {...s,can:p=>s.user.value?.permissions.includes(p)??false,
          async saveProductionPlan(){saves.push(JSON.parse(JSON.stringify(s.productionPlanForm.value)));return true}}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, saves } = await server.ssrLoadModule('\0plan-editor-store')
  const { controls } = await server.ssrLoadModule('\0plan-editor-select')
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/production/ProductionPlanEditor.vue')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  store.user = { id: 1, roles: [], permissions: ['production_plan.create'] }
  store.productionPlanOptions = planOptionsFixture()
  store.productionPlanOptions.boms.push({ ...store.productionPlanOptions.boms[0], id: 100, version: 3 },
    { ...store.productionPlanOptions.boms[0], id: 200, material_id: 2, version: 8 })
  store.productionPlanOptions.sales_lines = [{ id: 10, material_id: 1, available_quantity: '50', sales_order_id: 10, reference: '客户交付' }]
  store.productionPlanForm = planInputFixture()
  const line = store.productionPlanForm.lines[0]
  line.sales_order_line_id = 10
  let state
  async function render(show = true) {
    controls.length = 0
    let vnode
    const html = await renderToString(createSSRApp({ render: () => (vnode = h(View, { show })) }).use(pinia))
    state = vnode.component.setupState
    return html
  }
  const bom = () => controls.find(control => control.attrs['aria-label'] === '计划 BOM 版本')
  const html = await render()
  const productStart = html.indexOf('data-column="product"'), bomStart = html.indexOf('data-column="bom"'), salesStart = html.indexOf('data-column="sales"')
  assert.ok(productStart >= 0 && productStart < bomStart && bomStart < salesStart)
  assert.doesNotMatch(html.slice(productStart, bomStart), /计划 BOM 版本/)
  assert.match(html.slice(bomStart, salesStart), /计划 BOM 版本/)
  assert.deepEqual(bom().props.options.map(option => option.value), [1, 100])
  assert.equal(bom().props.disabled, false)
  // 调用真实 v-model 回调切换版本，销售来源必须保留，保存使用新版本编号。
  bom().attrs['onUpdate:modelValue'](100)
  assert.equal(line.bom_id, 100)
  assert.equal(line.sales_order_line_id, 10)
  await state.save()
  assert.equal(saves[0].lines[0].bom_id, 100)
  state.selectProduct(line, 2)
  assert.equal(line.bom_id, 200)
  assert.equal(line.sales_order_line_id, null)
  await render()
  assert.deepEqual(bom().props.options.map(option => option.value), [200])
  state.selectProduct(line, 0)
  await render()
  assert.equal(bom().props.disabled, true)
  assert.deepEqual(bom().props.options, [])
  await state.save()
  assert.equal(saves.length, 1)
  // 离线、撤销权限、窗口已收起均不得保存；无候选时字段禁用。
  line.bom_id = 1
  store.connectionLost = true
  await render(); assert.equal(bom().props.disabled, true); await state.save()
  store.connectionLost = false; store.user.permissions = []
  await render(); assert.equal(bom().props.disabled, true); await state.save()
  store.user.permissions = ['production_plan.create']
  await render(false); await state.save()
  assert.equal(saves.length, 1)
})
