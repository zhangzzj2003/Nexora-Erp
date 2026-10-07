import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createPeriodClosingActions } from '../src/renderer/src/store/modules/period-closing-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { callBackend } from '../src/main/backend.ts'

const permissions = ['accounting_period.view','accounting_period.closing_view','accounting_period.close','accounting_period.reopen']
const period = { id: 1, version: 3, status: 'open', code: 'JAN' }

test('结账 IPC 拒绝路径和动作注入，只传版本及原因', async t => {
  const previous = process.env.NEXORA_API_URL
  t.after(() => { if (previous === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = previous })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: options.body })
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test-token', user: { id: 1 } } : {})
  })
  await callBackend('login', {})
  await callBackend('periodClosingCheck', { id: 4 })
  assert.equal(calls.at(-1).path, '/api/v1/finance/accounting-periods/4/closing-check')
  await callBackend('periodClosingHistory', { id: 4 })
  assert.equal(calls.at(-1).path, '/api/v1/finance/accounting-periods/4/closings')
  for (const action of ['close','reopen']) {
    await callBackend('changePeriodClosingStatus', { id: 4, version: 7, action, reason: '核对', status: '伪造', evidence: { ledger: '伪造' } })
    assert.equal(calls.at(-1).path, '/api/v1/finance/accounting-periods/4/'+action)
    assert.deepEqual(JSON.parse(calls.at(-1).body), {version:7,reason:'核对'})
  }
  await assert.rejects(callBackend('changePeriodClosingStatus', {id:4,action:'../users'}), /结账操作无效/)
  for (const operation of ['periodClosingCheck','periodClosingHistory','changePeriodClosingStatus'])
    await assert.rejects(callBackend(operation, { id: '../users' }), /记录编号无效/)
})

test('过时检查不能覆盖新期间，退出和撤权清除快照并丢弃迟到结果', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = {id:1,permissions}
  let resolveOld
  globalThis.window = {nexora:{callApi(action,{id}) {
    if (id === 1) return new Promise(resolve => { resolveOld = resolve })
    return Promise.resolve({period:{id},can_close:true})
  }}}
  const actions = createPeriodClosingActions(state, async action => action())
  const first = actions.loadPeriodClosingCheck(1)
  assert.equal(await actions.loadPeriodClosingCheck(2), true)
  resolveOld({period:{id:1},can_close:false})
  assert.equal(await first, false)
  assert.equal(state.periodClosingCheck.value.period.id, 2)
  const late = actions.loadPeriodClosingHistory(1)
  state.user.value = null
  resolveOld([{id:1}])
  assert.equal(await late, false)
  assert.deepEqual(state.periodClosingHistory.value, [])
  assert.equal(state.periodClosingCheck.value,null)
  assert.equal(state.periodClosingLoading.value,false)
  state.user.value = {id:2,permissions:['accounting_period.view']}
  assert.equal(await actions.loadPeriodClosingCheck(2),false)
})

test('失败显示可重试错误，写入保留旧版本且权限和离线状态限制操作', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state = createAppState(); state.user.value = {id:1,permissions}
  const calls = []; let fail = true
  globalThis.window = {nexora:{async callApi(action,input) {
    calls.push([action,input]); if(fail)throw new Error('版本已变化，请刷新核对')
    return {period,can_close:true}
  }}}
  const actions = createPeriodClosingActions(state, async action => {try{await action()}catch(error){state.error.value=error.message}})
  assert.equal(await actions.loadPeriodClosingCheck(1),false)
  assert.match(state.periodClosingError.value,/刷新核对/)
  assert.equal(state.periodClosingLoading.value,false)
  assert.equal(await actions.changePeriodClosingStatus(period,'close','核对'),false)
  assert.equal(period.version,3)
  assert.deepEqual(calls.at(-1),['changePeriodClosingStatus',{id:1,version:3,action:'close',reason:'核对'}])
  fail=false
  assert.equal(await actions.loadPeriodClosingCheck(1),true)
  assert.equal(state.periodClosingError.value,'')
  assert.equal(await actions.changePeriodClosingStatus(period,'close','核对'),true)
  const count=calls.length; state.connectionLost.value=true
  assert.equal(await actions.changePeriodClosingStatus(period,'close','核对'),false)
  state.connectionLost.value=false; state.user.value={id:1,permissions:['accounting_period.view']}
  assert.equal(await actions.changePeriodClosingStatus(period,'reopen','越权'),false)
  assert.equal(calls.length,count)
})

test('其他模块读取失败前，数据加载器先清除失去授权的结账证据', async t => {
  const old = globalThis.window; t.after(() => { globalThis.window = old })
  const state=createAppState(); state.user.value={id:1,permissions}
  state.periodClosingCheck.value={period,can_close:true}; state.periodClosingHistory.value=[{id:1}]
  globalThis.window={nexora:{async callApi(action){
    if (action === 'documentNumbering') return { configured: true };
    if(action==='me')return {id:1,permissions:['inventory.view']}
    if(action==='materials')throw new Error('业务模块失败')
    return []
  }}}
  const loader=createDataLoader(state, code=>state.user.value.permissions.includes(code),()=>{})
  await assert.rejects(loader.refreshData(),/业务模块失败/)
  assert.equal(state.periodClosingCheck.value,null)
  assert.deepEqual(state.periodClosingHistory.value,[])
})
