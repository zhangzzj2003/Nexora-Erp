import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'
import { createPinia } from 'pinia'
import { createSSRApp, createRenderer, h, nextTick, ssrContextKey } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createMemoryHistory, createRouter } from 'vue-router'

let server, useApp, useFlow, View, LotEditor, WorkOrdersView
before(async () => {
  // 测试真实 Pinia 模块及 Vue 页面，仅替换 Electron 不存在的浏览器路由环境。
  server = await createServer({ configFile: false, plugins: [vue(), Icons({ compiler: 'vue3' }), {
    name: 'flow-test-router', enforce: 'pre',
    transform(code, id) { if (id.endsWith('/WorkspaceDocumentDialog.vue')) return code.replace(/(['"])\.\.\/app\/AppModal\.vue\1/g, "'virtual:flow-test-modal'") },
    resolveId(id) { if (id === 'virtual:flow-test-modal') return '\0flow-test-modal' },
    load(id) {
      if (id === '\0flow-test-modal') return "import {defineComponent,h} from 'vue'; export default defineComponent({props:['show','ready'],setup(p,{slots}){return()=>p.show&&p.ready!==false?h('section',slots.default?.()):null}})"
      if (id.endsWith('/router/browser-router.ts')) return "import { createRouter, createMemoryHistory } from 'vue-router'; export const workspaceRouter = createRouter({ history:createMemoryHistory(),routes:[] })"
    }
  }], ssr: { noExternal: ['vxe-table'] }, optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  ;({ usePiniaAppStore: useApp } = await server.ssrLoadModule('/src/renderer/src/store/app-store.ts'))
  ;({ useMaterialFlowStore: useFlow } = await server.ssrLoadModule('/src/renderer/src/store/modules/material-flow-store.ts'))
  ;({ default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/ProductionMaterialFlowView.vue'))
  ;({ default: LotEditor } = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceLotLineEditor.vue'))
  ;({ default: WorkOrdersView } = await server.ssrLoadModule('/src/renderer/src/views/workspace/production/ProductionWorkOrdersView.vue'))
})
after(() => server?.close())
const permissions = ['material_flow.view', 'material_dispatch.create', 'material_dispatch.post', 'material_receipt.sign']
function setup() {
  const pinia = createPinia(), app = useApp(pinia)
  app.user = { id: 1, username: 'warehouse', roles: ['warehouse'], permissions: [...permissions] }
  app.server = { id: 'server-a', fingerprint: 'test' }; app.connectionLost = false
  app.refreshData = async () => {}
  return { pinia, app, flow: useFlow(pinia) }
}
const page = (id = 1) => ({ items: [], total: id, page: 1, page_size: 20, summary: { draft: id }, actors: [], work_orders: [] })
const query = { kind: 'dispatch', page: 1, page_size: 20 }
const summary = { work_order_id: 2, lines: [], sources: [], dispatches: [], receipts: [], exchanges: [], returns: [] }

test('过期筛选响应不能覆盖新结果，同账号例行刷新不丢草稿', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const pending = []
  globalThis.window = { nexora: { callApi: async () => new Promise(resolve => pending.push(resolve)) } }
  const { app, flow } = setup()
  const first = flow.query({ ...query, q: '旧' }); const second = flow.query({ ...query, q: '新' })
  pending[1](page(22)); await second; pending[0](page(11)); await first
  assert.equal(flow.pages['dispatch:order:0'].total, 22)
  flow.draft('dispatch').reason = '暂存原因'
  app.user = { ...app.user, permissions: [...permissions] }; await nextTick()
  assert.equal(flow.drafts.dispatch.reason, '暂存原因')
})

test('换服务器、换号和撤权清理列表与草稿，并丢弃迟到响应', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  let resolve
  globalThis.window = { nexora: { callApi: async () => new Promise(done => { resolve = done }) } }
  const { app, flow } = setup()
  flow.draft('exchange').reason = '甲账号的申请'
  const request = flow.query(query)
  app.user = { ...app.user, id: 2 }; resolve(page(9)); await request
  assert.deepEqual(flow.pages, {}); assert.deepEqual(flow.drafts, {})
  flow.draft('return').reason = '另一个草稿'
  app.server = { id: 'server-b', fingerprint: 'new' }; assert.deepEqual(flow.drafts, {})
  app.user = { ...app.user, permissions: [] }; assert.equal(flow.available, false)
})

test('权限在执行前与等待响应时均复核，断线丢弃旧结果', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const calls = []; let resolve
  globalThis.window = { nexora: { callApi: async (action, input) => { calls.push({ action, input }); return new Promise(done => { resolve = done }) } } }
  const { app, flow } = setup()
  const draft = flow.draft('dispatch'); draft.reason = '待重试'
  const requestId = draft.request_id
  app.user = { ...app.user, permissions: ['material_flow.view'] }
  await flow.execute({ kind: 'receipt', id: 1, version: 1, request_id: 'receipt-sign-01', lines: [{ line_id: 1, quantity: '58' }] })
  assert.equal(calls.length, 0); assert.match(flow.error, /不允许/)
  app.user = { ...app.user, permissions: [...permissions] }
  const read = flow.loadOrder(2); app.connectionLost = true; resolve(summary); await read
  assert.equal(flow.orders[2], undefined)
  app.connectionLost = false
  assert.ok(requestId)
})

test('四页真实组件都有搜索、独立标题和角色受限的新建入口', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  globalThis.window = { location: { hash: '', pathname: '/' }, nexora: { callApi: async () => page() } }
  for (const [kind, title] of [['dispatch', '生产发料'], ['receipt', '生产领料'], ['exchange', '生产换料'], ['return', '生产退料']]) {
    const { pinia, app } = setup()
    app.user.permissions = ['material_flow.view', 'material_dispatch.create', 'material_exchange.create', 'material_flow_return.create']
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: View }] }); await router.push('/'); await router.isReady()
    const application = createSSRApp({ render: () => h(View, { kind }) }).use(pinia).use(router); setupSsrStyles(application)
    const context = {}; const html = await renderToString(application, context)
    assert.equal((context.teleports?.['#workspace-page-summary']?.match(/class="summary-filter-count"/g) ?? []).length, 5)
    assert.doesNotMatch(html, /<h1[ >]/); assert.match(html, /搜索单据/); assert.match(html, /单号、工单、产品或物料/)
    if (kind === 'receipt') assert.doesNotMatch(html, /新建生产领料/)
    else assert.match(html, new RegExp(`新建${title}`))
  }
})


test('写入失败保留草稿和防重标识，签收只调用签收接口', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const { app, flow } = setup(); const calls = []
  const draft = flow.draft('dispatch'); draft.reason = '已填写的说明'
  const requestId = draft.request_id
  globalThis.window = { nexora: { callApi: async (action, input) => { calls.push({ action, input }); throw Error('连接暂时中断') } } }
  await flow.create({ kind: 'dispatch', work_order_id: 2, warehouse_id: 1, request_id: requestId, lines: [{ work_order_line_id: 4, quantity: '60' }] })
  assert.equal(flow.drafts.dispatch.request_id, requestId); assert.equal(flow.drafts.dispatch.reason, '已填写的说明')
  assert.match(flow.error, /连接暂时中断/)
  const receipt = { kind: 'receipt', id: 7, document_no: 'SCLL-20261014-000007', version: 2, work_order_id: 2, warehouse_id: 1, lines: [], executions: [] }
  globalThis.window.nexora.callApi = async (action, input) => { calls.push({ action, input }); return action === 'workOrderMaterialFlow' ? summary : receipt }
  await flow.execute({ kind: 'receipt', id: 7, version: 1, request_id: 'receipt-sign-58', lines: [{ line_id: 3, quantity: '58' }] })
  assert.equal(calls.at(-2).action, 'executeMaterialFlow'); assert.equal(calls.at(-2).input.lines[0].quantity, '58')
  assert.equal(calls.filter(call => call.action === 'postMaterialIssue').length, 0)
  assert.equal(flow.documents['receipt:7'].version, 2)
})

