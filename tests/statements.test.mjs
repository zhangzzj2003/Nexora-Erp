import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createStatementActions } from '../src/renderer/src/store/modules/statement-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { callBackend } from '../src/main/backend.ts'
import { compatibleStatementGroups, manualTransferIds, statementPolicyProblems, statementContributions } from '../src/renderer/src/views/workspace/finance/statement-display.ts'
import { routeByKey, canVisitRoute, resolveWorkspaceRoute } from '../src/renderer/src/router/workspace-routes.ts'

const permissions = ['financial_statement.view', 'financial_statement.configure', 'financial_statement.archive']
const policy = { version: 1, lines: [{ code: 'CASH', name: '货币资金', group: 'asset' }],
  allocations: [{ account_id: 1, line_code: 'CASH' }], manual_transfer_ids: [], reason: '公司核对' }
const query = { from_date: '2026-01-01', to_date: '2026-01-31' }
const archive = { ...query, policy_version: 1, fingerprint: 'a'.repeat(64), reason: '核对归档' }

test('财务报表独立查看权限开放入口，财务或凭证权限不替代报表授权', () => {
  const route = routeByKey('financialStatements')
  assert.equal(route.path, '/workspace/financial-statements')
  assert.equal(canVisitRoute(route, ['financial_statement.view']), true)
  assert.equal(canVisitRoute(route, ['finance.view', 'journal.view']), false)
  assert.equal(resolveWorkspaceRoute(route.path, []).key, 'home')
})

test('成本必须明确资产或费用范围，非法项目与类别不一致阻止配置保存', () => {
  assert.deepEqual(compatibleStatementGroups({ category: 'cost' }), ['asset', 'expense'])
  assert.deepEqual(compatibleStatementGroups({ category: 'income' }), ['revenue'])
  assert.deepEqual(statementPolicyProblems(policy, [{ id: 1, category: 'asset' }]), [])
  assert.match(statementPolicyProblems(policy, [{ id: 1, category: 'equity' }]).join(), /类别不一致/)
  const duplicate = { ...policy, lines: [...policy.lines, ...policy.lines] }
  assert.match(statementPolicyProblems(duplicate, [{ id: 1, category: 'asset' }]).join(), /不能重复/)
  assert.match(statementPolicyProblems({ ...policy, lines: [{ code: 'bad-code', name: '', group: 'asset' }] }, []).join(), /名称不能为空/)
})

test('手工结转编号拒绝小数、重复、零、负数、不安全整数与混合文本', () => {
  assert.deepEqual(manualTransferIds(''), [])
  assert.deepEqual(manualTransferIds('12、15，18 20'), [12, 15, 18, 20])
  for (const value of ['1.2', '1、1', '0', '-1', '9007199254740992', '记-12', '12foo', '1e2']) assert.equal(manualTransferIds(value), null, value)
})

test('未结转损益下钻使用收入减费用的字符串符号，不丢失大额金额精度', () => {
  const report = { balance_rows: [{ code: '_UNCLOSED_PROFIT', account_ids: [1, 2, 3] }], contributions: [
    { account_id: 1, group: 'revenue', line_code: 'REV', opening: '0.00', closing: '99999999999999999.12', movement: '100.00' },
    { account_id: 2, group: 'expense', line_code: 'EXP', opening: '-0.00', closing: '100.10', movement: '10.10' },
    { account_id: 3, group: 'expense', line_code: 'EXP', opening: '-1.00', closing: '-10.10', movement: '-5.10' }
  ] }
  const before = structuredClone(report)
  const result = statementContributions(report, '_UNCLOSED_PROFIT')
  assert.deepEqual(result.map(item => item.closing), ['99999999999999999.12', '-100.10', '10.10'])
  assert.deepEqual(result.map(item => item.opening), ['0.00', '0.00', '1.00'])
  assert.equal(statementContributions(report, 'REV').length, 1)
  assert.deepEqual(report, before)
})

function fixture(t, callApi, perform = action => action()) {
  const old = globalThis.window
  t.after(() => { globalThis.window = old })
  globalThis.window = { nexora: { callApi } }
  const state = createAppState()
  state.user.value = { id: 1, permissions }
  state.statementQuery.value = { ...query }
  return { state, actions: createStatementActions(state, perform) }
}

test('财务报表 IPC 固定路径并剔除客户端金额、来源、状态及嵌套额外字段', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test-token', user: { id: 1 } } : {})
  })
  await callBackend('login', {})
  for (const [operation, suffix] of [['statementOptions', '/options'], ['statementPolicyChanges', '/policy/changes'], ['statementArchives', '/archives']]) {
    await callBackend(operation, undefined)
    assert.equal(calls.at(-1).path, '/api/v1/finance/statements' + suffix)
  }
  await callBackend('statementArchiveDetail', { id: 4 })
  assert.equal(calls.at(-1).path, '/api/v1/finance/statements/archives/4')
  await assert.rejects(callBackend('statementArchiveDetail', { id: '../users' }))
  await callBackend('saveStatementPolicy', { ...policy, status: 'posted', lines: [{ ...policy.lines[0], amount: '999' }],
    allocations: [{ ...policy.allocations[0], source: 'forged' }] })
  assert.deepEqual(JSON.parse(calls.at(-1).body), policy)
  await assert.rejects(callBackend('saveStatementPolicy', { ...policy, allocations: {} }))
  await callBackend('queryStatement', { ...query, amount: '999', sources: [] })
  assert.deepEqual(JSON.parse(calls.at(-1).body), query)
  await callBackend('archiveStatement', { ...archive, snapshot: {}, csv: 'fake', amount: '999' })
  assert.deepEqual(JSON.parse(calls.at(-1).body), archive)
})

