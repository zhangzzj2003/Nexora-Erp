import type { MaterialChoice } from './material-api'
export type InventoryWarningStatus = 'normal' | 'low' | 'out_of_stock' | 'disabled'
export interface InventoryWarningSnapshot {
  id: number; warehouse_id: number; material_id: number; threshold: string; enabled: boolean; version: number
  created_by: number; created_at: string; warehouse_code: string; warehouse_name: string
  sku: string; material_name: string; unit: string
}
export interface InventoryWarningRow extends InventoryWarningSnapshot {
  quantity: string; status: InventoryWarningStatus; shortage: string | null
}
export interface InventoryWarningChange {
  id: number; reason: string; changed_by: number; changed_by_name: string; created_at: string
  before: InventoryWarningSnapshot | null; after: InventoryWarningSnapshot
}
export interface InventoryWarningDetail { row: InventoryWarningRow; changes: InventoryWarningChange[] }
export interface InventoryWarningOverview {
  as_of: string; warehouse_id: number | null; rows: InventoryWarningRow[]
  warehouses: {id: number; code: string; name: string}[]
  materials: MaterialChoice[]
  summary: Record<InventoryWarningStatus | 'configured' | 'unconfigured', number>
}
export interface InventoryWarningEvent {
  id: number; rule_id: number; warehouse_id: number; material_id: number
  previous_status: InventoryWarningStatus | null; status: 'low' | 'out_of_stock'
  quantity: string; threshold: string; shortage: string; rule_version: number
  warehouse_code: string; warehouse_name: string; sku: string; material_name: string; unit: string
  observed_at: string; created_at: string
}
export interface InventoryWarningEventPage {
  as_of: string; warehouse_id: number | null; events: InventoryWarningEvent[]; next_before_id: number | null
}
export interface InventoryWarningInput {
  warehouse_id: number; material_id: number; version: number; threshold: string; enabled: boolean; reason: string
}
export interface InventoryWarningOperations {
  inventoryWarnings: { input: {warehouseId?: number} | undefined; output: InventoryWarningOverview }
  inventoryWarningEvents: { input: {warehouseId?: number; beforeId?: number} | undefined; output: InventoryWarningEventPage }
  inventoryWarningDetail: { input: {warehouse_id: number; material_id: number}; output: InventoryWarningDetail }
  saveInventoryWarning: { input: InventoryWarningInput; output: InventoryWarningDetail }
}
export const inventoryWarningLabels: Record<InventoryWarningStatus, string> = {
  normal: '正常', low: '低库存', out_of_stock: '缺货', disabled: '已停用'
}
export function warningThresholdValid(value: string): boolean {
  if (!/^(?:0|[1-9]\d{0,6})(?:\.\d{1,3})?$/.test(value)) return false
  const [integer, fraction=''] = value.split('.')
  return BigInt(integer!) * 1000n + BigInt(fraction.padEnd(3, '0')) <= 1000000000n
}
