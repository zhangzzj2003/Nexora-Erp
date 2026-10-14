import type { DocumentApprovalState } from './document-approval-api'
import { receiptLotMilli } from './receipt-lot-api.ts'

// 四类业务共用数量契约，但发出、签收、收旧和退库始终保留各自事实。
export const materialFlowKinds = ['dispatch', 'receipt', 'exchange', 'return'] as const
export type MaterialFlowKind = typeof materialFlowKinds[number]
export type MaterialFlowStatus = 'draft' | 'partial' | 'completed' | 'closed' | 'reversed'
export interface MaterialFlowLine {
  id: number; work_order_line_id: number; material_id: number; sku: string; material_name: string; unit: string
  quantity: string; executed_quantity: string; received_quantity: string; remaining_quantity: string; dispatched_quantity?: string
  closed_quantity?: string; handover_returned_quantity?: string; replacement_available_quantity?: string
  source_receipt_line_id: number | null; legacy_issue_line_id: number | null; exchange_line_id: number | null
  source_document_kind?: MaterialFlowKind | 'legacy_issue' | null; source_document_id?: number | null; source_document_no?: string | null
  disposal?: 'physical' | 'loss'; evidence?: string
}
export interface MaterialFlowExecutionLine {
  id?: number; line_id: number; quantity: string; movement_id?: number | null
  source_movement_id?: number | null; reverses_line_id?: number | null
  lots?: { lot_id: number; code: string; quantity: string }[]
}
export interface MaterialFlowExecution {
  id: number; action: string; quantity?: string; created_at: string; created_by_name?: string
  actor_name?: string; reason?: string; lines?: MaterialFlowExecutionLine[]
}
export interface MaterialFlowDocument {
  id: number; document_no: string; kind: MaterialFlowKind; work_order_id: number; work_order_document_no: string
  product_name: string; warehouse_id: number; warehouse_name: string; status: MaterialFlowStatus; version: number
  reference: string; reason: string; note: string; created_by: number; created_by_name: string; created_at: string
  source_document_no: string | null; source_document_id?: number | null; source_document_kind?: MaterialFlowKind | 'legacy_issue' | null
  approval: DocumentApprovalState | null; lines: MaterialFlowLine[]; executions: MaterialFlowExecution[]
  planned_quantity: string; executed_quantity: string; received_quantity: string; remaining_quantity: string; damaged_quantity: string
}
export interface MaterialFlowQuery {
  kind: MaterialFlowKind; page: number; page_size: number; q?: string; status?: string; warehouse_id?: number
  created_by?: number; date_from?: string; date_to?: string; work_order_id?: number; timezone_offset_minutes?: number
}
export interface MaterialFlowPage { items: MaterialFlowDocument[]; total: number; page: number; page_size: number; summary: Record<string, number>; actors?: { id: number; name: string }[]; work_orders?: { id: number; document_no: string; product_name: string; warehouse_id: number; status: string }[]; warehouses?: { id: number; name: string }[] }
export interface MaterialFlowSource {
  source_receipt_line_id: number | null; legacy_issue_line_id: number | null; work_order_line_id: number
  material_id: number; sku: string; material_name: string; unit: string; source_document_no: string
  quantity: string; available_quantity: string; warehouse_id?: number
}
export interface WorkOrderMaterialFlow {
  work_order_id: number
  lines: { work_order_line_id: number; material_id: number; sku: string; material_name: string; unit: string
    required_quantity: string; signed_quantity: string; returned_quantity: string; damaged_quantity: string; in_transit_quantity?: string; historical_direct_quantity?: string
    reserved_quantity: string; effective_quantity: string; available_quantity?: string; dispatchable_quantity: string }[]
  sources: MaterialFlowSource[]; dispatches: MaterialFlowDocument[]; receipts: MaterialFlowDocument[]
  exchanges: MaterialFlowDocument[]; returns: MaterialFlowDocument[]
}
export interface MaterialFlowDraftLine {
  work_order_line_id: number; quantity: string; source_receipt_line_id?: number; legacy_issue_line_id?: number
  exchange_line_id?: number; disposal?: 'physical' | 'loss'; evidence?: string
}
export interface MaterialFlowCreate {
  kind: Exclude<MaterialFlowKind, 'receipt'>; work_order_id: number; warehouse_id: number
  request_id: string; reference?: string; reason?: string; note?: string; lines: MaterialFlowDraftLine[]
}
export interface MaterialFlowTarget { kind: MaterialFlowKind; id: number }
export interface MaterialFlowWrite extends MaterialFlowTarget { version: number; request_id: string; reason?: string }
export interface MaterialFlowExecute extends MaterialFlowWrite {
  lines: { line_id: number; quantity: string; lots?: { lot_id: number; quantity: string }[] }[]
}
export interface MaterialFlowLots { lines: { line_id: number; lots: { lot_id: number; code: string; quantity: string }[] }[] }
export interface MaterialFlowOperations {
  materialFlowQuery: { input: MaterialFlowQuery; output: MaterialFlowPage }
  materialFlowDetail: { input: MaterialFlowTarget; output: MaterialFlowDocument }
  createMaterialFlow: { input: MaterialFlowCreate; output: MaterialFlowDocument }
  updateMaterialFlow: { input: MaterialFlowCreate & { id: number; version: number }; output: MaterialFlowDocument }
  executeMaterialFlow: { input: MaterialFlowExecute; output: MaterialFlowDocument }
  handoverReturnMaterialFlow: { input: MaterialFlowExecute; output: MaterialFlowDocument }
  closeMaterialFlow: { input: MaterialFlowWrite; output: MaterialFlowDocument }
  reverseMaterialFlow: { input: MaterialFlowWrite; output: MaterialFlowDocument }
  createExchangeDispatch: { input: MaterialFlowWrite; output: MaterialFlowDocument }
  materialFlowLots: { input: MaterialFlowTarget; output: MaterialFlowLots }
  workOrderMaterialFlow: { input: { orderId: number }; output: WorkOrderMaterialFlow }
}
const bases: Record<MaterialFlowKind, string> = {
  dispatch: 'material-dispatches', receipt: 'material-receipts', exchange: 'material-exchanges', return: 'material-returns/flow'
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('生产物料参数无效')
  return value as Record<string, unknown>
}
function id(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw Error('生产物料编号无效')
  return value
}
function text(value: unknown, max = 500): string {
  if (value === undefined) return ''
  if (typeof value !== 'string' || value.length > max || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value)) throw Error('生产物料文字参数无效')
  return value.trim()
}
function quantity(value: unknown): string {
  if (typeof value !== 'string' || receiptLotMilli(value) === null) throw Error('数量须为最多三位小数的正数')
  return value
}
function kind(value: unknown): MaterialFlowKind {
  if (!(materialFlowKinds as readonly unknown[]).includes(value)) throw Error('生产物料类型无效')
  return value as MaterialFlowKind
}
function requestId(value: unknown): string {
  const result = text(value, 100)
  if (!/^[A-Za-z0-9_-]{8,100}$/.test(result)) throw Error('请重新发起本次生产物料操作')
  return result
}
function lines(value: unknown, execute: boolean): Record<string, unknown>[] {
  if (!Array.isArray(value) || !value.length || value.length > 100) throw Error('请选择一至一百行物料')
  const seen = new Set<string>()
  return value.map(entry => {
    const row = record(entry), key = execute ? 'line_id' : 'work_order_line_id'
    const result: Record<string, unknown> = { [key]: id(row[key]), quantity: quantity(row.quantity) }
    if (!execute) {
      for (const source of ['source_receipt_line_id', 'legacy_issue_line_id', 'exchange_line_id'])
        if (row[source] !== undefined) result[source] = id(row[source])
      if (row.source_receipt_line_id !== undefined && row.legacy_issue_line_id !== undefined) throw Error('每行只能选择一个领料来源')
      if (row.disposal !== undefined) {
        if (!['physical', 'loss'].includes(String(row.disposal))) throw Error('旧料处理方式无效')
        result.disposal = row.disposal; result.evidence = text(row.evidence)
        if (row.disposal === 'loss' && !result.evidence) throw Error('无实物损耗须填写审批依据')
      }
    }
    const unique = `${result[key]}:${result.source_receipt_line_id ?? ''}:${result.legacy_issue_line_id ?? ''}:${result.exchange_line_id ?? ''}`
    if (seen.has(unique)) throw Error('同一来源物料不能重复添加')
    seen.add(unique)
    if (execute && row.lots !== undefined) {
      if (!Array.isArray(row.lots) || !row.lots.length || row.lots.length > 20) throw Error('实物批次数量无效')
      const lots = new Set<number>()
      result.lots = row.lots.map(entry => {
        const part = record(entry), lotId = id(part.lot_id)
        if (lots.has(lotId)) throw Error('实物批次不能重复')
        lots.add(lotId)
        return { lot_id: lotId, quantity: quantity(part.quantity) }
      })
      const sum = (result.lots as { quantity: string }[]).reduce((total, part) => total + receiptLotMilli(part.quantity)!, 0n)
      if (sum !== receiptLotMilli(result.quantity as string)) throw Error('实物批次合计须等于本次执行数量')
    }
    return result
  })
}
// IPC 只能选择固定业务路径，丢弃页面夹带的审批状态、库存数量等服务端字段。
export function materialFlowRequest(action: string, value: unknown): { method: string; path: string; body?: unknown } | undefined {
  if (!['materialFlowQuery', 'materialFlowDetail', 'createMaterialFlow', 'updateMaterialFlow', 'executeMaterialFlow',
    'handoverReturnMaterialFlow', 'closeMaterialFlow', 'reverseMaterialFlow', 'createExchangeDispatch', 'materialFlowLots', 'workOrderMaterialFlow'].includes(action)) return
  const row = record(value)
  if (action === 'workOrderMaterialFlow') return { method: 'GET', path: `/api/v1/work-orders/${id(row.orderId)}/material-flow` }
  const type = kind(row.kind), base = `/api/v1/${bases[type]}`
  if (action === 'materialFlowQuery') {
    const query = new URLSearchParams({ page: String(id(row.page)), page_size: String(id(row.page_size)) })
    if (Number(row.page_size) > 100) throw Error('每页数量不能超过一百条')
    for (const key of ['warehouse_id', 'created_by', 'work_order_id']) if (row[key] !== undefined) query.set(key, String(id(row[key])))
    for (const key of ['q', 'status', 'date_from', 'date_to']) if (row[key]) query.set(key, text(row[key], 200))
    if (row.status && !['draft', 'partial', 'completed', 'closed', 'reversed'].includes(String(row.status))) throw Error('生产物料状态无效')
    for (const key of ['date_from', 'date_to']) if (row[key] && !/^\d{4}-\d{2}-\d{2}$/.test(String(row[key]))) throw Error('日期格式无效')
    if (row.timezone_offset_minutes !== undefined) {
      const offset = row.timezone_offset_minutes
      if (typeof offset !== 'number' || !Number.isInteger(offset) || offset < -840 || offset > 840) throw Error('日期时区参数无效')
      query.set('timezone_offset_minutes', String(offset))
    }
    return { method: 'GET', path: `${base}?${query}` }
  }
  if (['createMaterialFlow', 'updateMaterialFlow'].includes(action)) {
    if (type === 'receipt') throw Error('领料单由实际发料自动生成')
    const body = { work_order_id: id(row.work_order_id), warehouse_id: id(row.warehouse_id), request_id: requestId(row.request_id),
      reference: text(row.reference, 100), reason: text(row.reason, 200), note: text(row.note), lines: lines(row.lines, false),
      ...(action === 'updateMaterialFlow' ? { version: id(row.version) } : {}) }
    if (['exchange', 'return'].includes(type) && !body.reason) throw Error('请填写退换料原因')
    return { method: action === 'updateMaterialFlow' ? 'PUT' : 'POST', path: action === 'updateMaterialFlow' ? `${base}/${id(row.id)}` : base, body }
  }
  const path = `${base}/${id(row.id)}`
  if (action === 'materialFlowDetail') return { method: 'GET', path }
  if (action === 'materialFlowLots') return { method: 'GET', path: `${path}/available-lots` }
  const body = { version: id(row.version), request_id: requestId(row.request_id), reason: text(row.reason, 200) }
  if (['closeMaterialFlow', 'reverseMaterialFlow', 'handoverReturnMaterialFlow'].includes(action) && !body.reason) throw Error('请填写本次操作原因')
  if (action === 'createExchangeDispatch' && type !== 'exchange' || action === 'handoverReturnMaterialFlow' && type !== 'receipt') throw Error('操作与单据类型不匹配')
  const suffix = { executeMaterialFlow: 'execute', handoverReturnMaterialFlow: 'handover-return', closeMaterialFlow: 'close', reverseMaterialFlow: 'reverse', createExchangeDispatch: 'create-dispatch' }[action]
  return { method: 'POST', path: `${path}/${suffix}`, body: { ...body,
    ...(['executeMaterialFlow', 'handoverReturnMaterialFlow'].includes(action) ? { lines: lines(row.lines, true) } : {}) } }
}