// 断线后新的重试拥有自己的写锁；旧请求完成不能清掉新请求的锁。
test('写入中断线并重连可重试，迟到请求不污染新写锁', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const { app, flow } = setup(), pending = []
  const receipt = { kind: 'receipt', id: 7, document_no: 'SCLL-7', version: 2, work_order_id: 2, warehouse_id: 1, lines: [], executions: [] }
  globalThis.window = { nexora: { callApi: async action => action === 'workOrderMaterialFlow' ? summary : new Promise(resolve => pending.push(resolve)) } }
  const input = { kind: 'receipt', id: 7, version: 1, request_id: 'receipt-retry-01', lines: [{ line_id: 3, quantity: '1' }] }
  const first = flow.execute(input); assert.equal(flow.busy, true)
  app.connectionLost = true; app.connectionLost = false; assert.equal(flow.busy, false)
  const second = flow.execute(input); assert.equal(pending.length, 2)
  pending[0](receipt); await first; assert.equal(flow.busy, true)
  pending[1](receipt); assert.equal((await second).id, 7); assert.equal(flow.busy, false)
})

test('写入已经成功时快照刷新失败仍返回成功单据并提示刷新', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const { app, flow } = setup()
  const receipt = { kind: 'receipt', id: 7, document_no: 'SCLL-7', version: 2, work_order_id: 2, warehouse_id: 1, lines: [], executions: [] }
  app.refreshData = async () => { throw Error('快照暂时不可用') }
  globalThis.window = { nexora: { callApi: async action => action === 'workOrderMaterialFlow' ? summary : receipt } }
  const saved = await flow.execute({ kind: 'receipt', id: 7, version: 1, request_id: 'receipt-commit-01', lines: [{ line_id: 3, quantity: '1' }] })
  assert.equal(saved.version, 2); assert.match(app.notice, /已更新.*刷新失败/); assert.equal(flow.busy, false)
})

