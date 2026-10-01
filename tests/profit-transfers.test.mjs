import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createProfitTransferActions } from '../src/renderer/src/store/modules/profit-transfer-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { callBackend } from '../src/main/backend.ts'

const permissions = ['profit_transfer.view', 'profit_transfer.configure', 'profit_transfer.generate']
const policy = { version: 2, start_date: '2026-01-01', target_account_id: 7, cost_account_ids: [5], reason: '核对范围' }
const input = { period_id: 1, period_version: 1, policy_version: 2, fingerprint: 'a'.repeat(64), reference: 'TRANSFER', reason: '核对' }

test('结转 IPC 固定请求地址，拒绝路径注入并剔除客户端分录、日期与状态', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test-token', user: { id: 1 } } : {})
  })
  await callBackend('login', {})
  await callBackend('profitTransferOptions', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/finance/profit-transfers/policy')
  await callBackend('profitTransferPolicyChanges', undefined)
  assert.equal(calls.at(-1).path, '/api/v1/finance/profit-transfers/policy/changes')
  await callBackend('profitTransferPreview', { id: 1 })
  assert.equal(calls.at(-1).path, '/api/v1/finance/profit-transfers/periods/1')
  await assert.rejects(callBackend('profitTransferPreview', { id: '../users' }))
  await callBackend('saveProfitTransferPolicy', { ...policy, status: 'posted' })
  assert.deepEqual(JSON.parse(calls.at(-1).body), policy)
  await callBackend('generateProfitTransfer', { ...input, lines: [], journal_date: '2026-01-01', status: 'posted', amount: '999', evidence: {} })
  assert.equal(calls.at(-1).path, '/api/v1/finance/profit-transfers/generate')
  assert.deepEqual(JSON.parse(calls.at(-1).body), input)
})

test('迟到期间预览不能覆盖新选择，撤权清除配置、来源与审计', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  let resolve
  globalThis.window = { nexora: { callApi(operation, fields) {
    return fields.id === 1 ? new Promise(done => { resolve = done }) : Promise.resolve({ period: { id: 2 } })
  } } }
  const actions = createProfitTransferActions(state, action => action())
  const first = actions.loadProfitTransferPreview(1)
  assert.equal(await actions.loadProfitTransferPreview(2), true)
  resolve({ period: { id: 1 } }); assert.equal(await first, false)
  assert.equal(state.profitTransferPreview.value.period.id, 2)
  const late = actions.loadProfitTransferPreview(1)
  state.profitTransferOptions.value = { policy }; state.profitTransferPolicyChanges.value = [{ id: 1 }]
  state.user.value = { id: 2, permissions: [] }; resolve({ period: { id: 1 } })
  assert.equal(await late, false)
  assert.equal(state.profitTransferPreview.value, null)
  assert.equal(state.profitTransferOptions.value, null)
  assert.deepEqual(state.profitTransferPolicyChanges.value, [])
  assert.equal(state.profitTransferLoading.value, false)
})

test('配置按需读取，分页历史不预加载，读取故障清除旧余额', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  globalThis.window = { nexora: { async callApi(operation) { return operation === 'profitTransferOptions' ? { policy } : [{ id: 1 }] } } }
  const actions = createProfitTransferActions(state, action => action())
  assert.equal(await actions.loadProfitTransferOptions(), true)
  assert.equal(state.profitTransferOptions.value.policy.version, 2)
  assert.deepEqual(state.profitTransferPolicyChanges.value, [])
  state.profitTransferPreview.value = { can_generate: true }
  globalThis.window.nexora.callApi = async () => { throw Error('源凭证读取失败') }
  assert.equal(await actions.loadProfitTransferPreview(1), false)
  assert.equal(state.profitTransferPreview.value, null)
  assert.match(state.profitTransferError.value, /源凭证读取失败/)
})

test('配置保存失败保留草稿与版本，离线或撤权禁止生成', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  const calls = []
  globalThis.window = { nexora: { async callApi(operation, fields) { calls.push([operation, fields]); throw Error('版本已变化') } } }
  const actions = createProfitTransferActions(state, async action => { try { await action() } catch (error) { state.error.value = error.message } })
  const copy = structuredClone(policy)
  assert.equal(await actions.saveProfitTransferPolicy(policy), false)
  assert.deepEqual(policy, copy)
  assert.deepEqual(calls[0], ['saveProfitTransferPolicy', copy])
  state.connectionLost.value = true
  assert.equal(await actions.generateProfitTransfer(input), false)
  state.connectionLost.value = false; state.user.value = { id: 1, permissions: ['profit_transfer.view'] }
  assert.equal(await actions.generateProfitTransfer(input), false)
  assert.equal(calls.length, 1)
})

test('全局刷新时切换账号，写入结果不关闭新账号输入或重载旧配置', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  const calls = []
  globalThis.window = { nexora: { async callApi(operation) { calls.push(operation); return {} } } }
  const actions = createProfitTransferActions(state, async action => {
    await action(); state.user.value = { id: 2, permissions }
  })
  assert.equal(await actions.generateProfitTransfer(input), false)
  assert.deepEqual(calls, ['generateProfitTransfer'])
})

test('其他业务接口失败前已清除被撤权的损益预览和配置', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  state.profitTransferOptions.value = { policy }; state.profitTransferPreview.value = { can_generate: true }
  state.profitTransferPolicyChanges.value = [{ id: 1 }]
  globalThis.window = { nexora: { async callApi(operation) {
    if (operation === 'me') return { id: 1, permissions: ['inventory.view'] }
    if (operation === 'menuIcons') throw Error('资料读取失败')
    return []
  } } }
  await assert.rejects(createDataLoader(state, permission => state.user.value.permissions.includes(permission), () => {}).refreshData(), /资料读取失败/)
  assert.equal(state.profitTransferOptions.value, null)
  assert.equal(state.profitTransferPreview.value, null)
  assert.deepEqual(state.profitTransferPolicyChanges.value, [])
})
