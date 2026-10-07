import type { NumberedDocument } from './document-numbering'
import type { MaterialChoice } from './material-api'
export type QualityKind = 'scrap' | 'rework'
export type QualityTreatment = 'absorb' | 'expense' | 'carry'
export type QualityStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'cancelled' | 'posted' | 'reversed'
export type QualityAction = 'submit' | 'approve' | 'reject' | 'post' | 'cancel' | 'reverse'
export interface QualitySource {
  id: number; work_order_id: number; product_material_id: number; product_sku: string; product_name: string; product_unit: string
  reported_quantity: string; accepted_quantity: string; rejected_quantity: string; qc_note: string; reference: string
  warehouse_id: number; warehouse_name: string; work_order_status: string; posted_at: string; inspected_by: number; inspected_at: string
  valid: boolean
}
export interface QualityCase extends QualitySource {
  reserved_quantity: string; remaining_quantity: string; settled: boolean; settlement_id: number | null
}
export interface QualityMaterial { material_id: number; quantity: string }
export interface QualityInput {
  completion_id: number; reference: string; kind: QualityKind; quantity: string; loss_treatment: QualityTreatment
  defect: string; action_note: string; warehouse_id: number | null; materials: QualityMaterial[]; reason: string
}
export interface QualityDraft extends Omit<QualityInput,'loss_treatment'> { loss_treatment: QualityTreatment | '' }
export interface QualityEvidence extends Omit<QualityInput,'reason'> , NumberedDocument {
  id: number; status: QualityStatus; version: number; created_by: number; created_by_name: string; created_at: string
  submitted_by: number | null; reviewed_by: number | null; posted_by: number | null; reversed_by: number | null
  submitted_at: string | null; reviewed_at: string | null; posted_at: string | null; reversed_at: string | null
  rework_order_id: number | null; frozen_source: QualitySource; current_source_valid: boolean; author_ids: number[]
  source_work_order_id: number; source_work_order_status: string
  materials: (QualityMaterial & {sku:string; material_name:string; unit:string})[]
  changes: {id:number; action:string; reason:string; changed_by:number; changed_by_name:string; created_at:string;
    before: Record<string,unknown> | null; after: Record<string,unknown>}[]
  cost_visible: boolean; cost_allocation: {settlement_id:number; amount:string | null; loss_treatment:QualityTreatment} | null
}
export interface QualityOverview {
  cases: QualityCase[]; dispositions: QualityEvidence[]
  materials: MaterialChoice[]; warehouses:{id:number; name:string}[]
}
export interface QualityOperations {
  qualityOverview: {input:undefined; output:QualityOverview}
  qualityDetail: {input:{id:number}; output:QualityEvidence}
  saveQualityDisposition: {input:QualityInput & {id?:number; version?:number}; output:QualityEvidence}
  changeQualityDisposition: {input:{id:number; version:number; action:QualityAction; reason:string}; output:QualityEvidence}
}
export interface ReworkCostSource {
  disposition_id:number; reference:string; completion_id:number; origin_work_order_id:number; quantity:string
  origin_settlement_id:number | null; amount:string | null
}
