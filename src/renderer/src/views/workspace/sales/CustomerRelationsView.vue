<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import './sales-editors.css'
import SalesSectionTabs from './SalesSectionTabs.vue'
import CrmCustomerHub from './CrmCustomerHub.vue'
import { selectCrmFormCustomer } from './crm-customers'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import { useLocalPagination } from '../../../composables/use-local-pagination'
import type { WorkspaceTableColumn } from '../../../utils/table-columns'
import type { AppStatusTone } from '../../../components/app/AppStatusTag.vue'
import AppModal from '../../../components/app/AppModal.vue'
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel } from '../../../../../shared/document-numbering'
import { computed,onMounted,onUnmounted,ref,watch } from 'vue'
import { storeToRefs } from 'pinia'

import type { CrmKind,CrmRecord,CrmContact,CrmActivity,CrmOpportunity,CrmQuote,CrmQuoteAction } from '../../../../../shared/crm-api'
import { usePiniaAppStore } from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import CrmEditor from './CrmEditor.vue'
import CrmEvidence from './CrmEvidence.vue'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import ContactImportDialog from './ContactImportDialog.vue'
import OpportunityImportDialog from './OpportunityImportDialog.vue'
import { crmKindLabel,crmQuoteLabel,crmActivityLabel,crmStageLabel,crmCommandLabel,quoteActions } from './crm-display'

