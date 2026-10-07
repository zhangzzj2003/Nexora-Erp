import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule = `import {ref} from 'vue';import {defineStore} from 'pinia';
export const usePiniaAppStore=defineStore('sales-return-view',()=>{
const salesReturns=ref([]);return {
salesReturns,error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),
warehouses:ref([]),shipments:ref([]),salesReturnReversalReasons:ref({}),
salesReturnForm:ref({shipment_id:0,warehouse_id:1,reason:'',lines:[]}),
selectedSalesReturnShipment:ref(null),can:()=>true,localTime:value=>value,
chooseSalesReturnShipment(){},createSalesReturn(){},loadAvailableSalesReturnLots(){},
postSalesReturn(){},cancelSalesReturn(){},reverseSalesReturn(){}}});`

test('销售退货显示回仓批次证据与旧单据差额', async t => {
  const server = await createServer({configFile: false, plugins: [{name: 'return-lot-view-fixture', enforce: 'pre',
    resolveId(id, importer) {
      if (importer?.includes('/views/workspace/sales/SalesReturnsView')
          && id.endsWith('/store/app-store')) return '\0return-view-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0sales-proof-approval-dialog'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0return-view-table'
      if (id.endsWith('/WorkspaceSelect.vue')) return '\0return-view-select'
    }, load(id) {
      if(id==='\0sales-proof-approval-dialog')return `export default {render:()=>null}`
      if (id === '\0return-view-store') return storeModule
      if (id === '\0return-view-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[
        ...(props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if (id === '\0return-view-select') return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }}, vue()], optimizeDeps: {noDiscovery: true, include: []},
    server: {middlewareMode: true, hmr: false}, appType: 'custom'})
  t.after(() => server.close())
  const {usePiniaAppStore} = await server.ssrLoadModule('\0return-view-store')
  const pinia = createPinia()
  const store = usePiniaAppStore(pinia)
  const line = {id: 7, shipment_line_id: 5, material_id: 3, sku: 'A', material_name: '成品',
    unit: '件', quantity: '1.000', line_total: '10.00'}
  const record = {id: 2, shipment_id: 1, warehouse_id: 1, warehouse_name: '主仓库',
    customer_name: '客户', reason: '退回', status: 'posted', created_at: '2026-10-03',
    created_by_name: 'admin', total_amount: '10.00', reversal_id: null, lines: [
      {...line, physical_lots: [{id: 8, code: 'SR2-L7-P1', quantity: '1.000',
        source_kind: 'sales_return'}]}]}
  store.salesReturns = [record, {...record, id: 3, lines: [{...line, physical_lots: []}]}]
  const {default: Component} = await server.ssrLoadModule(
    '/src/renderer/src/views/workspace/sales/SalesReturnsView.vue')
  const html = await renderToString(createSSRApp({render: () => h(Component)}).use(pinia))
  assert.match(html, /SR2-L7-P1/)
  assert.match(html, /退货新批次/)
  assert.match(html, /普通确认未指定实物批次/)
  assert.equal((html.match(/普通确认未指定实物批次/g) ?? []).length, 1)
})
