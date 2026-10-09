import type { WorkspaceTableColumn } from './table-columns'
// 新建表格保留原草稿行，详情和 MRP 直接携带物料编号；不从名称反查或猜测物料。
export function materialSupplyId(row: unknown): number {
  if (!row || typeof row !== 'object') return 0
  const value = row as Record<string, unknown>
  const line = value.line && typeof value.line === 'object' ? value.line as Record<string, unknown> : value
  return typeof line.material_id === 'number' && Number.isSafeInteger(line.material_id) && line.material_id > 0
    ? line.material_id : 0
}

// 供需列参与公共列宽管理，不改写页面保存的原列定义。
export function materialSupplyColumns(columns: readonly WorkspaceTableColumn[], enabled: boolean): readonly WorkspaceTableColumn[] {
  if (!enabled) return columns
  const result = [...columns]
  const index = result.findIndex(column => column.key === 'actions')
  result.splice(index < 0 ? result.length : index, 0, {key: 'materialSupply', title: '物料供需（全仓）', width: '290'})
  return result
}
