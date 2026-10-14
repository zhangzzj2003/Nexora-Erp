import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { execFileSync } from 'node:child_process'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createInventoryLedgerDetailActions } from '../src/renderer/src/store/modules/inventory-ledger-detail-actions.ts'
import { validateInventoryLedgerDocument } from '../src/shared/inventory-ledger-document.ts'
import { callBackend } from '../src/main/backend.ts'

export const ledgerRow = { id: 19, material_id: 3, sku: 'EL-03', material_name: '连接器 · 2P', warehouse_id: 1,
  warehouse_name: '主仓库', unit: '个', quantity: '100', balance_quantity: '1234', source_type: 'other_inbound',
  source_id: 8, source_line_id: 7, source_document_no: 'QTRK-20261013-000002', created_at: '2026-10-13T05:47:44Z', created_by_name: '处理人甲' }
export const documentRecord = { document_type: 'WarehouseInbound', document_id: 8, intent: 'execute',
  document_no: ledgerRow.source_document_no, business_status: 'posted', reversal_reason: '',
  summary: [{ label: '仓库', value: '主仓库' }, { label: 'EL-03 · 连接器', value: '100 个' }],
  content_matches: true, can_submit: false, can_review: false, can_withdraw: false, events: [],
  version: 0, status: 'draft', generation: 0, current_step: 0, steps: [], policy_version: null,
  submitted_by: null, submitted_at: null, executed_by: null, executed_at: null }
const pageResult = (page = 1, row = ledgerRow, pageSize = 20) => ({ rows: [row],
  groups: [{ ...row, opening_quantity: '1134', closing_quantity: '1234' }], total: 41, page, page_size: pageSize })
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
function setup(t, response) {
  const old = globalThis.window
  const scope = effectScope(), state = createAppState(), calls = []
  state.user.value = { id: 1, roles: ['admin', 'viewer'], permissions: ['inventory.view', 'inventory_report.view'] }
  globalThis.window = { nexora: { callApi: async (op, input) => {
    calls.push([op, structuredClone(input)])
    if (response) return response(op, input)
    if (op === 'materialDetail') return { id: input.id, sku: 'EL-03', name: '连接器' }
    if (op === 'inventoryLedgerDocument') return { movement_id: input.movement_id, document: documentRecord }
    return pageResult(input.page, ledgerRow, input.page_size)
  } } }
  const actions = scope.run(() => createInventoryLedgerDetailActions(state))
  t.after(() => { scope.stop(); globalThis.window = old })
  return { state, actions, calls }
}

test('台账物料详情独立分页，保留完整范围汇总和主表页码', async t => {
  const { state, actions, calls } = setup(t)
  state.ledgerQuery.value = { warehouse_id: 1, material_id: null, from_date: '2026-10-01', to_date: '2026-10-13', source_type: 'other_inbound', page: 3, page_size: 10 }
  state.ledgerResult.value = pageResult(3)
  const before = JSON.stringify([state.ledgerQuery.value, state.ledgerResult.value])
  await actions.openLedgerMaterial(ledgerRow)
  assert.deepEqual(calls[0], ['materialDetail', { id: 3 }])
  assert.deepEqual(calls[1][1], { ...state.ledgerQuery.value, material_id: 3, page: 1, page_size: 20 })
  await actions.queryLedgerMaterial(2)
  assert.equal(state.ledgerMaterialQuery.value.page, 2)
  assert.equal(state.ledgerMaterialResult.value.groups[0].closing_quantity, '1234')
  await actions.queryLedgerMaterial(4, 10)
  assert.equal(calls.at(-1)[1].page, 1)
  await actions.openLedgerDocument(ledgerRow)
  assert.deepEqual(calls.at(-1), ['inventoryLedgerDocument', { movement_id: 19 }])
  assert.equal(state.ledgerDocumentRecord.value.document_id, 8)
  actions.closeLedgerDocument()
  assert.equal(state.ledgerMaterialTarget.value.material_id, 3)
  state.user.value = { ...state.user.value, roles: [...state.user.value.roles].reverse(), permissions: [...state.user.value.permissions].reverse() }
  assert.equal(state.ledgerMaterialTarget.value.material_id, 3)
  actions.closeLedgerMaterial()
  assert.equal(JSON.stringify([state.ledgerQuery.value, state.ledgerResult.value]), before)
})