async function mountFlow(kind, workOrderId = 2) {
  globalThis.window.location = { hash: '', pathname: '/' }
  const state = setup()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: View }] }); await router.push('/'); await router.isReady()
  let view
  const application = createSSRApp({ render: () => h(View, { kind, workOrderId }) }).use(state.pinia).use(router)
  application.mixin({ created() { if (this.$options.__name === 'ProductionMaterialFlowView') view = this.$.setupState } })
  setupSsrStyles(application); await renderToString(application)
  return { ...state, view }
}
const demand = { work_order_line_id: 4, material_id: 5, sku: 'M5', material_name: '上盖', unit: '个', dispatchable_quantity: '40' }
const signedSource = { ...demand, source_receipt_line_id: 3, legacy_issue_line_id: null, source_document_no: 'SCLL-3', quantity: '60', available_quantity: '60', warehouse_id: 1 }

test('工单入口首次新建自动带出剩余40，普通发料不引用已签收60', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const order = { ...summary, lines: [demand], sources: [signedSource] }, calls = []
  globalThis.window = { nexora: { callApi: async (action, input) => { calls.push({ action, input }); if (action === 'workOrderMaterialFlow') return order; if (action === 'materialFlowQuery') return page(); throw Error('保持草稿') } } }
  const { view, flow } = await mountFlow('dispatch')
  await view.openCreate()
  assert.equal(flow.drafts.dispatch.rows.length, 1); assert.equal(flow.drafts.dispatch.rows[0].quantity, '40')
  view.changeMaterial(flow.drafts.dispatch.rows[0]); assert.equal(flow.drafts.dispatch.rows[0].quantity, '40.000'); assert.equal(flow.drafts.dispatch.rows[0].source_key, '')
  await view.saveDraft()
  assert.deepEqual(calls.at(-1).input.lines, [{ work_order_line_id: 4, quantity: '40.000' }])
  const key = calls.at(-1).input.request_id
  await view.saveDraft(); assert.equal(calls.at(-1).input.request_id, key)
  flow.drafts.dispatch.rows[0].compact = false; assert.equal(flow.drafts.dispatch.request_id, key)
  flow.drafts.dispatch.rows[0].quantity = '20'; await view.saveDraft(); assert.notEqual(calls.at(-1).input.request_id, key)
})

