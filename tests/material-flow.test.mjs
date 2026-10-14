import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateDocumentApprovalResponse } from '../src/shared/document-approval-api.ts'
import { callBackend } from '../src/main/backend.ts'
import { materialFlowRequest, validateMaterialFlowDocument, validateMaterialFlowResult } from '../src/shared/material-flow-api.ts'
import { materialFlowExecutionHint, materialFlowExecutionLabels, materialFlowApprovalExecutionHint } from '../src/renderer/src/utils/material-flow-progress.ts'
import { routeByKey, routeGroupByKey, canVisitRoute } from '../src/renderer/src/router/workspace-routes.ts'

// 通过真实 IPC 验证权限边界之外的输入与响应，不以字符串查找代替业务测试。
const doc = (kind = 'dispatch') => ({ id: 7, document_no: 'SCFL-20261014-000007', kind, work_order_id: 2,
  work_order_document_no: 'SCGD-20261014-000002', product_name: '机器', warehouse_id: 1, warehouse_name: '主仓库',
  status: 'partial', version: 2, reference: '', reason: '', note: '', created_by: 1, created_by_name: '仓管', created_at: '2026-10-14 08:00:00',
  source_document_no: null, approval: kind === 'receipt' ? null : { status: 'draft', version: 0, generation: 0, current_step: 0, steps: [], policy_version: null, submitted_by: null, submitted_at: null, executed_by: null, executed_at: null }, planned_quantity: '100', executed_quantity: '60', received_quantity: '58', remaining_quantity: '40', damaged_quantity: '0',
  lines: [{ id: 3, work_order_line_id: 4, material_id: 5, sku: 'M5', material_name: '上盖', unit: '个', quantity: '100', executed_quantity: '60', received_quantity: '58', remaining_quantity: '40',
    source_receipt_line_id: null, legacy_issue_line_id: null, exchange_line_id: null }], executions: [] })
const write = { kind: 'dispatch', id: 7, version: 2, request_id: 'test-request-0001', lines: [{ line_id: 3, quantity: '2.125', lots: [{ lot_id: 11, quantity: '1.125' }, { lot_id: 12, quantity: '1' }] }] }

test('四个仓库页面共享查看权限，但保持独立路由', () => {
  for (const [suffix, path] of [['Dispatches', 'dispatches'], ['Receipts', 'receipts'], ['Exchanges', 'exchanges'], ['Returns', 'returns']]) {
    const route = routeByKey(`production${suffix}`)
    assert.equal(route.path, `/workspace/production-${path}`)
    assert.equal(routeGroupByKey(route.key).key, 'warehouse')
    assert.equal(canVisitRoute(route, ['material_flow.view']), true)
    assert.equal(canVisitRoute(route, ['inventory.view']), false)
  }
})

test('部分执行 IPC 固定四类路径并保留版本和防重复标识', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, body: options.body })
    if (url.pathname.endsWith('/login')) return Response.json({ token: 'test', user: { id: 1 } })
    return Response.json(doc())
  })
  await callBackend('login', {})
  await callBackend('executeMaterialFlow', { ...write, status: 'completed', created_by: 99 })
  assert.equal(calls.at(-1).path, '/api/v1/material-dispatches/7/execute')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { version: 2, request_id: write.request_id, reason: '', lines: write.lines })
  for (const [kind, base] of [['dispatch', 'material-dispatches'], ['receipt', 'material-receipts'], ['exchange', 'material-exchanges'], ['return', 'material-returns/flow']]) {
    const request = materialFlowRequest('materialFlowDetail', { kind, id: 7 })
    assert.equal(request.path, `/api/v1/${base}/7`)
  }
  const before = calls.length
  for (const change of [{ kind: '../users' }, { id: '../users' }, { version: 0 }, { request_id: '' }, { lines: [{ line_id: 3, quantity: '-2' }] },
    { lines: [write.lines[0], write.lines[0]] }, { lines: [{ line_id: 3, quantity: '3', lots: write.lines[0].lots }] }]) {
    await assert.rejects(callBackend('executeMaterialFlow', { ...write, ...change }))
  }
  assert.equal(calls.length, before)
})

test('签收和交接退回分开，不能创建领料申请或跨类型补发', () => {
  assert.equal(materialFlowRequest('executeMaterialFlow', { ...write, kind: 'receipt', lines: [{ line_id: 3, quantity: '58' }] }).path, '/api/v1/material-receipts/7/execute')
  assert.equal(materialFlowRequest('handoverReturnMaterialFlow', { ...write, kind: 'receipt', reason: '未交付的实物已回仓' }).path, '/api/v1/material-receipts/7/handover-return')
  assert.throws(() => materialFlowRequest('handoverReturnMaterialFlow', { ...write, kind: 'receipt' }), /原因/)
  assert.throws(() => materialFlowRequest('createExchangeDispatch', write), /类型不匹配/)
  assert.throws(() => materialFlowRequest('createMaterialFlow', { kind: 'receipt' }), /自动生成/)
})

test('退换来源唯一、无实物损耗有依据，服务端产生字段不由客户端传入', () => {
  const draft = { kind: 'exchange', work_order_id: 2, warehouse_id: 1, reason: '装配损坏', request_id: 'exchange-create-01',
    status: 'approved', lines: [{ work_order_line_id: 4, source_receipt_line_id: 3, quantity: '2', disposal: 'loss', evidence: '损耗记录 001' }] }
  const result = materialFlowRequest('createMaterialFlow', draft)
  assert.equal(result.body.status, undefined)
  assert.equal(result.body.lines[0].evidence, '损耗记录 001')
  assert.throws(() => materialFlowRequest('createMaterialFlow', { ...draft, lines: [{ ...draft.lines[0], evidence: '' }] }), /依据/)
  assert.throws(() => materialFlowRequest('createMaterialFlow', { ...draft, lines: [{ ...draft.lines[0], legacy_issue_line_id: 9 }] }), /一个领料来源/)
  assert.throws(() => materialFlowRequest('closeMaterialFlow', { ...write, reason: '' }), /原因/)
})

