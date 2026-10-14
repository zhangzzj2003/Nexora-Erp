import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createStockOverviewActions } from '../src/renderer/src/store/modules/stock-overview-actions.ts'
import { createInventoryReportActions } from '../src/renderer/src/store/modules/inventory-report-actions.ts'
import { createReportActions } from '../src/renderer/src/store/modules/report-actions.ts'
import { callBackend } from '../src/main/backend.ts'

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const stockPage = (page = 1, page_size = 20) => ({ items: [{ id: page, sku: 'EL-1', name: '电阻', unit: '个', quantity: '0.001', total_quantity: '0.001', category_code: 'EL-SR', category_group_name: '电子类', category_name: '电子类 / 电阻', warehouses: [] }], total: 65, page, page_size,
  summary: { material_count: 65, posted_receipt_count: 5, movement_count: 90, positive_material_count: 1, zero_material_count: 64, negative_material_count: 0 } })
const reportPage = (page = 1, page_size = 20) => ({ kind: 'inventory_balance', rows: [{ quantity: '0.001' }], columns: [], total: 65, page, page_size })
function setup(t, createActions) {
  const old = globalThis.window, scope = effectScope()
  t.after(() => { scope.stop(); globalThis.window = old })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['inventory.view', 'inventory_report.view'] }
  return { state, actions: scope.run(() => createActions(state)) }
}

// 两种页面都要传递目标页、重置筛选，并拒绝旧请求覆盖新分页结果。
for (const [label, prefix, method, operation, factory, pageResult] of [
  ['库存总览', 'stockOverview', 'queryStockOverview', 'queryStock', createStockOverviewActions, stockPage],
  ['库存报表', 'inventoryReport', 'queryInventoryReport', 'queryInventoryReport', createInventoryReportActions, reportPage]
]) {
  test(`${label}真实服务端分页、筛选重置和失败重试`, async t => {
    const { state, actions } = setup(t, factory)
    const calls = []; let fail = false
    globalThis.window = { nexora: { async callApi(op, input) {
      calls.push([op, structuredClone(input)]); if (fail) throw Error('查询失败')
      return pageResult(Math.min(input.page, 3), input.page_size)
    } } }
    await actions[method](2)
    assert.equal(calls[0][0], operation)
    assert.equal(calls[0][1].page, 2)
    assert.equal(calls[0][1].page_size, 20)
    assert.equal(state[prefix + 'Result'].value.total, 65)
    // 同账号例行刷新不改变分页快照，避免登录或全局刷新期间出现空表。
    state.user.value = { ...state.user.value }
    assert.equal(state[prefix + 'Result'].value.total, 65)
    await actions[method](5, 10)
    assert.equal(calls[1][1].page, 1)
    assert.equal(calls[1][1].page_size, 10)
    await actions[method](99)
    assert.equal(state[prefix + 'Query'].value.page, 3)
    state[prefix + 'Query'].value.warehouse_id = 2
    assert.equal(state[prefix + 'Query'].value.page, 1)
    assert.equal(state[prefix + 'Result'].value, null)
    fail = true
    await actions[method](2)
    assert.equal(state[prefix + 'Error'].value, '查询失败')
    assert.equal(state[prefix + 'Result'].value, null)
    assert.equal(state[prefix + 'Loading'].value, false)
    fail = false
    await actions[method](state[prefix + 'Query'].value.page)
    assert.equal(state[prefix + 'Error'].value, '')
    assert.equal(state[prefix + 'Result'].value.page, 2)
    assert.equal(calls.at(-1)[1].warehouse_id, 2)
    state.server.value = { id: 'another-instance' }
    assert.equal(state[prefix + 'Result'].value, null)
  })
  test(`${label}丢弃慢响应、变更筛选和退出后的晚到响应`, async t => {
    const { state, actions } = setup(t, factory)
    const pending = [deferred(), deferred(), deferred(), deferred()]; let index = 0
    globalThis.window = { nexora: { callApi() { return pending[index++].promise } } }
    const first = actions[method](1), second = actions[method](2)
    pending[0].resolve(pageResult(1)); await first
    assert.equal(state[prefix + 'Loading'].value, true)
    pending[1].resolve(pageResult(2)); await second
    assert.equal(state[prefix + 'Result'].value.page, 2)
    const third = actions[method](3)
    state[prefix + 'Query'].value.warehouse_id = 3
    pending[2].resolve(pageResult(3)); await third
    assert.equal(state[prefix + 'Result'].value, null)
    const fourth = actions[method]()
    state.user.value = null
    pending[3].resolve(pageResult()); await fourth
    assert.equal(state[prefix + 'Result'].value, null)
    await actions[method]()
    assert.equal(index, 4)
  })
}

