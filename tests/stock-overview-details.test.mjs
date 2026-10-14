import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createStockOverviewActions } from '../src/renderer/src/store/modules/stock-overview-actions.ts'
import { createInventoryLedgerDetailActions } from '../src/renderer/src/store/modules/inventory-ledger-detail-actions.ts'
import { validateStockOverview, isNegativeStock } from '../src/shared/stock-overview.ts'

const stock = { id: 3, sku: 'FLOW', name: '精密电阻', unit: '个', category_code: 'EL-SR', category_group_name: '电子类',
  category_name: '电子类 / 电阻', quantity: '100000000000000000.001', total_quantity: '100000000000000000.001', warehouses: [
    { warehouse_id: 1, warehouse_code: 'MAIN', warehouse_name: '主仓库', quantity: '100000000000000000.101' },
    { warehouse_id: 2, warehouse_code: 'OTHER', warehouse_name: '辅仓', quantity: '-0.100' }] }
const page = item => ({ items: [item], page: 1, page_size: 1, total: 1,
  summary: { material_count: 1, positive_material_count: 1, zero_material_count: 0, negative_material_count: 0 } })
const ledger = q => ({ rows: [], groups: [], total: 0, page: 1, page_size: q.page_size })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function setup(t, handler) {
  const previous = globalThis.window, scope = effectScope(), state = createAppState(), calls = []
  state.user.value = { id: 1, roles: ['admin'], permissions: ['inventory.view'] }
  state.warehouses.value = [{ id: 1, name: '主仓库' }, { id: 2, name: '辅仓' }]
  globalThis.window = { nexora: { callApi: async (op, input) => {
    calls.push([op, structuredClone(input)])
    if (handler) return handler(op, input)
    if (op === 'materialDetail') return { id: input.id, sku: stock.sku, name: stock.name }
    if (op === 'queryStock') return page(stock)
    return ledger(input)
  } } }
  const actions = scope.run(() => ({ ...createStockOverviewActions(state), ...createInventoryLedgerDetailActions(state) }))
  t.after(() => { scope.stop(); globalThis.window = previous })
  return { state, actions, calls }
}

test('总览打开全仓分布和独立流水，仓库切换不改变主表或全仓数量', async t => {
  const { state, actions, calls } = setup(t)
  state.stockOverviewQuery.value = { warehouse_id: 2, keyword: '电阻', category_group: 'EL', page: 4, page_size: 10 }
  const original = JSON.stringify(state.stockOverviewQuery.value)
  await actions.openStockMaterial(stock)
  assert.equal(state.stockMaterialMode.value, true)
  assert.deepEqual(calls.find(([op]) => op === 'queryStock')[1], { material_id: 3, warehouse_id: null, page: 1, page_size: 1 })
  assert.equal(state.ledgerMaterialQuery.value.warehouse_id, 2)
  assert.equal(state.stockMaterialSnapshot.value.total_quantity, stock.total_quantity)
  await actions.selectStockMaterialWarehouse(1)
  assert.equal(calls.at(-1)[1].warehouse_id, 1)
  assert.equal(calls.at(-1)[1].page, 1)
  assert.equal(state.stockMaterialSnapshot.value.warehouses.length, 2)
  await actions.selectStockMaterialWarehouse(null)
  assert.equal(state.ledgerMaterialQuery.value.warehouse_id, null)
  const count = calls.length
  await actions.selectStockMaterialWarehouse(999)
  assert.equal(calls.length, count)
  state.user.value = { ...state.user.value }
  assert.ok(state.stockMaterialSnapshot.value)
  actions.closeLedgerMaterial()
  assert.equal(state.stockMaterialMode.value, false)
  assert.equal(state.stockMaterialSnapshot.value, null)
  assert.equal(JSON.stringify(state.stockOverviewQuery.value), original)
})