test('报表详情使用稳定编号及行仓库，余额忽略隐藏的开始日期，收发存保留日期', async t => {
  const { state, actions, calls } = setup(t)
  const row = { material_id: '3', warehouse_id: '1', sku: 'EL-03', material_name: '包含 · 分隔符的物料' }
  state.inventoryReportQuery.value = { ...state.inventoryReportQuery.value, page: 4, from_date: '2026-10-10', to_date: '2026-10-13' }
  await actions.openReportMaterial(row)
  assert.equal(state.ledgerMaterialQuery.value.from_date, null)
  assert.equal(state.ledgerMaterialQuery.value.to_date, '2026-10-13')
  assert.equal(state.ledgerMaterialQuery.value.warehouse_id, 1)
  assert.equal(state.ledgerMaterialTarget.value.material_name, row.material_name)
  assert.equal(state.inventoryReportQuery.value.page, 4)
  state.inventoryReportQuery.value.kind = 'stock_flow'
  assert.equal(state.ledgerMaterialTarget.value, null)
  await actions.openReportMaterial(row)
  assert.equal(state.ledgerMaterialQuery.value.from_date, '2026-10-10')
  const before = calls.length
  await actions.openReportMaterial({ material: 'EL-03 · 连接器' })
  assert.equal(calls.length, before)
  assert.match(state.inventoryReportError.value, /升级服务端/)
  state.user.value.permissions = ['inventory_report.view']
  await actions.openReportMaterial(row)
  assert.equal(calls.length, before)
})

test('物料资料失败不报首屏就绪；分页失败保留旧正文；错误范围不能覆盖成功快照', async t => {
  let fail = true, wrong = false
  const { state, actions } = setup(t, async (op, input) => {
    if (op === 'materialDetail') throw Error('物料读取失败')
    if (fail && input.page === 2) throw Error('明细读取失败')
    return pageResult(input.page, wrong ? { ...ledgerRow, material_id: 99 } : ledgerRow)
  })
  assert.equal(await actions.openLedgerMaterial(ledgerRow), false)
  assert.match(state.ledgerMaterialError.value, /物料读取失败/)
  assert.equal(state.ledgerMaterialResult.value.rows.length, 1)
  assert.equal(await actions.queryLedgerMaterial(2), false)
  assert.equal(state.ledgerMaterialQuery.value.page, 2)
  assert.equal(state.ledgerMaterialResult.value.rows.length, 1)
  assert.match(state.ledgerMaterialRowsError.value, /明细读取失败/)
  fail = false
  await actions.queryLedgerMaterial(state.ledgerMaterialQuery.value.page)
  assert.equal(state.ledgerMaterialRowsError.value, '')
  wrong = true
  assert.equal(await actions.queryLedgerMaterial(), false)
  assert.equal(state.ledgerMaterialResult.value.rows.length, 1)
  assert.match(state.ledgerMaterialRowsError.value, /范围或分页不匹配/)
  assert.equal(state.ledgerMaterialResult.value.rows[0].material_id, 3)
})

test('关闭、切换物料、筛选及断线阻止晚到的响应重开详情', async t => {
  const pending = []
  const { state, actions } = setup(t, (op, input) => {
    const job = deferred(); pending.push({ ...job, op, input }); return job.promise
  })
  const first = actions.openLedgerMaterial(ledgerRow)
  const second = actions.openLedgerMaterial({ ...ledgerRow, material_id: 4 })
  pending[0].resolve({ id: 3 }); pending[1].resolve(pageResult()); await first
  assert.equal(state.ledgerMaterialDetail.value, null)
  assert.equal(state.ledgerMaterialLoading.value, true)
  pending[2].resolve({ id: 4 }); pending[3].resolve(pageResult(1, { ...ledgerRow, material_id: 4 })); await second
  const documentRead = actions.openLedgerDocument(ledgerRow)
  actions.closeLedgerDocument()
  pending[4].resolve({ movement_id: 19, document: documentRecord }); await documentRead
  assert.equal(state.ledgerDocumentRecord.value, null)
  const pageRead = actions.queryLedgerMaterial(2)
  state.connectionLost.value = true
  pending[5].resolve(pageResult(2)); await pageRead
  assert.equal(state.ledgerMaterialTarget.value, null)
  state.connectionLost.value = false
  const third = actions.openLedgerMaterial(ledgerRow)
  state.ledgerQuery.value.to_date = '2026-11-01'
  pending[6].resolve({ id: 3 }); pending[7].resolve(pageResult()); await third
  assert.equal(state.ledgerMaterialTarget.value, null)
})