test('库存 CSV 导出请求不带页码，并保存完整筛选结果；取消不误报成功', async t => {
  const { state, actions } = setup(t, createInventoryReportActions)
  const calls = [], saved = []; let accept = true
  globalThis.window = { nexora: {
    async callApi(op, input) { calls.push([op, structuredClone(input)]); return op === 'queryInventoryReport' ? reportPage(2) : { kind: 'inventory_balance', csv: '完整筛选全部行' } },
    async saveReportCsv(name, csv) { saved.push([name, csv]); return accept }
  } }
  state.inventoryReportQuery.value.warehouse_id = 2
  await actions.queryInventoryReport(2)
  await actions.exportInventoryReport()
  assert.equal(calls.at(-1)[0], 'queryReport')
  assert.equal(calls.at(-1)[1].warehouse_id, 2)
  assert.equal('page' in calls.at(-1)[1], false)
  assert.equal('page_size' in calls.at(-1)[1], false)
  assert.equal(saved[0][1], '完整筛选全部行')
  assert.equal(state.notice.value, '完整筛选结果 CSV 已保存。')
  state.notice.value = ''; accept = false
  await actions.exportInventoryReport()
  assert.equal(state.notice.value, '')
})

test('库存导出失败可重试，筛选和会话改变后不能弹出旧结果保存框', async t => {
  const { state, actions } = setup(t, createInventoryReportActions)
  let pending = deferred(), saves = 0
  globalThis.window = { nexora: {
    callApi: async op => op === 'queryInventoryReport' ? reportPage() : pending.promise,
    saveReportCsv: async () => { saves++; return true }
  } }
  await actions.queryInventoryReport()
  const failed = actions.exportInventoryReport()
  pending.reject(Error('导出失败')); await failed
  assert.equal(state.inventoryReportError.value, '导出失败')
  assert.equal(state.inventoryReportExporting.value, false)
  pending = deferred()
  const old = actions.exportInventoryReport()
  state.inventoryReportQuery.value.kind = 'stock_flow'
  pending.resolve({ kind: 'inventory_balance', csv: '旧查询' }); await old
  assert.equal(saves, 0)
  await actions.queryInventoryReport()
  pending = deferred()
  const disconnected = actions.exportInventoryReport()
  state.connectionLost.value = true
  pending.resolve({ kind: 'stock_flow', csv: '旧会话' }); await disconnected
  assert.equal(saves, 0)
})

test('采购报表继续保存查询快照中的 CSV，不受库存分页改动影响', async t => {
  const { state } = setup(t, createInventoryReportActions)
  const calls = [], saved = []
  globalThis.window = { nexora: { callApi: async (op, input) => { calls.push([op, input]); return { kind: 'purchase_requests', rows: [], columns: [], csv: '采购快照' } },
    saveReportCsv: async (name, csv) => { saved.push(csv); return true } } }
  const actions = createReportActions(state, async (action, message) => { await action(); state.notice.value = message })
  await actions.queryPurchaseReport(); await actions.exportPurchaseReport()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].kind, 'purchase_requests')
  assert.deepEqual(saved, ['采购快照'])
})

test('库存总览与报表的桌面桥接转发到固定分页接口', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push([url.pathname, options.method, JSON.parse(options.body)])
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test', user: { id: 1 } } : {})
  })
  await callBackend('login', {})
  for (const [operation, path, input] of [
    ['queryStock', '/api/v1/stock/query', { warehouse_id: 2, page: 3, page_size: 10 }],
    ['queryInventoryReport', '/api/v1/reports/inventory/query', { kind: 'stock_flow', warehouse_id: 1, page: 2, page_size: 10 }]
  ]) {
    await callBackend(operation, input)
    assert.deepEqual(calls.at(-1), [path, 'POST', input])
  }
})
