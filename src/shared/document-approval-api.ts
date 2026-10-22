import type { MaterialChoice } from './material-api'
import { validateMaterialMetadata } from './material-choice-validation.ts'
// 类型白名单与后端目录一致；领料仅更正需要审批，普通签收不申请独立审批。
export const documentApprovalTypes = [
  'PurchaseRequest', 'PurchaseOrder', 'PurchaseGoodsReceipt', 'Receipt', 'PurchaseReturn',
  'WarehouseInbound', 'WarehouseOutbound', 'Transfer', 'Stocktake', 'StockAdjustment',
  'CrmQuote', 'SalesOrder', 'Shipment', 'SalesReturn', 'AfterSalesCase',
  'WorkOrder', 'MaterialIssue', 'MaterialReturn', 'MaterialDispatch', 'MaterialReceipt', 'MaterialExchange', 'ProductionMaterialReturn', 'ProductionCompletion', 'QualityDisposition',
  'ProductionPlan', 'MrpPlan', 'ProductionCostSettlement', 'MaintenanceJob', 'Journal', 'OpeningBalance',
  'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ControlBalanceTransfer'
] as const
export type DocumentApprovalType = typeof documentApprovalTypes[number]
export type DocumentApprovalStepAction = 'review' | 'verify' | 'approve'
export interface DocumentApprovalStep { name: string; role: string | null; action?: DocumentApprovalStepAction }
export const amountApprovalTypes: readonly DocumentApprovalType[] = ['PurchaseRequest', 'PurchaseOrder', 'SalesOrder',
  'CrmQuote', 'Journal', 'ProductionCostSettlement', 'PaymentRecord', 'SubledgerPayment',
  'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ControlBalanceTransfer']
export interface DocumentApprovalBranch {
  name: string; min_amount: string; max_amount: string | null; steps: DocumentApprovalStep[]
}
export interface DocumentApprovalRouting {
  mode: 'amount' | 'reverse_default'; basis: string; amount: string | null
  branch: Omit<DocumentApprovalBranch, 'steps'> | null
}
// 兼容已固定的旧快照；新规则显式绑定动作，修改名称不会改变按钮授权。
export function documentApprovalStepAction(step: DocumentApprovalStep): DocumentApprovalStepAction {
  return step.action ?? (step.name.includes('核准') || step.name.includes('复核') ? 'verify'
    : step.name.includes('批准') ? 'approve' : 'review')
}
export const documentApprovalStepLabels = { review: '审核', verify: '核准', approve: '批准' } as const
export interface DocumentApprovalPolicy {
  document_type: DocumentApprovalType
  title: string
  version: number
  steps: DocumentApprovalStep[]
  branches?: DocumentApprovalBranch[]
  amount_basis?: string | null
  configured_by: number | null
  configured_at: string | null
}
export interface DocumentApprovalPolicyInput {
  document_type: DocumentApprovalType
  version: number
  steps: DocumentApprovalStep[]
  branches?: DocumentApprovalBranch[]
}
export interface DocumentApprovalOperations {
  documentApprovalPolicies: { input: undefined; output: DocumentApprovalPolicy[] }
  documentApprovalPolicy: { input: { document_type: DocumentApprovalType }; output: DocumentApprovalPolicy }
  saveDocumentApprovalPolicy: { input: DocumentApprovalPolicyInput; output: DocumentApprovalPolicy }
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('单据审批格式不正确')
  return value as Record<string, unknown>
}

export function documentApprovalType(value: unknown): DocumentApprovalType {
  const name = record(value).document_type
  if (typeof name !== 'string' || !(documentApprovalTypes as readonly string[]).includes(name)) {
    throw new Error('单据审批类型无效')
  }
  return name as DocumentApprovalType
}

function steps(value: unknown): DocumentApprovalStep[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 5) throw new Error('审批步骤须为一至五步')
  return value.map(item => {
    const step = record(item)
    if (Object.keys(step).some(key => !['name', 'role', 'action'].includes(key))
      || typeof step.name !== 'string' || !step.name.trim() || step.name.trim().length > 40
      || ('action' in step && (typeof step.action !== 'string' || !['review', 'verify', 'approve'].includes(step.action)))
      || !(step.role === null || typeof step.role === 'string' && /^[a-z][a-z0-9_]{2,39}$/.test(step.role))) {
      throw new Error('审批步骤名称或角色无效')
    }
    return { name: step.name.trim(), role: step.role as string | null,
      ...('action' in step ? { action: step.action as DocumentApprovalStepAction } : {}) }
  })
}