test('补发草稿编辑保留换料来源并使用补发专用额度', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  const order = { ...summary, lines: [demand], sources: [signedSource], exchanges: [{ lines: [{ id: 8, replacement_available_quantity: '1' }] }] }
  const calls = []
  globalThis.window = { nexora: { callApi: async (action, input) => { calls.push({ action, input }); if (action === 'workOrderMaterialFlow') return order; if (action === 'materialFlowQuery') return page(); throw Error('保持草稿') } } }
  const { view, flow, app } = await mountFlow('dispatch')
  flow.documents['dispatch:9'] = { id: 9, kind: 'dispatch', version: 1, status: 'draft', work_order_id: 2, warehouse_id: 1, reference: '', reason: '', note: '',
    lines: [{ ...demand, id: 10, quantity: '2', exchange_line_id: 8, source_receipt_line_id: null, legacy_issue_line_id: null }] }
  view.activeKind = 'dispatch'; view.activeId = 9; view.detailOpen = true
  flow.readReady['dispatch:9'] = true; flow.readReady['order:2'] = true
  app.documentApprovalTarget = { document_type: 'MaterialDispatch', document_id: 9, intent: 'execute' }
  app.documentApprovalRecord = { document_type: 'MaterialDispatch', document_id: 9, intent: 'execute', status: 'draft', version: 1 }
  await view.editDraft()
  assert.equal(flow.drafts.dispatch.rows[0].exchange_line_id, 8); assert.equal(view.rowLimit(flow.drafts.dispatch.rows[0]), '3.000')
  await view.saveDraft()
  assert.equal(calls.at(-1).action, 'updateMaterialFlow'); assert.deepEqual(calls.at(-1).input.lines, [{ work_order_line_id: 4, quantity: '2', exchange_line_id: 8 }])
})

test('旧料交接额度不使用新料待签量，关闭余额与多来源关联显示原事实', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  globalThis.window = { nexora: { callApi: async action => action === 'materialFlowQuery' ? page() : summary } }
  const { view, flow } = await mountFlow('exchange')
  flow.documents['exchange:8'] = { id: 8, kind: 'exchange', work_order_id: 2, lines: [], executions: [] }
  view.activeKind = 'exchange'; view.activeId = 8
  const line = { quantity: '2', executed_quantity: '2', received_quantity: '0', remaining_quantity: '2', closed_quantity: '5' }
  assert.equal(view.operationLimit(line), '0'); assert.match(view.lineProgress(line, 'return', 'closed'), /已关闭余额 5/)
  flow.orders[2] = { ...summary, returns: [{ id: 11, kind: 'return', lines: [{ source_document_kind: 'exchange', source_document_id: 8 }] }] }
  assert.equal(view.relatedDocuments[0].id, 11)
})


test('可选来源批次未指定时显示有效余量，并允许移除最后一行', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  globalThis.window = { location: { hash: '', pathname: '/' } }
  for (const parts of [[], [{ lot_id: 3, quantity: '1' }]]) {
    let editor, removed
    const application = createSSRApp({ render: () => h(LotEditor, { lots: parts, expected: '1', optional: true, selectable: true, onRemove: index => { removed = index } }) }).use(createPinia())
    application.mixin({ created() { if (this.$options.__name === 'WorkspaceLotLineEditor') editor = this.$.setupState } })
    setupSsrStyles(application); const html = await renderToString(application)
    assert.doesNotMatch(html, /请填写有效数量/)
    if (!parts.length) { assert.match(html, /未指定批次，提交时核对来源/); assert.equal(editor.allocation.remaining, '1') }
    else { editor.remove(0); assert.equal(removed, 0) }
  }
})


