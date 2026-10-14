import type { InventoryWarningRow, InventoryWarningStatus } from '../../../../../shared/inventory-warning-api'
import type { PhysicalLotRow } from '../../../../../shared/physical-lot-api'

export type WarningFilter = InventoryWarningStatus | 'attention' | 'all'
export type LotFilter = 'all' | 'identified' | 'legacy'

// 搜索只过滤展示，不修改完整快照；概览数量和批次补证仍以原始范围为准。
export function filterWarningRows(rows: InventoryWarningRow[], query: string, status: WarningFilter): InventoryWarningRow[] {
  const keyword = query.trim().toLocaleLowerCase()
  return rows.filter(row => (status === 'all' || (status === 'attention'
    ? row.status === 'low' || row.status === 'out_of_stock' : row.status === status))
    && [row.warehouse_code, row.warehouse_name, row.sku, row.material_name].join(' ').toLocaleLowerCase().includes(keyword))
}

export function warningTone(status: unknown): 'danger' | 'pending' | 'success' | 'neutral' {
  return status === 'out_of_stock' ? 'danger' : status === 'low' ? 'pending' : status === 'normal' ? 'success' : 'neutral'
}

export function filterLotRows(rows: PhysicalLotRow[], query: string, kind: LotFilter): PhysicalLotRow[] {
  const keyword = query.trim().toLocaleLowerCase()
  return rows.filter(row => (kind === 'all' || (kind === 'legacy' ? row.source_kind === 'legacy' : row.source_kind !== 'legacy'))
    && [row.warehouse_name, row.sku, row.material_name, row.lot_code, row.supplier_lot ?? ''].join(' ').toLocaleLowerCase().includes(keyword))
}

// 一个批次可分布在多个仓库，因此概览统计结存记录，避免把跨仓行数误称为批次数。
export function lotSummary(rows: PhysicalLotRow[]): Record<LotFilter, number> {
  const legacy = rows.filter(row => row.source_kind === 'legacy').length
  return { all: rows.length, identified: rows.length - legacy, legacy }
}
