// 工单关联只包含数量与来源，财务成本和客户信息不进入这个只读协议。
export interface ProductionAssociationTarget { kind: 'work_order' | 'completion'; id: number }
export interface AssociationDocument {
  id: number; document_no: string | null; reference: string; status: string; created_at: string
  posted_at: string | null; reversal_reason: string | null
}
export interface IssueSource {
  lot_id: number; lot_code: string; quantity: string; evidence_kind: 'allocation' | 'supplement'
  origin_movement_id: number | null; source_type: string | null; source_id: number | null
  source_document_no: string | null; supplier_id: number | null; supplier_name: string | null; receipt_reversed: boolean
}
export interface AssociationReturn extends AssociationDocument { line_id: number; quantity: string; effective: boolean }
export interface AssociationIssue extends AssociationReturn {
  returned_quantity: string; returns: AssociationReturn[]; sources: IssueSource[]; unassigned_quantity: string | null
}
export interface PurchaseReference {
  receipt_id: number; document_no: string | null; line_id: number; quantity: string; posted_at: string
  supplier_id: number; supplier_name: string
}
export interface AssociationComponent {
  id: number; material_id: number; sku: string; name: string; unit: string; required_quantity: string
  net_issued_quantity: string; issues: AssociationIssue[]; purchase_references: PurchaseReference[]
}
export interface AssociationCompletion extends AssociationDocument {
  reported_quantity: string; accepted_quantity: string | null; rejected_quantity: string | null; effective: boolean
}
export interface ProductionAssociations {
  target: ProductionAssociationTarget; scope: 'work_order'; inventory_visible: boolean; references_included: boolean
  reference_cutoff: string; reference_limit: number
  work_order: AssociationDocument & { target_quantity: string; product_name: string; product_sku: string }
  bom: { id: number; version: number; base_quantity: string }
  components: AssociationComponent[]; completions: AssociationCompletion[]
}
export interface ProductionAssociationOperations {
  productionAssociations: { input: ProductionAssociationTarget & { include_references: boolean }; output: ProductionAssociations }
}
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('生产关联数据格式无效')
  return value as Record<string, unknown>
}
const text = (value: unknown) => typeof value === 'string'
const quantity = (value: unknown) => typeof value === 'string' && /^-?\d+(?:\.\d{1,3})?$/.test(value)
const numberLabel = (value: unknown) => value === null || text(value) && !!String(value).trim()
const time = (value: unknown) => text(value) && Number.isFinite(Date.parse(String(value)))
const rows = (value: unknown): unknown[] => {if (!Array.isArray(value)) throw Error('生产关联明细格式无效'); return value}
export function productionAssociationInput(value: unknown): ProductionAssociationTarget & {include_references: boolean} {
  const row = object(value)
  if (!positive(row.id) || !['work_order', 'completion'].includes(String(row.kind)) || typeof row.include_references !== 'boolean'
    || Object.keys(row).some(key => !['kind', 'id', 'include_references'].includes(key))) throw Error('生产关联查询参数无效')
  return {kind: row.kind as ProductionAssociationTarget['kind'], id: Number(row.id), include_references: row.include_references}
}
function document(value: unknown): Record<string, unknown> {
  const row = object(value)
  if (!positive(row.id) || !numberLabel(row.document_no) || !text(row.reference) || !text(row.status) || !time(row.created_at)
    || !(row.posted_at === null || time(row.posted_at)) || !(row.reversal_reason === null || text(row.reversal_reason))) throw Error('生产关联单据身份无效')
  return row
}
export function validateProductionAssociations(value: unknown): asserts value is ProductionAssociations {
  const row = object(value), target = object(row.target), work = document(row.work_order), bom = object(row.bom)
  productionAssociationInput({...target, include_references: false})
  if (row.scope !== 'work_order' || typeof row.inventory_visible !== 'boolean' || typeof row.references_included !== 'boolean'
    || !time(row.reference_cutoff) || row.reference_limit !== 50 || !positive(bom.id) || !positive(bom.version) || !quantity(bom.base_quantity)
    || !quantity(work.target_quantity) || !text(work.product_name) || !text(work.product_sku)
    || target.kind === 'work_order' && work.id !== target.id || !row.inventory_visible && row.references_included) throw Error('生产关联范围无效')
  for (const value of rows(row.components)) {
    const component = object(value)
    if (!positive(component.id) || !positive(component.material_id) || !['sku','name','unit'].every(key => text(component[key]))
      || !quantity(component.required_quantity) || !quantity(component.net_issued_quantity)) throw Error('生产需求数量无效')
    for (const value of rows(component.issues)) {
      const issue = document(value)
      if (!positive(issue.line_id) || !quantity(issue.quantity) || !quantity(issue.returned_quantity) || typeof issue.effective !== 'boolean'
        || !(issue.unassigned_quantity === null || quantity(issue.unassigned_quantity))) throw Error('领料关联数量无效')
      for (const value of rows(issue.returns)) {
        const returned = document(value)
        if (!positive(returned.line_id) || !quantity(returned.quantity) || typeof returned.effective !== 'boolean') throw Error('退料关联无效')
      }
      const sources = rows(issue.sources)
      if (!row.inventory_visible && (sources.length || issue.unassigned_quantity !== null)) throw Error('生产来源权限范围不匹配')
      for (const value of sources) {
        const source = object(value)
        if (!positive(source.lot_id) || !text(source.lot_code) || !quantity(source.quantity) || Number(source.quantity) <= 0
          || !['allocation','supplement'].includes(String(source.evidence_kind)) || !numberLabel(source.source_document_no)
          || !['origin_movement_id','source_id','supplier_id'].every(key => source[key] === null || positive(source[key]))
          || !(source.source_type === null || text(source.source_type)) || !(source.supplier_name === null || text(source.supplier_name))
          || typeof source.receipt_reversed !== 'boolean' || source.supplier_id !== null && (source.source_type !== 'receipt' || source.origin_movement_id === null)) throw Error('实物来源证据无效')
      }
    }
    const references = rows(component.purchase_references)
    if ((!row.inventory_visible || !row.references_included) && references.length || references.length > 50) throw Error('采购参考范围无效')
    for (const value of references) {
      const ref = object(value)
      if (!positive(ref.receipt_id) || !positive(ref.line_id) || !positive(ref.supplier_id) || !text(ref.supplier_name)
        || !numberLabel(ref.document_no) || !quantity(ref.quantity) || !time(ref.posted_at)) throw Error('采购参考记录无效')
    }
  }
  const completions = rows(row.completions)
  for (const value of completions) {
    const completion = document(value)
    if (!quantity(completion.reported_quantity) || !['accepted_quantity','rejected_quantity'].every(key => completion[key] === null || quantity(completion[key]))
      || typeof completion.effective !== 'boolean') throw Error('完工关联数量无效')
  }
  if (target.kind === 'completion' && !completions.some(value => object(value).id === target.id)) throw Error('完工关联目标不匹配')
}
