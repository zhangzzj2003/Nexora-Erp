import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h, nextTick } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'
import { findDocumentApprovalItem } from '../src/renderer/src/utils/document-approval-item.ts'

let server, useStore, router, routeByKey, MaterialIssuesView, PurchaseOrdersView, buttons
before(async () => {
  // 保留真实 Pinia、业务写入和列表刷新，只替换浏览器历史与无关展示容器。
  server = await createServer({ configFile: false, plugins: [vue(), Icons({ compiler: 'vue3' }), {
    name: 'detail-lifecycle-fixture', enforce: 'pre',
    resolveId(id) {
      if (id.endsWith('/AppButton.vue')) return '\0detail-button'
      if (id.endsWith('/WorkspaceDocumentDialog.vue')) return '\0detail-footer'
      if (['WorkspaceTable.vue', 'WorkspaceLotDialog.vue'].some(name => id.endsWith('/' + name))) return '\0detail-container'
    },
    load(id) {
      if (id.endsWith('/router/browser-router.ts')) return `
        import {createRouter,createMemoryHistory} from 'vue-router';
        import {workspaceRoutes} from '/src/renderer/src/router/workspace-routes.ts';
        export const workspaceRouter=createRouter({history:createMemoryHistory(),routes:workspaceRoutes.map(r=>({path:r.path,component:{render:()=>null}}))});`
      if (id === '\0detail-container') return 'export default {render:()=>null}'
      if (id === '\0detail-footer') return `export default {props:['show'],render(){return this.show?this.$slots.footer?.():null}}`
      if (id === '\0detail-button') return `import {h} from 'vue'; export const buttons=[];
        export default {props:['disabled'],setup(p,{attrs,slots}){return()=>{
          const children=slots.default?.()??[];
          buttons.push({label:children.map(v=>typeof v.children==='string'?v.children:'').join('').trim(),click:attrs.onClick,disabled:p.disabled});
          return h('button',attrs,children)
        }}}`
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ usePiniaAppStore: useStore } = await server.ssrLoadModule('/src/renderer/src/store/app-store.ts'))
  ;({ workspaceRouter: router } = await server.ssrLoadModule('/src/renderer/src/router/browser-router.ts'))
  ;({ routeByKey } = await server.ssrLoadModule('/src/renderer/src/router/workspace-routes.ts'))
  ;({ default: MaterialIssuesView } = await server.ssrLoadModule('/src/renderer/src/views/workspace/production/MaterialIssuesView.vue'))
  ;({ default: PurchaseOrdersView } = await server.ssrLoadModule('/src/renderer/src/views/workspace/purchase/PurchaseOrdersView.vue'))
  ;({ buttons } = await server.ssrLoadModule('\0detail-button'))
})
after(() => server?.close())

const target = { document_type: 'PurchaseOrder', document_id: 7, intent: 'execute' }
function record(type = 'PurchaseOrder', executed = false) {
  // 历史必须与服务端版本一致，避免用不合法快照绕过真实响应校验。
  const events = ['submit', 'approve', ...(executed ? ['execute'] : [])].map((action, i) => ({
    id: i + 1, version: i + 1, generation: 1, action, step: i === 0 ? 0 : 1,
    step_name: i === 0 ? null : '批准', actor_id: 1, actor_name: '管理员', reason: '', created_at: '2026-10-12 12:00:00'
  }))
  return { ...target, document_type: type, document_no: 'DEMO-20261012-000007',
    business_status: executed ? 'confirmed' : 'draft', reversal_reason: '', summary: [], content_matches: true,
    version: events.length, status: executed ? 'executed' : 'approved', generation: 1, current_step: 1,
    steps: [{ name: '批准', role: null }], policy_version: 1,
    submitted_by: 1, submitted_at: '2026-10-12 12:00:00',
    executed_by: executed ? 1 : null, executed_at: executed ? '2026-10-12 12:00:00' : null,
    can_submit: false, can_review: false, can_withdraw: !executed, events }
}
async function environment(t, override = async () => undefined) {
  await router.push(routeByKey('purchase').path)
  const previous = globalThis.window, calls = [], pinia = createPinia()
  const account = { id: 1, roles: ['admin'], permissions: ['inventory.view', 'production.view', 'purchase_order.confirm', 'material_issue.post'] }
  let executed = false
  globalThis.window = { nexora: { callApi: async (action, input) => {
    calls.push([action, input])
    const custom = await override(action, input)
    if (custom !== undefined) return custom
    if (action === 'me') return account
    if (action === 'documentNumbering') return { configured: true, locked: true, version: 1 }
    if (action === 'documentApproval') return record(input.document_type, executed)
    if (action === 'confirmPurchaseOrder') { executed = true; return {} }
    if (action === 'purchaseOrders') return [{ id: 7, status: executed ? 'confirmed' : 'draft', lines: [], approval: record('PurchaseOrder', executed) }]
    return []
  } } }
  const store = useStore(pinia)
  store.user = account; store.server = { id: 'instance-a', fingerprint: 'a' }
  t.after(() => { store.$dispose(); globalThis.window = previous })
  return { store, pinia, calls }
}

test('同号不同类型不能定位为当前详情，正确类型仍可定位', () => {
  const rows = [{ id: 7 }, { id: 8 }]
  assert.equal(findDocumentApprovalItem(target, 'MaterialIssue', rows), null)
  assert.equal(findDocumentApprovalItem(null, 'PurchaseOrder', rows), null)
  assert.equal(findDocumentApprovalItem({ ...target, document_id: 9 }, 'PurchaseOrder', rows), null)
  assert.equal(findDocumentApprovalItem(target, 'PurchaseOrder', rows), rows[0])
})

test('真实领料页拒绝工单同号页脚，创建领料导航后清理旧详情并保留草稿', async t => {
  const { store, pinia, calls } = await environment(t)
  await router.push(routeByKey('workOrders').path)
  const workTarget = { ...target, document_type: 'WorkOrder' }
  assert.equal(await store.openDocumentApproval(workTarget), true)
  store.workOrders = [{ id: 7, status: 'released', lines: [{ id: 71, remaining_quantity: '3' }] }]
  store.materialIssues = [{ id: 7, status: 'draft', approval: { status: 'approved' }, lines: [] }]
  async function render() {
    buttons.length = 0
    await renderToString(createSSRApp({ render: () => h(MaterialIssuesView) }).use(pinia))
  }
  await render()
  assert.equal(buttons.some(button => button.label === '确认领料'), false)
  // 同一页面改为合法领料目标时，真实按钮绑定仍使用该单据 ID。
  store.documentApprovalTarget = { ...target, document_type: 'MaterialIssue' }
  store.documentApprovalRecord = record('MaterialIssue')
  await render()
  const confirm = buttons.find(button => button.label === '确认领料')
  assert.ok(confirm)
  await confirm.click()
  assert.ok(calls.some(([action, input]) => action === 'postMaterialIssue' && input.issueId === 7))
  store.documentApprovalTarget = workTarget
  store.workOrders = [{ id: 7, status: 'released', lines: [{ id: 71, remaining_quantity: '3' }] }]
  const navigated = new Promise(resolve => {
    const remove = router.afterEach(() => { remove(); resolve() })
  })
  store.selectIssueOrder(7)
  await navigated
  assert.equal(router.currentRoute.value.path, routeByKey('materialIssues').path)
  assert.equal(store.documentApprovalTarget, null)
  assert.equal(store.documentApprovalRecord, null)
  assert.deepEqual(store.materialIssueForm.lines, [{ work_order_line_id: 71, quantity: '3' }])
})

test('真实确认订单同时更新列表和打开的审批记录，不重复全量读取', async t => {
  const { store, calls } = await environment(t)
  assert.equal(await store.openDocumentApproval(target), true)
  assert.equal(store.documentApprovalRecord.can_withdraw, true)
  calls.length = 0
  await store.confirmPurchaseOrder(7)
  assert.ok(store.purchaseOrders[0])
  assert.equal(store.purchaseOrders[0].status, 'confirmed')
  assert.equal(store.documentApprovalRecord.status, 'executed')
  assert.equal(store.documentApprovalRecord.version, 3)
  assert.equal(store.documentApprovalRecord.can_withdraw, false)
  assert.equal(calls.filter(([action]) => action === 'me').length, 1)
  assert.equal(calls.filter(([action]) => action === 'documentApproval').length, 1)
  assert.equal(store.busy, false)
})

test('写入响应丢失后重读审批，读取失败时清除旧操作权限并显示错误', async t => {
  let attempted = false, failRead = false
  const { store } = await environment(t, async (action, input) => {
    if (action === 'confirmPurchaseOrder') { attempted = true; throw Error('写入响应超时') }
    if (action === 'documentApproval') {
      if (failRead) throw Error('审批读取失败')
      return record(input.document_type, attempted)
    }
  })
  await store.openDocumentApproval(target)
  await store.confirmPurchaseOrder(7)
  assert.match(store.error, /响应超时/)
  assert.equal(store.documentApprovalRecord.status, 'executed')
  failRead = true
  await store.confirmPurchaseOrder(7)
  assert.equal(store.documentApprovalRecord, null)
  assert.match(store.documentApprovalError, /读取失败/)
  assert.equal(store.busy, false)
})

test('业务操作期间切页，迟到写入不会恢复审批或触发旧详情读取', async t => {
  let finish
  const { store, calls } = await environment(t, async action => {
    if (action === 'confirmPurchaseOrder') return new Promise(resolve => { finish = resolve })
  })
  await store.openDocumentApproval(target)
  calls.length = 0
  const writing = store.confirmPurchaseOrder(7)
  assert.equal(store.busy, true)
  await router.push(routeByKey('materialIssues').path)
  assert.equal(store.documentApprovalTarget, null)
  finish({})
  await writing
  assert.equal(store.documentApprovalRecord, null)
  assert.equal(calls.some(([action]) => action === 'documentApproval'), false)
  assert.equal(store.busy, false)
})

test('列表刷新失败仍重新核对审批，关闭后重开同号单据不接收旧操作刷新', async t => {
  let written = false
  const { store, calls } = await environment(t, async (action, input) => {
    if (action === 'confirmPurchaseOrder') { written = true; return {} }
    if (action === 'documentApproval') return record(input.document_type, written)
    if (action === 'purchaseOrders' && written) throw Error('列表刷新失败')
  })
  await store.openDocumentApproval(target)
  await store.confirmPurchaseOrder(7)
  assert.match(store.error, /列表刷新失败/)
  assert.equal(store.documentApprovalRecord.status, 'executed')
  assert.equal(store.busy, false)
  const oldRefresh = store.captureDocumentApprovalRefresh()
  store.closeDocumentApproval()
  written = false
  await store.openDocumentApproval(target)
  calls.length = 0
  assert.equal(await oldRefresh(), false)
  assert.equal(calls.length, 0)
  assert.equal(store.documentApprovalRecord.status, 'approved')
})

test('失败导航保留当前详情，成功导航阻止在途审批读取恢复弹窗', async t => {
  let finish, delay = false
  const { store } = await environment(t, async action => {
    if (delay && action === 'documentApproval') return new Promise(resolve => { finish = resolve })
  })
  await store.openDocumentApproval(target)
  const remove = router.beforeEach(() => false)
  await router.push(routeByKey('materialIssues').path)
  assert.equal(store.documentApprovalRecord.status, 'approved')
  remove()
  delay = true
  const reading = store.loadDocumentApproval()
  await nextTick()
  await router.push(routeByKey('materialIssues').path)
  finish(record())
  assert.equal(await reading, false)
  assert.equal(store.documentApprovalTarget, null)
  assert.equal(store.documentApprovalRecord, null)
  assert.equal(store.documentApprovalLoading, false)
})

// 使用真实页面、公共审批弹窗、Pinia 和请求链，覆盖加载失败后重试到执行的完整入口。
test('订单详情读取成功前没有确认入口，重试成功后才可执行', async t => {
  let finishRead, failRead = false, delay = true
  const { store, pinia, calls } = await environment(t, async action => {
    if (action === 'documentApproval') {
      if (failRead) throw Error('审批读取失败')
      if (delay) return new Promise(resolve => { finishRead = resolve })
    }
  })
  store.purchaseOrders = [{ id: 7, status: 'draft', lines: [], approval: { status: 'approved' } }]
  async function render() {
    buttons.length = 0
    await renderToString(createSSRApp({ render: () => h(PurchaseOrdersView) }).use(pinia))
  }
  const opening = store.openDocumentApproval(target)
  await render()
  assert.equal(store.documentApprovalLoading, true)
  assert.equal(buttons.some(button => button.label === '确认订单'), false)
  assert.equal(buttons.find(button => button.label === '关闭').disabled, false)
  finishRead(record())
  await opening
  delay = false
  failRead = true
  assert.equal(await store.loadDocumentApproval(), false)
  await render()
  assert.equal(buttons.some(button => button.label === '确认订单'), false)
  assert.equal(calls.some(([action]) => action === 'confirmPurchaseOrder'), false)
  failRead = false
  assert.equal(await store.loadDocumentApproval(), true)
  await render()
  const confirm = buttons.find(button => button.label === '确认订单')
  assert.ok(confirm)
  assert.equal(confirm.disabled, false)
  await confirm.click()
  assert.equal(calls.filter(([action]) => action === 'confirmPurchaseOrder').length, 1)
  assert.equal(store.documentApprovalRecord.status, 'executed')
  await render()
  assert.equal(buttons.some(button => button.label === '确认订单'), false)
})

test('真实页脚在加载或断线时可关闭，保留意见并丢弃迟到响应，忙碌时仍锁定', async t => {
  let finishRead, delay = false
  const { store, pinia } = await environment(t, async action => {
    if (delay && action === 'documentApproval') return new Promise(resolve => { finishRead = resolve })
  })
  async function closeButton() {
    buttons.length = 0
    await renderToString(createSSRApp({ render: () => h(PurchaseOrdersView) }).use(pinia))
    return buttons.find(button => button.label === '关闭')
  }
  await store.openDocumentApproval(target)
  store.documentApprovalReasons['PurchaseOrder:7:execute'] = '待核对合同'
  delay = true
  const reading = store.loadDocumentApproval()
  await nextTick()
  let close = await closeButton()
  assert.equal(close.disabled, false)
  close.click()
  assert.equal(store.documentApprovalTarget, null)
  finishRead(record())
  assert.equal(await reading, false)
  assert.equal(store.documentApprovalRecord, null)
  assert.equal(store.documentApprovalReasons['PurchaseOrder:7:execute'], '待核对合同')
  delay = false
  await store.openDocumentApproval(target)
  store.busy = true
  close = await closeButton()
  assert.equal(close.disabled, true)
  close.click()
  assert.ok(store.documentApprovalTarget)
  store.busy = false
  store.connectionLost = true
  close = await closeButton()
  assert.equal(close.disabled, false)
  close.click()
  assert.equal(store.documentApprovalTarget, null)
})
