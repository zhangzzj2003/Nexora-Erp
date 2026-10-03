import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { callBackend } from '../src/main/backend.ts'
import { createBankReconciliationActions } from '../src/renderer/src/store/modules/bank-reconciliation-actions.ts'
import { createWorkspaceRouter, installWorkspaceAccessGuard } from '../src/renderer/src/router/index.ts'
import { createMemoryHistory } from 'vue-router'
import { workspaceRoutes } from '../src/renderer/src/router/workspace-routes.ts'

test('银行勾对入口只允许独立查看权限', async () => {
  const component = { render: () => null }
  const router = createWorkspaceRouter(createMemoryHistory(), Object.fromEntries(workspaceRoutes.map(route => [route.key, component])))
  let permissions = ['finance.view']
  installWorkspaceAccessGuard(router, () => permissions)
  await router.push('/workspace/bank-reconciliation')
  assert.equal(router.currentRoute.value.name, 'home')
  permissions = ['bank_reconciliation.view']
  await router.push('/workspace/bank-reconciliation')
  assert.equal(router.currentRoute.value.name, 'bankReconciliation')
})

test('银行写操作失败保留草稿和撤销原因，成功后清空', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const calls = []
  let fail = true
  globalThis.window = { nexora: { async callApi(action, payload) {
    calls.push([action, structuredClone(payload)])
    if (fail) throw Error('写入失败')
  } } }
  const state = {
    server: ref({ id: 'server-a', fingerprint: 'trusted' }),
    user: ref({ id: 1, permissions: ['bank_reconciliation.account', 'bank_reconciliation.record', 'bank_reconciliation.match', 'bank_reconciliation.reverse'] }),
    connectionLost: ref(false),
    bankOverview: ref(null),
    bankAccountForm: ref({ code: 'MAIN', name: '基本户' }),
    bankCsvForm: ref({ account_id: 2, file_name: 'bank.csv', content_base64: 'YQ==' }),
    bankCsvPreview: ref(null),
    bankLineForm: ref({ account_id: 2, transaction_id: 'T-1', occurred_on: '2026-10-03', amount: '10.00', counterparty: '', note: '' }),
    bankMatchForm: ref({ statement_line_id: 3, source_type: 'order_payment', source_id: 4, reason: '流水原件' }),
    bankReverseReasons: ref({ 5: '关联错误' })
  }
  const actions = createBankReconciliationActions(state, async action => {
    try { await action() } catch { /* 测试失败路径与真实 perform 的保留行为 */ }
  })
  await actions.createBankAccount()
  await actions.importBankLine()
  await actions.matchBankLine()
  await actions.reverseBankMatch(5)
  assert.equal(state.bankAccountForm.value.code, 'MAIN')
  assert.equal(state.bankLineForm.value.transaction_id, 'T-1')
  assert.equal(state.bankMatchForm.value.source_id, 4)
  assert.equal(state.bankReverseReasons.value[5], '关联错误')
  fail = false
  await actions.createBankAccount()
  await actions.importBankLine()
  await actions.matchBankLine()
  await actions.reverseBankMatch(5)
  assert.equal(state.bankAccountForm.value.code, '')
  assert.equal(state.bankLineForm.value.transaction_id, '')
  assert.equal(state.bankMatchForm.value.source_id, 0)
  assert.equal(state.bankReverseReasons.value[5], undefined)
  assert.deepEqual(calls.slice(0, 4).map(item => item[0]),
    ['createBankAccount', 'importBankLines', 'matchBankLine', 'reverseBankMatch'])
  assert.deepEqual(calls[1][1], { account_id: 2, lines: [{ transaction_id: 'T-1', occurred_on: '2026-10-03', amount: '10.00', counterparty: '', note: '' }] })
})

test('切换账号后清除银行快照，旧写入返回不能覆盖新账号草稿', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  let finish
  globalThis.window = { nexora: { callApi: () => new Promise(resolve => { finish = resolve }) } }
  const state = {
    server: ref({ id: 'server-a', fingerprint: 'trusted' }),
    user: ref({ id: 1, permissions: ['bank_reconciliation.account'] }),
    connectionLost: ref(false), bankOverview: ref({ accounts: [{ id: 1 }] }),
    bankAccountForm: ref({ code: 'OLD', name: '旧账户' }),
    bankCsvForm: ref({ account_id: 1, file_name: 'old.csv', content_base64: 'YQ==' }),
    bankCsvPreview: ref(null),
    bankLineForm: ref({ account_id: 1, transaction_id: 'OLD', occurred_on: '', amount: '', counterparty: '', note: '' }),
    bankMatchForm: ref({ statement_line_id: 1, source_type: 'order_payment', source_id: 1, reason: '旧' }),
    bankReverseReasons: ref({ 1: '旧原因' })
  }
  const actions = createBankReconciliationActions(state, async action => { await action() })
  const pending = actions.createBankAccount()
  state.user.value = { id: 2, permissions: ['bank_reconciliation.account'] }
  assert.equal(state.bankOverview.value, null)
  assert.equal(state.bankAccountForm.value.code, '')
  assert.equal(state.bankCsvForm.value.file_name, '')
  state.bankAccountForm.value = { code: 'NEW', name: '新账户' }
  finish({})
  await pending
  assert.equal(state.bankAccountForm.value.code, 'NEW')
  assert.deepEqual(state.bankReverseReasons.value, {})
})

