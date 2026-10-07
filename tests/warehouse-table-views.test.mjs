import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// vxe 的真实外壳另有组件测试；这里展开行插槽，核对迁移后的业务信息与权限分支。
const storeModule = `
import { ref } from 'vue'
import { defineStore } from 'pinia'
export const permissions = new Set()
const rows = [
  { id: 71, status: 'draft', approval: {status:'approved'} },
  { id: 72, status: 'posted', reversal_approval: {status:'approved'} },
  { id: 75, status: 'draft' },
  { id: 73, status: 'posted', reversal_id: 74, reversal_reason: '重复录入', reversed_by_name: '复核人', reversed_at: '2026-09-30' }
].map(row => ({...row, created_at: '2026-09-30', created_by_name: '操作员', reference: '测试参考号',
  from_warehouse_name: '原料仓', to_warehouse_name: '成品仓', warehouse_name: '原料仓',
  lines: [{id:1, material_name:'测试铝材', quantity:'5', book_quantity:'8', counted_quantity:'6', difference:'-2', unit:'米'}]}))
export const state = {
  busy: ref(false), connectionLost: ref(false), error: ref(''), notice: ref(''), materials:ref([]), warehouses:ref([]),
  transfers: ref(rows), stocktakes: ref(rows), transferForm:ref({lines:[]}), stocktakeForm:ref({lines:[]}),
  transferReversalReasons:ref({}), stocktakeReversalReasons:ref({}),
  can: permission => permissions.has(permission), localTime: value => value
}
export const usePiniaAppStore = defineStore('warehouse-table-fixture', () => state)
`
const tableModule = `
import { defineComponent, h } from 'vue'
export default defineComponent({props:['data','columns','title','showTitle'], setup(props,{slots}) {
  return () => h('section', [slots.actions?.(), slots.filters?.(),
    ...props.data.map(row=>h('article',props.columns.map(column=>slots['cell-'+column.key]?.({row})))),
    props.data.length ? null : slots.empty?.()])
}})
`

test('调拨和盘点表格保留明细、冲销记录、权限及断线禁用', async t => {
  const server = await createServer({configFile:false, plugins:[{
    name:'warehouse-test-fixtures', enforce:'pre',
    resolveId(id, importer) {
      // 业务页与公共单据弹窗共用这份表格替身。
      if (!importer?.includes('/src/renderer/src/')) return
      if (id.endsWith('/store/app-store')) return '\0warehouse-test-store'
      if (id.endsWith('/DocumentApprovalDialog.vue')) return '\0approval-dialog-stub'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0warehouse-test-table'
    },
    load(id) {
      if (id === '\0approval-dialog-stub') return `export default {render:()=>null}`
      if (id === '\0warehouse-test-store') return storeModule
      if (id === '\0warehouse-test-table') return tableModule
    }
  }, vue()], optimizeDeps:{noDiscovery:true,include:[]}, server:{middlewareMode:true}, appType:'custom'})
  t.after(()=>server.close())
  for (const [file, kind, confirm, reversed] of [
    ['WarehouseTransfersView.vue','transfer','确认调拨','执行已批准冲销'],
    ['InventoryStocktakesView.vue','stocktake','确认盘点','执行已批准冲销']
  ]) {
    const {default: View} = await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/'+file)
    const {state, permissions} = await server.ssrLoadModule('\0warehouse-test-store')
    const render = () => renderToString(createSSRApp({render:()=>h(View)}).use(createPinia()))
    permissions.clear()
    state.connectionLost.value = false
    const readonly = await render()
    assert.match(readonly, /测试铝材/)
    assert.match(readonly, /测试参考号/)
    assert.match(readonly, /重复录入/)
    assert.match(readonly, /复核人/)
    assert.doesNotMatch(readonly, new RegExp('>\\s*' + confirm + '\\s*<'))
    assert.doesNotMatch(readonly, new RegExp('>\\s*' + reversed + '\\s*<'))
    if (kind === 'transfer') assert.match(readonly, /原料仓 → 成品仓/)
    else assert.match(readonly, /账面 8 → 实盘 6 米 · 差异 -2/)

    for (const action of ['create','post','cancel','reverse']) permissions.add(kind+'.'+action)
    const editable = await render()
    assert.equal([...editable.matchAll(new RegExp('>\\s*' + confirm + '\\s*<', 'g'))].length, 1)
    assert.equal([...editable.matchAll(new RegExp('>\\s*' + reversed + '\\s*<', 'g'))].length, 1)
    if (kind === 'stocktake') assert.match(editable, />\s*取消\s*</)
    state.connectionLost.value = true
    const offline = await render()
    const buttons = [...offline.matchAll(/<button\b([^>]*)>/g)]
    assert.ok(buttons.length >= 3)
    assert.ok(buttons.every(button=>button[1].includes('disabled')))
  }
})