function cents(value: unknown): bigint {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]{0,18})(\.[0-9]{1,2})?$/.test(value)) throw Error('金额界限须为非负金额文本，最多两位小数')
  const [whole, fraction = ''] = value.split('.')
  const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  if (amount > 100000000000000000000n) throw Error('金额界限超过允许范围')
  return amount
}
function branchRange(value: unknown): Omit<DocumentApprovalBranch, 'steps'> {
  const row = record(value)
  if (typeof row.name !== 'string' || !row.name.trim() || row.name.trim().length > 40) throw Error('金额分支名称无效')
  const low = cents(row.min_amount)
  if (row.max_amount !== null && cents(row.max_amount) <= low) throw Error('金额上限须大于下限')
  return { name: row.name.trim(), min_amount: row.min_amount as string, max_amount: row.max_amount as string | null }
}
function branches(value: unknown, type: DocumentApprovalType): DocumentApprovalBranch[] {
  if (!Array.isArray(value) || value.length > 5) throw Error('金额分支最多五个')
  if (value.length && !amountApprovalTypes.includes(type)) throw Error('此类单据没有可用于审批分支的固定金额')
  const checked: DocumentApprovalBranch[] = []
  for (const item of value) {
    const row = record(item), range = branchRange(row)
    if (Object.keys(row).some(key => !['name', 'min_amount', 'max_amount', 'steps'].includes(key))) throw Error('金额分支字段无效')
    if (checked.some(other => other.name === range.name)) throw Error('金额分支名称不能重复')
    if (checked.some(other => (other.max_amount === null || cents(range.min_amount) < cents(other.max_amount))
      && (range.max_amount === null || cents(other.min_amount) < cents(range.max_amount)))) throw Error('金额分支区间不能重叠')
    checked.push({ ...range, steps: steps(row.steps) })
  }
  return checked
}
function routing(value: unknown): void {
  const row = record(value)
  if (!['amount', 'reverse_default'].includes(String(row.mode)) || typeof row.basis !== 'string'
    || !row.basis.trim() || row.basis.length > 100) throw Error('审批分支依据无效')
  if (row.mode === 'reverse_default') {
    if (row.amount !== null || row.branch !== null) throw Error('更正审批须使用默认步骤')
  } else {
    const amount = cents(row.amount)
    if (row.branch !== null) {
      const range = branchRange(row.branch)
      if (amount < cents(range.min_amount) || range.max_amount !== null && amount >= cents(range.max_amount)) throw Error('审批金额与命中区间不符')
    }
  }
}

export function documentApprovalPolicyBody(value: unknown): Omit<DocumentApprovalPolicyInput, 'document_type'> {
  const row = record(value)
  const type = documentApprovalType(row)
  if (Object.keys(row).some(key => !['document_type', 'version', 'steps', 'branches'].includes(key))
    || !Number.isSafeInteger(row.version) || Number(row.version) < 1) throw new Error('审批模板版本或字段无效')
  return { version: row.version as number, steps: steps(row.steps),
    ...(row.branches !== undefined ? { branches: branches(row.branches, type) } : {}) }
}

export function validateDocumentApprovalPolicy(value: unknown): asserts value is DocumentApprovalPolicy {
  const row = record(value)
  documentApprovalType(row)
  steps(row.steps)
  if (row.branches !== undefined) branches(row.branches, row.document_type as DocumentApprovalType)
  if (row.amount_basis !== undefined && row.amount_basis !== null && (typeof row.amount_basis !== 'string' || !row.amount_basis.trim() || row.amount_basis.length > 100)) throw Error('服务端金额依据无效')
  if (typeof row.title !== 'string' || !row.title.trim() || row.title.length > 100
    || !Number.isSafeInteger(row.version) || Number(row.version) < 1
    || !(row.configured_by === null || Number.isSafeInteger(row.configured_by) && Number(row.configured_by) > 0)
    || !(row.configured_at === null || typeof row.configured_at === 'string' && Number.isFinite(Date.parse(row.configured_at)))
    || (row.configured_by === null) !== (row.configured_at === null)) {
    throw new Error('服务端审批模板格式不匹配，请核对版本')
  }
}

