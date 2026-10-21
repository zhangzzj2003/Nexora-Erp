import type { MaterialChoice } from './material-api'
import type { Warehouse } from './erp-api'
import type { NumberedDocument } from './document-numbering'
import type { DocumentApprovalState } from './document-approval-api'
import { validateDocumentApprovalState } from './document-approval-api.ts'

// 计划正文与执行事实分别建模，客户端不能提交 BOM 快照、已下达量或审批结果。
export type ProductionPlanPriority = 'normal' | 'high' | 'urgent'
export interface ProductionPlanLineInput {
  bom_id: number; warehouse_id: number; sales_order_line_id: number | null; quantity: string
  start_date: string; end_date: string; priority: ProductionPlanPriority
  production_requirements?: string
}
export interface ProductionPlanInput { reference: string; note: string; reason: string; lines: ProductionPlanLineInput[] }
export interface ProductionPlanBom {
  id: number; material_id: number; version: number; base_quantity: string; sku: string; name: string; unit: string
  components: { material_id: number; quantity: string; component_bom_id: number | null }[]
}
export interface ProductionPlanSalesLine extends NumberedDocument {
  id: number; sales_order_id: number; reference: string; material_id: number
  quantity: string; remaining_quantity: string; available_quantity: string
}
export interface ProductionPlanOptions {
  today: string; boms: ProductionPlanBom[]; materials: MaterialChoice[]; warehouses: Warehouse[]
  sales_lines: ProductionPlanSalesLine[]
  unavailable_boms?: { id: number; reason: string }[]
}
export interface ProductionPlanLine extends ProductionPlanLineInput, NumberedDocument {
  id: number; plan_id: number; position: number; material_id: number; sku: string; name: string; unit: string
  bom_version: number; warehouse_name: string; sales_order_id: number | null; sales_reference: string
  released_quantity: string; unreleased_quantity: string; reported_quantity: string
  accepted_quantity: string; rejected_quantity: string; remaining_quantity: string; overdue: boolean
}
export interface ProductionPlanRelease extends NumberedDocument {
  id: number; plan_id: number; line_id: number; work_order_id: number; quantity: string
  work_order_status: string; reported_quantity: string; accepted_quantity: string; rejected_quantity: string
  request_id: string; reason: string; created_by: number; created_at: string
}
export interface ProductionPlan extends NumberedDocument {
  id: number; reference: string; note: string; reason: string; status: 'draft' | 'cancelled'; version: number
  created_by: number; created_at: string; approval: DocumentApprovalState
  progress: 'unreleased' | 'released' | 'in_progress' | 'completed'; can_edit: boolean
  line_count: number; overdue_count: number; start_date: string; end_date: string; products: string
}
export interface ProductionPlanDetail extends ProductionPlan {
  lines: ProductionPlanLine[]; releases: ProductionPlanRelease[]
  changes: { id: number; action: string; reason: string; changed_by: number; created_at: string; before: unknown; after: unknown }[]
}
export interface ProductionPlanReleaseInput {
  id: number; version: number; approval_version: number; line_id: number; quantity: string; reason: string; request_id: string
}
export interface ProductionPlanOperations {
  productionPlanDemands: { input: undefined; output: ProductionPlanDetail[] }
  productionPlans: { input: undefined; output: ProductionPlan[] }
  productionPlanOptions: { input: undefined; output: ProductionPlanOptions }
  productionPlanDetail: { input: { id: number }; output: ProductionPlanDetail }
  createProductionPlan: { input: ProductionPlanInput; output: ProductionPlanDetail }
  updateProductionPlan: { input: ProductionPlanInput & { id: number; version: number }; output: ProductionPlanDetail }
  cancelProductionPlan: { input: { id: number; version: number; reason: string }; output: ProductionPlanDetail }
  releaseProductionPlan: { input: ProductionPlanReleaseInput; output: ProductionPlanDetail }
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('生产计划数据格式不正确')
  return value as Record<string, unknown>
}
export function productionPlanId(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) throw Error('生产计划编号或版本无效')
  return value as number
}
// 要求独立提示长度与类型问题，避免误报成计划名称或操作依据。
function requirementText(value: unknown): string {
  if (typeof value !== 'string' || value.length > 500) throw Error('生产要求须为不超过 500 字的文字')
  return value.trim()
}
function text(value: unknown, limit: number, required = true): string {
  if (typeof value !== 'string' || value.length > limit || required && !value.trim()) throw Error('请填写有效的计划名称或操作依据')
  return value.trim()
}
export function productionPlanDate(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)
    || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) throw Error('请填写有效的计划日期')
  return value
}
export function productionPlanQuantity(value: unknown, allowZero = false): string {
  if (typeof value !== 'string' || !/^\d{1,7}(?:\.\d{1,3})?$/.test(value)
    || Number(value) > 1_000_000 || Number(value) < (allowZero ? 0 : 0.001)) throw Error('数量须大于零、最多三位小数且不超过一百万')
  return value
}
export function productionPlanBody(value: unknown): ProductionPlanInput {
  const row = object(value)
  if (!Array.isArray(row.lines) || !row.lines.length || row.lines.length > 100) throw Error('生产计划须包含 1 至 100 条产品明细')
  return { reference: text(row.reference, 100), reason: text(row.reason, 500), note: text(row.note, 500, false),
    lines: row.lines.map(value => {
      const line = object(value), start = productionPlanDate(line.start_date), end = productionPlanDate(line.end_date)
      if (line.bom_id === 0) throw Error('请选择生产产品和启用的 BOM 版本')
      if (line.warehouse_id === 0) throw Error('请选择完工目标仓库')
      if (end < start || (Date.parse(end) - Date.parse(start)) / 86400000 > 730) throw Error('完工日须在开工日起 730 天内')
      if (!['normal', 'high', 'urgent'].includes(String(line.priority))) throw Error('请选择有效优先级')
      return { ...(line.production_requirements !== undefined ? { production_requirements: requirementText(line.production_requirements) } : {}),
        bom_id: productionPlanId(line.bom_id), warehouse_id: productionPlanId(line.warehouse_id),
        sales_order_line_id: line.sales_order_line_id === null ? null : productionPlanId(line.sales_order_line_id),
        quantity: productionPlanQuantity(line.quantity), start_date: start, end_date: end, priority: line.priority as ProductionPlanPriority }
    }) }
}
export function productionPlanCommand(value: unknown, release: boolean): Record<string, unknown> {
  const row = object(value)
  const body: Record<string, unknown> = { version: productionPlanId(row.version), reason: text(row.reason, 500) }
  if (release) {
    const request = text(row.request_id, 80)
    if (!/^[a-zA-Z0-9-]{16,80}$/.test(request)) throw Error('下达请求编号无效，请重新打开')
    Object.assign(body, { approval_version: productionPlanId(row.approval_version), line_id: productionPlanId(row.line_id),
      quantity: productionPlanQuantity(row.quantity), request_id: request })
  }
  return body
}

