import type { SalesOrder, Shipment, SalesReturn } from '../../../shared/erp-api'
import type { WorkspaceTableColumn } from './table-columns'
import type { AppStatusTone } from '../components/app/AppStatusTag.vue'

export type SalesDocument = SalesOrder | Shipment | SalesReturn
export type SalesDocumentKind = 'order' | 'shipment' | 'return'
export type SalesSummaryKey = '' | 'pending' | 'active' | 'completed' | 'cancelled' | 'reversed'
// 概览按业务结果分组，审批中、驳回和撤回仍属于尚未执行的草稿。
export function salesSummaryGroup(row: {status:string; reversal_id?:number|null}): SalesSummaryKey {
  if (row.reversal_id) return 'reversed'
  if (row.status === 'cancelled') return 'cancelled'
  if (row.status === 'draft') return 'pending'
  if (['posted', 'shipped', 'closed'].includes(row.status)) return 'completed'
  return 'active'
}
export function salesBusinessStatus(row: {status:string; reversal_id?:number|null}, kind: SalesDocumentKind): {label: string; tone: AppStatusTone} {
  if (row.reversal_id) return {label: '已冲销', tone: 'reversed'}
  const labels: Record<string, {label: string; tone: AppStatusTone}> = {
    draft: {label: '草稿', tone: 'neutral'}, confirmed: {label: '待出库', tone: 'ready'},
    partially_shipped: {label: '部分出库', tone: 'pending'}, shipped: {label: '全部出库', tone: 'success'},
    closed: {label: '剩余交付已终止', tone: 'neutral'}, cancelled: {label: '已取消', tone: 'neutral'},
    posted: {label: kind === 'return' ? '已退货入库' : '已出库', tone: 'success'},
  }
  return labels[row.status] ?? {label: '状态待核对', tone: 'neutral'}
}
export function salesApprovalStatus(row: Pick<SalesDocument, 'approval'>): {label: string; tone: AppStatusTone} {
  const labels: Record<string, {label: string; tone: AppStatusTone}> = {
    draft: {label: '未送审', tone: 'neutral'}, submitted: {label: '审批中', tone: 'pending'},
    approved: {label: '已批准', tone: 'ready'}, rejected: {label: '已驳回', tone: 'danger'},
    withdrawn: {label: '已撤回', tone: 'neutral'}, executed: {label: '已执行', tone: 'success'},
  }
  // 未读取到审批信息时不推断为已批准或已执行。
  return labels[row.approval?.status ?? 'draft'] ?? {label: '待核对', tone: 'neutral'}
}
export function salesListColumns(kind: SalesDocumentKind): WorkspaceTableColumn[] {
  // 与生产计划一样按字段分列，固定编号和操作，长列表只在表格内部横向滚动。
  return [
    {key:'document', title:kind === 'order' ? '订单编号' : kind === 'shipment' ? '出库单号' : '退货单号', width:'220'},
    {key:'customer_name', title:'客户', width:'200'},
    ...(kind !== 'shipment' ? [{key:'amount', title:kind === 'return' ? '退货金额（元）' : '订单金额（元）', width:'160', align:'right' as const}] : []),
    {key:'approval', title:'审批状态', width:'130'}, {key:'status', title:'业务状态', width:kind === 'order' ? '170' : '140'},
    {key:'materials', title:'物料摘要', width:'220'},
    ...(kind === 'order' ? [{key:'reference', title:'参考单号', width:'180'}] : [
      {key:'source', title:kind === 'return' ? '原出库单' : '销售订单', width:'220'},
      {key:'warehouse_name', title:kind === 'return' ? '退货仓库' : '出库仓库', width:'160'}]),
    {key:'created_at', title:'创建时间', width:'180'}, {key:'created_by_name', title:'创建人', width:'130'},
    {key:'actions', title:'操作', width:'100', align:'center'},
  ]
}
export function salesLineColumns(kind: SalesDocumentKind): WorkspaceTableColumn[] {
  const columns: WorkspaceTableColumn[] = [{key:'sku',title:'物料编码',width:'170'}, {key:'material_name',title:'物料名称',width:'220'},
    {key:'unit',title:'单位',width:'80'}, {key:'quantity',title:kind === 'order' ? '订购数量' : kind === 'shipment' ? '出库数量' : '退货数量',width:'130',align:'right'}]
  if(kind !== 'shipment') columns.push({key:'unit_price',title:'单价（元）',width:'140',align:'right'}, {key:'line_total',title:'金额（元）',width:'150',align:'right'})
  if(kind === 'order') columns.push(...['shipped_quantity','returned_quantity','net_delivered_quantity','remaining_quantity'].map((key,index)=>({key,title:['已出库','已退货','净交付','待交付'][index],width:'130',align:'right' as const})),
    {key:'warranty_days',title:'保修天数',width:'120'}, {key:'warranty_basis',title:'保修依据',width:'240'})
  else {
    if(kind === 'shipment') columns.push({key:'returned_quantity',title:'已退数量',width:'130',align:'right'}, {key:'returnable_quantity',title:'可退数量',width:'130',align:'right'})
    columns.push({key:'physical_lots',title:'实物批次',width:'280'})
  }
  return columns
}