export function validateDocumentApprovalPolicies(value: unknown): asserts value is DocumentApprovalPolicy[] {
  if (!Array.isArray(value)) throw new Error('服务端审批模板列表格式不匹配')
  const names = new Set<DocumentApprovalType>()
  for (const row of value) {
    validateDocumentApprovalPolicy(row)
    if (names.has(row.document_type)) throw new Error('服务端审批模板重复')
    names.add(row.document_type)
  }
}

export type DocumentApprovalStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'withdrawn' | 'executed'
export type DocumentApprovalIntent = 'execute' | 'reverse'
export type DocumentApprovalAction = 'submit' | 'approve' | 'reject' | 'withdraw'
export interface DocumentApprovalState {
  routing?: DocumentApprovalRouting
  version: number; status: DocumentApprovalStatus; generation: number; current_step: number
  steps: DocumentApprovalStep[]; policy_version: number | null
  submitted_by: number | null; submitted_at: string | null
  executed_by: number | null; executed_at: string | null
}
export interface DocumentApprovalEvent {
  routing?: DocumentApprovalRouting
  id: number; version: number; generation: number; action: DocumentApprovalAction | 'execute'
  step: number; step_name: string | null; actor_id: number; actor_name: string; reason: string; evidence?: string; created_at: string
}
// 审批明细来自服务端固定快照，不能用当前计划或物料档案替换送审名称、数量和排期。
export interface ProductionPlanApprovalLine {
  production_requirements?: string
  sku: string; name: string; unit: string; quantity: string; bom_version: number
  start_date: string; end_date: string; warehouse_name: string
  priority: 'normal' | 'high' | 'urgent'; sales_source: string
}
export interface DocumentApprovalRecord extends DocumentApprovalState {
  reopen_trace?: import('./erp-api').OtherInboundReopenLink[]
  document_type: DocumentApprovalType; document_id: number; intent: DocumentApprovalIntent
  document_no: string | null; business_status: string; reversal_reason: string; reversal_evidence?: string
  summary: { label: string; value: string; material_id?: number; material?: MaterialChoice; production_plan_line?: ProductionPlanApprovalLine }[]; content_matches: boolean
  can_submit: boolean; can_review: boolean; can_withdraw: boolean; events: DocumentApprovalEvent[]
}
export interface DocumentApprovalTarget {
  document_type: DocumentApprovalType; document_id: number; intent: DocumentApprovalIntent
}
export interface DocumentApprovalActionInput extends DocumentApprovalTarget {
  action: DocumentApprovalAction; version: number; reason: string; evidence?: string
}
export interface DocumentApprovalOperations {
  documentApproval: { input: DocumentApprovalTarget; output: DocumentApprovalRecord }
  actDocumentApproval: { input: DocumentApprovalActionInput; output: DocumentApprovalRecord }
}

export function documentApprovalTarget(value: unknown): DocumentApprovalTarget {
  const row = record(value)
  const type = documentApprovalType(row)
  if (!Number.isSafeInteger(row.document_id) || Number(row.document_id) < 1
      || !['execute', 'reverse'].includes(String(row.intent))) throw Error('审批单据或操作意图无效')
  return { document_type: type, document_id: row.document_id as number, intent: row.intent as DocumentApprovalIntent }
}

