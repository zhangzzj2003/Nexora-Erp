import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createInventoryLedgerActions } from '../src/renderer/src/store/modules/inventory-ledger-actions.ts'
import { callBackend } from '../src/main/backend.ts'

const result = (page = 1, pageSize = 20) => ({ rows: [{ id: page }], groups: [{ opening_quantity: '10' }], total: 65, page, page_size: pageSize })
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
function setup(t) {
  const old = globalThis.window
  const scope = effectScope()
  t.after(() => { scope.stop(); globalThis.window = old })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['inventory.view'] }
  const actions = scope.run(() => createInventoryLedgerActions(state))
  return { state, actions }
}

// 使用真实 Pinia 状态与查询操作，验证翻页请求和返回元数据共同驱动页面。
test('台账翻页只请求目标页，每页条数和筛选变化回首页', async t => {
  const { state, actions } = setup(t)
  const calls = []
  globalThis.window = { nexora: { async callApi(operation, input) {
    calls.push([operation, structuredClone(input)])
    return result(input.page, input.page_size)
  } } }
  await actions.queryLedger(2)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'inventoryLedger')
  assert.deepEqual(calls[0][1], { page: 2, page_size: 20, warehouse_id: null, material_id: null, from_date: null, to_date: null, source_type: null })
  assert.equal(state.ledgerResult.value.rows[0].id, 2)
  // 常规权限刷新会替换用户对象，同身份和权限不应清空已查询的页。
  state.user.value = { ...state.user.value }
  assert.equal(state.ledgerResult.value.rows[0].id, 2)
  await actions.queryLedger(3, 10)
  assert.equal(calls[1][1].page, 1)
  assert.equal(calls[1][1].page_size, 10)
  await actions.queryLedger(3)
  state.ledgerQuery.value.warehouse_id = 2
  assert.equal(state.ledgerQuery.value.page, 1)
  assert.equal(state.ledgerQuery.value.page_size, 10)
  assert.deepEqual(state.ledgerResult.value.rows, [])
  await actions.queryLedger()
  assert.equal(calls.at(-1)[1].warehouse_id, 2)
  assert.equal(calls.at(-1)[1].page, 1)
  state.server.value = { id: 'another-instance' }
  assert.deepEqual(state.ledgerResult.value.rows, [])
})

test('台账末页回退采用服务端页码，失败隐藏旧结果并保留目标页重试', async t => {
  const { state, actions } = setup(t)
  let fail = false
  globalThis.window = { nexora: { async callApi() { if (fail) throw Error('查询失败'); return result(2) } } }
  await actions.queryLedger(99)
  assert.equal(state.ledgerQuery.value.page, 2)
  fail = true
  await actions.queryLedger(3)
  assert.equal(state.ledgerQuery.value.page, 3)
  assert.equal(state.ledgerError.value, '查询失败')
  assert.equal(state.ledgerLoading.value, false)
  assert.deepEqual(state.ledgerResult.value.rows, [])
  assert.deepEqual(state.ledgerResult.value.groups, [])
  fail = false
  await actions.queryLedger(state.ledgerQuery.value.page)
  assert.equal(state.ledgerError.value, '')
  assert.equal(state.ledgerResult.value.total, 65)
})

test('台账慢响应不能覆盖新页面，筛选和会话变化使旧请求失效', async t => {
  const { state, actions } = setup(t)
  const pending = [deferred(), deferred(), deferred(), deferred()]
  let index = 0
  globalThis.window = { nexora: { callApi() { return pending[index++].promise } } }
  const first = actions.queryLedger(1)
  const second = actions.queryLedger(2)
  pending[0].resolve(result(1)); await first
  assert.equal(state.ledgerLoading.value, true)
  pending[1].resolve(result(2)); await second
  assert.equal(state.ledgerResult.value.page, 2)
  const third = actions.queryLedger(3)
  state.ledgerQuery.value.source_type = 'receipt'
  pending[2].resolve(result(3)); await third
  assert.deepEqual(state.ledgerResult.value.rows, [])
  const fourth = actions.queryLedger()
  state.user.value = null
  pending[3].resolve(result()); await fourth
  assert.deepEqual(state.ledgerResult.value.rows, [])
  await actions.queryLedger()
  assert.equal(index, 4)
})

test('断线使晚到的结果失效，旧服务端不能伪装成已分页', async t => {
  const { state, actions } = setup(t)
  const pending = deferred()
  globalThis.window = { nexora: { callApi() { return pending.promise } } }
  const request = actions.queryLedger()
  state.connectionLost.value = true
  pending.resolve(result()); await request
  assert.deepEqual(state.ledgerResult.value.rows, [])
  assert.equal(state.ledgerLoading.value, false)
  state.connectionLost.value = false
  globalThis.window.nexora.callApi = async () => ({ rows: [{ id: 1 }], groups: [] })
  await actions.queryLedger()
  assert.match(state.ledgerError.value, /升级服务端/)
  assert.deepEqual(state.ledgerResult.value.rows, [])
})

// 贯通桌面桥接：分页参数必须原样到达库存台账查询接口。
test('库存台账 IPC 传递分页与筛选参数', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push([url.pathname, options.method, JSON.parse(options.body)])
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test', user: { id: 1 } } : result(2, 10))
  })
  await callBackend('login', {})
  const input = { warehouse_id: 1, material_id: null, from_date: '2026-01-01', to_date: null, source_type: 'receipt', page: 2, page_size: 10 }
  assert.deepEqual(await callBackend('inventoryLedger', input), result(2, 10))
  assert.deepEqual(calls.at(-1), ['/api/v1/inventory-ledger/query', 'POST', input])
})
