import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, h, nextTick, ref, ssrContextKey } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'

// 真实页面 setup 与真实 Pinia 读请求参与测试；仅用内存渲染器省略无关表格和 Electron 外壳。
const emptyPage = { items: [], total: 0, page: 1, page_size: 20, summary: {}, actors: [], work_orders: [] }
const summary = id => ({ work_order_id: id, lines: [], sources: [], dispatches: [], receipts: [], exchanges: [], returns: [] })
const document = (id, kind = 'dispatch') => ({ id, kind, document_no: `FLOW-${id}`, version: 1, status: 'draft', work_order_id: id + 100,
  warehouse_id: 1, reference: '', reason: '', note: '', lines: [{ id: id + 10, material_id: 5, quantity: '2', remaining_quantity: '2', executed_quantity: '0', received_quantity: '0' }], executions: [] })
const permissions = ['material_flow.view', 'material_dispatch.create', 'material_dispatch.post', 'material_dispatch.close', 'material_dispatch.reverse', 'material_receipt.sign']
const settle = async () => { await Promise.resolve(); await Promise.resolve(); await nextTick() }
async function fixture(t, component = 'view') {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'material-flow-preparation-fixture', enforce: 'pre',
    resolveId(id, importer) { if (importer?.includes('/src/renderer/') && id.endsWith('.vue')) return '\0flow-preparation-empty' },
    load(id) {
      if (id === '\0flow-preparation-empty') return 'export default {render:()=>null}'
      if (id.endsWith('/router/browser-router.ts')) return "import {createRouter,createMemoryHistory} from 'vue-router';export const workspaceRouter=createRouter({history:createMemoryHistory(),routes:[]})"
    }
  }, vue(), Icons({ compiler: 'vue3' })], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const previous = globalThis.window, calls = []
  globalThis.window = { location: { hash: '', pathname: '/' }, nexora: { callApi: (method, payload) => method === 'materialFlowQuery' ? Promise.resolve(emptyPage)
    : new Promise((resolve, reject) => calls.push({ method, payload, resolve, reject })) } }
  t.after(() => { globalThis.window = previous })
  const { usePiniaAppStore } = await server.ssrLoadModule('/src/renderer/src/store/app-store.ts')
  const { useMaterialFlowStore } = await server.ssrLoadModule('/src/renderer/src/store/modules/material-flow-store.ts')
  const origin = await server.ssrLoadModule('/src/renderer/src/utils/dialog-origin.ts')
  t.after(origin.clearDialogOrigins)
  const { provideDialogPreparation } = await server.ssrLoadModule('/src/renderer/src/composables/use-dialog-presentation.ts')
  const pinia = createPinia(), app = usePiniaAppStore(pinia)
  app.user = { id: 1, username: 'warehouse', roles: ['warehouse'], permissions: [...permissions] }
  app.server = { id: 'test-a', fingerprint: 'cert-a' }; app.connectionLost = false; app.refreshData = async () => {}
  const flow = useMaterialFlowStore(pinia), approvals = []; let approvalGeneration = 0
  app.closeDocumentApproval = () => { approvalGeneration++; app.documentApprovalTarget = null; app.documentApprovalRecord = null; app.documentApprovalLoading = false; app.documentApprovalError = '' }
  app.openDocumentApproval = target => {
    const ticket = ++approvalGeneration
    app.documentApprovalTarget = target; app.documentApprovalLoading = true; app.documentApprovalError = ''
    return new Promise(resolve => approvals.push({ target, resolve(ok = true) {
      if (ticket !== approvalGeneration) { resolve(false); return }
      app.documentApprovalLoading = false
      if (ok) app.documentApprovalRecord = { ...target, version: ticket, status: 'approved', content_matches: true }
      else app.documentApprovalError = '审批读取失败'
      resolve(ok)
    } }))
  }
  const path = component === 'panel' ? '/src/renderer/src/components/workspace/WorkOrderMaterialFlowPanel.vue' : '/src/renderer/src/views/workspace/warehouse/ProductionMaterialFlowView.vue'
  const { default: Component } = await server.ssrLoadModule(path)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
  await router.push('/'); await router.isReady()
  const props = ref(component === 'panel' ? { orderId: 101 } : { kind: 'dispatch', embedded: true })
  let state, barrier
  const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}), insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
  const MountedComponent = { ...Component, render: () => null }
  const application = renderer.createApp({ setup() { barrier = provideDialogPreparation(); return () => h(MountedComponent, props.value) } }).use(pinia).use(router)
  application.provide(ssrContextKey, { modules: new Set() })
  application.mixin({ created() { if (this.$options.__name === Component.__name) state = this.$.setupState } })
  application.mount({}); t.after(() => application.unmount())
  return { app, flow, calls, approvals, state, props, barrier, origin }
}
async function finishDetail(f, request, value) {
  f.calls.at(-1).resolve(value); await settle()
  if (value.kind !== 'receipt') { f.approvals.at(-1).resolve(); await settle() }
  f.calls.at(-1).resolve(summary(value.work_order_id)); await request; await settle()
}

