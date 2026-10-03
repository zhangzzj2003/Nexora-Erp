import { watch } from 'vue'
import type { CrmKind, CrmRecord, CrmQuote, CrmQuoteAction, CrmActivity, CrmOpportunity, CrmContact, CrmForms } from '../../../../shared/crm-api'
import type { ContactImportRow, OpportunityImportRow } from '../../../../shared/crm-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function emptyCrmForms(): CrmForms {
  return { contact: {customer_id:0,name:'',job_title:'',phone:'',email:'',note:'',is_active:true},
    opportunity: {customer_id:0,contact_id:null,title:'',owner_id:0,stage:'prospect',estimated_amount:'0.00',expected_close_date:'',note:''},
    activity: {customer_id:0,contact_id:null,opportunity_id:null,subject:'',owner_id:0,due_date:'',note:''},
    quote: {opportunity_id:0,contact_id:null,reference:'',valid_until:'',terms:'',lines:[{material_id:0,quantity:'1',unit_price:'0'}]} }
}

export function createCrmActions(state: AppState, perform: (run: () => Promise<unknown>, message: string) => Promise<void>) {
  let owner = 0; let reads = 0; let details = 0; let ownerReads = 0
  const can = (permission: string) => state.user.value?.permissions.includes(permission) ?? false
  const available = () => !!window.nexora && !state.connectionLost.value
  function clearCrmDetail(): void { details++; state.crmDetail.value=null; state.crmChanges.value=[] }
  function invalidate(): void {
    reads++;ownerReads++;clearCrmDetail();state.crmOptions.value=null;state.crmOverview.value=null;state.crmOwnerChanges.value=[];state.crmLoading.value=false;state.crmError.value=''
  }
  watch(()=>`${state.user.value?.id}:${state.user.value?.permissions.join('|')}`,()=>{
    owner++;invalidate();state.crmForms.value=emptyCrmForms();state.crmEdit.value={}
  },{flush:'sync'})
  // 断线作废所有读取；同账号正在填写的表单保留，重连后重新核对版本。
  watch(state.connectionLost,()=>{owner++;invalidate()},{flush:'sync'})
  async function loadCrm(): Promise<boolean> {
    if (!can('crm.view') || !available() || state.crmLoading.value) return false
    const ticket=++reads;const session=owner;state.crmLoading.value=true;state.crmError.value='';clearCrmDetail()
    try {
      const [options,overview]=await Promise.all([window.nexora!.callApi('crmOptions',undefined),window.nexora!.callApi('crmOverview',undefined)])
      if (session!==owner || ticket!==reads || !can('crm.view')) return false
      state.crmOptions.value=options;state.crmOverview.value=overview
      return true
    } catch (error) {
      if (session===owner && ticket===reads) {state.crmOptions.value=null;state.crmOverview.value=null;state.crmError.value=displayError(error)}
      return false
    } finally {if(session===owner && ticket===reads)state.crmLoading.value=false}
  }
  async function loadCrmDetail(kind: CrmKind, id: number): Promise<boolean> {
    if(!can('crm.view') || !available())return false
    clearCrmDetail();const ticket=details;const session=owner;state.crmError.value=''
    try {
      const [record,changes]=await Promise.all([window.nexora!.callApi('crmDetail',{kind,id}),window.nexora!.callApi('crmChanges',{kind,id})])
      if(session!==owner || ticket!==details || !can('crm.view'))return false
      state.crmDetail.value={kind,record};state.crmChanges.value=changes;return true
    }catch(error){if(session===owner && ticket===details)state.crmError.value=displayError(error);return false}
  }
  async function loadCustomerOwnerChanges(id:number): Promise<boolean> {
    if(!can('customer.assign') || !available())return false
    const session=owner;const ticket=++ownerReads;state.crmOwnerChanges.value=[];state.crmError.value=''
    try{
      const changes=await window.nexora!.callApi('customerOwnerChanges',{id})
      if(session!==owner || ticket!==ownerReads || !can('customer.assign'))return false
      state.crmOwnerChanges.value=changes;return true
    }catch(error){if(session===owner && ticket===ownerReads)state.crmError.value=displayError(error);return false}
  }
  async function assignCustomerOwner(id:number,owner_id:number,version:number,reason:string):Promise<boolean>{
    if(!can('customer.assign') || !available() || state.busy.value)return false
    const session=owner;let saved=false
    await perform(async()=>{if(session!==owner || !available())return
      await window.nexora!.callApi('assignCustomerOwner',{id,owner_id,version,reason});saved=true
    },'客户负责人已更新，变更依据已留存。')
    if(!saved || session!==owner)return false
    await loadCrm();await loadCustomerOwnerChanges(id)
    return session===owner
  }
  async function editCrm(kind: Exclude<CrmKind,'activity'>, id: number): Promise<boolean> {
    const permission=kind==='contact'?'crm_contact.manage':kind==='opportunity'?'crm_opportunity.manage':'crm_quote.create'
    if(!can(permission) || !await loadCrmDetail(kind,id))return false
    const row=state.crmDetail.value?.record
    if(!row || !can(permission))return false
    if(kind==='contact'){
      const contact=row as CrmContact
      state.crmForms.value.contact={customer_id:contact.customer_id,name:contact.name,job_title:contact.job_title,
        phone:contact.phone,email:contact.email,note:contact.note,is_active:!!contact.is_active}
    }else if(kind==='opportunity'){
      const opportunity=row as CrmOpportunity
      if(opportunity.stage==='won')return false
      state.crmForms.value.opportunity={customer_id:opportunity.customer_id,contact_id:opportunity.contact_id,title:opportunity.title,
        owner_id:opportunity.owner_id,stage:opportunity.stage,estimated_amount:opportunity.estimated_amount,
        expected_close_date:opportunity.expected_close_date,note:opportunity.note}
    }else {
      const quote=row as CrmQuote
      if(!['draft','rejected'].includes(quote.status) || ['won','lost'].includes(quote.opportunity_stage))return false
      state.crmForms.value.quote={opportunity_id:quote.opportunity_id,contact_id:quote.contact_id,reference:quote.reference,
        valid_until:quote.valid_until,terms:quote.terms,lines:quote.lines.map(({material_id,quantity,unit_price})=>({material_id,quantity,unit_price}))}
    }
    state.crmEdit.value[kind]={kind,id,version:row.version,reason:''};state.error.value='';return true
  }
  function startNewCrm(kind: CrmKind): void {
    // 各类编辑目标独立保留；显式新建只丢弃本类的旧编辑，防止把修订意外提交成新记录。
    if(state.crmEdit.value[kind]){
      const empty=emptyCrmForms()
      if(kind==='contact')state.crmForms.value.contact=empty.contact
      else if(kind==='activity')state.crmForms.value.activity=empty.activity
      else if(kind==='opportunity')state.crmForms.value.opportunity=empty.opportunity
      else state.crmForms.value.quote=empty.quote
    }
    delete state.crmEdit.value[kind];state.error.value=''
  }
  async function write(permission: string, run: () => Promise<CrmRecord>, message: string, kind: CrmKind): Promise<boolean> {
    if(!can(permission) || !available() || state.busy.value)return false
    const session=owner;let saved: CrmRecord | null=null
    await perform(async()=>{if(session!==owner || !can(permission) || !available())return;const result=await run();if(session===owner && can(permission))saved=result},message)
    if(!saved || session!==owner || !can(permission))return false
    const id=(saved as CrmRecord).id
    await loadCrm()
    if(session===owner)await loadCrmDetail(kind,id)
    return session===owner && can(permission)
  }
  async function saveCrm(kind: CrmKind): Promise<boolean> {
    const edit=state.crmEdit.value[kind]
    const version=edit?.kind===kind ? {id:edit.id,version:edit.version,reason:edit.reason} : {}
    const forms=state.crmForms.value;const session=owner
    const saved=await (kind==='contact' ? write('crm_contact.manage',()=>window.nexora!.callApi('saveCrmContact',{...forms.contact,...version}),'联系人已保存。',kind)
      : kind==='opportunity' ? write('crm_opportunity.manage',()=>window.nexora!.callApi('saveCrmOpportunity',{...forms.opportunity,...version}),'商机已保存，预估金额不计收入。',kind)
      : kind==='activity' ? write('crm_activity.manage',()=>window.nexora!.callApi('createCrmActivity',{...forms.activity}),'跟进已安排。',kind)
      : write('crm_quote.create',()=>window.nexora!.callApi('saveCrmQuote',{...forms.quote,...version,lines:forms.quote.lines.map(({material_id,quantity,unit_price})=>({material_id,quantity,unit_price}))}),'报价已保存，须提交并独立审核。',kind))
    if(saved && session===owner){
      const empty=emptyCrmForms()
      if(kind==='contact')state.crmForms.value.contact=empty.contact
      else if(kind==='activity')state.crmForms.value.activity=empty.activity
      else if(kind==='opportunity')state.crmForms.value.opportunity=empty.opportunity
      else state.crmForms.value.quote=empty.quote
      delete state.crmEdit.value[kind]
    }
    return saved
  }
  async function importContactRows(rows: ContactImportRow[], reason: string, allow_similar: boolean): Promise<boolean> {
    if (!can('crm_contact.manage') || !available() || state.busy.value) return false
    const session = owner
    let saved = false
    await perform(async () => {
      if (session !== owner || !can('crm_contact.manage') || !available()) return
      await window.nexora!.callApi('importContacts', { rows, reason, allow_similar })
      saved = true
    }, '联系人已批量建立，逐条变更依据已留存。')
    if (!saved || session !== owner) return false
    // 写入已经成功；资料刷新失败时也不让用户误以为可以重新导入。
    await loadCrm()
    return session === owner
  }
  async function importOpportunityRows(rows: OpportunityImportRow[], reason: string, allow_similar: boolean): Promise<boolean> {
    if (!can('crm_opportunity.manage') || !available() || state.busy.value) return false
    const session = owner
    let saved = false
    await perform(async () => {
      if (session !== owner || !can('crm_opportunity.manage') || !available()) return
      await window.nexora!.callApi('importOpportunities', { rows, reason, allow_similar })
      saved = true
    }, '商机已批量建立，逐条变更依据已留存；预估金额不计收入。')
    if (!saved || session !== owner) return false
    // 已写入的商机不能因列表刷新失败而让用户误以为需要再次导入。
    await loadCrm()
    return session === owner
  }
  return {loadCrm,loadCrmDetail,loadCustomerOwnerChanges,assignCustomerOwner,
    clearCrmDetail,editCrm,startNewCrm,saveCrm,importContactRows,importOpportunityRows,
    closeCrmActivity:(item: CrmActivity, action:'complete'|'cancel',reason:string)=>write('crm_activity.manage',
      ()=>window.nexora!.callApi('closeCrmActivity',{id:item.id,version:item.version,action,reason}),'跟进状态已登记，原记录保留。','activity'),
    reopenCrmOpportunity:(item:CrmOpportunity,reason:string)=>write('crm_opportunity.manage',
      ()=>window.nexora!.callApi('reopenCrmOpportunity',{id:item.id,version:item.version,reason}),'商机已重开，原订单与报价保留。','opportunity'),
    changeCrmQuote:(item:CrmQuote,action:CrmQuoteAction,reason:string)=>write(['approve','reject'].includes(action)?'crm_quote.review':`crm_quote.${action}`,
      ()=>window.nexora!.callApi('changeCrmQuote',{id:item.id,version:item.version,action,reason}),'报价阶段已更新。','quote'),
    convertCrmQuote:(item:CrmQuote,acceptance_reference:string,reason:string)=>can('sales_order.create') ? write('crm_quote.convert',
      ()=>window.nexora!.callApi('convertCrmQuote',{id:item.id,version:item.version,opportunity_version:item.opportunity_version,acceptance_reference,reason}),
      '已建立销售订单草稿；仍须确认及出库，尚未记收入或收款。','quote') : Promise.resolve(false)}
}