const store=usePiniaAppStore()
const {crmOverview:overview,crmForecast:forecast,crmOptions:options,crmDetail:detail,crmError:failure,crmLoading:loading,crmForms:forms,crmOwnerChanges:ownerChanges,busy,user,connectionLost,error}=storeToRefs(store)
// 主入口按客户、跟进、报价组织，商机仍可从客户详情进入。
const showingCustomers=ref(true)
const mode=ref<CrmKind>('activity');const editor=ref<CrmKind|null>(null);const customer=ref(0);const query=ref('')
const contactImportOpen=ref(false)
const opportunityImportOpen=ref(false)
const ownerModal=ref(false);const ownerCustomer=ref(0);const nextOwner=ref(0);const ownerReason=ref('')
const preparing=ref(false);const reason=ref('');const acceptance=ref('')
type Command=CrmQuoteAction|'convert'|'complete'|'cancelActivity'|'reopen'
const command=ref<{kind:CrmKind;record:CrmRecord;action:Command}|null>(null)
const disabled=computed(()=>busy.value || loading.value || connectionLost.value || preparing.value)
const permission=(kind:CrmKind)=>kind==='contact'?'crm_contact.manage':kind==='activity'?'crm_activity.manage':kind==='opportunity'?'crm_opportunity.manage':'crm_quote.create'
const customers=computed(()=>[{label:'全部客户',value:0},...(options.value?.customers??[]).map(row=>({label:row.name,value:row.id}))])
const ownerCustomerRecord=computed(()=>options.value?.customers.find(row=>row.id===ownerCustomer.value))
const ownerName=(id:number|null)=>id===null?'未分配':options.value?.owners.find(row=>row.id===id)?.name??`账号 #${id}`
watch(ownerCustomer,id=>{nextOwner.value=ownerCustomerRecord.value?.owner_id??0;ownerReason.value='';if(id)void store.loadCustomerOwnerChanges(id)})
async function saveOwner():Promise<void>{
  const row=ownerCustomerRecord.value
  if(!row || !nextOwner.value || !ownerReason.value.trim() || disabled.value)return
  if(await store.assignCustomerOwner(row.id,nextOwner.value,row.version,ownerReason.value.trim()))ownerReason.value=''
}
function rowTitle(row:CrmRecord):string {return 'reference' in row?row.reference:'title' in row?row.title:'subject' in row?row.subject:row.name}
function rowStatus(row:CrmRecord):string {return 'stage' in row?crmStageLabel[row.stage]:'due_date' in row?crmActivityLabel[row.status]:'lines' in row?crmQuoteLabel[row.status]:row.is_active?'启用':'停用'}
function deadline(row:CrmRecord):string{return 'valid_until' in row?row.valid_until:'expected_close_date' in row?row.expected_close_date:'due_date' in row?row.due_date:'—'}
// 每个页签按实际业务字段分列，客户、编号、金额和日期不再挤在同一个单元格。
const allRecords=computed<CrmRecord[]>(()=>mode.value==='contact'?overview.value?.contacts??[]:mode.value==='activity'?overview.value?.activities??[]:mode.value==='opportunity'?overview.value?.opportunities??[]:overview.value?.quotes??[])
const summary=ref('')
function groupFor(row:CrmRecord):string {
  if('is_active' in row)return row.is_active?'active':'inactive'
  if('stage' in row)return row.stage==='won'?'completed':row.stage==='lost'?'inactive':'active'
  if('due_date' in row)return row.status==='completed'?'completed':row.status==='cancelled'?'inactive':row.overdue?'attention':'active'
  return row.status==='converted'?'completed':row.status==='cancelled'?'inactive':row.expired||row.status==='rejected'?'attention':'active'
}
// 逾期仍属于待跟进；概览与客户页使用相同待办口径。
function matchesSummary(row:CrmRecord,key:string):boolean {
  if(!key)return true
  if(key==='active' && 'due_date' in row)return row.status==='planned'
  return groupFor(row)===key
}
function statusTone(row:CrmRecord):AppStatusTone {
  return ({active:'info',inactive:'neutral',completed:'success',attention:'danger'} as const)[groupFor(row) as 'active'|'inactive'|'completed'|'attention']
}
const counts=computed(()=>[
  {key:'',label:'全部记录'}, {key:'active',label:mode.value==='contact'?'已启用':mode.value==='activity'?'待跟进':mode.value==='opportunity'?'进行中':'待处理'},
  ...(mode.value==='activity'||mode.value==='quote'?[{key:'attention',label:mode.value==='activity'?'已逾期':'需关注'}]:[]),
  ...(mode.value!=='contact'?[{key:'completed',label:mode.value==='activity'?'已完成':'已转单'}]:[]),
  {key:'inactive',label:mode.value==='contact'?'已停用':mode.value==='opportunity'?'已丢单':'已取消'},
].map(group=>({...group,count:allRecords.value.filter(row=>matchesSummary(row,group.key)).length,
  hint:group.key==='attention'&&mode.value==='quote'?'已过期或被驳回的非终结报价':'当前页签全部可见记录，不随客户和关键词筛选改变',
  tone:group.key==='attention'?'danger' as const:group.key==='completed'?'success' as const:'neutral' as const})))
const searchFilters=computed({get:()=>({customer:customer.value}),set:value=>{customer.value=value.customer}})
const records=computed(()=>allRecords.value.filter(row=>(!customer.value || row.customer_id===customer.value) && (matchesSummary(row,summary.value)) && [documentSearch(row),rowTitle(row),row.customer_name,row.contact_name,
  'owner_name' in row?row.owner_name:'',rowStatus(row),'phone' in row?row.phone:'','email' in row?row.email:''].join(' ').toLowerCase().includes(query.value.toLowerCase().trim()))
  .sort((a,b)=>mode.value==='activity' ? Number('overdue' in b && b.overdue)-Number('overdue' in a && a.overdue) : 0))
