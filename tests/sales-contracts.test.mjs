import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { callBackend } from '../src/main/backend.ts'
import { createSalesActions } from '../src/renderer/src/store/modules/sales-actions.ts'

const contract = { sales_order_id: 4, status: 'confirmed', version: 1,
  current: { id: 7, version: 1, body: '合同全文', acceptance_reference: '客户签署 A',
    reason: '登记', created_by: 1, created_by_name: 'admin', created_at: '2026-10-05' }, history: [] }

test('合同 IPC 固定路径并只发送版本、正文、客户确认依据和原因', async t => {
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  const sent = []
  globalThis.fetch = async (url, options) => {
    const path = new URL(url).pathname
    if (path.endsWith('/login')) return new Response(JSON.stringify({ token: 'test', user: { id: 1 } }), { status: 200 })
    sent.push([path, options.method, options.body ? JSON.parse(options.body) : null])
    return new Response(JSON.stringify(contract), { status: 200 })
  }
  await callBackend('login', {})
  await callBackend('salesOrderContract', { orderId: 4, path: '/api/v1/users' })
  await callBackend('reviseSalesOrderContract', { orderId: 4, expected_version: 0,
    body: ' 合同全文 ', acceptance_reference: ' 客户签署 A ', reason: ' 登记 ', hidden: '不可发送' })
  assert.deepEqual(sent, [
    ['/api/v1/sales-orders/4/contract', 'GET', null],
    ['/api/v1/sales-orders/4/contract', 'POST', {
      expected_version: 0, body: '合同全文', acceptance_reference: '客户签署 A', reason: '登记'
    }]
  ])
  await assert.rejects(callBackend('salesOrderContract', { orderId: '../users' }), /记录编号无效/)
  await assert.rejects(callBackend('reviseSalesOrderContract', { orderId: 4, expected_version: -1,
    body: '正文', acceptance_reference: '签署', reason: '更正' }), /合同正文、客户确认依据或版本无效/)
  await assert.rejects(callBackend('reviseSalesOrderContract', { orderId: 4, expected_version: 1,
    body: ' ', acceptance_reference: '签署', reason: '更正' }), /合同正文、客户确认依据或版本无效/)
  assert.equal(sent.length, 2)
})

test('合同读取及登记遵循销售权限和账号会话', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  const calls = []
  globalThis.window = { nexora: { async callApi(operation, data) {
    calls.push([operation, data]); return contract
  } } }
  const state = { user: ref({ id: 2, permissions: [] }), connectionLost: ref(false),
    error: ref(''), notice: ref(''), busy: ref(false) }
  const actions = createSalesActions(state, async run => { await run() })
  assert.equal(await actions.loadSalesOrderContract(4), null)
  assert.equal(await actions.reviseSalesOrderContract(4, 0, '正文', '签署', '登记'), null)
  assert.equal(calls.length, 0)
  state.user.value.permissions = ['sales.view', 'sales_order.confirm']
  assert.equal((await actions.loadSalesOrderContract(4)).version, 1)
  assert.equal((await actions.reviseSalesOrderContract(4, 0, '正文', '签署', '登记')).version, 1)
  assert.deepEqual(calls, [
    ['salesOrderContract', { orderId: 4 }],
    ['reviseSalesOrderContract', { orderId: 4, expected_version: 0,
      body: '正文', acceptance_reference: '签署', reason: '登记' }]
  ])
})

test('合同迟到读取在账号或查看权限变化后失效', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  let resolve
  globalThis.window = { nexora: { callApi: () => new Promise(done => { resolve = done }) } }
  const state = { user: ref({ id: 2, permissions: ['sales.view'] }), connectionLost: ref(false),
    error: ref(''), notice: ref(''), busy: ref(false) }
  const actions = createSalesActions(state, async run => { await run() })
  const pending = actions.loadSalesOrderContract(4)
  state.user.value = { id: 3, permissions: ['sales.view'] }
  resolve(contract)
  assert.equal(await pending, null)
  const next = actions.loadSalesOrderContract(4)
  state.user.value = { id: 3, permissions: [] }
  resolve(contract)
  assert.equal(await next, null)
})
