import assert from 'node:assert/strict'
import { test } from 'node:test'
import { toRaw } from 'vue'
import { createMemoryHistory } from 'vue-router'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createLedgerActions } from '../src/renderer/src/store/modules/ledger-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { createWorkspaceRouter, installWorkspaceAccessGuard } from '../src/renderer/src/router/index.ts'
import { workspaceRoutes, visibleRouteGroups } from '../src/renderer/src/router/workspace-routes.ts'
import { callBackend } from '../src/main/backend.ts'

test('总账科目和期间分别授权，管理权限不能代替查看权限', async () => {
  const routes = visibleRouteGroups(['ledger_account.view', 'accounting_period.view'])
    .find(group => group.key === 'finance').routes
  assert.deepEqual(routes.map(route => route.key), ['ledgerAccounts', 'accountingPeriods'])
  const router = createWorkspaceRouter(createMemoryHistory(), Object.fromEntries(workspaceRoutes.map(route => [route.key, { render: () => null }])))
  let permissions = ['ledger_account.view', 'accounting_period.view']
  installWorkspaceAccessGuard(router, () => permissions)
  for (const route of routes) { await router.push(route.path); assert.equal(router.currentRoute.value.name, route.key) }
  permissions = ['ledger_account.manage', 'accounting_period.manage']
  await router.push('/workspace/home')
  for (const route of routes) { await router.push(route.path); assert.equal(router.currentRoute.value.name, 'home') }
})

test('编辑只提交名称启停和旧版本，冲突保留草稿；创建成功清空', async t => {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  const state = createAppState()
  const calls = []
  let fail = true
  globalThis.window = { nexora: { async callApi(action, input) {
    calls.push([action, structuredClone(input)])
    if (fail) throw new Error('版本冲突')
  } } }
  const actions = createLedgerActions(state, async action => {
    try { await action() } catch (error) { state.error.value = error.message }
  })
  actions.editLedgerAccount({ id: 4, code: '1001', name: '现金', category: 'asset', normal_balance: 'debit', is_active: true, version: 7, created_by: 1, created_at: 'date' })
  state.ledgerAccountForm.value.name = '改名'
  state.ledgerAccountForm.value.reason = '核对科目'
  const draft = structuredClone(toRaw(state.ledgerAccountForm.value))
  assert.equal(await actions.saveLedgerAccount(), false)
  assert.deepEqual(state.ledgerAccountForm.value, draft)
  assert.deepEqual(calls[0], ['updateLedgerAccount', { id: 4, version: 7, name: '改名', is_active: true, reason: '核对科目' }])
  fail = false
  assert.equal(await actions.saveLedgerAccount(), true)
  assert.equal(state.ledgerAccountForm.value.id, null)
  actions.editAccountingPeriod({ id: 9, code: '2026-01', name: '一月', start_date: '2026-01-01', end_date: '2026-01-31', status: 'open', version: 2 })
  state.accountingPeriodForm.value.name = '首月'
  state.accountingPeriodForm.value.reason = '更正'
  fail = true
  assert.equal(await actions.saveAccountingPeriod(), false)
  assert.equal(state.accountingPeriodForm.value.version, 2)
  assert.deepEqual(calls.at(-1), ['updateAccountingPeriod', { id: 9, version: 2, name: '首月', reason: '更正' }])
  fail = false
  actions.editLedgerAccount()
  Object.assign(state.ledgerAccountForm.value, { code: '1002', name: '银行', reason: '科目表' })
  assert.equal(await actions.saveLedgerAccount(), true)
  assert.deepEqual(calls.at(-1), ['createLedgerAccount', { code: '1002', name: '银行', category: 'asset', normal_balance: 'debit', reason: '科目表' }])
})

test('授权撤销时先清理旧科目和期间，即使其他业务读取失败', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState()
  state.user.value = { permissions: ['ledger_account.view', 'accounting_period.view'] }
  state.ledgerAccounts.value = [{ id: 1 }]; state.accountingPeriods.value = [{ id: 1 }]
  globalThis.window = { nexora: { async callApi(action) {
    if (action === 'documentNumbering') return { configured: true };
    if (action === 'me') return { permissions: ['inventory.view'] }
    if (action === 'materials') throw new Error('其他模块失败')
    return []
  } } }
  const { refreshData } = createDataLoader(state, code => state.user.value.permissions.includes(code), () => {})
  await assert.rejects(refreshData(), /其他模块失败/)
  assert.deepEqual(state.ledgerAccounts.value, [])
  assert.deepEqual(state.accountingPeriods.value, [])
})

test('总账 IPC 限定固定路径及修改字段，拒绝路径注入', async t => {
  const previous = process.env.NEXORA_API_URL
  t.after(() => { if (previous === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = previous })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test-token', user: { id: 1 } } : [])
  })
  await callBackend('login', {})
  for (const [action,path] of [['ledgerAccounts','ledger-accounts'],['accountingPeriods','accounting-periods']]) {
    await callBackend(action, undefined)
    assert.equal(calls.at(-1).path, '/api/v1/finance/'+path)
  }
  await callBackend('updateLedgerAccount', { id: 4, version: 2, name: '现金', is_active: false, reason: '停用', code: '禁止修改' })
  assert.equal(calls.at(-1).path, '/api/v1/finance/ledger-accounts/4')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { name: '现金', is_active: false, version: 2, reason: '停用' })
  await callBackend('updateAccountingPeriod', { id: 9, version: 1, name: '首月', reason: '改名', end_date: '禁止修改' })
  assert.deepEqual(JSON.parse(calls.at(-1).body), { name: '首月', version: 1, reason: '改名' })
  await callBackend('ledgerAccountChanges', { id: 4 })
  assert.equal(calls.at(-1).path, '/api/v1/finance/ledger-accounts/4/changes')
  await callBackend('accountingPeriodChanges', { id: 9 })
  assert.equal(calls.at(-1).path, '/api/v1/finance/accounting-periods/9/changes')
  for (const action of ['updateLedgerAccount','updateAccountingPeriod','ledgerAccountChanges','accountingPeriodChanges'])
    await assert.rejects(callBackend(action, { id: '../users' }), /记录编号无效/)
})