test('生产物料详情等单据、审批与工单材料全部就绪才展开，刷新失败保留正文但禁用业务操作', async t => {
  const f = await fixture(t), value = document(1)
  const request = f.state.openDetail(value)
  assert.equal(f.state.detailOpen, true); assert.equal(f.state.detailReady, false)
  f.calls[0].resolve(value); await settle()
  assert.equal(f.state.detailReady, false); assert.equal(f.state.detailDisabled, true)
  f.approvals[0].resolve(); await settle()
  assert.equal(f.calls.at(-1).method, 'workOrderMaterialFlow'); assert.equal(f.state.detailReady, false)
  f.calls.at(-1).resolve(summary(value.work_order_id)); await request; await settle()
  assert.equal(f.state.detailReady, true); assert.equal(f.state.detailDisabled, false)
  const refresh = f.state.refreshDetail()
  assert.equal(f.state.detail.document_no, value.document_no); assert.equal(f.state.detailDisabled, true)
  f.calls.at(-1).reject(Error('详情刷新失败')); await refresh
  assert.equal(f.state.detail.document_no, value.document_no); assert.equal(f.state.detailDisabled, true)
  assert.match(f.state.detailLoadError, /详情刷新失败/)
  const writes = f.calls.length
  await f.state.prepare('execute'); await f.state.submitOperation()
  assert.equal(f.calls.length, writes, '旧正文和旧审批不得恢复可执行权限')
})

test('同单取消重开与 show 持续为 true 的换单各有代次，并替换真实来源', async t => {
  const f = await fixture(t), first = document(1), second = document(2)
  const element = id => ({ id, getBoundingClientRect: () => ({ left: id * 10, top: 10, width: 80, height: 30 }) })
  const a = element(1), b = element(2), c = element(3)
  const cancelled = f.state.openDetail(first, { currentTarget: a })
  f.state.closeDetail(false)
  const reopened = f.state.openDetail(first, { currentTarget: b })
  f.calls[0].resolve(first); await cancelled
  assert.equal(f.state.detailLoading, true); assert.equal(f.approvals.length, 0)
  assert.equal(f.origin.getDialogOrigin(f.state.detailOriginKey).element, b)
  f.calls[1].resolve(first); await settle()
  const swapped = f.state.openDetail(second, { currentTarget: c })
  f.approvals[0].resolve(); await reopened
  assert.equal(f.state.detailOpen, true); assert.equal(f.state.detailLoading, true)
  assert.equal(f.calls.filter(call => call.method === 'workOrderMaterialFlow').length, 0)
  assert.equal(f.origin.getDialogOrigin(f.state.detailOriginKey).element, c)
  await finishDetail(f, swapped, second)
  assert.equal(f.state.detail.id, 2); assert.equal(f.state.detailDisabled, false)
})

test('新建及编辑的准备都可取消，失败不覆盖已有草稿，会话失效后迟到结果不再弹出', async t => {
  const f = await fixture(t)
  f.flow.draft('dispatch').work_order_id = 101
  const opening = f.state.openCreate()
  assert.equal(f.state.createOpen, true); assert.equal(f.state.createLoading, true)
  f.state.closeCreate(false)
  f.calls[0].resolve({ ...summary(101), lines: [{ material_id: 9, dispatchable_quantity: '7' }] }); await opening
  assert.equal(f.state.createOpen, false); assert.deepEqual(f.flow.draft('dispatch').rows, [])
  const detail = f.state.openDetail(document(1)); await finishDetail(f, detail, document(1))
  f.flow.draft('dispatch').reason = '已保留草稿'
  const editing = f.state.editDraft()
  assert.equal(f.state.createOpen, true); assert.equal(f.state.createLoading, true)
  f.calls.at(-1).reject(Error('额度读取失败')); await editing
  assert.match(f.state.createError, /额度读取失败/); assert.equal(f.flow.draft('dispatch').reason, '已保留草稿')
  f.state.closeCreate(false)
  const late = f.state.openDetail(document(3))
  f.app.user = { ...f.app.user, id: 2 }
  assert.equal(f.state.detailOpen, false); assert.equal(f.state.createOpen, false)
  f.calls.at(-1).resolve(document(3)); await late
  assert.equal(f.state.detailOpen, false); assert.equal(f.flow.documents['dispatch:3'], undefined)
})

test('批次准备失败或取消不能当作空批次成功，也不能让迟到结果覆盖新操作', async t => {
  const f = await fixture(t), value = document(1)
  const detail = f.state.openDetail(value); await finishDetail(f, detail, value)
  const first = f.state.prepare('execute')
  assert.equal(f.state.operationLoading, true); assert.equal(f.state.detailReady, false)
  const cancel = f.state.cancelOperation()
  f.approvals.at(-1).resolve(); await cancel; await settle()
  f.calls.find(call => call.method === 'materialFlowLots').resolve({ lines: [{ line_id: 11, lots: [{ lot_id: 99 }] }] }); await first
  assert.equal(f.state.operation, ''); assert.deepEqual(f.state.lots, { lines: [] })
  const second = f.state.prepare('execute')
  f.calls.at(-1).reject(Error('批次读取失败')); await second
  assert.equal(f.state.operationLoading, false); assert.match(f.state.operationError, /批次读取失败/)
  const count = f.calls.length
  await f.state.submitOperation()
  assert.equal(f.calls.length, count)
})

test('工单四区摘要注册父详情首屏屏障，换工单与取消读取隔离迟到响应', async t => {
  const f = await fixture(t, 'panel')
  assert.equal(f.barrier.pending.value, true)
  f.props.value = { orderId: 102 }; await nextTick()
  f.calls[0].resolve(summary(101)); await settle()
  assert.equal(f.barrier.pending.value, true); assert.equal(f.flow.orders[101], undefined)
  f.calls[1].reject(Error('材料核对失败')); await settle()
  assert.equal(f.barrier.pending.value, false); assert.match(f.barrier.error.value, /材料核对失败/)
})
