import type { WarehouseOutbound } from '../../../../../shared/erp-api'
import { documentSearch } from '../../../../../shared/document-numbering.ts'
import { physicalLotKindLabel } from '../../../../../shared/physical-lot-api.ts'
import { dateFieldError } from '../../../utils/date-field.ts'
import type { AppStatusTone } from '../../../components/app/AppStatusTag.vue'
import type { WorkspaceSelectOption } from '../../../utils/workspace-select'

export type OutboundStatusFilter = 'all' | 'pending' | 'processed' | 'cancelled' | 'reversed'
type OutboundState = Pick<WarehouseOutbound, 'status' | 'reversal_id' | 'purchase_return_reversal_id' | 'approval'>
export type OutboundListFilters = {
  operatorId: number | null
  warehouseId: number | null
  source: WarehouseOutbound['reason'] | null
  fromDate: string
  toDate: string
}
export const outboundReasonNames = { scrap: '报废', sample: '样品', other: '其他', purchase_return: '采购退货' }

// 终态优先；采购退货的冲销来自原退货单，不能误计为已处理的正常出库。
export function outboundGroup(item: OutboundState): Exclude<OutboundStatusFilter, 'all'> {
  if (item.status === 'cancelled') return 'cancelled'
  if (item.reversal_id || item.purchase_return_reversal_id) return 'reversed'
  return item.status === 'posted' ? 'processed' : 'pending'
}
export function outboundSummary(items: readonly OutboundState[]): Record<OutboundStatusFilter, number> {
  const summary = { all: items.length, pending: 0, processed: 0, cancelled: 0, reversed: 0 }
  for (const item of items) summary[outboundGroup(item)] += 1
  return summary
}
export function outboundStatus(item: OutboundState): string {
  if (item.status === 'cancelled') return '已取消'
  if (item.purchase_return_reversal_id) return '采购退货已冲销'
  if (item.reversal_id) return '已冲销'
  if (item.status === 'posted') return '已出库'
  return { draft: '待送审', submitted: '审批中', approved: '已批准待出库', rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }[item.approval?.status ?? 'draft']
}
export function outboundStatusTone(item: OutboundState): AppStatusTone {
  const group = outboundGroup(item)
  if (group === 'cancelled') return 'neutral'
  if (group === 'reversed') return 'reversed'
  if (group === 'processed') return 'success'
  return ({ draft: 'pending', submitted: 'info', approved: 'ready', rejected: 'danger', withdrawn: 'neutral', executed: 'success' } as const)[item.approval?.status ?? 'draft']
}

// 筛选只影响列表，不写入创建草稿，也不改变完整快照上的概览数量。
export function emptyOutboundFilters(): OutboundListFilters {
  return { operatorId: null, warehouseId: null, source: null, fromDate: '', toDate: '' }
}
export function outboundDateIssue(filters: Pick<OutboundListFilters, 'fromDate' | 'toDate'>): string {
  const issue = dateFieldError(filters.fromDate, {}) || dateFieldError(filters.toDate, {})
  if (issue) return issue
  return filters.fromDate && filters.toDate && filters.fromDate > filters.toDate ? '开始日期不能晚于结束日期。' : ''
}
export function outboundOperatorOptions(items: readonly WarehouseOutbound[]): WorkspaceSelectOption<number | null>[] {
  // 使用账号编号区分同名处理人，名单由完整历史单据提供。
  const names = new Map(items.map(item => [item.created_by, item.created_by_name]))
  return [{ value: null, label: '全部处理人' }, ...Array.from(names, ([value, name]) => ({ value, label: `${name}（#${value}）` }))]
}
export function outboundWarehouseOptions(items: readonly WarehouseOutbound[], warehouses: readonly { id: number; name: string }[]): WorkspaceSelectOption<number | null>[] {
  // 历史单据中的仓库也要可选，当前档案更名时优先展示新名称。
  const names = new Map(items.map(item => [item.warehouse_id, item.warehouse_name]))
  for (const warehouse of warehouses) names.set(warehouse.id, warehouse.name)
  return [{ value: null, label: '全部仓库' }, ...Array.from(names, ([value, label]) => ({ value, label }))]
}
export function filterOutbounds(items: readonly WarehouseOutbound[], query: string, filters: OutboundListFilters, status: OutboundStatusFilter): WarehouseOutbound[] {
  if (outboundDateIssue(filters)) return []
  const keyword = query.trim().toLowerCase()
  return items.filter(item => {
    if (status !== 'all' && outboundGroup(item) !== status) return false
    if (filters.operatorId !== null && item.created_by !== filters.operatorId) return false
    if (filters.warehouseId !== null && item.warehouse_id !== filters.warehouseId) return false
    if (filters.source !== null && item.reason !== filters.source) return false
    if (filters.fromDate || filters.toDate) {
      // 与其他入库一致：服务端无时区时间按 UTC 解析，再按本地显示日期包含首尾全天。
      const normalized = item.created_at.replace(' ', 'T')
      const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : normalized + 'Z')
      if (Number.isNaN(date.getTime())) return false
      const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
      if ((filters.fromDate && day < filters.fromDate) || (filters.toDate && day > filters.toDate)) return false
    }
    return [documentSearch(item), item.id, item.reference, item.warehouse_name, item.note,
      ...item.lines.flatMap(line => [line.sku, line.material_name])].join(' ').toLowerCase().includes(keyword)
  })
}

// 行内只展示前两项，悬停仍能核对普通出库或实物批次证据，完整明细继续由详情提供。
export function outboundMaterialTitle(item: WarehouseOutbound, line: WarehouseOutbound['lines'][number]): string {
  const summary = `${line.material_name} × ${line.quantity} ${line.unit}`
  if (item.status !== 'posted') return summary
  const proof = line.physical_lots?.length
    ? `实物批次：${line.physical_lots.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、')}`
    : '普通出库，未指定实物批次。'
  return `${summary}\n${proof}`
}
