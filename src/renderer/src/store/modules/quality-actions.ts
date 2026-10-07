import { validateDocumentApprovalRecord } from '../../../../shared/document-approval-api.ts'
import { watch } from 'vue'
import type { QualityAction, QualityDraft, QualityEvidence, QualityInput } from '../../../../shared/quality-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function emptyQualityForm(): QualityDraft {
  return {completion_id:0,reference:'',kind:'scrap',quantity:'1',loss_treatment:'',defect:'',action_note:'',warehouse_id:1,materials:[],reason:''}
}

export function createQualityActions(state: AppState, perform: (run: () => Promise<unknown>, message: string) => Promise<void>) {
  let owner=0, reads=0, details=0
  const can=(permission:string)=>state.user.value?.permissions.includes(permission)??false
  const available=()=>!!window.nexora && !state.connectionLost.value
  function clearQualityDetail():void {details++;state.qualityDetail.value=null}
  function invalidate():void {
    reads++;clearQualityDetail();state.qualityOverview.value=null;state.qualityError.value='';state.qualityLoading.value=false
  }
  watch(()=>`${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`,()=>{
    owner++;invalidate();state.qualityForm.value=emptyQualityForm();state.qualityEdit.value=null
  },{flush:'sync'})
  // 断线清除旧证据，但同账号尚未保存的处置输入与旧版本仍保留。
  watch(state.connectionLost,()=>{owner++;invalidate()},{flush:'sync'})
  async function loadQuality():Promise<boolean> {
    if(!can('quality.view') || !available() || state.qualityLoading.value)return false
    const ticket=++reads, session=owner;state.qualityLoading.value=true;state.qualityError.value='';clearQualityDetail()
    try {
      const result=await window.nexora!.callApi('qualityOverview',undefined)
      if(ticket!==reads || session!==owner || !can('quality.view'))return false
      state.qualityOverview.value=result;return true
    }catch(error){if(ticket===reads && session===owner){state.qualityOverview.value=null;state.qualityError.value=displayError(error)}return false}
    finally{if(ticket===reads && session===owner)state.qualityLoading.value=false}
  }
  async function loadQualityDetail(id:number):Promise<boolean> {
    if(!can('quality.view') || !available())return false
    clearQualityDetail();const ticket=details,session=owner;state.qualityError.value=''
    try {
      const result=await window.nexora!.callApi('qualityDetail',{id})
      if(ticket!==details || session!==owner || !can('quality.view'))return false
      state.qualityDetail.value=result;return true
    }catch(error){if(ticket===details && session===owner)state.qualityError.value=displayError(error);return false}
  }
  async function refreshQualityApproval(id:number):Promise<void> {
    const session=owner,detail=state.qualityDetail.value,detailTicket=details
    if(!await loadQuality())throw new Error('处置列表刷新失败，请重新读取。')
    // 已关闭、切换详情或实例后不恢复迟到证据，未保存表单继续保留。
    if(session===owner && details===detailTicket+1 && detail?.id===id){
      if(!await loadQualityDetail(id))throw new Error('处置详情刷新失败，请重新读取。')
    }
  }
  function startQualityDisposition(completionId:number):boolean {
    if(!can('quality.create') || !available())return false
    const source=state.qualityOverview.value?.cases.find(row=>row.id===completionId)
    if(!source || source.settled || Number(source.remaining_quantity)<=0)return false
    if(state.qualityEdit.value)state.qualityForm.value=emptyQualityForm()
    state.qualityEdit.value=null;state.qualityForm.value.completion_id=completionId
    state.qualityForm.value.quantity=source.remaining_quantity;state.qualityForm.value.defect ||= source.qc_note
    state.error.value='';clearQualityDetail();return true
  }
  async function editQualityDisposition(id:number):Promise<boolean> {
    if(!can('quality.create') || !await loadQualityDetail(id))return false
    const row=state.qualityDetail.value
    if(!row || !['draft','rejected'].includes(row.status))return false
    state.qualityForm.value={completion_id:row.completion_id,reference:row.reference,kind:row.kind,quantity:row.quantity,
      loss_treatment:row.loss_treatment,defect:row.defect,action_note:row.action_note,warehouse_id:row.warehouse_id,
      materials:row.materials.map(({material_id,quantity})=>({material_id,quantity})),reason:''}
    state.qualityEdit.value={id:row.id,version:row.version};state.error.value='';return true
  }
  async function write(permission:string,run:()=>Promise<QualityEvidence|null>,message:string):Promise<boolean> {
    if(!can(permission) || !available() || state.busy.value)return false
    const session=owner;let saved:QualityEvidence|null=null
    await perform(async()=>{
      if(session!==owner || !can(permission) || !available())return
      const result=await run();if(session===owner && can(permission))saved=result
    },message)
    if(!saved || session!==owner || !can(permission))return false
    const id=(saved as QualityEvidence).id
    await loadQuality();if(session===owner)await loadQualityDetail(id)
    return session===owner && can(permission)
  }
  async function saveQualityDisposition():Promise<boolean> {
    const form=state.qualityForm.value, edit=state.qualityEdit.value, session=owner
    if(form.kind==='scrap' && !['absorb','expense'].includes(form.loss_treatment)){
      state.error.value='请明确选择报废成本由合格品承担，或列为独立损失。';return false
    }
    const data:QualityInput & {id?:number;version?:number}={completion_id:form.completion_id,reference:form.reference,
      kind:form.kind,quantity:form.quantity,loss_treatment:form.kind==='rework'?'carry':form.loss_treatment as QualityInput['loss_treatment'],
      defect:form.defect,action_note:form.action_note,warehouse_id:form.kind==='rework'?form.warehouse_id:null,
      materials:form.kind==='rework'?form.materials.map(({material_id,quantity})=>({material_id,quantity})):[],reason:form.reason,...edit}
    const saved=await write('quality.create',()=>window.nexora!.callApi('saveQualityDisposition',data),'处置草稿已保存，须提交并独立审核。')
    if(saved && session===owner){state.qualityForm.value=emptyQualityForm();state.qualityEdit.value=null}
    return saved
  }
  async function changeQualityDisposition(row:QualityEvidence,action:QualityAction,reason:string):Promise<boolean>{
    const session=owner
    return write(['approve','reject'].includes(action)?'quality.review':`quality.${action}`,async()=>{
      let fixedReason=reason
      if(action==='reverse'){
        const approved=await window.nexora!.callApi('documentApproval',{
          document_type:'QualityDisposition',document_id:row.id,intent:'reverse'})
        // 更正必须执行已批准的原因，换实例或撤权后不发出旧请求。
        if(session!==owner || !available() || !can('quality.reverse') || !can('quality.view'))return null
        validateDocumentApprovalRecord(approved)
        if(approved.document_type!=='QualityDisposition' || approved.document_id!==row.id || approved.intent!=='reverse' || approved.status!=='approved' || !approved.content_matches){
          throw new Error('请先完成处置更正审批。')
        }
        fixedReason=approved.reversal_reason
      }
      return window.nexora!.callApi('changeQualityDisposition',{id:row.id,version:row.version,action,reason:fixedReason})
    },action==='post'?'处置已确认；返工工单须独立审批、追加领料并重新检验，成本另行结算。':'处置阶段已更新，原单与更正证据保留。')
  }
  return {loadQuality,loadQualityDetail,refreshQualityApproval,clearQualityDetail,startQualityDisposition,editQualityDisposition,saveQualityDisposition,changeQualityDisposition}
}
