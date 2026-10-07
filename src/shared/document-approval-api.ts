// 类型白名单与后端 29 类编号/审批范围一致，页面不能提供任意表名或请求路径。
export const documentApprovalTypes = [
  'PurchaseRequest', 'PurchaseOrder', 'PurchaseGoodsReceipt', 'Receipt', 'PurchaseReturn',
  'WarehouseInbound', 'WarehouseOutbound', 'Transfer', 'Stocktake', 'StockAdjustment',
  'CrmQuote', 'SalesOrder', 'Shipment', 'SalesReturn', 'AfterSalesCase',
  'WorkOrder', 'MaterialIssue', 'MaterialReturn', 'ProductionCompletion', 'QualityDisposition',
  'MrpPlan', 'ProductionCostSettlement', 'MaintenanceJob', 'Journal', 'OpeningBalance',
  'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer'
] as const
export type DocumentApprovalType = typeof documentApprovalTypes[number]
export interface DocumentApprovalStep { name: string; role: string | null }
export interface DocumentApprovalPolicy {
  document_type: DocumentApprovalType
  title: string
  version: number
  steps: DocumentApprovalStep[]
  configured_by: number | null
  configured_at: string | null
}
export interface DocumentApprovalPolicyInput {
  document_type: DocumentApprovalType
  version: number
  steps: DocumentApprovalStep[]
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
    if (Object.keys(step).some(key => key !== 'name' && key !== 'role')
      || typeof step.name !== 'string' || !step.name.trim() || step.name.trim().length > 40
      || !(step.role === null || typeof step.role === 'string' && /^[a-z][a-z0-9_]{2,39}$/.test(step.role))) {
      throw new Error('审批步骤名称或角色无效')
    }
    return { name: step.name.trim(), role: step.role as string | null }
  })
}

export function documentApprovalPolicyBody(value: unknown): Omit<DocumentApprovalPolicyInput, 'document_type'> {
  const row = record(value)
  documentApprovalType(row)
  if (Object.keys(row).some(key => !['document_type', 'version', 'steps'].includes(key))
    || !Number.isSafeInteger(row.version) || Number(row.version) < 1) throw new Error('审批模板版本或字段无效')
  return { version: row.version as number, steps: steps(row.steps) }
}

export function validateDocumentApprovalPolicy(value: unknown): asserts value is DocumentApprovalPolicy {
  const row = record(value)
  documentApprovalType(row)
  steps(row.steps)
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
