import {watch} from 'vue'
import type {AfterSalesAction,AfterSalesAttachment,AfterSalesAttachmentList,AfterSalesDraft,AfterSalesEvidence,AfterSalesInput} from '../../../../shared/after-sales-api'
import type {AppState} from '../state'
import {displayError} from '../../utils/formatters.ts'

export function emptyAfterSalesForm():AfterSalesDraft {
  return {shipment_line_id:0,reference:'',kind:'return',quantity:'1',complaint:'',solution:'',charge_mode:'none',
    fee_amount:'0',customer_acceptance:'',warranty_days:null,warranty_basis:'',warehouse_id:1,replacement_material_id:null,replacement_quantity:null,
    replacement_unit_price:null,parts:[],reason:''}
}
export function createAfterSalesActions(state:AppState,perform:(run:()=>Promise<unknown>,message:string)=>Promise<void>){
  let owner=0,reads=0,details=0
  const can=(code:string)=>state.user.value?.permissions.includes(code)??false
  const available=()=>!!window.nexora && !state.connectionLost.value
  function clearAfterSalesDetail():void{details++;state.afterSalesDetail.value=null}
  function invalidate():void{reads++;clearAfterSalesDetail();state.afterSalesOverview.value=null;state.afterSalesLoading.value=false;state.afterSalesError.value=''}
  watch(()=>`${state.user.value?.id}:${state.user.value?.permissions.join('|')}`,()=>{
    owner++;invalidate();state.afterSalesForm.value=emptyAfterSalesForm();state.afterSalesEdit.value=null
  },{flush:'sync'})
  // 同账号断线只失效旧证据，填写内容与修订版本继续保留。
  watch(state.connectionLost,()=>{owner++;invalidate()},{flush:'sync'})
  async function loadAfterSales():Promise<boolean>{
    if(!can('after_sales.view') || !available() || state.afterSalesLoading.value)return false
    const ticket=++reads,session=owner;state.afterSalesLoading.value=true;state.afterSalesError.value='';clearAfterSalesDetail()
    try{
      const result=await window.nexora!.callApi('afterSalesOverview',undefined)
      if(ticket!==reads || session!==owner || !can('after_sales.view'))return false
      state.afterSalesOverview.value=result;return true
    }catch(error){if(ticket===reads && session===owner){state.afterSalesOverview.value=null;state.afterSalesError.value=displayError(error)}return false}
    finally{if(ticket===reads && session===owner)state.afterSalesLoading.value=false}
  }
  async function loadAfterSalesDetail(id:number):Promise<boolean>{
    if(!can('after_sales.view') || !available())return false
    clearAfterSalesDetail();const ticket=details,session=owner;state.afterSalesError.value=''
    try{
      const result=await window.nexora!.callApi('afterSalesDetail',{id})
      if(ticket!==details || session!==owner || !can('after_sales.view'))return false
      state.afterSalesDetail.value=result;return true
    }catch(error){if(ticket===details && session===owner)state.afterSalesError.value=displayError(error);return false}
  }
  function startAfterSalesCase(lineId:number):boolean{
    if(!can('after_sales.create') || !available() || state.busy.value)return false
    const original=state.afterSalesOverview.value?.sources.find(row=>row.shipment_line_id===lineId)
    if(!original || Number(original.remaining_quantity)<=0)return false
    state.afterSalesEdit.value=null;state.afterSalesForm.value={...emptyAfterSalesForm(),shipment_line_id:lineId,quantity:original.remaining_quantity,
      warranty_days:original.warranty_days??null,warranty_basis:original.warranty_basis??''}
    clearAfterSalesDetail();state.error.value='';return true
  }
  async function editAfterSalesCase(id:number):Promise<boolean>{
    if(!can('after_sales.create') || !await loadAfterSalesDetail(id))return false
    const row=state.afterSalesDetail.value
    if(!row || !['draft','rejected'].includes(row.status))return false
    state.afterSalesForm.value={shipment_line_id:row.shipment_line_id,reference:row.reference,kind:row.kind,quantity:row.quantity,
      complaint:row.complaint,solution:row.solution,charge_mode:row.charge_mode,fee_amount:row.fee_amount,
      customer_acceptance:row.customer_acceptance,warranty_days:row.warranty_days,warranty_basis:row.warranty_basis,
      warehouse_id:row.warehouse_id,replacement_material_id:row.replacement_material_id,
      replacement_quantity:row.replacement_quantity,replacement_unit_price:row.replacement_unit_price,
      parts:row.parts.map(({material_id,quantity})=>({material_id,quantity})),reason:''}
    state.afterSalesEdit.value={id:row.id,version:row.version};state.error.value='';return true
  }
  async function write(permission:string,run:()=>Promise<AfterSalesEvidence>,message:string):Promise<boolean>{
    if(!can(permission) || !available() || state.busy.value)return false
    const session=owner;let saved:AfterSalesEvidence|null=null
    await perform(async()=>{
      if(session!==owner || !available() || !can(permission))return
      const result=await run();if(session===owner && can(permission))saved=result
    },message)
    if(!saved || session!==owner || !can(permission))return false
    const id=(saved as AfterSalesEvidence).id
    await loadAfterSales();if(session===owner)await loadAfterSalesDetail(id)
    return session===owner && can(permission)
  }
  async function saveAfterSalesCase():Promise<boolean>{
    const form=state.afterSalesForm.value,edit=state.afterSalesEdit.value,session=owner
    if(form.kind==='repair' && !['free','charge'].includes(form.charge_mode)){
      state.error.value='请明确选择免费或收费维修，并填写客户同意依据。';return false
    }
    const data:AfterSalesInput&{id?:number;version?:number}={...form,
      charge_mode:form.kind==='repair'?form.charge_mode as 'free'|'charge':'none',
      fee_amount:form.kind==='repair' && form.charge_mode==='charge'?form.fee_amount:'0',
      warehouse_id:form.kind==='repair' && !form.parts.length?null:form.warehouse_id,
      replacement_material_id:form.kind==='exchange'?form.replacement_material_id:null,
      replacement_quantity:form.kind==='exchange'?form.replacement_quantity:null,
      replacement_unit_price:form.kind==='exchange'?form.replacement_unit_price:null,
      parts:form.kind==='repair'?form.parts.map(({material_id,quantity})=>({material_id,quantity})):[],...edit}
    const saved=await write('after_sales.create',()=>window.nexora!.callApi('saveAfterSalesCase',data),'售后草稿已保存，须提交并独立审核。')
    if(saved && session===owner){state.afterSalesForm.value=emptyAfterSalesForm();state.afterSalesEdit.value=null}
    return saved
  }
  async function loadAfterSalesAttachments(id:number):Promise<AfterSalesAttachmentList>{
    if(!available() || !can('after_sales.view'))throw new Error('当前不能读取售后附件。')
    const session=owner
    const result=await window.nexora!.callApi('afterSalesAttachments',{id})
    if(session!==owner || !can('after_sales.view'))throw new Error('会话或权限已变化，请重新读取售后附件。')
    return result
  }
  async function uploadAfterSalesAttachment(id:number,reason:string):Promise<AfterSalesAttachment|null>{
    if(!available() || !can('after_sales.attachment'))throw new Error('当前不能上传售后附件。')
    const session=owner
    const result=await window.nexora!.uploadAfterSalesAttachment(id,reason)
    if(session!==owner || !can('after_sales.attachment'))throw new Error('会话或权限已变化，请重新读取售后附件。')
    return result
  }
  async function reverseAfterSalesAttachment(caseId:number,attachmentId:number,reason:string):Promise<AfterSalesAttachment>{
    if(!available() || !can('after_sales.attachment'))throw new Error('当前不能撤销售后附件。')
    const session=owner
    const result=await window.nexora!.callApi('reverseAfterSalesAttachment',{caseId,attachmentId,reason})
    if(session!==owner || !can('after_sales.attachment'))throw new Error('会话或权限已变化，请重新读取售后附件。')
    return result
  }
  async function saveAfterSalesAttachment(caseId:number,attachmentId:number):Promise<string|null>{
    if(!available() || !can('after_sales.view'))throw new Error('当前不能导出售后附件。')
    const session=owner
    const result=await window.nexora!.saveAfterSalesAttachment(caseId,attachmentId)
    if(session!==owner || !can('after_sales.view'))throw new Error('会话或权限已变化，请重新读取售后附件。')
    return result
  }
  return {loadAfterSales,loadAfterSalesDetail,clearAfterSalesDetail,startAfterSalesCase,editAfterSalesCase,saveAfterSalesCase,
    loadAfterSalesAttachments,uploadAfterSalesAttachment,reverseAfterSalesAttachment,saveAfterSalesAttachment,
    recordAfterSalesLabor:(row:AfterSalesEvidence,hours:string,reason:string,evidence:string)=>write('after_sales.labor',
      ()=>window.nexora!.callApi('recordAfterSalesLabor',{id:row.id,version:row.version,hours,reason,evidence}),
      '维修实际工时已登记，原始证据保留；工时不自动形成成本或收费。'),
    reverseAfterSalesLabor:(row:AfterSalesEvidence,entryId:number,reason:string,evidence:string)=>write('after_sales.labor',
      ()=>window.nexora!.callApi('reverseAfterSalesLabor',{id:row.id,version:row.version,entry_id:entryId,reason,evidence}),
      '维修工时已追加反向更正，原始证据保留。'),
    changeAfterSalesCase:(row:AfterSalesEvidence,action:AfterSalesAction,reason:string,evidence:string,inspection_result?:'pass'|'fail')=>write(
      ['approve','reject'].includes(action)?'after_sales.review':`after_sales.${action}`,
      ()=>window.nexora!.callApi('changeAfterSalesCase',{id:row.id,version:row.version,action,reason,evidence,inspection_result}),
      action==='process'?'关联业务草稿已建立，库存与往来金额须由原单据确认。':'售后阶段及证据已更新，客户物品保管与原单据历史保留。')}
}
