import assert from 'node:assert/strict'
import { test } from 'node:test'
import { computed, createRenderer, h, nextTick, ref, ssrContextKey } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { useProductionRecords } from '../src/renderer/src/composables/use-production-records.ts'
import { validateDocumentApprovalRecord } from '../src/shared/document-approval-api.ts'
import { dialogPreviewResponse, dialogPreviewWorkOrders } from '../scripts/site-preview/dialog-fixtures.mjs'

test('闭环预览的审批和工单字段通过真实校验，示例桥拒绝业务写入', () => {
  const store = { user: {}, suppliers: [], materialCategories: [] }
  for (const [document_type, document_id] of [['WorkOrder', 903], ['MaterialDispatch', 904], ['ProductionCompletion', 908]]) {
    const record = dialogPreviewResponse('documentApproval', { document_type, document_id, intent: 'execute' }, store)
    assert.doesNotThrow(() => validateDocumentApprovalRecord(record))
  }
  assert.ok(dialogPreviewWorkOrders[0].created_at)
  assert.equal(dialogPreviewWorkOrders[0].lines[0].pending_dispatch_quantity, '40')
  assert.throws(() => dialogPreviewResponse('createProductionCompletion', {}, store), /未连接业务服务/)
})

const groups = [
  { key: 'active', label: '待完工', statuses: ['released', 'in_progress'] },
  { key: 'completed', label: '已完工', statuses: ['completed'] },
]

test('生产概览统计全部匹配记录，关键词、仓库和状态联动且不取当前表格页', () => {
  const records = ref(Array.from({ length: 43 }, (_, i) => ({ id: i + 1, status: i < 23 ? 'released' : 'completed',
    warehouse_id: i % 2 + 1, warehouse_name: i % 2 ? '成品仓' : '主仓库', reference: `工单-${i + 1}` })))
  const list = useProductionRecords(records, groups, row => [row.reference])
  assert.equal(list.recordSummaries.value[0].count, 43)
  list.recordFilters.value.status = 'active'
  assert.equal(list.filteredRecords.value.length, 23)
  assert.equal(list.recordSummaries.value[0].count, 43)
  list.recordFilters.value.warehouse = 2
  assert.equal(list.filteredRecords.value.length, 11)
  assert.equal(list.recordSummaries.value[0].count, 21)
  list.recordQuery.value = ' 工单-2 '
  assert.deepEqual(list.filteredRecords.value.map(row => row.id), [2, 20, 22])
  assert.equal(list.recordSummaries.value[0].count, 6)
  list.recordFilters.value.status = 'completed'
  assert.deepEqual(list.filteredRecords.value.map(row => row.id), [24, 26, 28])
  list.resetRecordFilters()
  assert.equal(list.filteredRecords.value.length, 43)
  // 快照更新必须同步重算统计，不能把上一轮数量固定在组件本地。
  records.value = []
  assert.equal(list.recordSummaries.value[0].count, 0)
  assert.deepEqual(list.recordFilterFields.value[1].options, [{ value: 0, label: '全部仓库' }])
})

test('来源工单约束先于全部统计，未知状态不放出其他工单记录', () => {
  const all = ref([{ status: 'posted', warehouse_id: 1, warehouse_name: '主仓库', work_order_id: 1 },
    { status: 'posted', warehouse_id: 1, warehouse_name: '主仓库', work_order_id: 2 }])
  const source = ref(1), list = useProductionRecords(computed(() => all.value.filter(row => row.work_order_id === source.value)),
    [{ key: 'posted', label: '已入库', statuses: ['posted'] }], row => [row.work_order_id])
  assert.equal(list.recordSummaries.value[0].count, 1)
  list.recordFilters.value.status = 'unknown'
  assert.equal(list.filteredRecords.value.length, 0)
  source.value = 3
  assert.equal(list.recordSummaries.value[0].count, 0)
})

const order = (id = 1, status = 'in_progress') => ({ id, status, warehouse_id: 1, warehouse_name: '主仓库',
  document_no: `SCGD-${id}`, product_name: '成品', product_sku: 'FIN', remaining_output_quantity: '60', lines: [] })
// 路由 replace 经过异步守卫；等它完成当前事件循环，再检查一次性意图已被消费。
const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)); await nextTick() }