export function validateProductionPlanResult(action: keyof ProductionPlanOperations, value: unknown, expectedId?: number): void {
  // 只接受完整的当前页面数据；坏响应不能被当作批准计划开放下达按钮。
  const validatePlan = (value: unknown, detail: boolean): void => {
    const row = object(value)
    productionPlanId(row.id); productionPlanId(row.version); validateDocumentApprovalState(row.approval)
    if (!['draft', 'cancelled'].includes(String(row.status)) || !['unreleased', 'released', 'in_progress', 'completed'].includes(String(row.progress))
      || typeof row.can_edit !== 'boolean' || !Number.isSafeInteger(row.line_count) || Number(row.line_count) < 1
      || !Number.isSafeInteger(row.overdue_count) || typeof row.reference !== 'string' || typeof row.products !== 'string') throw Error('生产计划响应格式不匹配，请升级服务端')
    productionPlanDate(row.start_date); productionPlanDate(row.end_date)
    if (expectedId !== undefined && row.id !== expectedId) throw Error('服务端返回了其他生产计划，请重新读取')
    if (!detail) return
    if (!Array.isArray(row.lines) || row.lines.length !== row.line_count || !Array.isArray(row.releases) || !Array.isArray(row.changes)) throw Error('生产计划详情不完整')
    const ids = new Set<number>()
    for (const entry of row.lines) {
      const line = object(entry), id = productionPlanId(line.id)
      if (ids.has(id) || line.plan_id !== row.id || typeof line.overdue !== 'boolean') throw Error('生产计划明细归属不一致')
      if (line.production_requirements !== undefined) requirementText(line.production_requirements)
      ids.add(id); productionPlanId(line.bom_id); productionPlanId(line.material_id); productionPlanId(line.warehouse_id)
      productionPlanDate(line.start_date); productionPlanDate(line.end_date); productionPlanQuantity(line.quantity)
      for (const key of ['released_quantity', 'unreleased_quantity', 'reported_quantity', 'accepted_quantity', 'rejected_quantity', 'remaining_quantity']) productionPlanQuantity(line[key], true)
      for (const key of ['sku', 'name', 'unit', 'warehouse_name']) if (typeof line[key] !== 'string') throw Error('生产计划产品资料不完整')
    }
    for (const entry of row.releases) {
      const release = object(entry)
      productionPlanId(release.id); productionPlanId(release.work_order_id); productionPlanQuantity(release.quantity)
      if (release.plan_id !== row.id || !ids.has(Number(release.line_id)) || typeof release.work_order_status !== 'string') throw Error('计划下达记录归属不一致')
    }
  }
  if (action === 'productionPlanDemands') {
    if (!Array.isArray(value)) throw Error('待生产需求响应不完整，请升级服务端')
    const ids = new Set<number>()
    for (const entry of value) {
      validatePlan(entry, true)
      const plan = entry as ProductionPlanDetail
      if (ids.has(plan.id) || plan.status === 'cancelled' || !['approved', 'executed'].includes(plan.approval.status)) throw Error('待生产计划状态不正确')
      ids.add(plan.id)
    }
    return
  }
  if (action === 'productionPlans') {
    if (!Array.isArray(value)) throw Error('生产计划列表格式不匹配')
    value.forEach(row => validatePlan(row, false)); return
  }
  if (action === 'productionPlanOptions') {
    const row = object(value)
    productionPlanDate(row.today)
    for (const key of ['boms', 'materials', 'warehouses', 'sales_lines']) {
      if (!Array.isArray(row[key])) throw Error('生产计划来源不完整')
      for (const item of row[key]) productionPlanId(object(item).id)
    }
    for (const entry of row.boms as unknown[]) {
      const bom = object(entry)
      productionPlanId(bom.material_id); productionPlanId(bom.version); productionPlanQuantity(bom.base_quantity)
      if (typeof bom.name !== 'string' || typeof bom.sku !== 'string' || !Array.isArray(bom.components)) throw Error('生产 BOM 格式不匹配')
    }
    for (const entry of row.sales_lines as unknown[]) {
      const sale = object(entry)
      productionPlanId(sale.material_id); productionPlanId(sale.sales_order_id)
      productionPlanQuantity(sale.available_quantity, true)
    }
    if (row.unavailable_boms !== undefined) {
      if (!Array.isArray(row.unavailable_boms)) throw Error('不可用 BOM 提示格式不匹配')
      for (const entry of row.unavailable_boms) {
        const bom = object(entry); productionPlanId(bom.id)
        if (typeof bom.reason !== 'string') throw Error('不可用 BOM 依据缺失')
      }
    }
    return
  }
  validatePlan(value, true)
}