const filterKey=computed(()=>JSON.stringify([mode.value,query.value,customer.value,summary.value]))
const {rows:pageRows,page,pageSize,total,changePage}=useLocalPagination(records,filterKey)
const columns=computed<WorkspaceTableColumn[]>(()=>[
  {key:'document',title:mode.value==='contact'?'联系人编号':mode.value==='quote'?'单据编号':'记录编号',width:'220'},
  {key:'title',title:mode.value==='contact'?'联系人姓名':mode.value==='activity'?'跟进事项':mode.value==='quote'?'报价编号':'商机名称',width:'220'},
  {key:'customer_name',title:'客户',width:'200'}, {key:'status',title:mode.value==='opportunity'?'商机阶段':'状态',width:'150'},
  ...(mode.value==='contact'?[{key:'phone',title:'电话',width:'180'},{key:'email',title:'邮箱',width:'240'},{key:'job_title',title:'职务',width:'140'}]:[
    ...(mode.value==='quote'?[{key:'total_amount',title:'报价金额（元）',width:'160',align:'right' as const}]:[{key:'owner_name',title:'负责人',width:'140'}]),
    ...(mode.value==='opportunity'?[{key:'estimated_amount',title:'预估金额（元）',width:'160',align:'right' as const},{key:'probability',title:'成交概率',width:'120'}]:[]),
    {key:'deadline',title:mode.value==='quote'?'有效期至':mode.value==='activity'?'跟进期限':'预计成交日',width:'160'},
  ]), {key:'actions',title:'操作',width:'100',align:'center'},
])
function selectMode(value:CrmKind):void{if(busy.value)return;showingCustomers.value=false;mode.value=value;summary.value='';editor.value=null;store.clearCrmDetail();query.value=''}
function selectSection(value:'customer'|CrmKind):void {
  if(busy.value)return
  if(value==='customer'){showingCustomers.value=true;store.clearCrmDetail()}
  else {customer.value=0;selectMode(value)}
}
function showCustomerRecords(kind:CrmKind,id:number):void{selectMode(kind);customer.value=id}
function assignOwner(id:number):void{ownerCustomer.value=id;ownerModal.value=true}
function newCustomerRecord(kind:CrmKind,id:number):void{newRecord(kind,{customer_id:id})}
function closeEditor():void {
  contactPending.value=false; pendingEditorKind.value=null
  // 弹窗关闭只收起视图，Pinia 中的草稿继续保留；保存期间禁止关闭。
  if(!busy.value)editor.value=null
}
function newRecord(kind:CrmKind, source?:CrmContact|CrmOpportunity|{customer_id:number}):void {
  if(!store.can(permission(kind)) || disabled.value)return
  // 从联系人或商机发起其他业务时，不能沿用上一类资料的状态筛选。
  if(!showingCustomers.value && mode.value!==kind){summary.value='';query.value='';mode.value=kind}
  store.startNewCrm(kind);editor.value=kind;store.clearCrmDetail()
  const selectedCustomer=source?.customer_id??customer.value
  if(selectedCustomer)selectCrmFormCustomer(forms.value,kind,selectedCustomer)
  if(kind==='activity'){
    forms.value.activity.owner_id ||= user.value?.id??0
    if(source && 'stage' in source){forms.value.activity.opportunity_id=source.id;forms.value.activity.contact_id=source.contact_id}
    else if(source && 'is_active' in source)forms.value.activity.contact_id=source.id
  }
  if(kind==='opportunity')forms.value.opportunity.owner_id ||= user.value?.id??0
  if(kind==='quote' && source && 'stage' in source){forms.value.quote.opportunity_id=source.id;forms.value.quote.contact_id=source.contact_id}
}
// 联系人编辑与命令读取分别保存打开意图，取消后不会被迟到结果重开。
const contactPending=ref(false), commandPending=ref(false), pendingEditorKind=ref<CrmKind|null>(null)
const activeEditorKind=computed(()=>editor.value ?? pendingEditorKind.value)
onUnmounted(()=>{contactPending.value=false;commandPending.value=false})
watch(()=>`${user.value?.id}:${user.value?.permissions.join('|')}`,()=>{contactPending.value=false;commandPending.value=false},{flush:'sync'})
async function editRecord(kind:Exclude<CrmKind,'activity'>, id:number):Promise<void>{
  if(disabled.value)return;preparing.value=true
  contactPending.value=true; pendingEditorKind.value=kind
  try{if(await store.editCrm(kind,id) && contactPending.value)editor.value=kind}finally{preparing.value=false;contactPending.value=false;pendingEditorKind.value=null}
}
function canEdit(row:CrmRecord):boolean{
  const kind:CrmKind='lines' in row?'quote':'stage' in row?'opportunity':'due_date' in row?'activity':'contact'
  return kind!=='activity' && store.can(permission(kind)) && ('lines' in row?['draft','rejected'].includes(row.status) && !['won','lost'].includes(row.opportunity_stage??''):'stage' in row?row.stage!=='won':true)
}
function quoteCommands(row:CrmRecord):(CrmQuoteAction|'convert')[]{return 'lines' in row?quoteActions(row,user.value?.permissions??[],user.value?.id??0):[]}
function canReopen(row:CrmRecord):boolean{return 'stage' in row && ['won','lost'].includes(row.stage) && row.orders.every(item=>item.status==='cancelled') && store.can('crm_opportunity.manage')}
async function openCommand(kind:CrmKind,id:number,action:Command):Promise<void>{
  if(disabled.value)return;commandPending.value=true;preparing.value=true;command.value=null;reason.value='';acceptance.value='';error.value=''
  try{
    if(!await store.loadCrmDetail(kind,id) || !detail.value || !commandPending.value)return
    const record=detail.value.record
    if(kind==='quote' && !quoteCommands(record).includes(action as CrmQuoteAction|'convert'))return
    if(kind==='activity' && (record as CrmActivity).status!=='planned')return
    if(kind==='opportunity' && !canReopen(record))return
    command.value={kind,record,action}
  }finally{preparing.value=false;commandPending.value=false}
}
async function execute():Promise<void>{
  const task=command.value
  if(!task || !reason.value.trim() || disabled.value)return
  // 弹窗打开后他人撤回、改版或当前账号撤权时，保留输入但不能继续使用旧批准。
  if(task.kind==='quote'){
    const current=overview.value?.quotes.find(row=>row.id===task.record.id)
    if(!current || current.version!==task.record.version || !quoteCommands(current).includes(task.action as CrmQuoteAction|'convert'))return
  }
  const saved=task.action==='convert' ? await store.convertCrmQuote(task.record as CrmQuote,acceptance.value.trim(),reason.value)
    : task.action==='reopen' ? await store.reopenCrmOpportunity(task.record as CrmOpportunity,reason.value)
    : task.kind==='activity' ? await store.closeCrmActivity(task.record as CrmActivity,task.action==='complete'?'complete':'cancel',reason.value)
    : await store.changeCrmQuote(task.record as CrmQuote,task.action as CrmQuoteAction,reason.value)
  if(saved)command.value=null
}
watch(()=>`${user.value?.id}:${user.value?.permissions.join('|')}`,()=>{command.value=null;editor.value=null;contactImportOpen.value=false;opportunityImportOpen.value=false;ownerModal.value=false;ownerCustomer.value=0;query.value='';customer.value=0;reason.value='';acceptance.value='';if(store.can('crm.view'))void store.loadCrm()})
watch(connectionLost,lost=>{command.value=null;reason.value='';acceptance.value='';if(!lost)void store.loadCrm()})
onMounted(()=>void store.loadCrm())
onUnmounted(()=>store.clearCrmDetail())
</script>
<template>
  <section class="stack crm-workspace">
    <Teleport v-if="!showingCustomers" defer to="#workspace-page-summary"><WorkspaceSummaryFilters v-model="summary" :options="counts" /></Teleport>
    <!-- 日常只展示三个入口；联系人和可选商机从客户详情展开。 -->
    <SalesSectionTabs :model-value="showingCustomers || mode==='opportunity' || mode==='contact'?'customer':mode" :disabled="busy" label="客户关系分类" :options="[{key:'customer',label:'客户'},{key:'activity',label:'跟进'},{key:'quote',label:'报价'}]" @update:model-value="selectSection" />
    <p v-if="connectionLost" role="alert">服务端连接中断，当前资料和可执行动作已失效。未保存的输入保留，恢复连接后重新读取再保存。</p>
    <p v-if="failure" role="alert">{{ failure }} 请刷新资料后重试。</p>

    <CrmCustomerHub v-if="showingCustomers" :disabled="disabled" @create="newCustomerRecord" @detail="store.loadCrmDetail" @records="showCustomerRecords" @assign="assignOwner" @import="contactImportOpen=true" />
    <template v-else>
      <div v-if="mode==='opportunity'" class="section-heading"><h2>{{ options?.customers.find(row=>row.id===customer)?.name || '客户' }} · 商机管理</h2><AppButton :disabled="busy" @click="selectSection('customer')">返回客户</AppButton></div>
      <WorkspaceTable :title="crmKindLabel[mode]" :show-title="false" :columns="columns" :data="pageRows" :pagination="{page,pageSize,total}" @page-change="changePage" :min-table-width="1250" :loading="loading">
        <!-- 列表功能统一放入公共筛选栏右侧，权限和事件沿用原按钮。 -->
        <template #actions>
          <AppButton :disabled="disabled" @click="store.loadCrm()">{{ loading?'正在读取…':'刷新资料' }}</AppButton>
          <AppButton v-if="mode==='contact' && store.can('crm_contact.manage')" :disabled="disabled || !options" @click.capture="captureDialogOrigin('ContactImportDialog:import', $event)" @click="contactImportOpen=true">导入联系人 CSV</AppButton>
          <AppButton v-if="mode==='opportunity' && store.can('crm_opportunity.manage')" :disabled="disabled || !options" @click.capture="captureDialogOrigin('OpportunityImportDialog:import', $event)" @click="opportunityImportOpen=true">导入商机 CSV</AppButton>
          <AppButton variant="primary" v-if="store.can(permission(mode))" :disabled="disabled || !options" @click.capture="captureDialogOrigin('CustomerRelationsView:contact', $event)" @click="newRecord(mode)">新建{{ crmKindLabel[mode] }}</AppButton>
        </template>
        <template #filters><WorkspaceSearchFilters v-model:query="query" v-model:filters="searchFilters" :search-label="`搜索${crmKindLabel[mode]}`" search-placeholder="名称、客户、负责人或阶段"
          :fields="[{kind:'select',key:'customer',label:'客户范围',options:customers}]" :reset-disabled="!query && !customer && !summary" @reset="query='';customer=0;summary=''" /></template>
        <template #cell-document="{row}"><AppButton variant="text" :disabled="disabled" @click.capture="captureDialogOrigin('crm-business-detail',$event)" @click="store.loadCrmDetail(mode,row.id)">{{documentLabel(row)}}</AppButton></template>
        <template #cell-title="{row}">{{rowTitle(row)}}</template>
        <template #cell-probability="{row}">{{(row as CrmOpportunity).probability_percent===null?'未评估':`${(row as CrmOpportunity).probability_percent}%`}}</template>
        <template #cell-deadline="{row}">{{deadline(row)}}</template>
        <template #cell-status="{row}"><AppStatusTag :label="rowStatus(row)" :tone="statusTone(row)" /><span v-if="'overdue' in row && row.overdue" class="crm-secondary">已逾期</span><span v-if="'expired' in row && row.expired" class="crm-secondary">有效期已过</span></template>
        <template #cell-actions="{row}"><AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('crm-business-detail',$event)" @click="store.loadCrmDetail(mode,row.id)">查看</AppButton></template>
        <template #empty>{{ connectionLost ? '连接恢复后将重新读取资料。' : failure ? '资料读取失败，请刷新后重试。' : query || customer ? '当前筛选没有匹配记录。' : store.can(permission(mode)) ? `尚无${crmKindLabel[mode]}，可从上方新建。` : `尚无${crmKindLabel[mode]}，须由有权限的人员建立。` }}</template>
      </WorkspaceTable>
    <section v-if="mode==='opportunity' && forecast" class="crm-forecast" aria-label="商机预测">
      <h2>开放商机预测</h2>
      <p>已评估 {{ forecast.rated_count }} 项 · 未评估 {{ forecast.unrated_count }} 项。仅按当前可见客户汇总；已丢单、已转单不参与计算。</p>
      <p>已评估预估金额 {{ forecast.estimated_amount }} 元 · 加权预计金额 <strong>{{ forecast.weighted_amount }} 元</strong>（人民币，逐项四舍五入到分）</p>
      <p v-if="!forecast.rated_count" class="muted">暂无已评估的开放商机，请在商机修订中填写成交概率。</p>
    </section>
    </template>
      <AppModal origin-key="crm-business-detail" preset="card" :title="detail?`${crmKindLabel[detail.kind]}详情`: '客户关系详情'" :show="!!detail && !editor && !contactPending && !command && !commandPending" :busy="busy"
        :style="{width:'min(1150px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" @update:show="value=>{if(!value)store.clearCrmDetail()}" @invalidated="store.clearCrmDetail()">
        <div class="crm-workspace"><CrmEvidence><template #actions><template v-if="detail">          <AppButton v-if="canEdit(detail.record)" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:contact', $event)" @click="editRecord(detail.kind as Exclude<CrmKind,'activity'>,detail.record.id)">修订</AppButton>
          <AppButton v-if="detail.kind==='contact' && (detail.record as CrmContact).is_active && store.can('crm_activity.manage')" size="small" :disabled="disabled" @click="newRecord('activity',detail.record as CrmContact)">安排跟进</AppButton>
          <AppButton v-if="detail.kind==='opportunity' && !['won','lost'].includes((detail.record as CrmOpportunity).stage) && store.can('crm_quote.create')" size="small" :disabled="disabled" @click="newRecord('quote',detail.record as CrmOpportunity)">编制报价</AppButton>
          <AppButton v-if="detail.kind==='opportunity' && store.can('crm_activity.manage')" size="small" :disabled="disabled" @click="newRecord('activity',detail.record as CrmOpportunity)">安排跟进</AppButton>
          <AppButton v-if="canReopen(detail.record)" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:command', $event)" @click="openCommand('opportunity',detail.record.id,'reopen')">重开商机</AppButton>
          <template v-if="detail.kind==='activity' && (detail.record as CrmActivity).status==='planned' && store.can('crm_activity.manage')"><AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:command', $event)" @click="openCommand('activity',detail.record.id,'complete')">完成跟进</AppButton><AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:command', $event)" @click="openCommand('activity',detail.record.id,'cancelActivity')">取消跟进</AppButton></template>
          <!-- 每张报价拥有自己的审批步骤；原提交/审核动作不再走无审批版本的接口。 -->
          <AppButton v-if="detail.kind==='quote'" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('document-approval', $event)" @click="store.openDocumentApproval({document_type:'CrmQuote',document_id:detail.record.id,intent:'execute'})">单据审批</AppButton>
          <AppButton v-for="action in quoteCommands(detail.record)" :key="action" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:command', $event)" @click="openCommand('quote',detail.record.id,action)">{{ crmCommandLabel[action] }}</AppButton>
