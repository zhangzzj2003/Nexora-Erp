<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed,onMounted,onUnmounted,ref,watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import type { QualityAction,QualityEvidence } from '../../../../../shared/quality-api'
import { usePiniaAppStore } from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import QualityEditor from './QualityEditor.vue'
import QualityEvidenceView from './QualityEvidence.vue'
import { qualityActions,qualityStatus,qualityTreatment,qualityCommand } from './quality-display'
const store=usePiniaAppStore()
const {qualityOverview:overview,qualityDetail:detail,qualityLoading:loading,qualityError:failure,busy,user,server,connectionLost,error}=storeToRefs(store)
const mode=ref<'cases'|'records'>('cases'),editor=ref(false),query=ref(''),preparing=ref(false),reason=ref('')
const command=ref<{row:QualityEvidence;action:QualityAction}|null>(null)
const disabled=computed(()=>busy.value || loading.value || preparing.value || connectionLost.value)
const cases=computed(()=>(overview.value?.cases??[]).filter(row=>[documentSearch(row), row.id,row.work_order_id,row.product_name,row.product_sku,row.qc_note].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const records=computed(()=>(overview.value?.dispositions??[]).filter(row=>[documentSearch(row),row.reference,row.completion_id,row.frozen_source.product_name,qualityStatus[row.status],row.created_by_name].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const caseColumns=[{key:'source',title:'原质检 / 成品'},{key:'quantity',title:'不合格 / 占用 / 剩余'},{key:'evidence',title:'检验依据'},{key:'actions',title:'处置'}]
const recordColumns=[{key:'source',title:'依据 / 原质检'},{key:'quantity',title:'方式 / 数量 / 成本处理'},{key:'status',title:'阶段'},{key:'actions',title:'操作 / 证据'}]
const actions=(row:QualityEvidence)=>qualityActions(row,user.value?.permissions??[],user.value?.id??0)
function newRecord(id:number):void {if(!disabled.value && store.startQualityDisposition(id))editor.value=true}
async function editRecord(id:number):Promise<void>{if(disabled.value)return;preparing.value=true;try{if(await store.editQualityDisposition(id))editor.value=true}finally{preparing.value=false}}
async function prepare(id:number,action:QualityAction):Promise<void>{
  if(disabled.value)return;preparing.value=true;command.value=null;reason.value='';error.value=''
  try{if(await store.loadQualityDetail(id) && detail.value && actions(detail.value).includes(action))command.value={row:detail.value,action}}finally{preparing.value=false}
}
async function execute():Promise<void>{
  const pending=command.value;if(!pending || disabled.value)return
  // 审批刷新或撤回使已打开弹窗失效，失败保留本次操作原因。
  const current=overview.value?.dispositions.find(row=>row.id===pending.row.id)
  if(!current || current.version!==pending.row.version || !actions(current).includes(pending.action)){
    error.value='处置或审批版本已变化，请刷新后核对。';return
  }
  if(await store.changeQualityDisposition(pending.row,pending.action,reason.value))command.value=null
}
function selectMode(value:'cases'|'records'):void{if(busy.value)return;mode.value=value;editor.value=false;query.value='';store.clearQualityDetail()}
watch(()=>`${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}`,()=>{command.value=null;editor.value=false;reason.value='';if(!connectionLost.value && store.can('quality.view'))void store.loadQuality()})
// 断线只关闭依赖旧证据的动作，保留正在填写的编辑器及修订版本。
watch(connectionLost,()=>{command.value=null;reason.value='';if(!connectionLost.value && store.can('quality.view'))void store.loadQuality()})
onMounted(()=>{void store.loadQuality()});onUnmounted(()=>store.clearQualityDetail())
</script>
<template>
  <section class="stack quality-workspace">
    <div class="quality-toolbar"><AppButton :variant="mode==='cases'?'primary':'secondary'" :disabled="busy" @click="selectMode('cases')">待处置来源</AppButton><AppButton :variant="mode==='records'?'primary':'secondary'" :disabled="busy" @click="selectMode('records')">处置记录</AppButton><AppButton :disabled="disabled" @click="store.loadQuality()">{{ loading?'正在读取…':'刷新来源与记录' }}</AppButton></div>
    <p v-if="connectionLost" role="alert">服务端连接中断，旧证据与动作已失效。未保存输入保留，恢复连接后重新读取并核对版本。</p>
    <p v-if="failure" role="alert">{{ failure }} 请刷新来源与记录后重试。</p>
    <QualityEditor v-if="editor && store.can('quality.create')" @close="editor=false" @saved="editor=false;mode='records'" />
    <template v-else>
      <WorkspaceTable v-if="mode==='cases'" title="不合格品质检来源" :show-title="false" :columns="caseColumns" :data="cases" :min-table-width="1000" :loading="loading">
        <template #filters><label>搜索质检来源<AppInput v-model="query" placeholder="完工单、工单、成品或检验依据" /></label></template>
        <template #cell-source="{row}"><strong>完工 {{ documentLabel(row) }} · 工单 {{ relatedDocumentLabel(row, 'work_order') }}</strong><span class="quality-secondary">{{ row.product_sku }} · {{ row.product_name }}</span></template>
        <template #cell-quantity="{row}"><span>不合格 {{ row.rejected_quantity }} {{ row.product_unit }}</span><span class="quality-secondary">已占用 {{ row.reserved_quantity }} · 剩余 {{ row.remaining_quantity }}</span></template>
        <template #cell-evidence="{row}">{{ row.qc_note }}<span class="quality-secondary">{{ store.localTime(row.inspected_at) }}</span></template>
        <template #cell-actions="{row}"><AppButton v-if="store.can('quality.create') && !row.settled && Number(row.remaining_quantity)>0" size="small" :disabled="disabled" @click="newRecord(row.id)">建立处置</AppButton><span v-else-if="row.settled" class="quality-secondary">成本已结算；更正须先冲销结算</span><span v-else-if="Number(row.remaining_quantity)<=0" class="quality-secondary">数量已全部占用，查看处置记录</span><span v-else class="quality-secondary">待有权限人员编制处置</span></template>
        <template #empty>{{ connectionLost?'连接恢复后重新读取质检来源。':failure?'读取失败，请刷新来源。':query?'没有匹配的质检来源。':'尚无已确认且未冲销的不合格报工。' }}</template>
      </WorkspaceTable>
      <WorkspaceTable v-else title="处置记录" :show-title="false" :columns="recordColumns" :data="records" :min-table-width="1100" :loading="loading">
        <template #filters><label>搜索处置记录<AppInput v-model="query" placeholder="依据编号、原质检、成品、编制人或阶段" /></label></template>
        <template #cell-source="{row}"><strong>{{ documentLabel(row) }} · {{ row.reference }}</strong><span class="quality-secondary">完工 {{ relatedDocumentLabel(row, 'completion') }} · {{ row.frozen_source.product_name }} · {{ row.created_by_name }}</span></template>
        <template #cell-quantity="{row}">{{ row.kind==='scrap'?'报废':'返工' }} {{ row.quantity }} {{ row.frozen_source.product_unit }}<span class="quality-secondary">{{ qualityTreatment[row.loss_treatment as keyof typeof qualityTreatment] }}</span><span v-if="row.rework_order_id" class="quality-secondary">返工工单 {{ relatedDocumentLabel(row, 'rework_order') }}</span></template>
        <template #cell-status="{row}">{{ qualityStatus[row.status as keyof typeof qualityStatus] }} · v{{ row.version }}<span v-if="row.cost_allocation" class="quality-secondary">原工单成本已固定</span></template>
        <template #cell-actions="{row}"><div class="quality-toolbar"><AppButton size="small" :disabled="disabled" @click="store.openDocumentApproval({document_type:'QualityDisposition',document_id:row.id,intent:'execute'})">单据审批</AppButton><AppButton v-if="row.status==='posted' && store.can('quality.reverse')" size="small" :disabled="disabled" @click="store.openDocumentApproval({document_type:'QualityDisposition',document_id:row.id,intent:'reverse'})">处置更正审批</AppButton><AppButton size="small" :disabled="disabled" @click="store.loadQualityDetail(row.id)">详情与证据</AppButton><AppButton v-if="store.can('quality.create') && ['draft','rejected'].includes(row.status)" size="small" :disabled="disabled" @click="editRecord(row.id)">修订</AppButton><AppButton v-for="action in actions(row)" :key="action" size="small" :disabled="disabled" @click="prepare(row.id,action)">{{ qualityCommand[action] }}</AppButton></div></template>
        <template #empty>{{ connectionLost?'连接恢复后重新读取处置记录。':failure?'读取失败，请刷新记录。':query?'没有匹配的处置记录。':'尚无处置单，请从待处置来源建立，或由有权限的人员编制。' }}</template>
      </WorkspaceTable>
      <QualityEvidenceView v-if="detail" :row="detail" />
    </template>
    <DocumentApprovalDialog title="不合格品处置审批" />
    <NModal :show="!!command" preset="card" :title="command?qualityCommand[command.action]:''" :style="{width:'min(760px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)command=null}">
      <form v-if="command" class="quality-operation" @submit.prevent="execute">
        <QualityEvidenceView :row="command.row" compact />
        <p v-if="['approve','reject'].includes(command.action)">核对原检验结果、本次数量、成本处理及返工材料。拥有当前步骤按钮权限的账号即可审批，包括编制人员和管理员。</p>
        <p v-else-if="command.action==='post'">确认报废保留隔离来源；确认返工只建立关联工单草稿，不增加可用库存。成本须另行结算。</p>
        <p v-else-if="command.action==='reverse'">执行已独立批准的固定更正原因，更正前须冲销原结算；有关返工报工、领料及费用须先完整更正，关联历史工单仍保留。</p>
        <p v-else>本次动作、原因、旧版本和正文将保留为操作证据。</p>
        <label v-if="command.action!=='reverse'">操作原因<AppInput v-model.trim="reason" maxlength="200" required :disabled="busy" /></label>
        <p v-if="error" role="alert">{{ error }} 原因已保留；关闭后刷新证据，按最新版本复核后重试。</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || (command.action!=='reverse' && !reason.trim())">{{ busy?'正在处理…':qualityCommand[command.action] }}</AppButton>
      </form>
    </NModal>
  </section>
</template>
<style scoped>
.quality-workspace{--quality-secondary:#50667d}
:global(:root[data-theme='dark'] .quality-workspace){--quality-secondary:#9aadc5}
.quality-workspace :deep(.quality-toolbar){display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.quality-workspace :deep(.quality-secondary){display:block;margin-top:4px;font-size:12px;color:var(--quality-secondary);overflow-wrap:anywhere}
.quality-workspace :deep(.quality-editor form),.quality-operation{display:grid;gap:18px}
.quality-workspace :deep(.quality-wide){grid-column:1/-1}
.quality-workspace :deep(.quality-material){display:grid;grid-template-columns:minmax(240px,2fr) minmax(150px,1fr) auto;gap:12px;align-items:end;margin-top:12px}
@media(max-width:1000px){.quality-workspace :deep(.form-grid){grid-template-columns:repeat(2,minmax(0,1fr))}.quality-workspace :deep(.quality-material){grid-template-columns:minmax(0,1fr) minmax(120px,1fr)}.quality-workspace :deep(.quality-material button){justify-self:start}}
</style>
