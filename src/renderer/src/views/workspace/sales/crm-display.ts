import type { CrmForms, CrmKind, CrmQuote, CrmQuoteAction } from '../../../../../shared/crm-api'
import { dateFieldError } from '../../../utils/date-field.ts'

export const crmKindLabel = {contact:'联系人',activity:'客户跟进',opportunity:'销售商机',quote:'销售报价'}
export const crmStageLabel = {prospect:'初步接洽',qualified:'需求明确',proposal:'方案报价',negotiation:'商务洽谈',won:'已转单',lost:'已丢单'}
export const crmQuoteLabel = {draft:'草稿',submitted:'待审核',approved:'已批准',rejected:'已驳回',cancelled:'已取消',converted:'已转单'}
export const crmActivityLabel = {planned:'待跟进',completed:'已完成',cancelled:'已取消'}
export const crmCommandLabel = {submit:'提交报价',approve:'批准报价',reject:'驳回报价',cancel:'取消报价',convert:'转销售草稿',
  complete:'完成跟进',cancelActivity:'取消跟进',reopen:'重开商机'}
export const crmAuditLabel: Record<string,string> = {create:'建立记录',edit:'修订记录',submit:'提交报价',approve:'批准报价',
  reject:'驳回报价',cancel:'取消记录',convert:'报价转单',withdraw:'撤回报价审批',complete:'完成跟进',reopen:'重开商机'}

export function quoteActions(quote: CrmQuote, permissions: string[], _userId: number): (CrmQuoteAction|'convert')[] {
  const result: (CrmQuoteAction|'convert')[]=[]
  const open=!['won','lost'].includes(quote.opportunity_stage)
  const valid=open && !quote.expired && quote.contact_active
  // 送审与审核统一在审批弹窗处理；转单必须同时取得本单批准和原领域授权。
  if(quote.status==='approved' && quote.approval?.status==='approved' && valid && permissions.includes('crm_quote.convert') && permissions.includes('sales_order.create'))result.push('convert')
  if(!['cancelled','converted'].includes(quote.status) && !['submitted','approved'].includes(quote.approval?.status??'') && permissions.includes('crm_quote.cancel'))result.push('cancel')
  return result
}

export function crmSnapshotRows(kind: CrmKind, source: Record<string,unknown>): {label:string; value:string}[] {
  const labels: Record<string,string>={version:'版本',customer_id:'客户编号',contact_id:'联系人编号',opportunity_id:'商机编号',
    name:'联系人姓名',job_title:'职务',phone:'电话',email:'邮箱',is_active:'启用状态',note:'说明',title:'商机名称',
    owner_id:'负责人编号',estimated_amount:'预估金额（元）',probability_percent:'成交概率（%）',expected_close_date:'预计成交日',subject:'跟进事项',due_date:'跟进期限',result:'跟进结果',
    reference:'报价编号',valid_until:'报价有效期',terms:'商务条款',total_amount:'报价金额（元）',sales_order_id:'销售订单编号',acceptance_reference:'客户接受依据'}
  const result=Object.entries(labels).filter(([key])=>key in source).map(([key,label])=>({label,value:key==='is_active' ? source[key]?'启用':'停用' : source[key]==null || source[key]===''?'未填写':String(source[key])}))
  if('stage' in source)result.push({label:'商机阶段',value:crmStageLabel[source.stage as keyof typeof crmStageLabel]??'状态待核对'})
  if('status' in source)result.push({label:'单据阶段',value:(kind==='quote'?crmQuoteLabel:crmActivityLabel)[source.status as never]??'状态待核对'})
  if(source.party && typeof source.party==='object'){
    const party=source.party as Record<string,unknown>
    for(const [key,label] of [['customer_name','报价客户'],['contact_name','报价联系人'],['phone','报价电话'],['email','报价邮箱']])result.push({label,value:String(party[key]||'未填写')})
  }
  return result
}

const amountValid=(value:string,max:number,precision:number)=>new RegExp(`^\\d+(?:\\.\\d{1,${precision}})?$`).test(value) && Number.isFinite(Number(value)) && Number(value)<=max
export function crmFormError(kind: CrmKind, forms: CrmForms): string {
  if(kind==='contact')return !forms.contact.customer_id || !forms.contact.name.trim() ? '请选择客户并填写联系人姓名。' : ''
  if(kind==='activity'){
    const item=forms.activity
    if(!item.customer_id || !item.owner_id || !item.subject.trim())return '请选择客户、负责人并填写跟进事项。'
    return dateFieldError(item.due_date,{required:true,min:'1900-01-01',max:'2199-12-31'}) ? '请填写有效的跟进期限。' : ''
  }
  if(kind==='opportunity'){
    const item=forms.opportunity
    if(!item.customer_id || !item.owner_id || !item.title.trim())return '请选择客户、负责人并填写商机名称。'
    if(!amountValid(item.estimated_amount,100_000_000_000,2))return '预估金额须非负、最多两位小数且不超过一千亿元。'
    if(item.probability_percent!==null && (!Number.isSafeInteger(item.probability_percent) || item.probability_percent<0 || item.probability_percent>100))return '成交概率须为 0 至 100 的整数，或留空表示未评估。'
    return dateFieldError(item.expected_close_date,{required:true,min:'1900-01-01',max:'2199-12-31'}) ? '请填写有效的预计成交日。' : ''
  }
  const item=forms.quote
  if(!item.opportunity_id || !item.reference.trim())return '请选择开放的商机并填写报价编号。'
  if(dateFieldError(item.valid_until,{required:true,min:'1900-01-01',max:'2199-12-31'}))return '请填写有效的报价有效期，服务端另行核对是否过期。'
  if(!item.lines.length || item.lines.length>100 || item.lines.some(line=>!line.material_id || !amountValid(line.quantity,1_000_000,3) || Number(line.quantity)<=0 || !amountValid(line.unit_price,1_000_000_000,4)))return '报价须有 1 至 100 行，数量为正、最多三位小数，单价非负、最多四位小数。'
  return new Set(item.lines.map(line=>line.material_id)).size!==item.lines.length ? '同一报价不能重复选择物料。' : ''
}
