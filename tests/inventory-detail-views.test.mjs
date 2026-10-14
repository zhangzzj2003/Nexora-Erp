import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 渲染真实页面和详情外壳；只替换表格与传送层，捕获可点击编号的真实事件绑定。
test('台账与库存报表按独立字段展示，编号打开只读详情且采购报表不受影响', async t => {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'inventory-detail-view-fixture', enforce: 'pre',
    transform(code, id) {
      if (id.endsWith('/InventoryDetailDialogs.vue') || id.endsWith('/WorkspaceDocumentDialog.vue')) return code.replace("'naive-ui'", "'virtual:detail-modal'")
    },
    resolveId(id) {
      if (id.endsWith('/store/app-store')) return '\0detail-store'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0detail-table'
      if (id.endsWith('/DocumentApprovalProgress.vue')) return '\0detail-progress'
      if (id === 'virtual:detail-modal') return '\0detail-modal'
    },
    load(id) {
      if (id === '\0detail-store') return `import {defineStore} from 'pinia';
        import {createAppState} from '/src/renderer/src/store/state.ts';
        export const calls=[];
        export const usePiniaAppStore=defineStore('detail-view',()=>({...createAppState(),can:()=>true,
          queryLedger(){},queryPurchaseReport(){},queryInventoryReport(){},exportPurchaseReport(){},exportInventoryReport(){},
          closeLedgerMaterial(){},closeLedgerDocument(){},loadLedgerMaterial(){},queryLedgerMaterial(){},loadLedgerDocument(){},
          openLedgerMaterial:row=>calls.push(['material',row]),openReportMaterial:row=>calls.push(['report',row]),openLedgerDocument:row=>calls.push(['document',row])}))`
      if (id === '\0detail-table') return `import {defineComponent,h} from 'vue';export const captured={};
        export default defineComponent({props:['data','title','columns','pagination','loading','error'],setup(p,{attrs,slots}){
          captured[p.title]={props:p,attrs,slots};return()=>h('section',[
            slots.filters?.(),slots.filterActions?.(),slots.actions?.(),h('table',[
              h('thead',h('tr',p.columns.map(c=>h('th',c.title)))),
              h('tbody',p.data.map(row=>h('tr',p.columns.map(c=>h('td',slots['cell-'+c.key]?.({row})??row[c.key])))))]),
            p.error,slots.errorActions?.(),slots.footer?.()])}})`
      if (id === '\0detail-modal') return `import {defineComponent,h} from 'vue';
        export const NModal=defineComponent({props:['show','title'],setup(p,{slots}){return()=>p.show?h('div',{role:'dialog','aria-label':p.title},[slots.default?.(),slots.footer?.()]):null}});
        export const NTabs=defineComponent({setup(p,{slots}){return()=>h('div',slots.default?.())}});
        export const NTabPane=defineComponent({props:['tab'],setup(p,{slots}){return()=>h('section',[h('h3',p.tab),slots.default?.()])}})`
      if (id === '\0detail-progress') return `export default {render:()=>null}`
    }
  }, vue()], server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Ledger } = await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryLedgerView.vue')
  const { default: Reports } = await server.ssrLoadModule('/src/renderer/src/components/workspace/BusinessReportsTable.vue')
  const { usePiniaAppStore, calls } = await server.ssrLoadModule('\0detail-store')
  const { captured } = await server.ssrLoadModule('\0detail-table')
  const { ledgerTime } = await server.ssrLoadModule('/src/renderer/src/utils/inventory-ledger-presentation.ts')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const render = async (view, props) => {
    const app = createSSRApp({ render: () => h(view, props) }).use(pinia)
    setupSsrStyles(app)
    return renderToString(app)
  }
  const row = { id: 15, material_id: 3, sku: 'EL-03', material_name: '连接器 · 2P', warehouse_id: 1,
    warehouse_name: '主仓库', unit: '个', quantity: '20', balance_quantity: '50', source_type: 'other_inbound',
    source_document_no: 'QTRK-20261013-000001', source_id: 8, source_line_id: 9, created_at: '2026-10-13T05:47:44Z', created_by_name: '处理人甲' }
  store.ledgerResult = { rows: [row], groups: [], page: 1, page_size: 20, total: 1 }
  const html = await render(Ledger)
  const table = captured['库存台账']
  assert.deepEqual(table.props.columns.map(c => c.title), ['物料编号', '物料名称', '时间', '处理人', '仓库', '单据类型', '单据编号', '变动', '筛选范围结余'])
  assert.ok(Number(table.props.columns.find(c => c.key === 'warehouse_name').width) < Number(table.props.columns.find(c => c.key === 'material_name').width))
  assert.match(html, new RegExp(ledgerTime(row.created_at)))
  assert.match(html, /<td>处理人甲<\/td>/)
  assert.match(html, /<td>连接器 · 2P<\/td>/)
  assert.doesNotMatch(html, /13:47:44|role="dialog"/)
  const click = (tableName, key, item) => {
    const nodes = captured[tableName].slots['cell-' + key]({ row: item })
    const target = nodes.find(node => node.props?.onClick)
    assert.ok(target, '编号必须有实际点击入口')
    target.props.onClick()
  }
  click('库存台账', 'sku', row)
  click('库存台账', 'source_document', row)
  assert.deepEqual(calls.map(([kind]) => kind), ['material', 'document'])
  assert.equal(calls[1][1].source_id, 8)

  store.ledgerMaterialTarget = row
  store.ledgerMaterialDetail = { id: 3, sku: 'EL-03', name: '连接器 · 2P', unit: '个', specification: '2.54mm', brand: '示例品牌', category_code: '', notes: '只读备注' }
  store.ledgerMaterialQuery = { warehouse_id: 1, material_id: 3, from_date: null, to_date: '2026-10-13', source_type: null, page: 2, page_size: 20 }
  store.ledgerMaterialResult = { ...store.ledgerResult, page: 2, total: 41 }
  const materialHtml = await render(Ledger)
  assert.match(materialHtml, /role="dialog" aria-label="物料详情 · EL-03"/)
  assert.match(materialHtml, /2.54mm/); assert.match(materialHtml, /只读备注/)
  assert.match(materialHtml, /台账明细/)
  assert.equal(captured['物料台账明细'].props.pagination.page, 2)
  assert.equal(captured['物料台账明细'].props.pagination.total, 41)

  store.ledgerDocumentTarget = row
  store.ledgerDocumentRecord = { document_no: row.source_document_no, document_type: 'WarehouseInbound', document_id: 8,
    content_matches: true, summary: [{ label: '仓库', value: '主仓库' }, { label: 'EL-03 · 连接器', value: '20 个' }] }
  const documentHtml = await render(Ledger)
  assert.match(documentHtml, /role="dialog" aria-label="单据详情 · QTRK-20261013-000001"/)
  assert.match(documentHtml, /物料明细/); assert.match(documentHtml, /20 个/)
  assert.doesNotMatch(documentHtml, /提交审批|撤回审批|保存草稿|确认入库/)
  store.ledgerDocumentRecord = null; store.ledgerDocumentError = '没有查看此类单据的权限'
  assert.match(await render(Ledger), /没有查看此类单据的权限.*重新读取单据/s)

  store.ledgerMaterialTarget = null; store.ledgerDocumentTarget = null
  const reportRow = { sku: 'EL-03', material_name: '连接器 · 2P', material_id: '3', warehouse_id: '1', warehouse: '主仓库', unit: '个', quantity: '50' }
  store.inventoryReportResult = { rows: [reportRow], columns: [{ key: 'sku', title: '物料编号' }, { key: 'material_name', title: '物料名称' }, { key: 'warehouse', title: '仓库' }], page: 1, page_size: 20, total: 1 }
  const reportHtml = await render(Reports, { domain: 'inventory' })
  assert.match(reportHtml, /<th>物料编号<\/th><th>物料名称<\/th><th>仓库<\/th>/)
  click('库存报表', 'sku', reportRow)
  assert.deepEqual(calls.at(-1), ['report', reportRow])
  store.purchaseReportResult = { rows: [{ material: '采购物料' }], columns: [{ key: 'material', title: '物料' }] }
  const purchaseHtml = await render(Reports, { domain: 'purchase' })
  assert.match(purchaseHtml, /采购物料/)
  assert.doesNotMatch(purchaseHtml, /物料编号|物料详情|role="dialog"/)
})
