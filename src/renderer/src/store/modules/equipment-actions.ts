import {watch} from 'vue'
import type {AppState} from '../state'
import type {EquipmentEntity,EquipmentForms,EquipmentDetail,EquipmentMeterInput,MaintenanceCommand,
  EquipmentAttachmentKind,EquipmentAttachment,EquipmentAttachmentList,MaintenancePurchaseInput} from '../../../../shared/equipment-api'
import {validateDocumentApprovalRecord} from '../../../../shared/document-approval-api.ts'
import {displayError} from '../../utils/formatters.ts'

export function emptyEquipmentForms():EquipmentForms {
  return {asset:{code:'',name:'',serial_number:'',location:'',status:'active',reason:''},
    plan:{equipment_id:0,reference:'',title:'',interval_days:30,next_due:'',enabled:true,reason:''},
    hour_plan:{equipment_id:0,reference:'',title:'',interval_hours:'100.00',next_due_hours:'',enabled:true,reason:''},
    job:{reference:'',equipment_id:0,kind:'corrective',plan_id:null,hour_plan_id:null,work_order_id:null,assigned_to:0,request_note:'',warehouse_id:null,parts:[],reason:''}}
}
export function createEquipmentActions(state:AppState,perform:(run:()=>Promise<unknown>,message:string)=>Promise<void>){
  let owner=0,reads=0,details=0
  const can=(code:string)=>state.user.value?.permissions.includes(code)??false
  const available=()=>!!window.nexora && !state.connectionLost.value && can('equipment.view')
  function resetForm(kind:EquipmentEntity):void{
    const empty=emptyEquipmentForms()
    if(kind==='asset')state.equipmentForms.value.asset=empty.asset
    else if(kind==='plan')state.equipmentForms.value.plan=empty.plan
    else if(kind==='hour_plan')state.equipmentForms.value.hour_plan=empty.hour_plan
    else state.equipmentForms.value.job=empty.job
  }
  function clearEquipmentDetail():void{details++;state.equipmentDetail.value=null}
  function invalidate():void{reads++;clearEquipmentDetail();state.equipmentOverview.value=null;state.equipmentLoading.value=false;state.equipmentError.value=''}
  watch(()=>`${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`,()=>{
    owner++;invalidate();state.equipmentForms.value=emptyEquipmentForms();state.equipmentEdit.value=null
  },{flush:'sync'})
  // 断线失效旧证据，保留同账号未保存正文和旧版本，恢复后由用户复核。
  watch(state.connectionLost,()=>{owner++;invalidate()},{flush:'sync'})
  async function loadEquipment():Promise<boolean>{
    if(!available() || state.equipmentLoading.value)return false
    const ticket=++reads,session=owner;state.equipmentLoading.value=true;state.equipmentError.value='';clearEquipmentDetail()
    try{
      const result=await window.nexora!.callApi('equipmentOverview',undefined)
      if(ticket!==reads || session!==owner || !available())return false
      state.equipmentOverview.value=result;return true
    }catch(error){if(ticket===reads && session===owner){state.equipmentOverview.value=null;state.equipmentError.value=displayError(error)}return false}
    finally{if(ticket===reads && session===owner)state.equipmentLoading.value=false}
  }
  async function loadEquipmentDetail(kind:EquipmentEntity,id:number):Promise<boolean>{
    if(!available())return false
    clearEquipmentDetail();const ticket=details,session=owner;state.equipmentError.value=''
    try{
      const result:EquipmentDetail=kind==='asset'?{kind,row:await window.nexora!.callApi('equipmentDetail',{id})}
        :kind==='plan'?{kind,row:await window.nexora!.callApi('maintenancePlanDetail',{id})}
        :kind==='hour_plan'?{kind,row:await window.nexora!.callApi('maintenanceHourPlanDetail',{id})}
        :{kind,row:await window.nexora!.callApi('maintenanceJobDetail',{id})}
      if(ticket!==details || session!==owner || !available())return false
      state.equipmentDetail.value=result;return true
    }catch(error){if(ticket===details && session===owner)state.equipmentError.value=displayError(error);return false}
  }
  function startEquipmentRecord(kind:EquipmentEntity,equipmentId=0,planId:number|null=null,hourPlanId:number|null=null):boolean{
    if(!available() || !can(kind==='job'?'equipment.create':'equipment.manage') || state.busy.value)return false
    resetForm(kind);state.equipmentEdit.value=null
    if(kind==='plan')state.equipmentForms.value.plan.equipment_id=equipmentId
    if(kind==='hour_plan')state.equipmentForms.value.hour_plan.equipment_id=equipmentId
    if(kind==='job')Object.assign(state.equipmentForms.value.job,{equipment_id:equipmentId,plan_id:planId,hour_plan_id:hourPlanId,
      kind:planId || hourPlanId?'preventive':'corrective',assigned_to:state.equipmentOverview.value?.executors.find(row=>row.id===state.user.value?.id)?.id??0})
    clearEquipmentDetail();state.error.value='';return true
  }
  async function editEquipmentRecord(kind:EquipmentEntity,id:number):Promise<boolean>{
    if(!can(kind==='job'?'equipment.create':'equipment.manage') || !await loadEquipmentDetail(kind,id))return false
    const detail=state.equipmentDetail.value;if(!detail || detail.kind!==kind)return false
    const row=detail.row
    if(detail.kind==='asset'){
      const item=detail.row;state.equipmentForms.value.asset={code:item.code,name:item.name,serial_number:item.serial_number,location:item.location,status:item.status,reason:''}
    }else if(detail.kind==='plan'){
      const item=detail.row;state.equipmentForms.value.plan={equipment_id:item.equipment_id,reference:item.reference,title:item.title,interval_days:item.interval_days,next_due:item.next_due,enabled:item.enabled,reason:''}
    }else if(detail.kind==='hour_plan'){
      const item=detail.row;state.equipmentForms.value.hour_plan={equipment_id:item.equipment_id,reference:item.reference,title:item.title,
        interval_hours:item.interval_hours,next_due_hours:item.next_due_hours,enabled:item.enabled,reason:''}
    }else{
      const item=detail.row;if(!item.can_edit)return false
      state.equipmentForms.value.job={reference:item.reference,equipment_id:item.equipment_id,kind:item.kind,plan_id:item.plan_id,hour_plan_id:item.hour_plan_id,
        work_order_id:item.work_order_id,assigned_to:item.assigned_to,request_note:item.request_note,warehouse_id:item.warehouse_id,
        parts:item.parts.map(({material_id,quantity})=>({material_id,quantity})),reason:''}
    }
    state.equipmentEdit.value={kind,id:row.id,version:row.version};state.error.value='';return true
  }
  async function write(kind:EquipmentEntity,permission:string,run:()=>Promise<{id:number}>,message:string):Promise<boolean>{
    if(!available() || !can(permission) || state.busy.value)return false
    const session=owner;let id:number|null=null
    await perform(async()=>{if(session!==owner || !available() || !can(permission))return
      const saved=await run();if(session===owner && available() && can(permission))id=saved.id
    },message)
    if(id===null || session!==owner || !available() || !can(permission))return false
    await loadEquipment();if(session===owner)await loadEquipmentDetail(kind,id)
    return session===owner && available() && can(permission)
  }
  async function saveEquipmentRecord(kind:EquipmentEntity):Promise<boolean>{
    const edit=state.equipmentEdit.value,session=owner
    if(edit && edit.kind!==kind)return false
    const revision=edit?{id:edit.id,version:edit.version}:{}
    const saved=await write(kind,kind==='job'?'equipment.create':'equipment.manage',()=>{
      const form=state.equipmentForms.value
      if(kind==='asset')return window.nexora!.callApi('saveEquipment',{...form.asset,...revision})
      if(kind==='plan')return window.nexora!.callApi('saveMaintenancePlan',{...form.plan,...revision})
      if(kind==='hour_plan')return window.nexora!.callApi('saveMaintenanceHourPlan',{...form.hour_plan,...revision})
      return window.nexora!.callApi('saveMaintenanceJob',{...form.job,plan_id:form.job.kind==='preventive'?form.job.plan_id:null,
        hour_plan_id:form.job.kind==='preventive'?form.job.hour_plan_id:null,
        warehouse_id:form.job.parts.length?form.job.warehouse_id:null,parts:form.job.parts.map(({material_id,quantity})=>({material_id,quantity})),...revision})
    },kind==='job'?'维护草稿已保存，须提交并独立审核。':'设备维护资料与修订记录已保存。')
    if(saved && session===owner){resetForm(kind);state.equipmentEdit.value=null}
    return saved
  }
  async function refreshEquipmentApproval(id:number):Promise<void>{
    const selected=state.equipmentDetail.value,session=owner,ticket=details
    const restore=selected?.kind==='job' && selected.row.id===id
    await loadEquipment()
    // 只恢复当前正在核对的维护单；刷新期间主动打开其他详情不能被旧请求覆盖。
    if(restore && session===owner && available() && details===ticket+1)await loadEquipmentDetail('job',id)
  }
  async function maintenanceCorrectionEvidence(id:number):Promise<{reason:string;evidence:string}|null>{
    if(!available() || !can('equipment.reverse') || state.busy.value)return null
    const session=owner
    try{
      const record=await window.nexora!.callApi('documentApproval',{document_type:'MaintenanceJob',document_id:id,intent:'reverse'})
      if(session!==owner || !available())return null
      validateDocumentApprovalRecord(record)
      if(record.document_type!=='MaintenanceJob' || record.document_id!==id || record.intent!=='reverse'
        || record.status!=='approved' || !record.content_matches || !record.reversal_reason || !record.reversal_evidence)throw Error('请先完成本单验收更正独立审批。')
      return {reason:record.reversal_reason,evidence:record.reversal_evidence}
    }catch(cause){if(session===owner)state.error.value=displayError(cause);return null}
  }
  async function changeMaintenanceJob(command:MaintenanceCommand):Promise<boolean>{
    const permission=['approve','reject'].includes(command.action)?'review':['start','report'].includes(command.action)?'execute':command.action==='rework'?'accept':command.action
    const session=owner
    let input={...command}
    if(command.action==='reverse'){
      const record=await maintenanceCorrectionEvidence(command.id)
      if(!record || session!==owner || !available())return false
      // 执行前重新读取固定依据，打开弹窗后撤回审批也不能继续更正。
      input={...command,reason:record.reason,evidence:record.evidence}
    }
    return write('job','equipment.'+permission,()=>window.nexora!.callApi('changeMaintenanceJob',input),
      '维护阶段与证据已更新；耗材实物及资金仍以原业务记录为准。')
  }
  function createMaintenancePurchaseRequest(input:MaintenancePurchaseInput):Promise<boolean>{
    if(!can('purchase_request.view'))return Promise.resolve(false)
    return write('job','purchase_request.create',()=>window.nexora!.callApi('createMaintenancePurchaseRequest',input),
      '已从维护工单创建采购申请草稿，仍须按采购流程提交、审核和转单。')
  }
  async function recordEquipmentMeter(input:EquipmentMeterInput):Promise<boolean>{
    if(!available() || !can('equipment.meter') || (input.correction && !can('equipment.manage')) || state.busy.value)return false
    const session=owner
    let saved=false
    await perform(async()=>{
      if(session!==owner || !available())return
      await window.nexora!.callApi('recordEquipmentMeter',input)
      saved=session===owner && available()
    },'设备运行小时已登记，读数历史保留原记录。')
    if(!saved)return false
    await loadEquipment()
    if(session===owner)await loadEquipmentDetail('asset',input.equipment_id)
    return session===owner && available()
  }
  async function loadEquipmentAttachments(kind:EquipmentAttachmentKind,id:number):Promise<EquipmentAttachmentList>{
    if(!available())throw new Error('会话或权限已变化，请重新读取设备维护附件')
    const session=owner
    const result=await window.nexora!.callApi('equipmentAttachments',{kind,id})
    if(session!==owner || !available())throw new Error('会话或权限已变化，请重新读取设备维护附件')
    return result
  }
  async function uploadEquipmentAttachment(kind:EquipmentAttachmentKind,id:number,reason:string):Promise<EquipmentAttachment|null>{
    if(!available() || !can('equipment.attachment'))throw new Error('会话或权限已变化，请重新上传设备维护附件')
    const session=owner
    const result=await window.nexora!.uploadEquipmentAttachment(kind,id,reason)
    if(session!==owner || !available() || !can('equipment.attachment'))throw new Error('会话或权限已变化，请刷新设备维护附件')
    return result
  }
  async function reverseEquipmentAttachment(kind:EquipmentAttachmentKind,id:number,
    attachmentId:number,reason:string):Promise<EquipmentAttachment>{
    if(!available() || !can('equipment.attachment'))throw new Error('会话或权限已变化，请重新撤销设备维护附件')
    const session=owner
    const result=await window.nexora!.callApi('reverseEquipmentAttachment',{kind,id,attachmentId,reason})
    if(session!==owner || !available() || !can('equipment.attachment'))throw new Error('会话或权限已变化，请刷新设备维护附件')
    return result
  }
  async function saveEquipmentAttachment(kind:EquipmentAttachmentKind,id:number,attachmentId:number):Promise<string|null>{
    if(!available())throw new Error('会话或权限已变化，请重新读取设备维护附件')
    const session=owner
    const result=await window.nexora!.saveEquipmentAttachment(kind,id,attachmentId)
    if(session!==owner || !available())throw new Error('会话或权限已变化，请重新读取设备维护附件')
    return result
  }
  return {loadEquipment,refreshEquipmentApproval,loadEquipmentDetail,clearEquipmentDetail,startEquipmentRecord,editEquipmentRecord,
    saveEquipmentRecord,maintenanceCorrectionEvidence,changeMaintenanceJob,createMaintenancePurchaseRequest,recordEquipmentMeter,
    loadEquipmentAttachments,uploadEquipmentAttachment,reverseEquipmentAttachment,saveEquipmentAttachment}
}