test('响应拒绝错单及非法数量，分页查询不把当前页当总量', () => {
  validateMaterialFlowDocument(doc(), { kind: 'dispatch', id: 7 })
  validateDocumentApprovalResponse(doc('receipt'))
  assert.throws(() => validateDocumentApprovalResponse({ ...doc(), approval: null }), /审批/)
  assert.throws(() => validateMaterialFlowDocument(doc(), { kind: 'receipt', id: 7 }), /不匹配/)
  assert.throws(() => validateMaterialFlowDocument({ ...doc(), lines: [{ ...doc().lines[0], received_quantity: '-2' }] }), /数量/)
  const page = { items: [doc()], total: 45, page: 2, page_size: 20, summary: { draft: 20, partial: 25 } }
  validateMaterialFlowResult('materialFlowQuery', page, { kind: 'dispatch' })
  assert.equal(page.total, 45)
  assert.equal(page.summary.partial, 25)
  assert.throws(() => validateMaterialFlowResult('materialFlowQuery', page, { kind: 'return' }), /类型不匹配/)
  const query = materialFlowRequest('materialFlowQuery', { kind: 'dispatch', page: 2, page_size: 20, q: '上盖 & 100', work_order_id: 2, status: 'partial', created_by: 7, date_from: '2026-10-01', date_to: '2026-10-14' })
  const params = new URL(query.path, 'http://local').searchParams
  assert.equal(params.get('q'), '上盖 & 100'); assert.equal(params.get('work_order_id'), '2'); assert.equal(params.get('page'), '2')
  assert.throws(() => materialFlowRequest('materialFlowQuery', { kind: 'dispatch', page: 1, page_size: 101 }), /一百/)
})


test('首批执行后的审批提示分别保留待发、待签及待收进度', () => {
  const partial = doc()
  const dispatched = materialFlowExecutionHint(partial)
  assert.match(dispatched, /仍待发：M5 40 个/); assert.match(dispatched, /生产签收进度另行记录/)
  assert.doesNotMatch(dispatched, /审批与业务执行均已完成/)
  assert.match(materialFlowExecutionHint({ ...partial, status: 'completed' }), /发出完成不代表生产已签收/)
  assert.match(materialFlowExecutionHint(doc('exchange')), /全部签收后才完成换料/)
  assert.match(materialFlowExecutionHint(doc('return')), /仍待收：M5 40 个/)
  assert.match(materialFlowExecutionHint({ ...partial, status: 'closed' }), /未执行余额已关闭/)
  assert.equal(materialFlowExecutionHint(doc('receipt')), '')
})

test('全部生产物料执行动作显示中文，生成补发、编辑和关闭冲销不泄露内部动作名', () => {
  const labels = { edit: '修改草稿', execute: '分批执行', handover_return: '交接退回',
    create_dispatch: '生成补发单', close: '关闭余额', reverse: '审批更正 / 冲销' }
  for (const [action, label] of Object.entries(labels)) assert.equal(materialFlowExecutionLabels[action], label)
})


test('本地日期时区严格透传，补发的同物料多换料来源分别保留', () => {
  const query = { kind: 'dispatch', page: 1, page_size: 20, date_from: '2026-10-14', timezone_offset_minutes: -480 }
  const path = materialFlowRequest('materialFlowQuery', query).path
  assert.equal(new URL(path, 'http://local').searchParams.get('timezone_offset_minutes'), '-480')
  for (const offset of [-841, 841, 0.5, '-480']) assert.throws(() => materialFlowRequest('materialFlowQuery', { ...query, timezone_offset_minutes: offset }), /时区/)
  const result = materialFlowRequest('updateMaterialFlow', { kind: 'dispatch', id: 7, version: 1, work_order_id: 2, warehouse_id: 1, request_id: 'replacement-01', lines: [
    { work_order_line_id: 4, exchange_line_id: 8, quantity: '1' }, { work_order_line_id: 4, exchange_line_id: 9, quantity: '2' }
  ] })
  assert.deepEqual(result.body.lines.map(line => line.exchange_line_id), [8, 9])
})


test('库存只读审批快照复用生产进度提示，不把计划数量当作剩余额度', () => {
  const record = { document_type: 'MaterialDispatch', intent: 'execute', business_status: 'partial' }
  assert.match(materialFlowApprovalExecutionHint(record), /仍有数量待发.*生产签收进度另行记录/)
  assert.match(materialFlowApprovalExecutionHint({ ...record, business_status: 'completed' }), /发出完成不代表生产已签收/)
  assert.match(materialFlowApprovalExecutionHint({ ...record, business_status: 'closed' }), /未执行余额已关闭/)
  assert.match(materialFlowApprovalExecutionHint({ ...record, document_type: 'ProductionMaterialReturn' }), /仍有数量待收.*不会提前增加库存/)
  for (const variant of [null, { ...record, document_type: 'MaterialReceipt' }, { ...record, intent: 'reverse' }, { ...record, document_type: 'WarehouseInbound' }])
    assert.equal(materialFlowApprovalExecutionHint(variant), undefined)
})
