import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { callBackend } from '../src/main/backend.ts'
import { createBankBalanceActions } from '../src/renderer/src/store/modules/bank-balance-actions.ts'
import { createWorkspaceRouter, installWorkspaceAccessGuard } from '../src/renderer/src/router/index.ts'
import { createMemoryHistory } from 'vue-router'
import { workspaceRoutes } from '../src/renderer/src/router/workspace-routes.ts'

test('银行余额调节页面沿用独立银行查看权限', async () => {
  const component = { render: () => null }
  const router = createWorkspaceRouter(createMemoryHistory(), Object.fromEntries(workspaceRoutes.map(route => [route.key, component])))
  let permissions = ['finance.view']
  installWorkspaceAccessGuard(router, () => permissions)
  await router.push('/workspace/bank-balance')
  assert.equal(router.currentRoute.value.name, 'home')
  permissions = ['bank_reconciliation.view']
  await router.push('/workspace/bank-balance')
  assert.equal(router.currentRoute.value.name, 'bankBalance')
})

test('IPC 只允许银行调节固定路径、严格金额、日期与成组明细', async t => {
  const originalUrl = process.env.NEXORA_API_URL
  t.after(() => {
    if (originalUrl === undefined) delete process.env.NEXORA_API_URL
    else process.env.NEXORA_API_URL = originalUrl
  })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, body: options.body })
    return Response.json({ token: 'test-token', user: { id: 1 } })
  })
  await callBackend('login', {})
  await callBackend('bankBalanceOverview', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/overview')
  await callBackend('bindBankLedgerAccount', { accountId: 2, ledger_account_id: 3,
    opening_balance: '0.00', effective_date: '2026-01-01', version: 1, reason: '期初凭据', ignored: true })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/accounts/2/binding')
  assert.equal(JSON.parse(calls.at(-1).body).ignored, undefined)
  await callBackend('bindBankLedgerAccount', { accountId: 2, ledger_account_id: 3,
    opening_balance: '10.00', effective_date: '2026-01-01', version: 1, reason: '期初凭据',
    opening_items: [{ side: 'bank', occurred_on: '2025-12-31', amount: '10.00',
      reference: 'OLD-1', description: '银行已收' }] })
  assert.equal(JSON.parse(calls.at(-1).body).opening_items[0].reference, 'OLD-1')
  const scope = { account_id: 2, as_of_date: '2026-01-31', declared_bank_closing: '-12.30' }
  await callBackend('previewBankBalance', scope)
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/preview')
  await callBackend('createBankBalanceReport', { ...scope, reason: '月末核对' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/reports')
  await callBackend('matchBankLedger', { account_id: 2, bank_line_ids: [1, 2],
    journal_line_ids: [3], reason: '合并凭据' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/ledger-matches')
  await callBackend('reverseBankLedgerMatch', { groupId: 4, reason: '核对错误' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/ledger-matches/4/reverse')
  await callBackend('clearBankOpeningItem', { openingItemId: 6, source_ids: [3], reason: '核销依据' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/opening-items/6/clearances')
  await callBackend('reverseBankOpeningClearance', { clearanceId: 7, reason: '撤销依据' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/opening-clearances/7/reverse')
  await callBackend('decideBankBalanceReport', { reportId: 5, action: 'approve', reason: '复核' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-balance/reports/5/decision')
  await assert.rejects(callBackend('bindBankLedgerAccount', { accountId: '../users', ledger_account_id: 3,
    opening_balance: '0.00', effective_date: '2026-01-01', version: 1, reason: '错误' }), /记录编号无效/)
  await assert.rejects(callBackend('previewBankBalance', { ...scope, as_of_date: '2026-02-30' }), /银行调节日期无效/)
  await assert.rejects(callBackend('previewBankBalance', { ...scope, declared_bank_closing: '1e3' }), /银行余额无效/)
  await assert.rejects(callBackend('matchBankLedger', { account_id: 2, bank_line_ids: [1, 1],
    journal_line_ids: [3], reason: '重复' }), /银行勾对明细编号无效/)
  await assert.rejects(callBackend('clearBankOpeningItem', { openingItemId: 6, source_ids: [3, 3],
    reason: '重复' }), /银行勾对明细编号无效/)
  await assert.rejects(callBackend('bindBankLedgerAccount', { accountId: 2, ledger_account_id: 3,
    opening_balance: '10.00', effective_date: '2026-01-01', version: 1, reason: '错误',
    opening_items: [{ side: 'bank', occurred_on: '2026-01-01', amount: '10.00',
      reference: 'OLD-1', description: '日期错误' }] }), /银行期初未达项日期须早于启用日/)
  await assert.rejects(callBackend('decideBankBalanceReport', { reportId: 5, action: 'delete', reason: '错误' }), /复核动作无效/)
})

function state() {
  return {
    server: ref({ id: 'server-a', fingerprint: 'trusted' }),
    user: ref({ id: 1, permissions: ['bank_reconciliation.view', 'bank_reconciliation.account',
      'bank_reconciliation.match', 'bank_reconciliation.reverse', 'bank_reconciliation.reconcile', 'bank_reconciliation.review'] }),
    connectionLost: ref(false), bankBalanceOverview: ref(null), bankBalancePreview: ref(null),
    bankBindingForm: ref({ accountId: 2, ledger_account_id: 3, opening_balance: '100.00',
      effective_date: '2026-01-01', version: 1, reason: '核对', opening_items: [] }),
    bankBalanceForm: ref({ account_id: 2, as_of_date: '2026-01-31', declared_bank_closing: '110.00', reason: '月末' }),
    bankLedgerMatchForm: ref({ account_id: 2, bank_line_ids: [4], journal_line_ids: [5], reason: '凭据' }),
    bankLedgerReverseReasons: ref({ 7: '撤销原因' }), bankReportDecisionReasons: ref({ 8: '复核依据' }),
    bankOpeningClearanceForm: ref({ opening_item_id: 0, source_ids: [], reason: '' }),
    bankOpeningReverseReasons: ref({})
  }
}

test('调节草稿只接受当前预览，成功后清理；换号后旧响应不得恢复证据', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const calls = []
  globalThis.window = { nexora: { async callApi(action, payload) {
    calls.push([action, structuredClone(payload)])
    return action === 'previewBankBalance' ? { balanced: true, fingerprint: 'current' } : {}
  } } }
  const current = state()
  const actions = createBankBalanceActions(current, async action => { await action() })
  await actions.previewBankBalance()
  assert.equal(current.bankBalancePreview.value.fingerprint, 'current')
  current.bankBalanceForm.value.as_of_date = '2026-02-28'
  await actions.createBankBalanceReport()
  assert.deepEqual(calls.map(item => item[0]), ['previewBankBalance'])
  current.bankBalanceForm.value.as_of_date = '2026-01-31'
  await actions.createBankBalanceReport()
  assert.equal(current.bankBalancePreview.value, null)
  assert.equal(current.bankBalanceForm.value.reason, '')
  assert.deepEqual(calls.map(item => item[0]), ['previewBankBalance', 'createBankBalanceReport'])

  let finish
  globalThis.window = { nexora: { callApi: () => new Promise(resolve => { finish = resolve }) } }
  const pending = actions.previewBankBalance()
  current.user.value = { id: 2, permissions: ['bank_reconciliation.view'] }
  assert.equal(current.bankBalancePreview.value, null)
  finish({ balanced: true, fingerprint: 'old' })
  await pending
  assert.equal(current.bankBalancePreview.value, null)
  assert.equal(current.bankLedgerMatchForm.value.bank_line_ids.length, 0)
})

test('期初核销失败保留输入，换号后迟到成功不清除新账号草稿', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const current = state()
  current.bankOpeningClearanceForm.value = { opening_item_id: 9, source_ids: [4], reason: '核对凭据' }
  globalThis.window = { nexora: { callApi: async () => { throw new Error('来源已被占用') } } }
  const actions = createBankBalanceActions(current, async action => {
    try { await action() } catch {}
  })
  await actions.clearBankOpeningItem()
  assert.deepEqual(current.bankOpeningClearanceForm.value,
    { opening_item_id: 9, source_ids: [4], reason: '核对凭据' })

  let finish
  globalThis.window = { nexora: { callApi: () => new Promise(resolve => { finish = resolve }) } }
  const pending = actions.clearBankOpeningItem()
  current.user.value = { id: 2, permissions: ['bank_reconciliation.match'] }
  current.bankOpeningClearanceForm.value = { opening_item_id: 10, source_ids: [5], reason: '新账号依据' }
  finish({ id: 1 })
  await pending
  assert.deepEqual(current.bankOpeningClearanceForm.value,
    { opening_item_id: 10, source_ids: [5], reason: '新账号依据' })
})