test('执行记录展示实际物料和批次，冲销保留负数且不虚构未登记批次', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  globalThis.window = { location: { hash: '', pathname: '/' }, nexora: { callApi: async () => page() } }
  const { pinia, flow } = setup()
  flow.documents['receipt:7'] = { kind: 'receipt', id: 7, document_no: 'SCLL-7', work_order_id: 2, work_order_document_no: 'SCGD-2', status: 'partial', version: 1,
    product_name: '机器', warehouse_name: '原料仓', created_by_name: '仓管', created_at: '2026-10-14 12:00:00', lines: [{ ...demand, id: 3, quantity: '60', executed_quantity: '58', received_quantity: '58', remaining_quantity: '2' }],
    executions: [{ id: 1, action: 'execute', created_by_name: '生产员', created_at: '2026-10-14 12:00:00', reason: '核对实收', lines: [
      { id: 21, line_id: 3, quantity: '58', movement_id: 99, lots: [{ lot_id: 8, code: 'LOT-A', quantity: '56.5' }] }
    ] }, { id: 2, action: 'reverse', created_by_name: '仓管', created_at: '2026-10-14 13:00:00', reason: '更正原实收记录', lines: [
      { id: 22, line_id: 3, quantity: '-58', reverses_line_id: 21, lots: [] }
    ] }] }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: View }] }); await router.push('/'); await router.isReady()
  const application = createSSRApp({ render: () => h(View, { kind: 'receipt' }) }).use(pinia).use(router)
  application.mixin({ created() { if (this.$options.__name === 'ProductionMaterialFlowView') { this.$.setupState.activeId = 7; this.$.setupState.detailOpen = true } } })
  setupSsrStyles(application); const html = await renderToString(application)
  const history = html.slice(html.indexOf('执行记录</h3>'))
  assert.match(history, /M5 · 上盖.*?：58 个/); assert.match(history, /批次 LOT-A：56.5 个/)
  assert.match(history, /未登记批次：1.5 个/); assert.match(history, /库存流水 #99/)
  assert.match(history, /M5 · 上盖.*?：-58 个/); assert.match(history, /更正原实收记录/); assert.match(history, /冲销原执行记录 #21/)
  assert.equal((history.match(/未登记批次/g) ?? []).length, 1)
})


test('工单深链接只响应稳定字段，同账号与同长度快照刷新不会重复打开审批', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  globalThis.window = { location: { hash: '', pathname: '/' } }
  const { pinia, app } = setup(); app.workOrders = [{ id: 1, lines: [] }]
  const { workspaceRouter } = await server.ssrLoadModule('/src/renderer/src/router/browser-router.ts')
  workspaceRouter.addRoute({ path: '/workspace/work-orders', component: WorkOrdersView })
  await workspaceRouter.push('/workspace/work-orders')
  const calls = []
  app.openDocumentApproval = async target => {
    calls.push(target); app.documentApprovalTarget = target
    // 模拟真实审批加载后的统一快照刷新：对象变新，账号和列表长度保持不变。
    app.user = { ...app.user, permissions: [...app.user.permissions] }
    app.workOrders = app.workOrders.map(order => ({ ...order }))
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: WorkOrdersView }] }); await router.push('/?document_id=1'); await router.isReady()
  // 挂载真实页面 setup 与 watch，空渲染宿主只排除本测试无关的桌面控件。
  const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
  const application = renderer.createApp({ ...WorkOrdersView, render: () => null }).use(pinia).use(router)
  application.provide(ssrContextKey, { modules: new Set() })
  application.mount({}); t.after(() => application.unmount())
  await nextTick(); await nextTick(); assert.equal(calls.length, 1)
  // 清空目标后刷新相同快照也不能触发深链接重新打开，避免关闭弹窗后再被刷新拉起。
  app.documentApprovalTarget = null
  app.user = { ...app.user }; app.workOrders = app.workOrders.map(order => ({ ...order }))
  await nextTick(); await nextTick(); assert.equal(calls.length, 1)
  // 列表数量改变时，同一已打开目标仍被守卫挡住，不重启正在进行的审批读取。
  app.documentApprovalTarget = { document_type: 'WorkOrder', document_id: 1, intent: 'execute' }
  app.workOrders = [...app.workOrders, { id: 2, lines: [] }]
  await nextTick(); assert.equal(calls.length, 1)
  await router.push('/?document_id=2'); await nextTick(); assert.equal(calls.length, 2); assert.equal(calls[1].document_id, 2)
})
