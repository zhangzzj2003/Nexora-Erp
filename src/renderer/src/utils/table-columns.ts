export interface WorkspaceTableColumn {
  key: string
  title: string
  width?: string
  // 表头和内容共用对齐方式；未配置的业务列保持表格默认布局。
  align?: 'left' | 'center' | 'right'
  // 留空沿用单据列表约定，显式 false 可让特殊业务列参与滚动。
  fixed?: 'left' | 'right' | false
}

// 只自动固定同时具备单据和操作的列表，避免把物料编辑表的移除列误当单据操作。
export function resolveTableColumns(columns: readonly WorkspaceTableColumn[]): WorkspaceTableColumn[] {
  const documentList = columns.some(column => column.key === 'document') && columns.some(column => column.key === 'actions')
  return columns.map(column => ({ ...column, fixed: column.fixed ?? (documentList
    ? column.key === 'document' ? 'left' : column.key === 'actions' ? 'right' : false
    : false) }))
}