test('主进程固定银行接口并拒绝无效金额、来源和路径编号', async t => {
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
  await callBackend('bankReconciliationOverview', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-reconciliation/overview')
  await callBackend('createBankAccount', { code: 'MAIN', name: '基本户', extra: 'ignored' })
  assert.deepEqual(JSON.parse(calls.at(-1).body), { code: 'MAIN', name: '基本户' })
  const goodLine = { transaction_id: 'T-1', occurred_on: '2026-10-03', amount: '-10.00', counterparty: '', note: '' }
  await callBackend('importBankLines', { account_id: 2, lines: [goodLine] })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-reconciliation/lines/import')
  await callBackend('previewBankCsv', { account_id: 2, file_name: 'bank.csv', content_base64: 'YQ==' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-reconciliation/imports/csv/preview')
  await callBackend('importBankCsv', { account_id: 2, file_name: 'bank.csv', content_base64: 'YQ==' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-reconciliation/imports/csv')
  await assert.rejects(callBackend('importBankCsv', { account_id: 2, file_name: '../bank.csv', content_base64: 'YQ==' }), /CSV 文件名无效/)
  await assert.rejects(callBackend('importBankCsv', { account_id: 2, file_name: 'bank.csv', content_base64: 'invalid!' }), /CSV 文件内容无效/)
  await assert.rejects(callBackend('importBankLines', { account_id: 2, lines: [{ ...goodLine, amount: '1e2' }] }), /银行金额无效/)
  await assert.rejects(callBackend('importBankLines', { account_id: 2, lines: [goodLine, goodLine] }), /同批银行交易号不能重复/)
  await assert.rejects(callBackend('matchBankLine', { statement_line_id: 3, source_type: 'other', source_id: 4, reason: '错误' }), /收付款来源无效/)
  await callBackend('matchBankLine', { statement_line_id: 3, source_type: 'order_payment', source_id: 4, reason: '流水原件' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-reconciliation/matches')
  await assert.rejects(callBackend('reverseBankMatch', { matchId: '../users', reason: '错误' }), /记录编号无效/)
  await callBackend('reverseBankMatch', { matchId: 5, reason: '关联错误', extra: 'ignored' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/bank-reconciliation/matches/5/reverse')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { reason: '关联错误' })
})

test('CSV 预检绑定当前草稿，导入成功后清除文件', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const calls = []
  globalThis.window = { nexora: { async callApi(action, payload) {
    calls.push([action, structuredClone(payload)])
    return action === 'previewBankCsv' ? { can_import: true, sha256: 'digest', row_count: 1 } : {}
  } } }
  const state = {
    server: ref({ id: 'server-a', fingerprint: 'trusted' }),
    user: ref({ id: 1, permissions: ['bank_reconciliation.record'] }),
    connectionLost: ref(false), bankOverview: ref(null),
    bankAccountForm: ref({ code: '', name: '' }),
    bankCsvForm: ref({ account_id: 2, file_name: 'bank.csv', content_base64: 'YQ==' }),
    bankCsvPreview: ref(null),
    bankLineForm: ref({ account_id: 0, transaction_id: '', occurred_on: '', amount: '', counterparty: '', note: '' }),
    bankMatchForm: ref({ statement_line_id: 0, source_type: 'order_payment', source_id: 0, reason: '' }),
    bankReverseReasons: ref({})
  }
  const actions = createBankReconciliationActions(state, async action => { await action() })
  await actions.previewBankCsv()
  assert.equal(state.bankCsvPreview.value.can_import, true)
  state.bankCsvForm.value = { ...state.bankCsvForm.value, account_id: 3 }
  await actions.importBankCsv()
  assert.deepEqual(calls.map(item => item[0]), ['previewBankCsv'])
  state.bankCsvForm.value = { ...state.bankCsvForm.value, account_id: 2 }
  await actions.importBankCsv()
  assert.equal(state.bankCsvForm.value.file_name, '')
  assert.equal(state.bankCsvPreview.value, null)
  assert.deepEqual(calls.map(item => item[0]), ['previewBankCsv', 'importBankCsv'])
})
