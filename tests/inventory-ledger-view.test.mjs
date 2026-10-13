import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 渲染真实页面，仅替换外部控件，检查公共表格分页绑定和翻页事件。
test('库存台账页面将服务端页码、总数和翻页事件接入公共表格', async t => {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'ledger-view-fixture', enforce: 'pre',
    transform(code, id) {
      if (id.endsWith('/InventoryLedgerView.vue')) return code.replace("'naive-ui'", "'virtual:ledger-controls'")
    },
    resolveId(id, importer) {
      if (id === 'virtual:ledger-controls') return '\0ledger-controls'
      if (!importer?.endsWith('/InventoryLedgerView.vue')) return
      if (id.endsWith('/store/app-store')) return '\0ledger-store'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0ledger-table'
      if (id.endsWith('.vue')) return '\0ledger-control'
    },
    load(id) {
      if (id === '\0ledger-store') return `import {ref} from 'vue';import {defineStore} from 'pinia';
        export const calls=[];
        export const usePiniaAppStore=defineStore('ledger-fixture',()=>({
          ledgerQuery:ref({page:2,page_size:10,warehouse_id:null,material_id:null,from_date:null,to_date:null,source_type:null}),
          ledgerResult:ref({rows:[],groups:[],page:2,page_size:10,total:35}),
          ledgerLoading:ref(false),ledgerError:ref(''),connectionLost:ref(false),warehouses:ref([]),materials:ref([]),
          localTime:value=>value,queryLedger:(...args)=>calls.push(args)
        }))`
      if (id === '\0ledger-table') return `import {defineComponent,h} from 'vue';export const captured={};
        export default defineComponent({props:['data','columns','pagination','loading','error'],setup(p,{attrs,slots}){
          Object.assign(captured,{props:p,attrs});return()=>h('section',[slots.filters?.(),slots.filterActions?.()])
        }})`
      if (id === '\0ledger-control' || id === '\0ledger-controls') return `import {defineComponent,h} from 'vue';
        const Control=defineComponent({setup(p,{slots}){return()=>h('div',slots.default?.())}});
        export default Control;export const NDatePicker=Control`
    }
  }, vue()], server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] }, appType: 'custom' })
  t.after(() => server.close())
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryLedgerView.vue')
  const { captured } = await server.ssrLoadModule('\0ledger-table')
  const { calls, usePiniaAppStore } = await server.ssrLoadModule('\0ledger-store')
  const pinia = createPinia()
  await renderToString(createSSRApp({ render: () => h(View) }).use(pinia))
  assert.deepEqual(captured.props.pagination, { page: 2, pageSize: 10, total: 35, disabled: false })
  captured.attrs.onPageChange(3, 10)
  assert.deepEqual(calls, [[3, 10]])
  const store = usePiniaAppStore(pinia)
  store.connectionLost = true
  store.ledgerError = '查询失败'
  await renderToString(createSSRApp({ render: () => h(View) }).use(pinia))
  assert.equal(captured.props.pagination.disabled, true)
  assert.equal(captured.props.error, '查询失败')
})
