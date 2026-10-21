// 草稿修订沿用原业务单据，仅追加版本、原因和可追溯正文。
export type SalesDraftType = 'SalesOrder' | 'Shipment' | 'SalesReturn'
export interface SalesDraftState {
  draft_version?: number
  draft_edit_block_reason?: string
}
export interface SalesRevisionInput { expected_version: number; revision_reason: string }
export interface SalesDraftSnapshot {
  customer_name?: string
  warehouse_name?: string
  reference?: string
  reason?: string
  sales_order_id?: number
  shipment_id?: number
  sales_order_document_no?: string
  shipment_document_no?: string
  lines: { id: number; material_id: number; sku: string; material_name: string; unit: string;
    quantity: string; unit_price?: string; warranty_days?: number | null; warranty_basis?: string }[]
}
export interface SalesDraftChange {
  id: number; version: number; reason: string; changed_by_name: string; created_at: string
  before: SalesDraftSnapshot; after: SalesDraftSnapshot
}
export function salesRevisionFields(value: unknown): SalesRevisionInput {
  const source = value as Partial<SalesRevisionInput> | null
  if (!source || !Number.isInteger(source.expected_version) || Number(source.expected_version) < 0 ||
      typeof source.revision_reason !== 'string' || !source.revision_reason.trim() || source.revision_reason.length > 200)
    throw Error('草稿版本或修订原因无效')
  return { expected_version: source.expected_version!, revision_reason: source.revision_reason.trim() }
}
export function salesDraftType(value: unknown): SalesDraftType {
  if (value !== 'SalesOrder' && value !== 'Shipment' && value !== 'SalesReturn') throw Error('销售单据类型无效')
  return value
}
