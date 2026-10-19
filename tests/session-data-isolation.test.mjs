import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { createConnectionActions } from '../src/renderer/src/store/connection-actions.ts'
import { StaleSessionRead } from '../src/renderer/src/store/session-state.ts'

const account = id => ({ id, username: `user-${id}`, roles: [], permissions: ['sales.view'] })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function fixture(t, api = () => []) {
  const previous = globalThis.window, scope = effectScope()
  const state = scope.run(createAppState)
  state.server.value = { id: 'server-a', fingerprint: 'cert-a' }
  state.user.value = account(1)
  globalThis.window = { nexora: { callApi: async (name, payload) => {
    if (name === 'me') return state.user.value
    if (name === 'documentNumbering') return { configured: true }
    return api(name, payload)
  } } }
  const loader = createDataLoader(state, code => state.user.value?.permissions.includes(code) ?? false, () => {})
  t.after(() => { scope.stop(); globalThis.window = previous })
  return { state, loader }
}

test('真实退出操作同步清空跨业务缓存与草稿，保留窗口和连接资料', async t => {
  const { state } = fixture(t)
  state.salesOrders.value = [{ id: 101 }]; state.purchaseOrders.value = [{ id: 202 }]
  state.workOrders.value = [{ id: 303 }]; state.journals.value = [{ id: 404 }]
  state.salesForm.value.customer_id = 42; state.resetPasswords.value = { 7: '旧密码' }
  state.productMaterialForm.value.name = '旧产品'; state.documentNumbering.value = { configured: true }
  state.version.value = 'test-version'; state.manualForm.value.address = '192.168.1.5'
  await createConnectionActions(state, async () => {}).logout()
  for (const key of ['salesOrders', 'purchaseOrders', 'workOrders', 'journals']) assert.deepEqual(state[key].value, [])
  assert.equal(state.salesForm.value.customer_id, 0); assert.deepEqual(state.resetPasswords.value, {})
  assert.equal(state.productMaterialForm.value.name, ''); assert.equal(state.documentNumbering.value, null)
  assert.equal(state.screen.value, 'login'); assert.equal(state.version.value, 'test-version')
  assert.equal(state.server.value.id, 'server-a'); assert.equal(state.manualForm.value.address, '192.168.1.5')
})

test('新账号读取失败也不会看到上一账号的客户和销售单据', async t => {
  let fail = false
  const { state, loader } = fixture(t, name => {
    if (fail && name === 'salesOrders') throw Error('列表读取失败')
    return name === 'salesOrders' ? [{ id: 101, customer_name: '账号 A 客户' }] : []
  })
  await loader.refreshData(); assert.equal(state.salesOrders.value.length, 1)
  state.user.value = account(2); fail = true
  await assert.rejects(loader.refreshData(), /列表读取失败/)
  assert.deepEqual(state.salesOrders.value, []); assert.deepEqual(state.customers.value, [])
})

test('临时断线与同身份快照刷新保留草稿，证书变化清除旧业务', t => {
  const { state } = fixture(t)
  state.salesForm.value.reference = '未保存输入'
  state.connectionLost.value = true; state.connectionLost.value = false
  state.user.value = { ...account(1) }; state.server.value = { ...state.server.value, host: '192.168.1.9' }
  assert.equal(state.salesForm.value.reference, '未保存输入')
  state.server.value = { ...state.server.value, fingerprint: 'cert-b' }
  assert.equal(state.salesForm.value.reference, '')
})

test('退出期间迟到的身份响应不能重新登录原账号', async t => {
  const pending = deferred(), { state, loader } = fixture(t)
  globalThis.window.nexora.callApi = () => pending.promise
  const reading = loader.refreshData(), rejected = assert.rejects(reading, StaleSessionRead)
  state.user.value = null; pending.resolve(account(1))
  await rejected; assert.equal(state.user.value, null)
})

test('快速退出再登录同一账号，旧销售列表响应仍然失效', async t => {
  const pending = deferred(), reached = deferred()
  const { state, loader } = fixture(t, name => {
    if (name === 'salesOrders') { reached.resolve(); return pending.promise }
    return []
  })
  const reading = loader.refreshData(), rejected = assert.rejects(reading, StaleSessionRead)
  await reached.promise
  state.user.value = null; state.user.value = account(1)
  state.salesOrders.value = [{ id: 202 }]
  pending.resolve([{ id: 101 }]); await rejected
  assert.deepEqual(state.salesOrders.value, [{ id: 202 }])
})

test('并发刷新只允许新一轮结果写入，旧错误不覆盖成功快照', async t => {
  const pending = deferred(), reached = deferred(); let reads = 0
  const { state, loader } = fixture(t, name => {
    if (name !== 'salesOrders') return []
    if (++reads === 1) { reached.resolve(); return pending.promise }
    return [{ id: 202 }]
  })
  const first = loader.refreshData(), rejected = assert.rejects(first, StaleSessionRead)
  await reached.promise; await loader.refreshData()
  pending.reject(Error('旧列表超时')); await rejected
  assert.deepEqual(state.salesOrders.value, [{ id: 202 }])
})

test('撤销销售和库存权限后，后续读取失败也已清空旧共享列表', async t => {
  const { state, loader } = fixture(t)
  state.salesOrders.value = [{ id: 1 }]; state.purchaseOrders.value = [{ id: 2 }]
  globalThis.window.nexora.callApi = async name => {
    if (name === 'me') return { ...account(1), permissions: [] }
    throw Error('编号读取失败')
  }
  await assert.rejects(loader.refreshData(), /编号读取失败/)
  assert.deepEqual(state.salesOrders.value, []); assert.deepEqual(state.purchaseOrders.value, [])
})

test('同账号保留销售查看但撤销全客户范围时，也立即清理旧客户数据和草稿', t => {
  const { state } = fixture(t)
  state.user.value = { ...account(1), permissions: ['sales.view', 'customer.view_all'] }
  state.salesOrders.value = [{ id: 1 }]; state.salesForm.value.customer_id = 10
  // 权限返回顺序变化不属于撤权，不应丢失同会话输入。
  state.user.value = { ...account(1), permissions: ['customer.view_all', 'sales.view'] }
  assert.equal(state.salesForm.value.customer_id, 10)
  state.user.value = account(1)
  assert.deepEqual(state.salesOrders.value, []); assert.equal(state.salesForm.value.customer_id, 0)
})
