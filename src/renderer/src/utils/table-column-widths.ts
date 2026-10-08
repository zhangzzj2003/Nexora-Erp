import type { WorkspaceTableColumn } from './table-columns'

export const MIN_TABLE_COLUMN_WIDTH = 64
export const MAX_TABLE_COLUMN_WIDTH = 2400
export type TableColumnWidths = Record<string, number>
export type TableWidthStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
export type SizedTableColumn = Omit<WorkspaceTableColumn, 'width'> & {
  width?: string | number
  minWidth?: string | number
}

// 路由、表格名称及字段共同隔离设置，只保存布局，不写入业务数据或账号信息。
export function tableColumnWidthKey(scope: string, title: string, fields: readonly string[]): string {
  return `nexora-table-widths:v1:${[scope, title, ...fields].map(encodeURIComponent).join(':')}`
}

export function validTableColumnWidth(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value)
    && value >= MIN_TABLE_COLUMN_WIDTH && value <= MAX_TABLE_COLUMN_WIDTH
}

// 某些浏览器连 localStorage 的读取入口都会抛错，当前窗口仍允许调整列宽。
export function tableWidthStorage(): TableWidthStorage | undefined {
  try { return typeof window === 'undefined' ? undefined : window.localStorage } catch { return undefined }
}

export function readTableColumnWidths(storage: TableWidthStorage | undefined, key: string, fields: readonly string[]): TableColumnWidths {
  try {
    const text = storage?.getItem(key)
    if (!text || text.length > 16384) return {}
    const value: unknown = JSON.parse(text)
    if (!value || typeof value !== 'object' || !('version' in value) || value.version !== 1
      || !('widths' in value) || !value.widths || typeof value.widths !== 'object' || Array.isArray(value.widths)) return {}
    const widths = value.widths
    // 字段白名单阻止旧表格字段或损坏配置影响当前列，非法宽度单独忽略。
    return Object.fromEntries(fields.flatMap(field => {
      const width = Object.hasOwn(widths, field) ? Reflect.get(widths, field) : undefined
      return validTableColumnWidth(width) ? [[field, width]] : []
    }))
  } catch { return {} }
}

export function saveTableColumnWidths(storage: TableWidthStorage | undefined, key: string, widths: TableColumnWidths): void {
  try { storage?.setItem(key, JSON.stringify({ version: 1, widths })) } catch {
    // 存储被禁用或空间不足时，只跳过下次启动的记忆，不回退当前拖动结果。
  }
}

export function clearTableColumnWidths(storage: TableWidthStorage | undefined, key: string): void {
  try { storage?.removeItem(key) } catch { /* 本地存储不可用时，仍恢复当前表格的默认布局。 */ }
}

export function resolveTableColumnWidths(columns: readonly WorkspaceTableColumn[], widths: TableColumnWidths,
  stretch: boolean, defaultWidth: number): SizedTableColumn[] {
  const hasFixedColumns = columns.some(column => column.fixed)
  // 全部列都调整过时仍留一列分配余量，避免再次出现列表右侧空白；优先选择中间业务列。
  const flexible = stretch && columns.length > 0 && columns.every(column => validTableColumnWidth(widths[column.key]))
    ? [...columns].reverse().find(column => !column.fixed)?.key ?? columns[columns.length - 1].key : undefined
  return columns.map(column => {
    const saved = validTableColumnWidth(widths[column.key]) ? widths[column.key] : undefined
    const fixedWidth = saved !== undefined && column.key !== flexible
    return { ...column,
      width: fixedWidth ? saved : stretch ? undefined : column.width || (hasFixedColumns ? defaultWidth : undefined),
      minWidth: stretch && !fixedWidth ? saved ?? (column.width || defaultWidth) : undefined }
  })
}
