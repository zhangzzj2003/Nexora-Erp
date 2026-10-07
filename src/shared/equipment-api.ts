import type { NumberedDocument } from './document-numbering'
import type { MaterialChoice } from './material-api'
export type EquipmentStatus = 'active' | 'inactive' | 'retired'
export type EquipmentAttachmentKind = 'asset' | 'job'
export interface EquipmentAttachment {
  id: number; entity_kind: EquipmentAttachmentKind; entity_id: number
  file_name: string; media_type: 'application/pdf' | 'image/png' | 'image/jpeg'
  byte_count: number; sha256: string; reason: string
  created_by: number; created_by_name: string; created_at: string
  reversal: {id: number; reason: string; created_by: number; created_by_name: string; created_at: string} | null
}
export interface EquipmentAttachmentList {
  entity_kind: EquipmentAttachmentKind; entity_id: number; can_modify: boolean; items: EquipmentAttachment[]
}
export type MaintenanceKind = 'preventive' | 'corrective'
export type MaintenanceStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'in_progress' | 'reported' | 'accepted' | 'cancelled' | 'reversed'
export type MaintenanceAction = 'submit' | 'approve' | 'reject' | 'start' | 'report' | 'rework' | 'accept' | 'cancel' | 'reverse'

export interface EquipmentChange {
  id: number; action: string; reason: string; evidence: string; changed_by: number
  changed_by_name: string; created_at: string
  before: Record<string, unknown> | null; after: Record<string, unknown>
}
export interface EquipmentDowntime {
  id: number; equipment_id: number; job_id: number; started_at: string; ended_at: string | null
  close_reason: string; started_by: number; ended_by: number | null
  started_by_name: string; ended_by_name: string | null; seconds: number; ongoing: boolean
}
export interface EquipmentInput {
  code: string; name: string; serial_number: string; location: string; status: EquipmentStatus; reason: string
}
export interface EquipmentMeterReading {
  id: number; equipment_id: number; hours: string; reference: string; reason: string
  previous_reading_id: number | null; correction: boolean
  recorded_by: number; recorded_by_name: string; recorded_at: string
}
export interface EquipmentMeterInput {
  equipment_id: number; hours: string; reference: string; reason: string
  previous_reading_id: number | null; correction: boolean
}
export interface EquipmentRecord extends Omit<EquipmentInput, 'reason'> {
  id: number; version: number; created_by: number; created_at: string
  running_job_ids: number[]; changes: EquipmentChange[]; downtimes: EquipmentDowntime[]
  meter_reading: EquipmentMeterReading | null; meter_readings: EquipmentMeterReading[]
}
export interface MaintenancePlanInput {
  equipment_id: number; reference: string; title: string; interval_days: number
  next_due: string; enabled: boolean; reason: string
}
export interface MaintenancePlanRecord extends Omit<MaintenancePlanInput, 'reason'> {
  id: number; version: number; created_by: number; created_at: string
  due: boolean; open_job_ids: number[]; changes: EquipmentChange[]
}
export interface MaintenanceHourPlanInput {
  equipment_id: number; reference: string; title: string; interval_hours: string
  next_due_hours: string; enabled: boolean; reason: string
}
export interface MaintenanceHourPlanRecord extends Omit<MaintenanceHourPlanInput, 'reason'> {
  id: number; version: number; created_by: number; created_at: string
  current_hours: string | null; current_reading_id: number | null
  due: boolean; open_job_ids: number[]; changes: EquipmentChange[]
}
export interface MaintenancePart { material_id: number; quantity: string }
export interface MaintenanceProcurementReceipt { id: number; status: string; accepted_quantity: string; inbound_receipt_id: number | null; inbound_status: string | null }
export interface MaintenanceProcurementOrder { id: number; status: string; quantity: string; goods_receipts: MaintenanceProcurementReceipt[] }
export interface MaintenanceProcurementRequest {
  id: number; reference: string; status: string; reason: string; evidence: string
  created_by: number; created_at: string
  lines: {material_id: number; quantity: string; orders: MaintenanceProcurementOrder[]}[]
}
export interface MaintenancePurchaseInput {
  id: number; version: number; reason: string; evidence: string; parts: MaintenancePart[]
}
export interface MaintenanceJobInput {
  reference: string; equipment_id: number; kind: MaintenanceKind; plan_id: number | null
  hour_plan_id: number | null
  work_order_id: number | null; assigned_to: number; request_note: string
  warehouse_id: number | null; parts: MaintenancePart[]; reason: string
}
export interface MaintenanceJobRecord extends Omit<MaintenanceJobInput, 'reason'> , NumberedDocument {
  id: number; version: number; status: MaintenanceStatus; plan_version: number | null; plan_due_date: string | null
  plan_due_hours: string | null; plan_meter_reading_id: number | null
  equipment_snapshot: Record<string, unknown>; work_order_snapshot: Record<string, unknown> | null
  work_order_linked: boolean; work_order_current_status: string | null
  parts_outbound_id: number | null; parts_status: 'draft' | 'posted' | 'cancelled' | 'reversed' | 'missing' | null
  solution: string; labor_hours: string | null; service_amount: string | null
  plan_roll: { before?: Record<string, unknown>; after?: Record<string, unknown>; reading_id?: number; reversal_effect?: 'restored_due' | 'retained_newer_schedule' | null }
  created_by: number; created_by_name: string; assigned_to_name: string; author_ids: number[]
  reviewed_by: number | null; reported_by: number | null; accepted_by: number | null
  created_at: string; started_at: string | null; reported_at: string | null; accepted_at: string | null
  allowed_actions: MaintenanceAction[]; can_edit: boolean; downtime: EquipmentDowntime | null; changes: EquipmentChange[]
  purchase_requests: MaintenanceProcurementRequest[]
}
export interface EquipmentOverview {
  as_of: string; equipment: EquipmentRecord[]; plans: MaintenancePlanRecord[]
  hour_plans: MaintenanceHourPlanRecord[]; jobs: MaintenanceJobRecord[]
  executors: { id: number; username: string }[]
  materials: MaterialChoice[]
  warehouses: { id: number; name: string }[]
  work_orders: { id: number; status: string; target_quantity: string }[]
}
export type MaintenanceCommand = { id: number; version: number; reason: string; evidence: string } & (
  { action: 'report'; solution: string; labor_hours: string; service_amount: string } |
  { action: Exclude<MaintenanceAction, 'report'>; solution?: never; labor_hours?: never; service_amount?: never }
)
export interface EquipmentOperations {
  equipmentAttachments: { input: {kind: EquipmentAttachmentKind; id: number}; output: EquipmentAttachmentList }
  addEquipmentAttachment: { input: {kind: EquipmentAttachmentKind; id: number; file_name: string; content_base64: string; reason: string}; output: EquipmentAttachment }
  reverseEquipmentAttachment: { input: {kind: EquipmentAttachmentKind; id: number; attachmentId: number; reason: string}; output: EquipmentAttachment }
  equipmentOverview: { input: undefined; output: EquipmentOverview }
  equipmentDetail: { input: { id: number }; output: EquipmentRecord }
  maintenancePlanDetail: { input: { id: number }; output: MaintenancePlanRecord }
  maintenanceHourPlanDetail: { input: { id: number }; output: MaintenanceHourPlanRecord }
  maintenanceJobDetail: { input: { id: number }; output: MaintenanceJobRecord }
  recordEquipmentMeter: { input: EquipmentMeterInput; output: EquipmentMeterReading }
  saveEquipment: { input: EquipmentInput & { id?: number; version?: number }; output: EquipmentRecord }
  saveMaintenancePlan: { input: MaintenancePlanInput & { id?: number; version?: number }; output: MaintenancePlanRecord }
  saveMaintenanceHourPlan: { input: MaintenanceHourPlanInput & { id?: number; version?: number }; output: MaintenanceHourPlanRecord }
  saveMaintenanceJob: { input: MaintenanceJobInput & { id?: number; version?: number }; output: MaintenanceJobRecord }
  changeMaintenanceJob: { input: MaintenanceCommand; output: MaintenanceJobRecord }
  createMaintenancePurchaseRequest: { input: MaintenancePurchaseInput; output: MaintenanceJobRecord }
}
export type EquipmentEntity = 'asset' | 'plan' | 'hour_plan' | 'job'
export type EquipmentDetail = {kind:'asset';row:EquipmentRecord} | {kind:'plan';row:MaintenancePlanRecord} |
  {kind:'hour_plan';row:MaintenanceHourPlanRecord} | {kind:'job';row:MaintenanceJobRecord}
export interface EquipmentForms {asset:EquipmentInput;plan:MaintenancePlanInput;hour_plan:MaintenanceHourPlanInput;job:MaintenanceJobInput}
