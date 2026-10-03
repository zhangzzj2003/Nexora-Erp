<script setup lang="ts">
import { computed,onMounted,onUnmounted,ref,watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import type { CrmKind,CrmRecord,CrmContact,CrmActivity,CrmOpportunity,CrmQuote,CrmQuoteAction } from '../../../../../shared/crm-api'
import { usePiniaAppStore } from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import CrmEditor from './CrmEditor.vue'
import CrmEvidence from './CrmEvidence.vue'
import ContactImportDialog from './ContactImportDialog.vue'
import OpportunityImportDialog from './OpportunityImportDialog.vue'
import { crmKindLabel,crmQuoteLabel,crmActivityLabel,crmStageLabel,crmCommandLabel,quoteActions } from './crm-display'

const store=usePiniaAppStore()
const {crmOverview:overview,crmOptions:options,crmDetail:detail,crmError:failure,crmLoading:loading,crmForms:forms,crmOwnerChanges:ownerChanges,busy,user,connectionLost,error}=storeToRefs(store)
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
const records=computed(()=>{
  const rows:CrmRecord[]=mode.value==='contact'?overview.value?.contacts??[]:mode.value==='activity'?overview.value?.activities??[]:mode.value==='opportunity'?overview.value?.opportunities??[]:overview.value?.quotes??[]
  return rows.filter(row=>(!customer.value || row.customer_id===customer.value) && [rowTitle(row),row.customer_name,row.contact_name,
    'owner_name' in row?row.owner_name:'',rowStatus(row),'phone' in row?row.phone:''].join(' ').toLowerCase().includes(query.value.toLowerCase().trim()))
    .sort((a,b)=>mode.value==='activity' ? Number('overdue' in b && b.overdue)-Number('overdue' in a && a.overdue) : 0)
})
const columns=computed(()=>[{key:'title',title:mode.value==='contact'?'联系人':'事项 / 编号',width:'24%'},{key:'customer_name',title:'客户',width:'16%'},
  {key:'context',title:mode.value==='contact'?'联系信息':mode.value==='quote'?'报价金额 / 有效期':'负责人 / 日期',width:'22%'},{key:'status',title:'阶段',width:'13%'},{key:'actions',title:'处理 / 证据',width:'25%'}])
function selectMode(value:CrmKind):void{if(busy.value)return;mode.value=value;editor.value=null;store.clearCrmDetail();query.value=''}
function newRecord(kind:CrmKind, source?:CrmContact|CrmOpportunity):void {
  if(!store.can(permission(kind)) || disabled.value)return
  store.startNewCrm(kind);editor.value=kind;mode.value=kind;store.clearCrmDetail()
  const selectedCustomer=source?.customer_id??customer.value
  if(kind!=='quote' && selectedCustomer)forms.value[kind].customer_id=selectedCustomer
  if(kind==='activity'){
    forms.value.activity.owner_id ||= user.value?.id??0
    if(source && 'stage' in source){forms.value.activity.opportunity_id=source.id;forms.value.activity.contact_id=source.contact_id}
    else if(source)forms.value.activity.contact_id=source.id
  }
  if(kind==='opportunity')forms.value.opportunity.owner_id ||= user.value?.id??0
  if(kind==='quote' && source && 'stage' in source){forms.value.quote.opportunity_id=source.id;forms.value.quote.contact_id=source.contact_id}
}
async function editRecord(kind:Exclude<CrmKind,'activity'>, id:number):Promise<void>{
  if(disabled.value)return;preparing.value=true
  try{if(await store.editCrm(kind,id))editor.value=kind}finally{preparing.value=false}
}
function canEdit(row:CrmRecord):boolean{
  return mode.value!=='activity' && store.can(permission(mode.value)) && ('lines' in row?['draft','rejected'].includes(row.status) && !['won','lost'].includes(row.opportunity_stage):'stage' in row?row.stage!=='won':true)
}
function quoteCommands(row:CrmRecord):(CrmQuoteAction|'convert')[]{return 'lines' in row?quoteActions(row,user.value?.permissions??[],user.value?.id??0):[]}
function canReopen(row:CrmRecord):boolean{return 'stage' in row && ['won','lost'].includes(row.stage) && row.orders.every(item=>item.status==='cancelled') && store.can('crm_opportunity.manage')}
async function openCommand(kind:CrmKind,id:number,action:Command):Promise<void>{
  if(disabled.value)return;preparing.value=true;command.value=null;reason.value='';acceptance.value='';error.value=''
  try{
    if(!await store.loadCrmDetail(kind,id) || !detail.value)return
    const record=detail.value.record
    if(kind==='quote' && !quoteCommands(record).includes(action as CrmQuoteAction|'convert'))return
    if(kind==='activity' && (record as CrmActivity).status!=='planned')return
    if(kind==='opportunity' && !canReopen(record))return
    command.value={kind,record,action}
  }finally{preparing.value=false}
}
async function execute():Promise<void>{
  const task=command.value
  if(!task || !reason.value.trim() || disabled.value)return
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
    <div class="crm-toolbar"><AppButton v-for="kind in (['contact','activity','opportunity','quote'] as const)" :key="kind" :variant="mode===kind?'primary':'secondary'" :disabled="busy" @click="selectMode(kind)">{{ crmKindLabel[kind] }}</AppButton>
      <AppButton :disabled="disabled" @click="store.loadCrm()">{{ loading?'正在读取…':'刷新资料' }}</AppButton>
      <AppButton v-if="store.can('customer.assign')" :disabled="disabled || !options" @click="ownerModal=true">分配客户负责人</AppButton>
      <AppButton v-if="mode==='contact' && store.can('crm_contact.manage')" :disabled="disabled || !options" @click="contactImportOpen=true">导入联系人 CSV</AppButton>
      <AppButton v-if="mode==='opportunity' && store.can('crm_opportunity.manage')" :disabled="disabled || !options" @click="opportunityImportOpen=true">导入商机 CSV</AppButton>
      <AppButton v-if="store.can(permission(mode))" :disabled="disabled || !options" @click="newRecord(mode)">新建{{ crmKindLabel[mode] }}</AppButton></div>
    <p>按客户追踪联系人、跟进和商机；报价经独立审核后，登记客户接受依据并转销售订单草稿。</p>
    <p v-if="connectionLost" role="alert">服务端连接中断，当前资料和可执行动作已失效。未保存的输入保留，恢复连接后重新读取再保存。</p>
    <p v-if="failure" role="alert">{{ failure }} 请刷新资料后重试。</p>
    <CrmEditor v-if="editor && store.can(permission(editor))" :kind="editor" @saved="editor=null" @close="editor=null" @create-opportunity="newRecord('opportunity')" />
    <template v-else>
      <WorkspaceTable :title="crmKindLabel[mode]" :show-title="false" :columns="columns" :data="records" :min-table-width="1050" :loading="loading">
        <template #filters><label>客户范围<WorkspaceSelect v-model="customer" :options="customers" :disabled="disabled" /></label><label>搜索{{ crmKindLabel[mode] }}<AppInput v-model="query" placeholder="名称、客户、负责人或阶段" /></label></template>
        <template #cell-title="{row}"><strong>{{ rowTitle(row) }}</strong><span class="crm-secondary muted">#{{ row.id }} · {{ row.created_by_name }}</span></template>
        <template #cell-context="{row}"><template v-if="mode==='contact'"><span>{{ (row as CrmContact).phone || '未填写电话' }}</span><span class="crm-secondary muted">{{ (row as CrmContact).email || '未填写邮箱' }}</span></template>
          <template v-else><span>{{ mode==='quote' ? (row as CrmQuote).total_amount+' 元' : (row as CrmOpportunity|CrmActivity).owner_name }}</span><span class="crm-secondary muted">{{ mode==='quote'?'有效至':mode==='opportunity'?'预计成交':'跟进期限' }} {{ deadline(row) }}</span>
          <span v-if="mode==='opportunity'" class="crm-secondary muted">预估 {{ (row as CrmOpportunity).estimated_amount }} 元</span></template></template>
        <template #cell-status="{row}">{{ rowStatus(row) }}<span v-if="mode==='activity' && (row as CrmActivity).overdue" class="crm-secondary">已逾期</span><span v-if="mode==='quote' && (row as CrmQuote).expired" class="crm-secondary">有效期已过</span></template>
        <template #cell-actions="{row}"><div class="crm-toolbar">
          <AppButton size="small" :disabled="disabled" @click="store.loadCrmDetail(mode,row.id)">详情与依据</AppButton>
          <AppButton v-if="canEdit(row)" size="small" :disabled="disabled" @click="editRecord(mode as Exclude<CrmKind,'activity'>,row.id)">修订</AppButton>
          <AppButton v-if="mode==='contact' && (row as CrmContact).is_active && store.can('crm_activity.manage')" size="small" :disabled="disabled" @click="newRecord('activity',row as CrmContact)">安排跟进</AppButton>
          <AppButton v-if="mode==='opportunity' && !['won','lost'].includes((row as CrmOpportunity).stage) && store.can('crm_quote.create')" size="small" :disabled="disabled" @click="newRecord('quote',row as CrmOpportunity)">编制报价</AppButton>
          <AppButton v-if="mode==='opportunity' && store.can('crm_activity.manage')" size="small" :disabled="disabled" @click="newRecord('activity',row as CrmOpportunity)">安排跟进</AppButton>
          <AppButton v-if="canReopen(row)" size="small" :disabled="disabled" @click="openCommand('opportunity',row.id,'reopen')">重开商机</AppButton>
          <template v-if="mode==='activity' && (row as CrmActivity).status==='planned' && store.can('crm_activity.manage')"><AppButton size="small" :disabled="disabled" @click="openCommand('activity',row.id,'complete')">完成跟进</AppButton><AppButton size="small" :disabled="disabled" @click="openCommand('activity',row.id,'cancelActivity')">取消跟进</AppButton></template>
          <AppButton v-for="action in quoteCommands(row)" :key="action" size="small" :disabled="disabled" @click="openCommand('quote',row.id,action)">{{ crmCommandLabel[action] }}</AppButton>
        </div></template>
        <template #empty>{{ connectionLost ? '连接恢复后将重新读取资料。' : failure ? '资料读取失败，请刷新后重试。' : query || customer ? '当前筛选没有匹配记录。' : store.can(permission(mode)) ? `尚无${crmKindLabel[mode]}，可从上方新建。` : `尚无${crmKindLabel[mode]}，须由有权限的人员建立。` }}</template>
      </WorkspaceTable>
      <CrmEvidence />
    </template>
    <ContactImportDialog v-if="store.can('crm_contact.manage')" v-model:show="contactImportOpen" />
    <OpportunityImportDialog v-if="store.can('crm_opportunity.manage')" v-model:show="opportunityImportOpen" />
    <NModal :show="!!command" preset="card" :title="command ? crmCommandLabel[command.action] : ''" :style="{width:'min(680px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)command=null}">
      <form v-if="command" class="crm-operation" @submit.prevent="execute">
        <p>{{ rowTitle(command.record) }} · {{ rowStatus(command.record) }} · v{{ command.record.version }}</p>
        <template v-if="command.kind==='quote'">
          <p>{{ (command.record as CrmQuote).party.customer_name }} · {{ (command.record as CrmQuote).party.contact_name || '未指定联系人' }} · {{ (command.record as CrmQuote).party.phone || '未填写电话' }} · {{ (command.record as CrmQuote).party.email || '未填写邮箱' }}</p>
          <p>人民币 {{ (command.record as CrmQuote).total_amount }} 元 · 有效至 {{ (command.record as CrmQuote).valid_until }}</p>
          <ul><li v-for="line in (command.record as CrmQuote).lines" :key="line.id">{{ line.sku }} · {{ line.material_name }} · {{ line.quantity }} {{ line.unit }} × {{ line.unit_price }} 元 ＝ {{ line.line_total }} 元</li></ul>
          <p>{{ (command.record as CrmQuote).terms || '未填写商务条款' }}</p>
        </template>
        <p v-if="command.action==='convert'">客户：{{ command.record.customer_name }} · 报价 {{ (command.record as CrmQuote).total_amount }} 元 · 有效至 {{ (command.record as CrmQuote).valid_until }}。使用固定报价的物料、数量及单价建立销售草稿，不增加库存或记收款。</p>
        <p v-else-if="['approve','reject'].includes(command.action)">请核对页面中的固定报价明细及商务条款。编制、修订及提交人不可审核自己的报价。</p>
        <p v-else-if="command.action==='complete'">登记实际跟进结果，结束后不可覆盖原结果；更正请另建跟进。</p>
        <p v-else-if="command.action==='reopen'">只有全部关联订单均已取消才能重开。原报价仍保留，不能再次转单，后续成交须建立新报价。</p>
        <p v-else>本次操作及原因将保留在变更记录中。</p>
        <label v-if="command.action==='convert'">客户接受依据编号<AppInput v-model.trim="acceptance" required maxlength="120" :disabled="busy" placeholder="邮件、签字确认或合同依据编号" /></label>
        <label>{{ command.action==='complete'?'实际跟进结果':'操作原因' }}<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy" /></label>
        <p v-if="error" role="alert">{{ error }} 当前输入已保留；关闭后刷新资料，核对最新版本再重试。</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !reason.trim() || (command.action==='convert' && !acceptance.trim())">{{ busy?'正在处理…':`确认${crmCommandLabel[command.action]}` }}</AppButton>
      </form>
    </NModal>
    <NModal :show="ownerModal" preset="card" title="分配客户负责人" :style="{width:'min(680px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)ownerModal=false}">
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
    </NModal>
  </section>
</template>
<style scoped>
.crm-workspace{--crm-secondary:#50667d}
:global(:root[data-theme='dark'] .crm-workspace){--crm-secondary:#9aadc5}
.crm-workspace :deep(.crm-toolbar){display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.crm-workspace :deep(.crm-secondary){display:block;margin-top:4px;font-size:12px;overflow-wrap:anywhere}
.crm-workspace :deep(.crm-editor form),.crm-operation{display:grid;gap:18px}
.crm-workspace :deep(.crm-wide){grid-column:1/-1}
.crm-workspace :deep(.crm-quote-line){display:grid;grid-template-columns:minmax(240px,2fr) minmax(120px,1fr) minmax(140px,1fr) auto;gap:12px;align-items:end}
.crm-workspace :deep(.crm-facts){display:grid;grid-template-columns:130px minmax(0,1fr);gap:8px 16px;margin:16px 0}
.crm-workspace :deep(.crm-facts dt),.crm-workspace :deep(.crm-secondary),.crm-workspace :deep(.crm-editor .muted){color:var(--crm-secondary)}
.crm-workspace :deep(.crm-facts dd){margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
.crm-workspace :deep(.crm-audit-grid){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
@media(max-width:1000px){.crm-workspace :deep(.crm-quote-line){grid-template-columns:minmax(200px,2fr) minmax(100px,1fr)}.crm-workspace :deep(.crm-audit-grid){grid-template-columns:1fr}}
</style>
