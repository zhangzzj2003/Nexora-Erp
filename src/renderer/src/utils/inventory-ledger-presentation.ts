import type { WorkspaceTableColumn } from './table-columns'
import { paddedShortLocalTime } from './formatters.ts'

// 主表与物料弹窗使用相同的字段顺序和紧凑列宽；编号保持完整，不截断真实业务单号。
export const ledgerMovementColumns: WorkspaceTableColumn[] = [
  { key: 'time', title: '时间', width: '140' },
  { key: 'operator', title: '处理人', width: '90' },
  { key: 'warehouse_name', title: '仓库', width: '94' },
  { key: 'source_type', title: '单据类型', width: '118' },
  { key: 'source_document', title: '单据编号', width: '218' },
  { key: 'quantity', title: '变动', width: '108', align: 'right' },
  { key: 'balance', title: '筛选范围结余', width: '130', align: 'right' }
]
export const ledgerColumns: WorkspaceTableColumn[] = [
  { key: 'sku', title: '物料编号', width: '152' },
  { key: 'material_name', title: '物料名称', width: '190' },
  ...ledgerMovementColumns
]
export const ledgerTime = paddedShortLocalTime