// 在边界拒绝错单和不完整响应，防止旧服务或跨页请求把数量显示到另一张单上。
export function validateMaterialFlowDocument(value: unknown, expected?: MaterialFlowTarget): asserts value is MaterialFlowDocument {
  const row = record(value)
  id(row.id); id(row.version); kind(row.kind); id(row.work_order_id); id(row.warehouse_id)
  if (expected && (row.id !== expected.id || row.kind !== expected.kind)) throw Error('返回的生产物料单据不匹配')
  if (typeof row.document_no !== 'string' || !row.document_no || !Array.isArray(row.lines) || !Array.isArray(row.executions)) throw Error('生产物料单据响应不完整')
  for (const entry of row.lines) {
    const line = record(entry); id(line.id); id(line.material_id); id(line.work_order_line_id)
    for (const key of ['quantity', 'executed_quantity', 'received_quantity', 'remaining_quantity'])
      if (typeof line[key] !== 'string' || !/^\d+(?:\.\d{1,3})?$/.test(line[key] as string)) throw Error('生产物料数量响应无效')
  }
}
export function validateMaterialFlowResult(action: string, value: unknown, payload: unknown): void {
  if (action === 'materialFlowQuery') {
    const row = record(value)
    if (!Array.isArray(row.items) || !Number.isSafeInteger(row.total) || Number(row.total) < 0 || !row.summary) throw Error('生产物料列表响应无效')
    id(row.page); id(row.page_size)
    for (const item of row.items) { validateMaterialFlowDocument(item); if (item.kind !== record(payload).kind) throw Error('生产物料列表类型不匹配') }
  } else if (action === 'workOrderMaterialFlow') {
    const row = record(value)
    if (row.work_order_id !== record(payload).orderId || !Array.isArray(row.lines) || !Array.isArray(row.sources)) throw Error('工单物料汇总响应无效')
    for (const key of ['dispatches', 'receipts', 'exchanges', 'returns']) {
      if (!Array.isArray(row[key])) throw Error('工单关联单据响应无效')
      for (const item of row[key] as unknown[]) validateMaterialFlowDocument(item)
    }
  } else if (action === 'materialFlowLots') {
    const row = record(value)
    if (!Array.isArray(row.lines)) throw Error('可用实物批次响应无效')
    for (const entry of row.lines) {
      const line = record(entry); id(line.line_id)
      if (!Array.isArray(line.lots)) throw Error('可用实物批次响应无效')
      for (const entry of line.lots) { const lot = record(entry); id(lot.lot_id); if (typeof lot.code !== 'string' || typeof lot.quantity !== 'string') throw Error('可用实物批次响应无效') }
    }
  } else if (['materialFlowDetail', 'createMaterialFlow', 'updateMaterialFlow', 'executeMaterialFlow', 'handoverReturnMaterialFlow', 'closeMaterialFlow', 'reverseMaterialFlow', 'createExchangeDispatch'].includes(action)) {
    const row = record(payload)
    validateMaterialFlowDocument(value, ['createMaterialFlow', 'createExchangeDispatch'].includes(action) ? undefined : { kind: kind(row.kind), id: id(row.id) })
  }
}
