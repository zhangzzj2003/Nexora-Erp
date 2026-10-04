import type {AfterSalesAction,AfterSalesEvidence,AfterSalesKind,AfterSalesStatus} from '../../../../../shared/after-sales-api'
export const afterSalesKind:Record<AfterSalesKind,string>={return:'退货',exchange:'换货',repair:'维修'}
export const afterSalesStatus:Record<AfterSalesStatus,string>={draft:'草稿',submitted:'待独立审核',approved:'方案已批准',
  rejected:'已驳回',processing:'退换货办理中',received:'客户物品已收件',repaired:'维修检验合格',closed:'已交付结案',cancelled:'已取消',reversed:'已更正'}
export const afterSalesCommand:Record<AfterSalesAction,string>={submit:'提交方案',approve:'批准方案',reject:'驳回申请',
  process:'建立退换货草稿',receive:'登记维修收件',inspect:'登记维修检验',close:'确认交付结案',cancel:'取消申请',reverse:'更正已结案单'}
export function repairFeeState(row:Pick<AfterSalesEvidence,'charge_mode'|'closed_at'|'reversed_at'>):string{
  if(row.charge_mode==='free')return row.closed_at?'已检验交还，免费维修不形成收费来源':'免费维修不形成收费来源'
  if(row.reversed_at)return '保留原收费及交接历史，已追加反向收费来源'
  return row.closed_at?'已检验交还，收费来源已固定':'尚未交还结案，不形成维修应收'
}
export function afterSalesReversalHint(row:Pick<AfterSalesEvidence,'kind'|'charge_mode'>):string{
  if(row.kind!=='repair')return '退换货须先更正关联业务。'
  return row.charge_mode==='charge'?'收费维修追加原服务费反向来源，不抹去实际保管交接。':'免费维修保留实际保管交接，不产生收费或反向收费来源。'
}
export function afterSalesActions(row:AfterSalesEvidence,permissions:string[],userId:number):AfterSalesAction[]{
  const permitted=(action:AfterSalesAction)=>permissions.includes(['approve','reject'].includes(action)?'after_sales.review':`after_sales.${action}`)
  const choices:AfterSalesAction[]=[]
  if(row.current_source_valid){
    if(row.status==='draft')choices.push('submit')
    if(row.status==='submitted' && !row.author_ids.includes(userId))choices.push('approve')
    if(row.status==='approved'){
      if(row.kind==='repair')choices.push('receive')
      else if(permissions.includes('sales_return.create') && (row.kind!=='exchange' || permissions.includes('sales_order.create')))choices.push('process')
    }
    if(row.status==='received')choices.push('inspect')
    if(['processing','repaired'].includes(row.status))choices.push('close')
  }
  if(row.status==='submitted' && !row.author_ids.includes(userId))choices.push('reject')
  if(['draft','submitted','approved','rejected','processing','received','repaired'].includes(row.status))choices.push('cancel')
  if(row.status==='closed')choices.push('reverse')
  return choices.filter(permitted)
}
const labels:Record<string,string>={reference:'售后依据',shipment_line_id:'原出库明细',kind:'处理方式',quantity:'数量',
  complaint:'客户诉求',solution:'办理方案',charge_mode:'收费选择',fee_amount:'服务费',customer_acceptance:'客户同意依据',
  warranty_days:'保修天数',warranty_basis:'保修依据',
  warehouse_id:'办理仓库',replacement_material_id:'换货物料',replacement_quantity:'换货数量',replacement_unit_price:'换货单价',
  status:'阶段',sales_return_id:'退货单',replacement_order_id:'换货订单',parts_outbound_id:'维修耗材出库单'}
function value(key:string,item:unknown):string{
  if(item==null)return '无'
  if(key==='status')return afterSalesStatus[item as AfterSalesStatus]??String(item)
  if(key==='kind')return afterSalesKind[item as AfterSalesKind]??String(item)
  if(key==='charge_mode')return ({none:'不涉及维修费',free:'免费维修',charge:'收费维修'} as Record<string,string>)[String(item)]??String(item)
  return String(item)
}
export function afterSalesChanges(change:AfterSalesEvidence['changes'][number]):string[]{
  const lines=Object.entries(labels).filter(([key])=>JSON.stringify(change.before?.[key])!==JSON.stringify(change.after[key]))
    .map(([key,label])=>`${label}：${value(key,change.before?.[key])} → ${value(key,change.after[key])}`)
  if(change.before?.parts_json!==change.after.parts_json){
    const parts=(raw:unknown):string=>{
      if(typeof raw!=='string')return '无'
      try{const rows=JSON.parse(raw) as {sku:string;material_name:string;quantity:string;unit:string}[]
        return rows.map(row=>`${row.sku} · ${row.material_name} ${row.quantity} ${row.unit}`).join('；')||'无'}catch{return '材料快照无法读取'}
    }
    lines.push(`维修耗材：${parts(change.before?.parts_json)} → ${parts(change.after.parts_json)}`)
  }
  return lines
}
