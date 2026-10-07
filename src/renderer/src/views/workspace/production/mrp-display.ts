import type { MrpAction, MrpPlan, MrpPlanInput, MrpSource, MrpCheck, MrpSuggestion } from '../../../../../shared/mrp-api'
import { dateFieldError } from '../../../utils/date-field.ts'

export const mrpStatus = { draft: '草稿', submitted: '待审核', approved: '已批准', rejected: '已驳回', cancelled: '已取消' }
export const mrpAction = { submit: '提交审核', approve: '批准计划', reject: '驳回计划', cancel: '取消计划' }
export const mrpMode = { auto: '自动：有启用 BOM 则生产', buy: '采购', make: '生产' }
export function mrpSourceStatus(status?: string): string {
  const names: Record<string, string> = { draft:'草稿', submitted:'待审批', approved:'已批准', rejected:'已驳回',
    confirmed:'已确认', partially_received:'部分入库', received:'已入库', partially_shipped:'部分出库',
    shipped:'已出库', released:'已下达', in_progress:'进行中', completed:'已完成', cancelled:'已取消' }
  return names[status ?? ''] ?? '状态待核对'
}
export function mrpActions(item: MrpPlan, permissions: string[], userId: number): MrpAction[] {
  const result: MrpAction[] = []
  // 审核动作统一进入共用审批弹窗，待审或已批准计划须先撤回才能取消。
  if (!['submitted', 'approved'].includes(item.approval?.status ?? '') && item.status !== 'cancelled' && permissions.includes('mrp.cancel') && item.conversions.every(row => row.target_status === 'cancelled')) result.push('cancel')
  return result
}
export function mrpCanConvert(item: MrpPlan | null, check: MrpCheck | null, row: MrpSuggestion, permissions: string[]): boolean {
  // 原生旧批准不能代替独立审批；分批转单沿用同一批准正文。
  return !!item && item.status === 'approved' && ['approved', 'executed'].includes(item.approval?.status ?? '')
    && !!check?.matched && permissions.includes('mrp.convert')
    && permissions.includes(row.supply_mode === 'buy' ? 'purchase_request.create' : 'work_order.create')
    && !item.conversions.some(value => value.suggestion_key === row.key)
}
export const mrpQuantityValid = (value: string): boolean => /^\d{1,7}(?:\.\d{1,3})?$/.test(value) && Number(value) <= 1_000_000
export function mrpDraftError(form: MrpPlanInput, today: string): string {
  if (!form.reference.trim() || !form.reason.trim()) return '请填写计划编号和编制依据。'
  if (dateFieldError(form.start_date, { required: true, min: today })) return '计划起日须有效且不早于服务端今天。'
  if ((Date.parse(form.start_date) - Date.parse(today)) / 86400000 > 730) return '计划起日不能晚于今天 730 天。'
  for (const row of [...form.demand_dates, ...form.supply_dates, ...form.manual_demands]) {
    if (dateFieldError(row.due_date, { required: true, min: form.start_date }) ||
      (Date.parse(row.due_date) - Date.parse(form.start_date)) / 86400000 > 730) return '请逐项安排计划起日起 730 天内的需求和供给日期。'
  }
  if (form.manual_demands.some(row => row.material_id <= 0 || !row.reference.trim() || !mrpQuantityValid(row.quantity) || Number(row.quantity) <= 0)) return '手工需求须选择物料、填写正数量和来源编号。'
  return ''
}
export function mrpSourceLabel(row: MrpSource): string {
  const kind = { sales_order:'销售订单', purchase_order:'采购订单', purchase_request:'采购申请', work_order:'工单',
    work_order_requirement:'工单待领', planned_work_order:'建议工单', manual:'手工需求' }[row.kind] ?? row.kind
  return `${kind} ${row.reference || (row.source_id ? '#' + row.source_id : row.parent_key || row.key)}${row.party_name ? ' · ' + row.party_name : ''}`
}
