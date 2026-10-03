import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule = `import {ref} from 'vue';import {defineStore} from 'pinia';
export const usePiniaAppStore=defineStore('material-return-view',()=>{
const materialReturns=ref([]);return {
materialReturns,error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),
workOrders:ref([]),materialIssues:ref([]),
materialReturnForm:ref({material_issue_id:0,reason:'',lines:[]}),
selectedReturnIssue:ref(null),can:()=>true,localTime:value=>value,
selectReturnIssue(){},createMaterialReturn(){},loadAvailableMaterialReturnLots(){},
postMaterialReturn(){},cancelMaterialReturn(){},reverseMaterialReturn(){}}});`

test('生产退料显示回仓批次证据与旧单据差额', async t => {
  const server = await createServer({configFile: false, plugins: [{name: 'return-lot-view-fixture', enforce: 'pre',
    resolveId(id, importer) {
      if (importer?.includes('/views/workspace/production/MaterialReturnsView')
          && id.endsWith('/store/app-store')) return '\0return-view-store'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0return-view-table'
      if (id.endsWith('/WorkspaceSelect.vue')) return '\0return-view-select'
    }, load(id) {
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
  const line = {id: 7, material_issue_line_id: 5, component_material_id: 3, sku: 'A',
    material_name: '组件', unit: '件', quantity: '1.000'}
  const record = {id: 2, material_issue_id: 1, work_order_id: 1, warehouse_id: 1,
    warehouse_name: '主仓库', reason: '退回', status: 'posted', created_at: '2026-10-03',
    created_by_name: 'admin', lines: [
      {...line, physical_lots: [{id: 8, code: 'MR2-L7-P1', quantity: '1.000',
        source_kind: 'material_return'}]}]}
  store.materialReturns = [record, {...record, id: 3, status: 'reversed', reversal_reason: '退料录错',
    reversed_at: '2026-10-03', lines: [{...line, physical_lots: []}]},
    {...record, id: 4, status: 'draft', lines: [{...line, physical_lots: []}]}]
  const {default: Component} = await server.ssrLoadModule(
    '/src/renderer/src/views/workspace/production/MaterialReturnsView.vue')
  const html = await renderToString(createSSRApp({render: () => h(Component)}).use(pinia))
  assert.match(html, /MR2-L7-P1/)
  assert.match(html, /退料新批次/)
  assert.match(html, /旧确认未指定实物批次/)
  assert.match(html, /核对批次并确认退料/)
  assert.match(html, /冲销已确认退料/)
  assert.match(html, /退料录错/)
  assert.match(html, /已冲销/)
  assert.equal((html.match(/旧确认未指定实物批次/g) ?? []).length, 1)
})
