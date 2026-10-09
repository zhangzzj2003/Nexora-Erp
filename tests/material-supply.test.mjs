import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createMaterialSupplyActions } from '../src/renderer/src/store/modules/material-supply-actions.ts'
import { materialSupplyBody, validateMaterialSupply } from '../src/shared/material-supply-api.ts'
import { materialSupplyId, materialSupplyColumns, formatMaterialSupplyQuantity } from '../src/renderer/src/utils/material-supply-row.ts'
import { callBackend } from '../src/main/backend.ts'
import { previewResponse } from '../scripts/site-preview/fixtures.mjs'

// 数量展示去掉多余零，但不得取整、隐藏真实小数、丢失大数精度或将无权限显示成零。
test('供需数量精简整数和小数尾零，保留负数、大数精度与权限提示', () => {
  for (const [value, expected] of [
    ['100.000', '100'], ['0.000', '0'], ['1000', '1000'], ['1.500', '1.5'],
    ['1.050', '1.05'], ['0.001', '0.001'], ['0.100', '0.1'], ['100.101', '100.101'],
    ['-12.300', '-12.3'], ['-100.000', '-100'], ['-0.000', '0'],
    ['9007199254740993.125', '9007199254740993.125'],
    ['9007199254740993.000', '9007199254740993'], [null, '无权限'],
  ]) assert.equal(formatMaterialSupplyQuantity(value), expected)
})

// 预览数量必须与明细相符，且不能因开放只读供需而放行任何业务写入。
test('仓库、采购与计划的示例供需响应守恒，业务写入保持隔离', () => {
  const response = previewResponse('materialSupply', {material_ids: [1, 2]})
  validateMaterialSupply(response, [1, 2])
  assert.equal(response.rows[0].awaiting_delivery_quantity, '700.000')
  assert.equal(previewResponse('mrpOptions').supplies[0].material_id, 1)
  assert.deepEqual(previewResponse('mrpPlans'), [])
  for (const operation of ['createMrpPlan', 'createPurchaseOrder', 'postReceipt']) assert.throws(() => previewResponse(operation, {}), /未连接业务服务/)
})

// 来源与数量独立列出，用十进制尾差和错配响应覆盖真实边界。
const row = id => ({material_id: id, sku: 'PART-' + id, name: '物料' + id, unit: '件',
  stock_quantity: '0.300', planned_quantity: null, awaiting_delivery_quantity: '0.000', awaiting_inbound_quantity: '0.000',
  sources: [
    {phase: 'stock', kind: 'warehouse', document_id: 1, document_no: null, reference: '', quantity: '0.100', warehouse_name: '主仓库'},
    {phase: 'stock', kind: 'warehouse', document_id: 2, document_no: null, reference: '', quantity: '0.200', warehouse_name: '第二仓库'}]})
const result = ids => ({scope: 'all_warehouses', generated_at: new Date().toISOString(), rows: ids.map(row)})
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return {promise, resolve, reject} }
function fixture(t, callApi) {
  const previous = globalThis.window
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous })
  globalThis.window = {nexora: {callApi}}
  const state = createAppState(); state.user.value = {id: 1, permissions: ['inventory.view']}
  return {state, actions: createMaterialSupplyActions(state)}
}

test('物料编号来自真实草稿或来源行，不猜测名称，也不改写草稿', () => {
  const line = {material_id: 7, quantity: '9'}, wrapped = {line, index: 3}
  assert.equal(materialSupplyId(line), 7); assert.equal(materialSupplyId(wrapped), 7)
  for (const invalid of [null, {}, {material_id: '7'}, {material_id: true}, {material_id: -1}, {sku: 'PART-7'}]) assert.equal(materialSupplyId(invalid), 0)
  assert.deepEqual(line, {material_id: 7, quantity: '9'})
})

test('IPC 只转发受限批量物料编号，拒绝非法输入并核对对应响应', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous })
  const calls = []
  globalThis.fetch = async (url, options) => {
    const path = new URL(url).pathname, body = JSON.parse(options.body)
    calls.push({path, body})
    return new Response(JSON.stringify(path.endsWith('/login') ? {token: 'supply-test', user: {id: 1}} : result(body.material_ids)))
  }
  await callBackend('login', {}); calls.length = 0
  await callBackend('materialSupply', {material_ids: [1, 2], permissions: ['admin'], scope: 'hacked'})
  assert.deepEqual(calls, [{path: '/api/v1/inventory/material-supply/query', body: {material_ids: [1, 2]}}])
  for (const input of [null, {}, {material_ids: []}, {material_ids: [true]}, {material_ids: [1, 1]},
    {material_ids: [0]}, {material_ids: ['1']}, {material_ids: Array.from({length: 101}, (_, index) => index + 1)}]) {
    assert.throws(() => materialSupplyBody(input), /编号无效/)
    await assert.rejects(callBackend('materialSupply', input), /编号无效/)
  }
  assert.equal(calls.length, 1)
})