</template></template></CrmEvidence></div>
      </AppModal>
      <DocumentApprovalDialog origin-key="document-approval" />
    <!-- 四类 CRM 表单复用统一弹窗，列表筛选和修订状态保留，迟到读取不能重新打开。 -->
    <AppModal class="sales-editor-dialog" :busy="busy" origin-key="CustomerRelationsView:contact" @invalidated="contactPending = false; editor = null" :show="!!activeEditorKind && (editor!==null || contactPending) && store.can(permission(activeEditorKind))" :ready="!contactPending" :load-error="failure" preset="card"
      :title="activeEditorKind ? `${store.crmEdit[activeEditorKind] ? '修订' : '新建'}${crmKindLabel[activeEditorKind]}` : '准备表单'"
      :style="{width:activeEditorKind==='quote'?'min(1200px,calc(100vw - 32px))':'min(860px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)'}"
      :mask-closable="false" :close-on-esc="!busy" :closable="!busy"
      @update:show="value=>{if(!value)closeEditor()}">
      <div class="crm-workspace sales-editor-host"><CrmEditor v-if="editor && store.can(permission(editor))" :kind="editor" dialog
        @saved="editor=null" @close="closeEditor" /></div>
    </AppModal>
    <ContactImportDialog v-if="store.can('crm_contact.manage')" v-model:show="contactImportOpen" />
    <OpportunityImportDialog v-if="store.can('crm_opportunity.manage')" v-model:show="opportunityImportOpen" />
    <AppModal :busy="busy" origin-key="CustomerRelationsView:command" @invalidated="commandPending = false; command = null" :show="commandPending || !!command" :ready="!commandPending && !!command" :load-error="failure" preset="card" :title="command ? crmCommandLabel[command.action] : ''" :style="{width:'min(680px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value){commandPending=false;command=null}}">
      <form v-if="command" class="crm-operation" @submit.prevent="execute">
        <p>{{ rowTitle(command.record) }} · {{ rowStatus(command.record) }} · v{{ command.record.version }}</p>
        <template v-if="command.kind==='quote'">
          <p>{{ (command.record as CrmQuote).party.customer_name }} · {{ (command.record as CrmQuote).party.contact_name || '未指定联系人' }} · {{ (command.record as CrmQuote).party.phone || '未填写电话' }} · {{ (command.record as CrmQuote).party.email || '未填写邮箱' }}</p>
          <p>人民币 {{ (command.record as CrmQuote).total_amount }} 元 · 有效至 {{ (command.record as CrmQuote).valid_until }}</p>
          <ul><li v-for="line in (command.record as CrmQuote).lines" :key="line.id">{{ line.sku }} · {{ line.material_name }} · {{ line.quantity }} {{ line.unit }} × {{ line.unit_price }} 元 ＝ {{ line.line_total }} 元</li></ul>
          <p>{{ (command.record as CrmQuote).terms || '未填写商务条款' }}</p>
        </template>
        <p v-if="command.action==='convert'">客户：{{ command.record.customer_name }} · 报价 {{ (command.record as CrmQuote).total_amount }} 元 · 有效至 {{ (command.record as CrmQuote).valid_until }}。使用固定报价的物料、数量及单价建立销售草稿，不增加库存或记收款。</p>
        <p v-else-if="['approve','reject'].includes(command.action)">请核对页面中的固定报价明细及商务条款。审核按当前步骤按钮权限办理；请核对报价内容和客户确认依据。</p>
        <p v-else-if="command.action==='complete'">登记实际跟进结果，结束后不可覆盖原结果；更正请另建跟进。</p>
        <p v-else-if="command.action==='reopen'">只有全部关联订单均已取消才能重开。原报价仍保留，不能再次转单，后续成交须建立新报价。</p>
        <p v-else>本次操作及原因将保留在变更记录中。</p>
        <label v-if="command.action==='convert'">客户接受依据编号<AppInput v-model.trim="acceptance" required maxlength="120" :disabled="busy" placeholder="邮件、签字确认或合同依据编号" /></label>
        <label>{{ command.action==='complete'?'实际跟进结果':'操作原因' }}<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy" /></label>
        <p v-if="error" role="alert">{{ error }} 当前输入已保留；关闭后刷新资料，核对最新版本再重试。</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !reason.trim() || (command.action==='convert' && !acceptance.trim())">{{ busy?'正在处理…':`确认${crmCommandLabel[command.action]}` }}</AppButton>
      </form>
    </AppModal>
    <AppModal :busy="busy" origin-key="CustomerRelationsView:owner" @invalidated="ownerModal = false" :show="ownerModal" preset="card" title="分配客户负责人" :style="{width:'min(680px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)ownerModal=false}">
      <form class="crm-operation" @submit.prevent="saveOwner">
        <p>旧客户保持未分配，须根据实际业务依据由管理员指定负责人。转交后原负责人立即失去该客户的 CRM 访问权。</p>
        <label>客户<WorkspaceSelect v-model="ownerCustomer" :options="(options?.customers??[]).map(row=>({label:row.name,value:row.id}))" required :disabled="disabled" /></label>
        <template v-if="ownerCustomerRecord">
          <p>当前负责人：{{ ownerName(ownerCustomerRecord.owner_id) }} · 归属版本 {{ ownerCustomerRecord.version }}</p>
          <label>新负责人<WorkspaceSelect v-model="nextOwner" :options="(options?.owners??[]).map(row=>({label:row.name,value:row.id}))" required :disabled="disabled" /></label>
          <label>分配或转交依据<AppInput v-model.trim="ownerReason" required maxlength="500" :disabled="disabled" /></label>
          <p v-if="error || failure" role="alert">{{ error || failure }} 请刷新客户资料并核对版本。</p>
          <AppButton type="submit" variant="primary" :disabled="disabled || !nextOwner || nextOwner===ownerCustomerRecord.owner_id || !ownerReason.trim()">确认分配</AppButton>
          <h3>归属变更记录</h3>
          <p v-if="!ownerChanges.length">暂无变更记录。</p>
          <ul v-else><li v-for="change in ownerChanges" :key="change.id">v{{ change.version }} · {{ ownerName(change.before_owner_id) }} → {{ ownerName(change.after_owner_id) }} · {{ change.reason }} · 操作账号 #{{ change.changed_by }} · {{ change.created_at }}</li></ul>
        </template>
      </form>
    </AppModal>
  </section>