test('首屏分布失败不报就绪，重试失败保留原先全仓快照', async t => {
  let fail = true, mismatch = false
  const { state, actions } = setup(t, async (op, input) => {
    if (op === 'queryStock') { if (fail) throw Error('分布读取失败'); return page({ ...stock, id: mismatch ? 9 : 3 }) }
    return op === 'materialDetail' ? { id: 3 } : ledger(input)
  })
  assert.equal(await actions.openStockMaterial(stock), false)
  assert.match(state.stockMaterialError.value, /分布读取失败/)
  assert.ok(state.ledgerMaterialDetail.value)
  assert.equal(state.ledgerMaterialRowsError.value, '')
  fail = false
  assert.equal(await actions.loadStockMaterial(), true)
  assert.equal(state.stockMaterialSnapshot.value.id, 3)
  mismatch = true
  assert.equal(await actions.loadStockMaterial(), false)
  assert.equal(state.stockMaterialSnapshot.value.id, 3)
  assert.match(state.stockMaterialError.value, /不一致/)
})

test('关闭、换物料及筛选变化使仓库分布慢响应失效', async t => {
  const pending = []
  const { state, actions } = setup(t, (op, input) => {
    if (op === 'queryStock') { const job = deferred(); pending.push(job); return job.promise }
    return Promise.resolve(op === 'materialDetail' ? { id: input.id } : ledger(input))
  })
  const first = actions.openStockMaterial(stock)
  const second = actions.openStockMaterial({ ...stock, id: 4 })
  pending[0].resolve(page(stock)); await first
  assert.equal(state.stockMaterialSnapshot.value, null)
  pending[1].resolve(page({ ...stock, id: 4 })); await second
  assert.equal(state.stockMaterialSnapshot.value.id, 4)
  const third = actions.loadStockMaterial()
  state.stockOverviewQuery.value.category_group = 'HW'
  pending[2].resolve(page({ ...stock, id: 4 })); await third
  assert.equal(state.stockMaterialSnapshot.value, null)
  assert.equal(state.ledgerMaterialTarget.value, null)
  assert.equal(state.stockOverviewQuery.value.page, 1)
})

test('搜索和分类在服务端查询、回首页，旧服务响应明确提示升级', async t => {
  let legacy = false
  const { state, actions, calls } = setup(t, (op, input) => Promise.resolve(legacy ? { items: [], summary: {} } : { ...page(stock), page_size: input.page_size }))
  state.stockOverviewQuery.value.page = 4
  state.stockOverviewQuery.value.keyword = '100%_ 电阻'
  state.stockOverviewQuery.value.category_group = 'EL'
  await actions.queryStockOverview()
  assert.equal(calls.at(-1)[1].page, 1)
  assert.equal(calls.at(-1)[1].keyword, '100%_ 电阻')
  assert.equal(calls.at(-1)[1].category_group, 'EL')
  await actions.resetStockOverview()
  assert.equal(calls.at(-1)[1].keyword, '')
  assert.equal(calls.at(-1)[1].category_group, null)
  legacy = true
  await actions.queryStockOverview()
  assert.equal(state.stockOverviewResult.value, null)
  assert.match(state.stockOverviewError.value, /升级服务端/)
  state.user.value.permissions = []
  const count = calls.length
  await actions.openStockMaterial(stock)
  assert.equal(calls.length, count)
})

test('分布与总览契约保留精确数量，拒绝重复仓库、残缺数据和错误统计', () => {
  assert.doesNotThrow(() => validateStockOverview(page(stock)))
  // 服务端 Decimal 的极小数量可使用指数格式，不能误判为无效或负零。
  assert.doesNotThrow(() => validateStockOverview(page({ ...stock, quantity: '-1E-9' })))
  for (const invalid of [page({ ...stock, warehouses: [...stock.warehouses, stock.warehouses[0]] }),
    page({ ...stock, quantity: 'NaN' }), { ...page(stock), summary: { ...page(stock).summary, material_count: 2 } }]) {
    assert.throws(() => validateStockOverview(invalid))
  }
  assert.equal(isNegativeStock('-0.000000000000000000001'), true)
  assert.equal(isNegativeStock('-0.000'), false)
  assert.equal(isNegativeStock('-0E-9'), false)
  assert.equal(isNegativeStock('-1E-9'), true)
  assert.equal(isNegativeStock('100000000000000000.001'), false)
})
