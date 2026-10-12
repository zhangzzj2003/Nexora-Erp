import type { OtherInbound } from '../../../../../shared/erp-api'
import { documentSearch } from '../../../../../shared/document-numbering.ts'
import { dateFieldError } from '../../../utils/date-field.ts'
import { otherInboundGroup, type OtherInboundFilter } from './other-inbound-summary.ts'
import type { WorkspaceSelectOption } from '../../../utils/workspace-select'

export type OtherInboundListFilters = {
  operatorId: number | null
  warehouseId: number | null
  source: OtherInbound['reason'] | null
  fromDate: string
  toDate: string
}

// 每次重置创建独立对象，搜索条件不会混入新建、详情或重开草稿。
export function emptyOtherInboundFilters(): OtherInboundListFilters {
  return { operatorId: null, warehouseId: null, source: null, fromDate: '', toDate: '' }
}

export function otherInboundDateIssue(filters: Pick<OtherInboundListFilters, 'fromDate' | 'toDate'>): string {
  const issue = dateFieldError(filters.fromDate, {}) || dateFieldError(filters.toDate, {})
  if (issue) return issue
  return filters.fromDate && filters.toDate && filters.fromDate > filters.toDate ? '开始日期不能晚于结束日期。' : ''
}

// 处理人按列表现有创建人字段匹配 ID，同名账号不会互相混淆；名单来自完整历史快照。
export function otherInboundOperatorOptions(inbounds: readonly OtherInbound[]): WorkspaceSelectOption<number | null>[] {
  const operators = new Map<number, string>()
  for (const item of inbounds) operators.set(item.created_by, item.created_by_name)
  return [{ value: null, label: '全部处理人' }, ...Array.from(operators, ([value, name]) => ({ value, label: `${name}（#${value}）` }))]
}

// 保留已移除仓库的历史选项，避免历史单据有记录却无法按仓库检索。
export function otherInboundWarehouseOptions(
  inbounds: readonly OtherInbound[], warehouses: readonly { id: number; name: string }[],
): WorkspaceSelectOption<number | null>[] {
  const names = new Map(inbounds.map(item => [item.warehouse_id, item.warehouse_name]))
  for (const warehouse of warehouses) names.set(warehouse.id, warehouse.name)
  return [{ value: null, label: '全部仓库' }, ...Array.from(names, ([value, label]) => ({ value, label }))]
}

export function filterOtherInbounds(
  inbounds: readonly OtherInbound[], query: string, filters: OtherInboundListFilters, status: OtherInboundFilter,
): OtherInbound[] {
  if (otherInboundDateIssue(filters)) return []
  const keyword = query.trim().toLowerCase()
  return inbounds.filter(item => {
    if (status !== 'all' && otherInboundGroup(item) !== status) return false
    if (filters.operatorId !== null && item.created_by !== filters.operatorId) return false
    if (filters.warehouseId !== null && item.warehouse_id !== filters.warehouseId) return false
    if (filters.source !== null && item.reason !== filters.source) return false
    if (filters.fromDate || filters.toDate) {
      // 无时区的 SQLite 时间按 UTC 解析，再取设备本地日期，与列表时间显示一致，结束日包含全天。
      const normalized = item.created_at.replace(' ', 'T')
      const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : normalized + 'Z')
      if (Number.isNaN(date.getTime())) return false
      const day = `${String(date.getFullYear()).padStart(4, '0')}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
      if ((filters.fromDate && day < filters.fromDate) || (filters.toDate && day > filters.toDate)) return false
    }
    return [documentSearch(item), item.id, item.reference, item.warehouse_name, item.note,
      ...item.lines.map(line => line.material_name)].join(' ').toLowerCase().includes(keyword)
  })
}
