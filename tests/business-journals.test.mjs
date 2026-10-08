import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createBusinessJournalActions } from '../src/renderer/src/store/modules/business-journal-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { callBackend } from '../src/main/backend.ts'
import { businessTotal, businessRoleRows, businessSourceMapping } from '../src/renderer/src/views/workspace/finance/business-journal-display.ts'

const permissions = ['business_journal.view', 'business_journal.configure', 'business_journal.generate']
const policy = { version: 3, start_date: '2026-01-01', mapping: { inventory: 1, payable: 2 }, reason: '核对' }
const input = { source_key: 'receipt:1', fingerprint: 'a'.repeat(64), policy_version: 3, reference: 'PO-1', journal_date: '2026-10-01', reason: '核对入库' }
const response = operation => operation === 'businessJournalOptions' ? { policy } : []

test('业务凭证 IPC 固定地址并剔除客户端金额、状态和来源快照', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test-token', user: { id: 1 } } : {})
  })
  await callBackend('login', {})
  for (const [operation, suffix] of [['businessJournalSources',''],['businessJournalOptions','/policy'],['businessJournalPolicyChanges','/policy/changes']]) {
    await callBackend(operation, undefined)
    assert.equal(calls.at(-1).path, '/api/v1/finance/business-journals' + suffix)
  }
  await callBackend('saveBusinessJournalPolicy', { ...policy, status: 'posted', lines: ['伪造'] })
  assert.deepEqual(JSON.parse(calls.at(-1).body), policy)
  await callBackend('generateBusinessJournal', { ...input, source_key: '../users', amount: '999', status: 'posted', evidence: {}, lines: [] })
  assert.equal(calls.at(-1).path, '/api/v1/finance/business-journals/generate')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { ...input, source_key: '../users' })
})

test('业务金额预览使用精确分位，销售收入与成本分别平衡', () => {
  const evidence = { roles: { inventory: '-0.10', receivable: '999999999999.91', income: '-999999999999.91', sales_cost: '0.10' } }
  assert.equal(businessTotal(evidence), '1000000000000.01')
  assert.deepEqual(businessRoleRows({roles:{inventory:'-1.01'}})[0], {role:'inventory',label:'库存',debit:'0.00',credit:'1.01'})
})

test('历史资金预览沿用原单科目，普通订单仍用配置且不改写来源与配置', () => {
  const configured={receivable:1,payable:2,cash:4}
  const source={source_type:'subledger_payment',records:[{kind:'receivable',account_id:5}]}
  const before=structuredClone(source)
  assert.deepEqual(businessSourceMapping(source,configured),{receivable:5,payable:2,cash:4})
  assert.deepEqual(businessSourceMapping({...source,records:[{kind:'payable',account_id:6}]},configured),{receivable:1,payable:6,cash:4})
  assert.deepEqual(businessSourceMapping({...source,source_type:'payment'},configured),configured)
  assert.deepEqual(businessSourceMapping(source,{cash:4}),{cash:4,receivable:5})
  for(const id of [true,0,-1,1.5,'5'])assert.deepEqual(businessSourceMapping({...source,records:[{kind:'receivable',account_id:id}]},configured),configured)
  assert.deepEqual(source,before);assert.deepEqual(configured,{receivable:1,payable:2,cash:4})
})

test('迟到来源不可覆盖新快照，换号或撤权会清除来源和配置审计', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  let pending = true; const resolvers = []
  globalThis.window = { nexora: { callApi(operation) {
    if (pending) return new Promise(resolve => resolvers.push(() => resolve(operation === 'businessJournalSources' ? [{key:'old'}] : response(operation))))
    return Promise.resolve(operation === 'businessJournalSources' ? [{key:'new'}] : response(operation))
  } } }
  const actions = createBusinessJournalActions(state, action => action())
  const first = actions.loadBusinessJournals(); pending = false
  assert.equal(await actions.loadBusinessJournals(), true)
  resolvers.splice(0).forEach(resolve => resolve())
  assert.equal(await first, false)
  assert.equal(state.businessJournalSources.value[0].key, 'new')
  pending = true; const late = actions.loadBusinessJournals()
  state.user.value = { id: 2, permissions: [] }
  resolvers.splice(0).forEach(resolve => resolve())
  assert.equal(await late, false)
  assert.deepEqual(state.businessJournalSources.value, [])
  assert.equal(state.businessJournalOptions.value, null)
  assert.deepEqual(state.businessJournalPolicyChanges.value, [])
  assert.equal(state.businessJournalLoading.value, false)
})

test('失败保留配置和依据输入，离线与撤权禁止写入', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  const calls = []
  globalThis.window = { nexora: { async callApi(operation, value) { calls.push([operation,value]); throw Error('版本已变化，请刷新核对') } } }
  const actions = createBusinessJournalActions(state, async action => { try { await action() } catch(error) { state.error.value = error.message } })
  const copy = structuredClone(policy)
  assert.equal(await actions.saveBusinessJournalPolicy(policy), false)
  assert.deepEqual(policy, copy)
  assert.deepEqual(calls.at(-1), ['saveBusinessJournalPolicy',copy])
  assert.equal(await actions.loadBusinessJournals(), false)
  assert.match(state.businessJournalError.value, /刷新核对/)
  const count = calls.length; state.connectionLost.value = true
  assert.equal(await actions.generateBusinessJournal(input), false)
  state.connectionLost.value = false; state.user.value = { id: 1, permissions: ['business_journal.view'] }
  assert.equal(await actions.generateBusinessJournal(input), false)
  assert.equal(calls.length, count)
})

test('写入完成后的全局刷新期间撤权，不能关闭新账号的表单或加载旧来源', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  const calls = []
  globalThis.window = { nexora: { async callApi(operation) { calls.push(operation); return {} } } }
  const actions = createBusinessJournalActions(state, async action => {
    await action(); state.user.value = { id: 2, permissions }
  })
  assert.equal(await actions.generateBusinessJournal(input), false)
  assert.deepEqual(calls, ['generateBusinessJournal'])
})

test('业务快照撤权清理先于其他模块加载失败', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = { id: 1, permissions }
  state.businessJournalSources.value = [{key:'receipt:1'}]; state.businessJournalOptions.value = {policy}
  state.businessJournalPolicyChanges.value = [{id:1}]
  globalThis.window = { nexora: { async callApi(operation) {
    if (operation === 'documentNumbering') return { configured: true };
    if (operation === 'me') return { id:1,permissions:['inventory.view'] }
    if (operation === 'materials') throw Error('资料读取失败')
    return []
  } } }
  await assert.rejects(createDataLoader(state, code => state.user.value.permissions.includes(code), () => {}).refreshData(), /资料读取失败/)
  assert.deepEqual(state.businessJournalSources.value, [])
  assert.equal(state.businessJournalOptions.value, null)
  assert.deepEqual(state.businessJournalPolicyChanges.value, [])
})