</template>
<style scoped>
.crm-forecast{padding:16px 20px;border:1px solid var(--workspace-field-border);border-radius:14px;background:var(--workspace-field-background)}
.crm-forecast h2{font-size:15px;margin:0 0 8px}
.crm-forecast p{font-size:12px;margin:6px 0;color:var(--workspace-field-muted)}
.crm-workspace{--crm-secondary:#50667d}
:global(:root[data-theme='dark'] .crm-workspace){--crm-secondary:#9aadc5}
.crm-workspace :deep(.crm-toolbar){display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.crm-workspace :deep(.crm-secondary){display:block;margin-top:4px;font-size:12px;overflow-wrap:anywhere}
.crm-operation{display:grid;gap:18px}
.crm-workspace :deep(.crm-wide){grid-column:1/-1}
.crm-workspace :deep(.crm-quote-line){display:grid;grid-template-columns:minmax(240px,2fr) minmax(120px,1fr) minmax(140px,1fr) minmax(130px,1fr) auto;gap:12px;align-items:end}
.crm-workspace :deep(.crm-facts){display:grid;grid-template-columns:130px minmax(0,1fr);gap:8px 16px;margin:16px 0}
.crm-workspace :deep(.crm-facts dt),.crm-workspace :deep(.crm-secondary),.crm-workspace :deep(.crm-editor .muted){color:var(--crm-secondary)}
.crm-workspace :deep(.crm-facts dd){margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
.crm-workspace :deep(.crm-audit-grid){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
@media(max-width:1000px){.crm-workspace :deep(.crm-quote-line){grid-template-columns:minmax(200px,2fr) minmax(100px,1fr)}.crm-workspace :deep(.crm-audit-grid){grid-template-columns:1fr}}
</style>
