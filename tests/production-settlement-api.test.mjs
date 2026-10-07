import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateProductionSettlementResponse } from '../src/shared/production-settlement-api.ts'
import { callBackend } from '../src/main/backend.ts'

// 草稿、正式结算和归档均须校验原生版本；批准投影不能代替执行信息。
test('成本结算拒绝伪造执行状态与无效版本', () => {
  const row = { work_order_id: 1, material_amount: '1.00', accepted_quantity: '1', status: 'draft', version: 1,
    executed_at: null, executed_by: null, cancelled_at: null, cancelled_by: null, cancellation_reason: '' }
  validateProductionSettlementResponse({ settlements: [row] })
  for (const change of [{version: true}, {version: 0}, {status: 'posted'}, {executed_at: '2026-10-07'}, {cancelled_by: 1}, {status: 'cancelled'}]) {
    assert.throws(() => validateProductionSettlementResponse({...row, ...change}))
  }
  validateProductionSettlementResponse({...row, status: 'active', executed_at: '2026-10-07T10:00:00Z', executed_by: 1})
  // 历史固定快照没有原生状态，不补造执行信息。
  validateProductionSettlementResponse({evidence: {work_order_id: 1, material_amount: '1.00', accepted_quantity: '1'}})
})

test('成本结算 IPC 保留业务正文并固定版本执行地址', async t => {
  const old = globalThis.fetch; t.after(() => {globalThis.fetch = old}); const calls = []
  globalThis.fetch = async (url, config) => {
    calls.push([new URL(url).pathname, JSON.parse(config.body)])
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login') ? {token: 'test', user: {id: 1}} : {}),
      {status: 200, headers: {'Content-Type': 'application/json'}})
  }
  await callBackend('login', {}); calls.length = 0
  const draft = {work_order_id: 1, reference: 'COST', note: '复核'}
  await callBackend('settleProductionCost', {...draft, status: 'active', document_no: 'FAKE', total_amount: '99'})
  await callBackend('changeProductionSettlementStatus', {id: 7, version: 3, action: 'post', reason: ' 核对分摊 ', approved_by: 1})
  assert.deepEqual(calls, [['/api/v1/production-costs/settlements', draft], ['/api/v1/production-costs/settlements/7/post', {version: 3, reason: '核对分摊'}]])
  for (const change of [{id: '../users'}, {version: true}, {version: 0}, {action: 'reverse'}, {reason: ' '}, {reason: '字'.repeat(201)}]) {
    await assert.rejects(callBackend('changeProductionSettlementStatus', {id: 7, version: 3, action: 'post', reason: '核对', ...change}))
  }
  assert.equal(calls.length, 2)
})
