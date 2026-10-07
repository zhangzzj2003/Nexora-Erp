import type { QualityAction, QualityEvidence, QualityStatus, QualityTreatment } from '../../../../../shared/quality-api'

export const qualityStatus:Record<QualityStatus,string>={draft:'草稿',submitted:'待独立审核',approved:'已批准',rejected:'已驳回',cancelled:'已取消',posted:'已确认',reversed:'已更正'}
export const qualityTreatment:Record<QualityTreatment,string>={absorb:'由合格品承担',expense:'独立报废损失',carry:'携带来源成本返工'}
export const qualityCommand:Record<QualityAction,string>={submit:'提交处置',approve:'批准处置',reject:'驳回处置',post:'确认处置',cancel:'取消处置',reverse:'更正处置'}
export function qualityActions(row:QualityEvidence,permissions:string[],userId:number):QualityAction[] {
  const can=(permission:string)=>permissions.includes(permission), result:QualityAction[]=[]
  // 送审与分步审核由共用审批弹窗处理，普通确认不能使用旧原生批准。
  if(row.status==='approved' && row.approval?.status==='approved' && row.current_source_valid && !row.cost_allocation && can('quality.post'))result.push('post')
  if(['draft','submitted','approved','rejected'].includes(row.status) && !['submitted','approved'].includes(row.approval?.status??'') && can('quality.cancel'))result.push('cancel')
  if(row.status==='posted' && row.reversal_approval?.status==='approved' && !row.cost_allocation && can('quality.reverse'))result.push('reverse')
  return result
}
const names:Record<string,string>={reference:'依据编号',quantity:'处置数量',kind:'处置方式',loss_treatment:'成本处理',
  defect:'缺陷记录',action_note:'处置说明',warehouse_id:'返工目标仓库',materials_json:'追加材料快照',source_json:'原质检快照',status:'状态',rework_order_id:'返工工单',version:'版本'}
function value(key:string,data:Record<string,unknown>|null):string {
  const content=data?.[key]
  if(content==null)return '—'
  if(key==='status')return qualityStatus[content as QualityStatus]??String(content)
  if(key==='loss_treatment')return qualityTreatment[content as QualityTreatment]??String(content)
  if(key==='kind')return content==='scrap'?'报废':'返工'
  if(key==='materials_json'){
    try { const lines=JSON.parse(String(content)) as {sku:string;material_name:string;quantity:string;unit:string}[]
      return lines.length?lines.map(line=>`${line.sku} · ${line.material_name} · ${line.quantity} ${line.unit}`).join('\n'):'无追加材料'
    }catch{return '快照无法读取，请重新加载证据'}
  }
  if(key==='source_json'){
    try { const source=JSON.parse(String(content)) as Record<string,unknown>
      return `完工 #${source.id} · 工单 #${source.work_order_id} · ${source.product_name}\n报工 ${source.reported_quantity} · 合格 ${source.accepted_quantity} · 不合格 ${source.rejected_quantity}\n${source.qc_note}`
    }catch{return '快照无法读取，请重新加载证据'}
  }
  return String(content)
}
export function qualityChanges(before:Record<string,unknown>|null,after:Record<string,unknown>):{name:string;before:string;after:string}[]{
  return Object.entries(names).filter(([key])=>!before || before[key]!==after[key]).map(([key,name])=>({name,before:value(key,before),after:value(key,after)}))
}