test('响应拒绝错物料、非法数量、非守恒汇总和未授权阶段的证据', () => {
  validateMaterialSupply(result([1]), [1])
  for (const mutate of [value => value.rows[0].material_id = 2, value => value.scope = 'current',
    value => value.rows[0].stock_quantity = '0.301', value => value.rows[0].stock_quantity = 'NaN',
    value => value.rows[0].sources[0].phase = 'planned', value => value.rows[0].sources[0].quantity = '1e3',
    value => value.rows[0].sources[0].kind = '__proto__', value => value.rows.push(row(2))]) {
    const value = result([1]); mutate(value); assert.throws(() => validateMaterialSupply(value, [1]), /响应格式不匹配/)
  }
})

test('同轮渲染合并物料，重复读取复用快照；超过上限自动拆批', async t => {
  const calls = [], {state, actions} = fixture(t, async (operation, input) => {
    assert.equal(operation, 'materialSupply'); calls.push(input.material_ids); return result(input.material_ids)
  })
  const loads = Array.from({length: 205}, (_, index) => actions.loadMaterialSupply(index + 1))
  assert.equal(await actions.loadMaterialSupply(1), false)
  assert.ok((await Promise.all(loads)).every(Boolean))
  assert.deepEqual(calls.map(ids => ids.length), [100, 100, 5])
  assert.equal(Object.keys(state.materialSupplyRows.value).length, 205)
  assert.equal(await actions.loadMaterialSupply(1), true); assert.equal(calls.length, 3)
  assert.equal(await actions.loadMaterialSupply(1, true), true); assert.equal(calls.length, 4)
})

test('切换账号、实例、权限或断线立即清空数据并拒绝迟到响应，原草稿保持不变', async t => {
  for (const mutate of [state => state.user.value = {id: 2, permissions: ['inventory.view']},
    state => state.user.value = {id: 1, permissions: []}, state => state.connectionLost.value = true,
    state => state.server.value = {id: 'other', fingerprint: 'new'}]) {
    const pending = deferred(), {state, actions} = fixture(t, () => pending.promise)
    const draft = JSON.stringify(state.otherInboundForm.value)
    const load = actions.loadMaterialSupply(1); await Promise.resolve(); mutate(state)
    pending.resolve(result([1])); assert.equal(await load, false)
    assert.deepEqual(state.materialSupplyRows.value, {}); assert.deepEqual(state.materialSupplyLoading.value, {})
    assert.equal(JSON.stringify(state.otherInboundForm.value), draft)
  }
})

test('业务入库更新使缓存失效，失败和错配响应显示错误，重试能恢复', async t => {
  let mode = 'ok'
  const {state, actions} = fixture(t, async () => {
    if (mode === 'fail') throw Error('服务读取失败')
    return result([mode === 'mismatch' ? 2 : 1])
  })
  assert.equal(await actions.loadMaterialSupply(1), true)
  state.receipts.value = []; assert.deepEqual(state.materialSupplyRows.value, {})
  for (mode of ['fail', 'mismatch']) {
    assert.equal(await actions.loadMaterialSupply(1, true), false)
    assert.ok(state.materialSupplyErrors.value[1]); assert.equal(state.materialSupplyRows.value[1], undefined)
  }
  mode = 'ok'; assert.equal(await actions.loadMaterialSupply(1, true), true)
  assert.equal(state.materialSupplyErrors.value[1], undefined)
})

// 显式启用才增加一列，保留固定操作列和调用方原始定义。
test('共享供需列放在操作之前，关闭时不改变原表格布局', () => {
  const columns = [{key: 'sku', title: '编码'}, {key: 'actions', title: '操作', fixed: 'right'}]
  assert.equal(materialSupplyColumns(columns, false), columns)
  const displayed = materialSupplyColumns(columns, true)
  assert.deepEqual(displayed.map(row => row.key), ['sku', 'materialSupply', 'actions'])
  assert.equal(displayed[2].fixed, 'right'); assert.equal(columns.length, 2)
  assert.deepEqual(materialSupplyColumns(columns.slice(0, 1), true).map(row => row.key), ['sku', 'materialSupply'])
})

test('可见物料共用一个刷新时钟，重复行不重复请求，关闭后释放定时读取', async t => {
  let tick, timers = 0
  const cleared = [], calls = []
  t.mock.method(globalThis, 'setInterval', callback => { tick = callback; timers++; return 42 })
  t.mock.method(globalThis, 'clearInterval', id => cleared.push(id))
  const {actions} = fixture(t, async (_operation, input) => { calls.push(input.material_ids); return result(input.material_ids) })
  const stop = [actions.subscribeMaterialSupply(1), actions.subscribeMaterialSupply(1), actions.subscribeMaterialSupply(2)]
  await new Promise(setImmediate)
  assert.equal(timers, 1); assert.deepEqual(calls, [[1, 2]])
  tick(); await new Promise(setImmediate)
  assert.deepEqual(calls, [[1, 2], [1, 2]])
  stop[0](); assert.deepEqual(cleared, [])
  stop[1](); stop[2](); assert.deepEqual(cleared, [42])
})
