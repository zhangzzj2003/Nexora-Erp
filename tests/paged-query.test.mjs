import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { usePagedQuery } from '../src/renderer/src/composables/use-paged-query.ts'

// 用可控请求验证乱序响应、失败重试与卸载，避免只验证模板文字。
test('分页查询忽略旧响应，失败后可重试，并使用服务端纠正页码', async () => {
  const pending = []
  const scope = effectScope()
  const state = scope.run(() => usePagedQuery(params => new Promise((resolve, reject) => pending.push({ params, resolve, reject }))))
  try {
    const old = state.load(2)
    const current = state.load(3, 10)
    pending[1].resolve({ items: [{ id: 20 }], total: 11, page: 2, page_size: 10 })
    await current
    pending[0].resolve({ items: [{ id: 1 }], total: 100, page: 2, page_size: 20 })
    await old
    assert.deepEqual(state.rows.value, [{ id: 20 }])
    assert.equal(state.page.value, 2)
    assert.equal(state.pageSize.value, 10)
    const failed = state.load()
    pending[2].reject(new Error('网络中断'))
    await failed
    assert.equal(state.error.value, '网络中断')
    assert.equal(state.loading.value, false)
    assert.deepEqual(state.rows.value, [])
    const retry = state.load()
    pending[3].resolve({ items: [], total: 0, page: 1, page_size: 10 })
    await retry
    assert.equal(state.error.value, '')
    assert.equal(state.page.value, 1)
    const disposed = state.load()
    scope.stop()
    pending[4].resolve({ items: [{ id: 99 }], total: 1, page: 1, page_size: 10 })
    await disposed
    assert.deepEqual(state.rows.value, [])
  } finally { scope.stop() }
})

test('搜索防抖并回到第一页，输入变化立即拒绝旧结果', async () => {
  const requests = []
  const scope = effectScope()
  const state = scope.run(() => usePagedQuery(params => new Promise(resolve => requests.push({ params, resolve }))))
  try {
    const old = state.load(4)
    state.search(' 旧词 ')
    state.search(' 新词 ')
    requests[0].resolve({ items: [{ id: 9 }], total: 90, page: 4, page_size: 20 })
    await old
    assert.deepEqual(state.rows.value, [])
    await new Promise(resolve => setTimeout(resolve, 300))
    assert.equal(requests.length, 2)
    assert.deepEqual(requests[1].params, { query: '新词', page: 1, page_size: 20 })
    requests[1].resolve({ items: [], total: 0, page: 1, page_size: 20 })
    await Promise.resolve()
  } finally { scope.stop() }
})

// 接受回调同样只收到最新一页，旧查询不能污染用于按钮操作的共享数据。
test('分页结果接受回调忽略乱序旧页', async () => {
  const pending = []; const accepted = []; const scope = effectScope()
  const state = scope.run(() => usePagedQuery(() => new Promise(resolve => pending.push(resolve)), result => accepted.push(result.items)))
  const old = state.load(1); const current = state.load(2)
  pending[1]({ items: [{id: 2}], total: 2, page: 2, page_size: 1 }); await current
  pending[0]({ items: [{id: 1}], total: 2, page: 1, page_size: 1 }); await old
  assert.deepEqual(accepted, [[{id: 2}]]); scope.stop()
})


// 翻页之后仍可读取表单所选单据，缓存只保留当前页及有界的表单引用。
test('分页共享快照保留选中单据并替换无关旧页', async () => {
  const {createAppState}=await import('../src/renderer/src/store/state.ts')
  const {createTableActions}=await import('../src/renderer/src/store/modules/table-actions.ts')
  const state=createAppState();state.user.value={id:1,roles:['admin'],permissions:[]}
  state.goodsReceiptForm.value.purchase_order_id=3
  state.purchaseOrders.value=[{id:3,lines:[{id:31}]},{id:4,lines:[]}]
  createTableActions(state).hydrateDataset('purchaseOrders',[{id:9,lines:[]}])
  assert.deepEqual(state.purchaseOrders.value.map(row=>row.id),[9,3])
  state.goodsReceiptForm.value.purchase_order_id=0
  createTableActions(state).hydrateDataset('purchaseOrders',[{id:10,lines:[]}])
  assert.deepEqual(state.purchaseOrders.value.map(row=>row.id),[10])
})

// 撤权后重新授权，较早的请求也必须失效。
test('请求范围识别同一账号撤权再授权', async () => {
  const {createAppState}=await import('../src/renderer/src/store/state.ts')
  const {createRequestScope}=await import('../src/renderer/src/utils/request-scope.ts')
  const state=createAppState();state.user.value={id:1,roles:['finance'],permissions:['finance.view']}
  const scope=createRequestScope(state);const old=scope.capture()
  state.user.value={id:1,roles:['finance'],permissions:[]}
  state.user.value={id:1,roles:['finance'],permissions:['finance.view']}
  assert.equal(scope.current(old),false)
  assert.equal(scope.current(scope.capture()),true)
})
