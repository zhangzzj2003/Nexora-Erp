import type { DocumentApprovalState } from './document-approval-api'
import type { NumberedDocument } from './document-numbering'
import type { Material, Warehouse } from './erp-api'

export type MrpSupplyMode = 'auto' | 'buy' | 'make'
export type MrpAction = 'submit' | 'approve' | 'reject' | 'cancel'
export interface MrpPolicyInput {
  version: number; supply_mode: MrpSupplyMode; lead_time_days: number
  safety_stock: string; minimum_quantity: string; multiple_quantity: string; reason: string
}
export interface MrpPolicy extends Omit<MrpPolicyInput, 'reason'> {
  material_id: number; changed_by: number | null; created_at: string | null
}
export interface MrpSchedule { key: string; due_date: string }
export interface MrpManualDemand { material_id: number; quantity: string; due_date: string; reference: string }
export interface MrpPlanInput {
  reference: string; start_date: string; demand_dates: MrpSchedule[]; supply_dates: MrpSchedule[]
  manual_demands: MrpManualDemand[]; reason: string
}
export interface MrpSource {
  key: string; kind: string; material_id: number; quantity: string
  source_id?: number; source_line_id?: number; reference?: string; party_name?: string; status?: string
  due_date?: string | null; scheduled_date?: string; parent_key?: string; bom_id?: number; bom_version?: number
}
export interface MrpBom {
  id: number; product_material_id: number; version: number; base_quantity: string
  lines: { id: number; component_material_id: number; quantity: string }[]
}
export interface MrpMovement {
  id: number; warehouse_id: number; material_id: number; quantity: string; source_type: string
  source_id: number; source_line_id: number; created_by: number | null; created_at: string
}
export interface MrpSources {
  materials: Material[]; policies: MrpPolicy[]; boms: MrpBom[]
  demands: MrpSource[]; supplies: MrpSource[]; reservations: MrpSource[]
}
export interface MrpOptions extends MrpSources { fingerprint: string; today: string; warehouses: Warehouse[] }
export interface MrpSuggestion extends Pick<Material, 'sku' | 'name' | 'unit'> {
  key: string; material_id: number; supply_mode: 'buy' | 'make'; quantity: string
  due_date: string; release_date: string; required_release_date: string; late: boolean
  bom_id: number | null; bom_version: number | null
}
export interface MrpRow extends Pick<Material, 'sku' | 'name' | 'unit'> {
  material_id: number; date: string; level: number; supply_mode: 'buy' | 'make'
  opening_quantity: string; gross_quantity: string; scheduled_quantity: string; safety_stock: string
  net_quantity: string; planned_quantity: string; closing_quantity: string; suggestion_key: string | null
  demand_sources: MrpSource[]; supply_sources: MrpSource[]
}
export interface MrpConversion {
  id: number; plan_id: number; suggestion_key: string; purchase_request_id: number | null
  work_order_id: number | null; due_date: string; reason: string; created_by: number
  created_by_name: string; created_at: string; target_status: string; target_reference: string
}
export interface MrpPlan extends NumberedDocument {
  approval?: DocumentApprovalState
  id: number; reference: string; start_date: string; fingerprint: string
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'cancelled'; version: number
  created_by: number; created_by_name: string; submitted_by: number | null; reviewed_by: number | null
  cancelled_by: number | null; author_ids: number[]; created_at: string; submitted_at: string | null
  reviewed_at: string | null; cancelled_at: string | null; suggestion_count: number; warning_count: number
  conversions: MrpConversion[]
}
export interface MrpDetail extends MrpPlan {
  input: MrpPlanInput; csv: string; snapshot: {
    rows: MrpRow[]; suggestions: MrpSuggestion[]; warnings: string[]; assumptions: string[]
    captured_at: string; sources: MrpSources & { movements: MrpMovement[] }
  }
}
export interface MrpCheck {
  matched: boolean; fingerprint: string; current_fingerprint: string
  cancelled_target: boolean; expired_start_date: boolean
}
export interface MrpChange<T> { id: number; action?: string; before: T | null; after: T
  reason: string; changed_by: number; changed_by_name: string; created_at: string }
export interface MrpOperations {
  mrpOptions: { input: undefined; output: MrpOptions }
  mrpPlans: { input: undefined; output: MrpPlan[] }
  mrpDetail: { input: { id: number }; output: MrpDetail }
  mrpCheck: { input: { id: number }; output: MrpCheck }
  mrpChanges: { input: { id: number }; output: MrpChange<MrpPlan>[] }
  mrpPolicyChanges: { input: { id: number }; output: MrpChange<MrpPolicy>[] }
  saveMrpPolicy: { input: MrpPolicyInput & { id: number }; output: MrpPolicy }
  createMrpPlan: { input: MrpPlanInput; output: MrpPlan }
  changeMrpStatus: { input: { id: number; version: number; action: MrpAction; reason: string }; output: MrpPlan }
  convertMrpSuggestion: { input: { id: number; version: number; suggestion_key: string; warehouse_id: number | null; reference: string; reason: string }; output: MrpConversion }
}
