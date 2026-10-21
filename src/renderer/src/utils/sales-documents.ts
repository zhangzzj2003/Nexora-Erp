import { salesSummaryGroup } from './sales-presentation.ts'
import type { SalesSummaryKey } from './sales-presentation'
import type { SalesDraftState } from '../../../shared/sales-draft-api'
import { purchasePrice } from './purchase-pricing.ts'
import { sumMoney } from './money-summary.ts'
import type {SalesOrder} from '../../../shared/erp-api'
import {receiptLotMilli} from '../../../shared/receipt-lot-api.ts'

export function canReviseSalesDraft(row: SalesDraftState & {status: string; approval?: {status: string}}): boolean {
  // 旧服务端没有修订能力时不显示可编辑入口，审批状态再次限制过期列表。
  return row.status === 'draft' && typeof row.draft_version === 'number' &&
    row.draft_edit_block_reason === '' && !['submitted', 'approved'].includes(row.approval?.status ?? '')
}
export const salesLineAmount = (line: {quantity: string; unit_price: string}): string =>
  purchasePrice(line.quantity, 'unit_price', line.unit_price)
export function salesAmountSummary(lines: readonly {quantity: string; unit_price: string}[]) {
  // 与采购共用十进制金额工具，不用浮点数累加，缺项也不能当作零元。
  return {total: sumMoney(lines.map(salesLineAmount)),
    zeroCount: lines.filter(line => line.unit_price.trim() !== '' && Number(line.unit_price) === 0).length}
}
export function shipmentDraftIssue(order: SalesOrder | undefined, lines: readonly {material_id:number; quantity:string}[]): string {
  if (!order) return '请先选择销售订单。'
  if (!['confirmed','partially_shipped'].includes(order.status)) return '订单已不处于可出库状态，请刷新后重新选择。'
  if (!lines.length) return '请至少保留一条待出库明细。'
  if (new Set(lines.map(line=>line.material_id)).size !== lines.length) return '同一张出库单不能重复选择物料。'
  for (const line of lines) {
    const source = order.lines.find(item=>item.material_id===line.material_id)
    if (!source) return '请选择该订单中的物料。'
    const quantity = receiptLotMilli(line.quantity), remaining = receiptLotMilli(source.remaining_quantity)
    if (quantity === null || quantity <= 0 || remaining === null || quantity > remaining)
      return `${source.material_name} 的数量须大于零，且不能超过订单剩余 ${source.remaining_quantity} ${source.unit}。`
  }
  return ''
}
export type SalesRecordFilters = {status: string; customer: number | null; from: string; to: string; group?: SalesSummaryKey}
export const newSalesFilters = (): SalesRecordFilters => ({status:'', customer:null, from:'', to:''})
export const salesStatusLabels: Record<string, string> = {
  draft:'未送审草稿', submitted:'审批中', approved:'已批准，待执行', rejected:'已驳回', withdrawn:'已撤回',
  confirmed:'待出库', partially_shipped:'部分出库', shipped:'全部出库', posted:'已确认', cancelled:'已取消', closed:'剩余交付已终止', reversed:'已冲销'
}
export function matchesSalesFilters(row: {status: string; created_at: string; reversal_id?: number | null;
  approval?: {status: string}}, customerId: number | undefined, filters: SalesRecordFilters): boolean {
  if (filters.group && salesSummaryGroup(row) !== filters.group) return false
  const status = row.reversal_id ? 'reversed' : row.status === 'draft' && row.approval?.status &&
    row.approval.status !== 'draft' ? row.approval.status : row.status
  if (filters.status && status !== filters.status) return false
  if (filters.customer !== null && customerId !== filters.customer) return false
  if (!filters.from && !filters.to) return true
  // 日期筛选按当前设备显示日期，与页面时间保持一致，不直接截取 UTC 日期。
  const timestamp = row.created_at.replace(' ', 'T')
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp) ? timestamp : timestamp + 'Z')
  if (!Number.isFinite(date.getTime())) return false
  const day = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
  return (!filters.from || day >= filters.from) && (!filters.to || day <= filters.to)
}