test('单据权限失败保留错误并可重试，错误流水身份不能显示', async t => {
  let mode = 'denied'
  const { state, actions } = setup(t, async (_, input) => {
    if (mode === 'denied') throw Error('没有查看此类单据的权限')
    return { movement_id: mode === 'wrong' ? 999 : input.movement_id, document: documentRecord }
  })
  await actions.openLedgerDocument(ledgerRow)
  assert.match(state.ledgerDocumentError.value, /权限/)
  assert.equal(state.ledgerDocumentLoading.value, false)
  mode = 'wrong'; await actions.loadLedgerDocument()
  assert.match(state.ledgerDocumentError.value, /不一致/)
  mode = 'ok'; await actions.loadLedgerDocument()
  assert.equal(state.ledgerDocumentRecord.value.document_id, 8)
  state.user.value = null
  assert.equal(state.ledgerDocumentTarget.value, null)
})

test('台账时间按设备时区显示两位年月日与时分，跨年不舍入秒数', () => {
  const output = execFileSync(process.execPath, ['--experimental-strip-types', '--input-type=module', '-e',
    `import {ledgerTime} from './src/renderer/src/utils/inventory-ledger-presentation.ts';console.log(JSON.stringify(['2026-10-13T05:47:44Z','2026-01-03 01:02:59','2026-12-31T16:00:59Z','未知'].map(ledgerTime)))`],
  { cwd: new URL('..', import.meta.url), env: { ...process.env, TZ: 'Asia/Shanghai' }, encoding: 'utf8' })
  assert.deepEqual(JSON.parse(output), ['26/10/13 13:47', '26/01/03 09:02', '27/01/01 00:00', '未知'])
})

test('台账单据 IPC 使用受限读取路径并校验流水与单据响应', async t => {
  const old = process.env.NEXORA_API_URL
  t.after(() => { if (old === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = old })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push([url.pathname, options.method])
    return Response.json(url.pathname.endsWith('/login') ? { token: 'test', user: { id: 1 } } : { movement_id: 19, document: documentRecord })
  })
  await callBackend('login', {})
  assert.equal((await callBackend('inventoryLedgerDocument', { movement_id: 19 })).document.document_id, 8)
  assert.deepEqual(calls.at(-1), ['/api/v1/inventory-ledger/19/document', 'GET'])
  await assert.rejects(callBackend('inventoryLedgerDocument', { movement_id: -1 }))
  await assert.rejects(callBackend('inventoryLedgerDocument', { movement_id: 20 }), /不一致/)
  assert.throws(() => validateInventoryLedgerDocument({ movement_id: 19, document: {} }, 19))
})

// 首屏须等资料和流水都完成，刷新复用已展示正文，关闭始终撤销这次展开意图。
test('库存详情复合读取只有全部成功才就绪，同单刷新保留正文并支持取消', async t => {
  let delayed = false
  const pending = []
  const { state, actions } = setup(t, (op, input) => {
    const result = op === 'materialDetail' ? { id: input.id, name: '连接器' } : pageResult(input.page)
    if (!delayed) return result
    const task = deferred(); pending.push({ ...task, result }); return task.promise
  })
  assert.equal(await actions.openLedgerMaterial(ledgerRow), true)
  const material = state.ledgerMaterialDetail.value, rows = state.ledgerMaterialResult.value
  delayed = true
  let ready = false
  const refresh = actions.openLedgerMaterial(ledgerRow).then(value => { ready = value; return value })
  assert.equal(state.ledgerMaterialDetail.value, material)
  assert.equal(state.ledgerMaterialResult.value, rows)
  pending[0].resolve(pending[0].result)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(ready, false)
  assert.equal(state.ledgerMaterialRowsLoading.value, true)
  pending[1].resolve(pending[1].result)
  assert.equal(await refresh, true)
  const cancelled = actions.openLedgerMaterial(ledgerRow)
  actions.closeLedgerMaterial()
  pending[2].resolve(pending[2].result); pending[3].resolve(pending[3].result)
  assert.equal(await cancelled, false)
  assert.equal(state.ledgerMaterialTarget.value, null)
})
