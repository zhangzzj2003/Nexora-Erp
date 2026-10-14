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
      if (id.endsWith('/InventoryDetailDialogs.vue') || id.endsWith('/WorkspaceDocumentDialog.vue')) return code.replace("'naive-ui'", "'virtual:detail-modal'").replace(/(['"])[^'"]*AppModal\.vue\1/g, "'virtual:detail-modal'")
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
          queryStockOverview(){},resetStockOverview(){},queryLedger(){},queryPurchaseReport(){},queryInventoryReport(){},exportPurchaseReport(){},exportInventoryReport(){},
          closeLedgerMaterial(){},closeLedgerDocument(){},loadLedgerMaterial(){},queryLedgerMaterial(){},loadLedgerDocument(){},
          openStockMaterial:row=>calls.push(['stock',row]),loadStockMaterial(){},selectStockMaterialWarehouse:id=>calls.push(['warehouse',id]),
          openLedgerMaterial:row=>calls.push(['material',row]),openReportMaterial:row=>calls.push(['report',row]),openLedgerDocument:row=>calls.push(['document',row])}))`
      if (id === '\0detail-table') return `import {defineComponent,h} from 'vue';export const captured={};
        export default defineComponent({props:['data','title','showTitle','columns','pagination','loading','error'],setup(p,{attrs,slots}){
          captured[p.title]={props:p,attrs,slots};return()=>h('section',[
            p.showTitle!==false?h('h3',p.title):null,
            slots.filters?.(),slots.filterActions?.(),slots.actions?.(),slots.beforeTable?.(),h('table',[
              h('thead',h('tr',p.columns.map(c=>h('th',c.title)))),
              h('tbody',p.data.map(row=>h('tr',p.columns.map(c=>h('td',slots['cell-'+c.key]?.({row})??row[c.key])))))]),
            p.error,slots.errorActions?.(),slots.footer?.()])}})`
      if (id === '\0detail-modal') return `import {defineComponent,h} from 'vue';
        export { NModal as default }; export const NModal=defineComponent({props:['show','title'],setup(p,{slots}){return()=>p.show?h('div',{role:'dialog','aria-label':p.title},[slots.default?.(),slots.footer?h('footer',{class:'n-card__footer'},slots.footer()):null]):null}});
        export const NTabs=defineComponent({setup(p,{slots}){return()=>h('div',{role:'tablist'},slots.default?.())}});
        export const NTabPane=defineComponent({props:['tab'],setup(p,{slots}){return()=>h('section',{role:'tabpanel'},[h('h3',p.tab),slots.default?.()])}})`
      if (id === '\0detail-progress') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['record','executionHint'],setup(p){return()=>h('p',{'data-approval-progress':''},p.executionHint||'审批进度')}})`
    }
  }, vue()], server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Ledger } = await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryLedgerView.vue')
  const { default: Overview } = await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryOverviewView.vue')
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
  assert.match(materialHtml, /2.54mm/); assert.match(materialHtml, /展开规格与更多资料/)
  assert.match(materialHtml, /台账明细/)
  // 三个入口均直接上下阅读；分页和日期范围仍沿用原查询，操作区位于正文之后。
  function assertStacked(html) {
    assert.doesNotMatch(html, /role="tablist"|role="tabpanel"/)
    assert.ok(html.indexOf('material-facts') < html.indexOf('ledger-scope'))
    assert.ok(html.indexOf('ledger-scope') < html.indexOf('n-card__footer'))
  }
  assertStacked(materialHtml)
  const reportMaterialHtml = await render(Reports, { domain: 'inventory' })
  assertStacked(reportMaterialHtml)
  assert.match(reportMaterialHtml, /2026-10-13/)
  assert.equal(captured['物料台账明细'].props.pagination.page, 2)
  assert.equal(captured['物料台账明细'].props.pagination.total, 41)

  store.ledgerDocumentTarget = row
  store.ledgerDocumentRecord = { document_no: row.source_document_no, document_type: 'WarehouseInbound', document_id: 8,
    content_matches: true, summary: [{ label: '仓库', value: '主仓库' }, { label: 'EL-03 · 连接器', value: '20 个' }] }
  const documentHtml = await render(Ledger)
  assert.match(documentHtml, /role="dialog" aria-label="单据详情 · QTRK-20261013-000001"/)
  assert.match(documentHtml, /物料明细/); assert.match(documentHtml, /20 个/)
  assert.doesNotMatch(documentHtml, /提交审批|撤回审批|保存草稿|确认入库/)
  // 新生产单保留分批状态，审批快照不能被显示成已全部发完或收完。
  for (const [type, source, hint] of [['MaterialDispatch', 'material_dispatch', /仍有数量待发/],
    ['ProductionMaterialReturn', 'production_material_return', /仍有数量待收/],
    ['MaterialExchange', 'material_dispatch', /全部签收后才完成换料/]]) {
    store.ledgerDocumentTarget = { ...row, source_type: source }
    store.ledgerDocumentRecord = { ...store.ledgerDocumentRecord, document_type: type, intent: 'execute', business_status: 'partial', status: 'executed' }
    const flowHtml = await render(Ledger)
    assert.match(flowHtml, hint); assert.doesNotMatch(flowHtml, /审批与业务执行均已完成|仍待发：。|仍待收：。/)
    assert.doesNotMatch(flowHtml, /提交审批|撤回审批|保存草稿/)
  }
  store.ledgerDocumentTarget = { ...row, source_type: 'material_handover_return' }
  store.ledgerDocumentRecord = { ...store.ledgerDocumentRecord, document_type: 'MaterialReceipt', intent: 'execute', status: 'draft',
    summary: [{ label: '签收方式', value: '无需普通审批，按权限确认签收；更正另行审批' }] }
  const receiptHtml = await render(Ledger)
  assert.match(receiptHtml, /未签收交接退回/); assert.match(receiptHtml, /无需普通审批，按权限确认签收/)
  assert.doesNotMatch(receiptHtml, /data-approval-progress|提交后进入审批流程/)
  store.ledgerDocumentRecord = { ...store.ledgerDocumentRecord, intent: 'reverse' }
  assert.match(await render(Ledger), /data-approval-progress/)
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

  // 总览坚持五列；两个入口都打开同一个上下排列的物料详情，而不是路由跳转。
  const stock = { id: 3, sku: 'EL-03', name: '连接器 · 2P', category_group_name: '电子类', category_name: '电子类 / 连接器', unit: '个', quantity: '-2', total_quantity: '8',
    warehouses: [{ warehouse_id: 1, warehouse_code: 'MAIN', warehouse_name: '主仓库', quantity: '-2' }, { warehouse_id: 2, warehouse_code: 'OTHER', warehouse_name: '辅仓', quantity: '10' }] }
  store.stockOverviewResult = { items: [stock], page: 1, page_size: 20, total: 1, summary: { material_count: 1, positive_material_count: 0, zero_material_count: 0, negative_material_count: 1 } }
  const overviewHtml = await render(Overview)
  assert.deepEqual(captured['库存总览'].props.columns.map(c => c.title), ['物料编号', '物料名称', '物料分类', '物料数量', '操作'])
  assert.match(overviewHtml, /电子类/); assert.match(overviewHtml, /stock-negative/)
  assert.doesNotMatch(overviewHtml, /已确认入库单/)
  // 检查真实按钮的边框与尺寸，防止操作列再次退化为仅有文字的入口。
  const viewButton = html => [...html.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)]
    .map(match => match[0]).find(button => button.replace(/<[^>]+>/g, '').trim() === '查看')
  assert.match(viewButton(overviewHtml), /app-button--secondary/)
  assert.match(viewButton(overviewHtml), /n-button--small-type/)
  assert.match(viewButton(overviewHtml), /n-button__border/)
  store.connectionLost = true
  assert.match(viewButton(await render(Overview)), / disabled(?:\s|>)/)
  store.connectionLost = false
  click('库存总览', 'sku', stock); click('库存总览', 'actions', stock)
  assert.deepEqual(calls.slice(-2), [['stock', stock], ['stock', stock]])
  store.stockMaterialMode = true; store.stockMaterialSnapshot = stock; store.ledgerMaterialTarget = row
  const stockDetailHtml = await render(Overview)
  assertStacked(stockDetailHtml)
  assert.match(stockDetailHtml, /各仓库库存/); assert.match(stockDetailHtml, /全仓合计/)
  assert.match(stockDetailHtml, /8 个/); assert.match(stockDetailHtml, /辅仓/)
  assert.ok(stockDetailHtml.indexOf('material-facts') < stockDetailHtml.indexOf('各仓库库存'))
  assert.ok(stockDetailHtml.indexOf('各仓库库存') < stockDetailHtml.indexOf('流水仓库'))
  click('各仓库库存', 'actions', stock.warehouses[1])
  assert.deepEqual(calls.at(-1), ['warehouse', 2])
})