test('修改查询日期立即清除旧报表并拒绝迟到结果，切换账号清空配置与归档', async t => {
  let resolve
  const { state, actions } = fixture(t, () => new Promise(done => { resolve = done }))
  state.statementReport.value = { csv: 'old' }
  const request = actions.queryStatement()
  assert.equal(state.statementReport.value, null)
  state.statementQuery.value.to_date = '2026-02-28'
  resolve({ csv: 'late' })
  assert.equal(await request, false)
  assert.equal(state.statementReport.value, null)
  assert.equal(state.statementLoading.value, false)
  state.statementOptions.value = { policy }; state.statementPolicyChanges.value = [{ id: 1 }]
  state.statementArchives.value = [{ id: 1 }]; state.statementArchive.value = { id: 1 }
  state.user.value = { id: 2, permissions }
  assert.equal(state.statementOptions.value, null)
  assert.equal(state.statementArchive.value, null)
  assert.deepEqual(state.statementPolicyChanges.value, [])
  assert.deepEqual(state.statementArchives.value, [])
})

test('归档详情关闭后迟到结果不重新打开，后续详情读取故障可诊断', async t => {
  let resolve
  const { state, actions } = fixture(t, () => new Promise(done => { resolve = done }))
  const request = actions.openStatementArchive(1)
  actions.closeStatementArchive()
  resolve({ id: 1, snapshot: { csv: 'old' } }); await request
  assert.equal(state.statementArchive.value, null)
  assert.equal(state.statementArchiveLoading.value, false)
  globalThis.window.nexora.callApi = async () => { throw Error('归档读取失败') }
  await actions.openStatementArchive(1)
  assert.match(state.statementError.value, /归档读取失败/)
  assert.equal(state.statementArchive.value, null)
})

test('配置、审计与归档一起载入，任何读取失败都不残留旧配置或报告', async t => {
  const { state, actions } = fixture(t, async operation => operation === 'statementOptions' ? { policy } : [{ id: 1 }])
  assert.equal(await actions.loadStatementOptions(), true)
  assert.equal(state.statementOptions.value.policy.version, 1)
  assert.equal(state.statementArchives.value.length, 1)
  state.statementReport.value = { csv: 'old' }
  globalThis.window.nexora.callApi = async operation => {
    if (operation === 'statementArchives') throw Error('历史列表失败')
    return { policy }
  }
  assert.equal(await actions.loadStatementOptions(), false)
  assert.equal(state.statementOptions.value, null)
  assert.equal(state.statementReport.value, null)
  assert.deepEqual(state.statementArchives.value, [])
  assert.match(state.statementError.value, /历史列表失败/)
})

test('保存失败保留配置输入，离线和撤权不发送归档请求', async t => {
  const calls = []
  const { state, actions } = fixture(t, async (operation, fields) => { calls.push([operation, fields]); throw Error('版本冲突') },
    async action => { try { await action() } catch { /* 外层消息机制保留输入。 */ } })
  const original = structuredClone(policy)
  assert.equal(await actions.saveStatementPolicy(policy), false)
  assert.deepEqual(policy, original)
  assert.deepEqual(calls[0], ['saveStatementPolicy', original])
  state.connectionLost.value = true
  assert.equal(await actions.archiveStatement(archive), false)
  state.connectionLost.value = false; state.user.value = { id: 1, permissions: ['financial_statement.view'] }
  assert.equal(await actions.archiveStatement(archive), false)
  assert.equal(calls.length, 1)
})

test('写入后的刷新切换账号，不重载原账号配置或报表', async t => {
  const calls = []
  let state
  const fixtureResult = fixture(t, async operation => { calls.push(operation); return {} }, async action => {
    await action(); state.user.value = { id: 2, permissions }
  })
  state = fixtureResult.state
  assert.equal(await fixtureResult.actions.archiveStatement(archive), false)
  assert.deepEqual(calls, ['archiveStatement'])
})

test('导出只接受当前查询或当前归档快照，已失效报告不得导出', async t => {
  const { state, actions } = fixture(t, async () => ({}))
  const saved = []
  globalThis.window.nexora.saveReportCsv = async (...args) => { saved.push(args); return true }
  state.statementReport.value = { filters: query, csv: 'current' }
  const report = state.statementReport.value
  await actions.exportStatement(report)
  assert.deepEqual(saved[0], ['statements-2026-01-01-2026-01-31.csv', 'current'])
  state.statementQuery.value.from_date = '2026-01-02'
  await actions.exportStatement(report)
  assert.equal(saved.length, 1)
  state.statementArchive.value = { id: 1, snapshot: { filters: query, csv: 'archived' } }
  await actions.exportStatement(state.statementArchive.value.snapshot)
  assert.equal(saved[1][1], 'archived')
})

test('其他数据读取失败前已清除被撤权的报表、配置、归档及审计', async t => {
  const { state } = fixture(t, async operation => {
    if (operation === 'documentNumbering') return { configured: true };
    if (operation === 'me') return { id: 1, permissions: ['inventory.view'] }
    if (operation === 'materials') throw Error('物料读取失败')
    return []
  })
  state.statementOptions.value = { policy }; state.statementReport.value = { csv: 'old' }
  state.statementArchive.value = { id: 1 }; state.statementArchives.value = [{ id: 1 }]
  state.statementPolicyChanges.value = [{ id: 1 }]
  await assert.rejects(createDataLoader(state, permission => state.user.value.permissions.includes(permission), () => {}).refreshData(), /物料读取失败/)
  assert.equal(state.statementOptions.value, null)
  assert.equal(state.statementReport.value, null)
  assert.equal(state.statementArchive.value, null)
  assert.deepEqual(state.statementArchives.value, [])
  assert.deepEqual(state.statementPolicyChanges.value, [])
})