async function fixture(t, name, query = {}, permissions = ['production.view', 'production_completion.create']) {
  const server = await createServer({ configFile: false, plugins: [{ name: 'production-cycle-view', enforce: 'pre',
    resolveId(id, importer) {
      if (importer?.includes('/src/renderer/') && id.endsWith('/store/app-store')) return '\0cycle-store'
      if (importer?.includes('/src/renderer/') && id.endsWith('.vue')) return '\0cycle-empty'
    }, load(id) {
      if (id === '\0cycle-empty') return 'export default {render:()=>null}'
      if (id === '\0cycle-store') return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
        import {createProductionActions} from '/src/renderer/src/store/modules/production-actions.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('production-cycle-view',()=>{const s=createAppState();return {...s,
          ...createProductionActions(s,async action=>{try{await action()}catch(e){s.error.value=e.message}},key=>calls.push(['navigate',key])),
          can:p=>s.user.value?.permissions.includes(p)??false,localTime:v=>v,
          openDocumentApproval:async target=>{s.documentApprovalTarget.value=target;return true},
          closeDocumentApproval(){s.documentApprovalTarget.value=null;calls.push(['close'])}}})`
    },
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, calls } = await server.ssrLoadModule('\0cycle-store')
  const { default: Component } = await server.ssrLoadModule(`/src/renderer/src/views/workspace/production/${name}.vue`)
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  store.user = { id: 1, roles: ['planner'], permissions }
  store.workOrders = [order(), order(2)]
  store.productionCompletions = [{ ...order(), work_order_id: 1, status: 'posted' }, { ...order(2), work_order_id: 2, status: 'draft' }]
  const path = name === 'ProductionWorkOrdersView' ? '/workspace/work-orders' : '/workspace/production-completions'
  const router = createRouter({ history: createMemoryHistory(), routes: ['/workspace/work-orders', '/workspace/production-completions']
    .map(path => ({ path, component: { render: () => null } })) })
  await router.push({ path, query }); await router.isReady()
  let state
  // 挂载真实页面 setup 和路由监听，仅省略与本次行为无关的弹窗及表格绘制。
  const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {},
    setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ render: () => h({ ...Component, render: () => null }) }).use(pinia).use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mixin({ created() { if (this.$options.__name === Component.__name) state = this.$.setupState } })
  app.mount({}); t.after(() => app.unmount()); await settle()
  return { store, state, calls, router }
}

test('工单创建完工关闭来源详情并携带建单意图；只读查看不触发建单', async t => {
  const f = await fixture(t, 'ProductionWorkOrdersView')
  f.store.documentApprovalTarget = { document_type: 'WorkOrder', document_id: 1, intent: 'execute' }
  await f.state.openCompletions(true)
  assert.equal(f.store.documentApprovalTarget, null)
  assert.equal(f.router.currentRoute.value.path, '/workspace/production-completions')
  assert.deepEqual(f.router.currentRoute.value.query, { work_order_id: '1', create_from_order: '1' })
  f.store.documentApprovalTarget = { document_type: 'WorkOrder', document_id: 2, intent: 'execute' }
  await f.state.openCompletions()
  assert.deepEqual(f.router.currentRoute.value.query, { work_order_id: '2' })
})

test('工单断线、撤销建单权限或没有待产量时拒绝开始完工', async t => {
  const f = await fixture(t, 'ProductionWorkOrdersView')
  f.store.documentApprovalTarget = { document_type: 'WorkOrder', document_id: 1, intent: 'execute' }
  f.store.connectionLost = true; await f.state.openCompletions(true)
  f.store.connectionLost = false; f.store.user.permissions = ['production.view']; await f.state.openCompletions(true)
  f.store.user.permissions.push('production_completion.create'); f.store.workOrders[0].remaining_output_quantity = '0'; await f.state.openCompletions(true)
  assert.equal(f.calls.length, 0)
  assert.equal(f.router.currentRoute.value.path, '/workspace/work-orders')
})

test('来源工单自动打开一次完工草稿；刷新列表与关闭弹窗不重置输入，失败保存保留草稿', async t => {
  const f = await fixture(t, 'ProductionCompletionsView', { work_order_id: '1', create_from_order: '1' })
  await settle()
  assert.equal(f.state.createOpen, true)
  assert.equal(f.store.completionForm.work_order_id, 1)
  assert.equal(f.store.completionForm.reported_quantity, '60')
  assert.deepEqual(f.router.currentRoute.value.query, { work_order_id: '1' })
  assert.equal(f.state.filteredRecords.length, 1)
  f.store.completionForm.reported_quantity = '12'; f.state.createOpen = false
  f.store.workOrders = [...f.store.workOrders, order(3)]; await settle()
  assert.equal(f.state.createOpen, false)
  assert.equal(f.store.completionForm.reported_quantity, '12')
  assert.equal(f.calls.filter(call => call[0] === 'navigate').length, 0)
  const previous = globalThis.window
  globalThis.window = { nexora: { callApi: async () => { throw Error('库存来源已变化') } } }
  t.after(() => { globalThis.window = previous })
  await f.store.createProductionCompletion()
  assert.equal(f.store.completionForm.reported_quantity, '12')
  assert.match(f.store.error, /库存来源已变化/)
  f.store.documentApprovalTarget = { document_type: 'ProductionCompletion', document_id: 1, intent: 'execute' }
  await f.state.returnToWorkOrder()
  assert.equal(f.store.documentApprovalTarget, null)
  assert.deepEqual(f.router.currentRoute.value.query, { document_id: '1' })
})

test('完工建单地址不能绕过权限；断线恢复后才消费有效建单意图', async t => {
  const f = await fixture(t, 'ProductionCompletionsView', { create_from_order: '1' }, ['production.view'])
  assert.equal(f.state.createOpen, false)
  f.store.connectionLost = true; f.store.user.permissions.push('production_completion.create'); await settle()
  assert.equal(f.state.createOpen, false)
  f.store.connectionLost = false; await settle()
  assert.equal(f.state.createOpen, true)
})

test('仅查看来源记录后手动新建仍选该工单；重开保留草稿，已完工来源不再建单', async t => {
  const f = await fixture(t, 'ProductionCompletionsView', { work_order_id: '2' })
  f.store.completionForm = { work_order_id: 1, reported_quantity: '12', reference: '另一工单草稿' }
  f.state.startCreate()
  assert.equal(f.store.completionForm.work_order_id, 2)
  f.store.completionForm.reported_quantity = '10'; f.state.createOpen = false
  f.state.startCreate()
  assert.equal(f.store.completionForm.reported_quantity, '10')
  f.state.createOpen = false; f.store.workOrders[1].status = 'completed'
  f.state.startCreate()
  assert.equal(f.state.createOpen, false)
  await f.router.replace({ query: { work_order_id: '2', create_from_order: '1' } }); await settle()
  assert.equal(f.state.createOpen, false)
})