export function documentApprovalActionBody(value: unknown): { version: number; intent: DocumentApprovalIntent; reason: string; evidence?: string } {
  const row = record(value), target = documentApprovalTarget(row)
  if (Object.keys(row).some(key => !['document_type', 'document_id', 'intent', 'action', 'version', 'reason', 'evidence'].includes(key))
      || !['submit', 'approve', 'reject', 'withdraw'].includes(String(row.action))
      || !Number.isSafeInteger(row.version) || Number(row.version) < 0
      || typeof row.reason !== 'string' || row.reason.trim().length > 500
      || row.action === 'reject' && !row.reason.trim()) throw Error('审批动作、版本或意见无效')
  // 仅维护保留独立现场依据；其他类型不能夹带此字段。
  if (['ControlBalanceTransfer', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ProductionCostSettlement'].includes(target.document_type) && row.action !== 'withdraw' && (!row.reason.trim() || row.reason.trim().length > 200)) throw Error('单据审批依据必填，最多二百字')
  if (target.document_type === 'MaintenanceJob') {
    if (row.reason.trim().length > 200 || row.action !== 'withdraw' && (!row.reason.trim()
        || typeof row.evidence !== 'string' || !row.evidence.trim())
        || row.evidence !== undefined && (typeof row.evidence !== 'string' || row.evidence.trim().length > 600)) throw Error('维护操作原因与现场依据无效')
  } else if (row.evidence !== undefined) throw Error('此类单据不接受维护现场依据')
  return { version: row.version as number, intent: target.intent, reason: row.reason.trim(),
    ...(typeof row.evidence === 'string' ? { evidence: row.evidence.trim() } : {}) }
}

function positive(value: unknown): boolean { return Number.isSafeInteger(value) && Number(value) > 0 }
function date(value: unknown): boolean { return typeof value === 'string' && Number.isFinite(Date.parse(value)) }
export function validateDocumentApprovalState(value: unknown): asserts value is DocumentApprovalState {
  const row = record(value)
  if (row.routing !== undefined) {
    if (row.status === 'draft') throw Error('未送审单据没有固定金额分支')
    routing(row.routing)
  }
  if (!['draft', 'submitted', 'approved', 'rejected', 'withdrawn', 'executed'].includes(String(row.status))
      || !Number.isSafeInteger(row.version) || Number(row.version) < 0
      || !Number.isSafeInteger(row.generation) || Number(row.generation) < 0
      || !Number.isSafeInteger(row.current_step) || Number(row.current_step) < 0
      || !Array.isArray(row.steps)) throw Error('服务端审批状态无效')
  if (row.status === 'draft') {
    if (row.version !== 0 || row.generation !== 0 || row.current_step !== 0 || row.steps.length !== 0
        || row.policy_version !== null || row.submitted_by !== null || row.submitted_at !== null
        || row.executed_by !== null || row.executed_at !== null) throw Error('服务端审批草稿格式不匹配')
    return
  }
  steps(row.steps)
  if (!positive(row.version) || !positive(row.generation) || !positive(row.policy_version)
      || !positive(row.submitted_by) || !date(row.submitted_at)
      || Number(row.current_step) > row.steps.length
      || row.status === 'submitted' && Number(row.current_step) >= row.steps.length
      || ['approved', 'executed'].includes(String(row.status)) && Number(row.current_step) !== row.steps.length
      || row.status === 'executed' && (!positive(row.executed_by) || !date(row.executed_at))
      || row.status !== 'executed' && (row.executed_by !== null || row.executed_at !== null)) {
    throw Error('服务端审批进度或执行人员格式不匹配')
  }
}

export function validateDocumentApprovalResponse(value: unknown): void {
  // 列表和执行结果也携带审批进度；旧响应可缺省，出现字段时必须是完整有效状态。
  if (Array.isArray(value)) {
    for (const item of value) validateDocumentApprovalResponse(item)
    return
  }
  if (!value || typeof value !== 'object') return
  const row = value as Record<string, unknown>
  for (const field of ['approval', 'reversal_approval', 'outbound_approval']) {
    // 生产领料签收本身没有审批，只有更正时读取独立的冲销审批。
    if (field === 'approval' && row.kind === 'receipt' && row[field] === null) continue
    if (Object.hasOwn(row, field)) validateDocumentApprovalState(row[field])
  }
}

export function validateDocumentApprovalRecord(value: unknown): asserts value is DocumentApprovalRecord {
  const row = record(value)
  if (row.routing !== undefined && (!amountApprovalTypes.includes(row.document_type as DocumentApprovalType)
    || (record(row.routing).mode === 'reverse_default') !== (row.intent === 'reverse'))) throw Error('审批分支与单据类型或意图不符')
  documentApprovalTarget(row); validateDocumentApprovalState(row)
  if (!(row.document_no === null || typeof row.document_no === 'string' && !!row.document_no.trim())
      || typeof row.business_status !== 'string' || !row.business_status || row.business_status.length > 40
      || typeof row.reversal_reason !== 'string' || row.reversal_reason.length > 200
      || typeof row.can_submit !== 'boolean' || typeof row.can_review !== 'boolean'
      || typeof row.can_withdraw !== 'boolean' || !Array.isArray(row.events)) throw Error('服务端单据审批格式不匹配')
  if (row.reversal_evidence !== undefined && (row.document_type !== 'MaintenanceJob'
      || typeof row.reversal_evidence !== 'string' || row.reversal_evidence.length > 600)) throw Error('服务端维护更正依据无效')
  if (typeof row.content_matches !== 'boolean' || !Array.isArray(row.summary) || row.summary.length > (['CrmQuote', 'AfterSalesCase', 'MaintenanceJob', 'Journal', 'SubledgerOpening'].includes(String(row.document_type)) ? 128 : 110)) throw Error('服务端审批摘要格式不匹配')
  for (const item of row.summary) {
    const entry = record(item)
    if (typeof entry.label !== 'string' || !entry.label.trim() || typeof entry.value !== 'string'
        || entry.label.length > 500 || entry.value.length > 1000) throw Error('服务端审批摘要字段无效')
    // 普通摘要允许没有物料身份；附带参数时必须由独立 material_id 证明所属物料。
    if (entry.material_id !== undefined && !positive(entry.material_id)) throw Error('服务端审批摘要物料编号无效')
    if (entry.material !== undefined) validateMaterialMetadata(entry.material,entry.material_id)
    if (entry.production_plan_line !== undefined) {
      const line = record(entry.production_plan_line)
      if (line.production_requirements !== undefined && (typeof line.production_requirements !== 'string' || line.production_requirements.length > 500)) throw Error('服务端生产要求格式不正确')
      // 新字段可缺省以兼容旧服务；出现时必须完整且仅属于计划产品。
      if (row.document_type !== 'ProductionPlan' || entry.label !== '计划产品' || !positive(entry.material_id)
          || ['sku', 'name', 'unit', 'warehouse_name', 'sales_source'].some(key => typeof line[key] !== 'string' || !String(line[key]).trim() || String(line[key]).length > 1000)
          || !positive(line.bom_version) || !['normal', 'high', 'urgent'].includes(String(line.priority))
          || typeof line.quantity !== 'string' || !/^\d+(\.\d{1,3})?$/.test(line.quantity) || Number(line.quantity) <= 0 || Number(line.quantity) > 1000000
          || [line.start_date, line.end_date].some(value => typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !date(value))
          || String(line.start_date) > String(line.end_date)) throw Error('服务端审批计划产品字段无效')
    }
  }
  // 服务端操作标志也必须符合进度，避免响应格式错误时显示不合时宜的审批按钮。
  if (row.can_review && (row.status !== 'submitted' || !row.content_matches)
      || row.can_submit && !['draft', 'rejected', 'withdrawn'].includes(row.status)
      || row.can_withdraw && !['submitted', 'approved'].includes(row.status)) throw Error('服务端审批操作与状态不一致')
  let version = 0
  for (const item of row.events) {
    const event = record(item)
    if (event.routing !== undefined) {
      routing(event.routing)
      if (!amountApprovalTypes.includes(row.document_type as DocumentApprovalType)
        || (record(event.routing).mode === 'reverse_default') !== (row.intent === 'reverse')) throw Error('历史分支与单据类型或意图不符')
    }
    if (event.evidence !== undefined && (row.document_type !== 'MaintenanceJob'
        || typeof event.evidence !== 'string' || event.evidence.length > 600)) throw Error('服务端维护审批现场依据无效')
    if (!positive(event.id) || !positive(event.generation) || Number(event.generation) > row.generation
        || event.version !== ++version || !Number.isSafeInteger(event.step) || Number(event.step) < 0
        || !['submit', 'approve', 'reject', 'withdraw', 'execute'].includes(String(event.action))
        || !(event.step_name === null || typeof event.step_name === 'string' && !!event.step_name.trim() && event.step_name.length <= 40)
        || !positive(event.actor_id) || typeof event.actor_name !== 'string' || !event.actor_name.trim()
        || typeof event.reason !== 'string' || event.reason.length > 500 || !date(event.created_at)) {
      throw Error('服务端审批历史格式不匹配')
    }
  }
  if (version !== row.version) throw Error('服务端审批历史不完整，请重新读取')
}
