<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel } from '../../../../../shared/document-numbering'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { MrpAction, MrpPlan, MrpSuggestion } from '../../../../../shared/mrp-api'
import { mrpActions, mrpAction, mrpStatus, mrpCanConvert } from './mrp-display'
import MrpEditor from './MrpEditor.vue'
import MrpPolicies from './MrpPolicies.vue'
import MrpEvidence from './MrpEvidence.vue'
import './mrp.css'
const store = usePiniaAppStore()
const { mrpPlans: records, mrpOptions: options, mrpDetail: detail, mrpCheck: check, mrpError: error,
  mrpLoading: loading, user, server, busy, connectionLost, error: operationError } = storeToRefs(store)
const mode = ref<'plans' | 'input' | 'policies'>('plans'); const query = ref('')
const command = ref<{ record: MrpPlan; action: MrpAction } | null>(null)
const conversion = ref<MrpSuggestion | null>(null)
const conversionPlan = ref<{ id: number; version: number } | null>(null)
const reason = ref(''); const reference = ref(''); const warehouse = ref<number | null>(null)
const preparing = ref(false)
const disabled = computed(() => loading.value || busy.value || connectionLost.value || preparing.value)
const warehouseOptions = computed(() => [{ value:null as number | null,label:'选择工单目标仓库',disabled:true },
  ...(options.value?.warehouses ?? []).map(row => ({value:row.id,label:`${row.code} · ${row.name}`}))])
const filtered = computed(() => records.value.filter(row => `${documentSearch(row)} ${row.reference} ${row.created_by_name} ${row.start_date}`.toLowerCase().includes(query.value.toLowerCase().trim())))
const columns = [{key:'reference',title:'计划编号',width:'240'}, {key:'start_date',title:'计划起日',width:'150'},
  {key:'suggestion_count',title:'供给建议'}, {key:'warning_count',title:'警告'}, {key:'status',title:'阶段',width:'150'}, {key:'actions',title:'核对 / 审核',width:'360'}]
const modalStyle = { width:'min(600px, calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto' as const }
const actions = (item: MrpPlan) => mrpActions(item,user.value?.permissions ?? [],user.value?.id ?? 0)
async function openAction(item: MrpPlan, action: MrpAction): Promise<void> {
  preparing.value = true
  try { if (await store.loadMrpDetail(item)) { command.value = {record:detail.value!,action}; reason.value = '' } }
  finally { preparing.value = false }
}
async function act(): Promise<void> {
  const value = command.value
  const current = records.value.find(row => row.id === value?.record.id)
  if (!current || current.version !== value?.record.version || !actions(current).includes(value.action)) { operationError.value = '计划阶段或审批已变化，请关闭并重新读取。'; return }
  if (value && reason.value.trim() && await store.changeMrpStatus(value.record,value.action,reason.value)) command.value = null
}
function openConversion(row: MrpSuggestion): void {
  if (disabled.value || !detail.value || !mrpCanConvert(detail.value, check.value, row, user.value?.permissions ?? [])) return
  conversionPlan.value = { id: detail.value.id, version: detail.value.version }; conversion.value = row; reason.value = ''; reference.value = ''; warehouse.value = null }
async function convert(): Promise<void> {
  // 固定打开弹窗的计划及版本，不能将旧建议写到后来打开或撤回的另一份计划。
  if (!conversion.value || !detail.value || detail.value.id !== conversionPlan.value?.id || detail.value.version !== conversionPlan.value.version
    || !mrpCanConvert(detail.value, check.value, conversion.value, user.value?.permissions ?? [])) { operationError.value = '计划或审批已变化，请关闭并重新读取。'; return }
  if (conversion.value && detail.value && reason.value.trim() && await store.convertMrpSuggestion(detail.value,conversion.value.key,warehouse.value,reference.value,reason.value)) conversion.value = null
}
onMounted(() => store.loadMrp())
onUnmounted(store.clearMrpDetail)
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}`, () => {
  command.value = null; conversion.value = null; mode.value = 'plans'; reason.value = ''; reference.value = ''
  if (store.can('mrp.view')) void store.loadMrp()
})
watch(connectionLost, lost => { command.value = null; conversion.value = null; if (!lost) void store.loadMrp() })
</script>
<template>
  <section class="stack mrp-workspace">
    <div class="mrp-toolbar">
      <AppButton :variant="mode==='plans' ? 'primary' : 'secondary'" @click="mode='plans'">固定计划</AppButton>
      <AppButton v-if="store.can('mrp.create')" :variant="mode==='input' ? 'primary' : 'secondary'" @click="mode='input'">需求编排</AppButton>
      <AppButton :variant="mode==='policies' ? 'primary' : 'secondary'" @click="mode='policies'">物料参数</AppButton>
      <AppButton :disabled="disabled" @click="store.loadMrp()">{{ loading ? '正在读取…' : '重新读取来源' }}</AppButton>
    </div>
    <p>按日期核对销售与手工需求、现有供给和全部仓库库存，逐层展开启用 BOM。预计供给包含待执行原单；建议经独立审核后转为采购申请或工单草稿。</p>
    <p v-if="connectionLost" role="alert">服务端连接中断，当前来源与核对结果已失效。恢复连接后重新读取；未保存的需求输入保留。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="mode==='plans'">
      <WorkspaceTable title="固定计划" :show-title="false" :columns="columns" :data="filtered" :min-table-width="1100" :loading="loading">
        <template #filters><label>搜索计划<AppInput v-model="query" placeholder="编号、编制人或计划起日" /></label></template>
        <template #cell-reference="{ row }"><strong>{{ documentLabel(row) }} · {{ row.reference }}</strong><span class="muted mrp-line">{{ row.created_by_name }} · {{ store.localTime(row.created_at) }}</span></template>
        <template #cell-status="{ row }">{{ mrpStatus[row.status] }} · v{{ row.version }}</template>
        <template #cell-actions="{ row }"><div class="mrp-toolbar"><AppButton size="small" :disabled="disabled" @click="store.loadMrpDetail(row)">结果与来源</AppButton>
          <AppButton size="small" :disabled="disabled" @click="store.openDocumentApproval({document_type:'MrpPlan',document_id:row.id,intent:'execute'})">单据审批</AppButton>
          <AppButton v-for="action in actions(row)" :key="action" size="small" :disabled="disabled" @click="openAction(row,action)">{{ mrpAction[action] }}</AppButton></div></template>
        <template #empty>{{ query ? '没有匹配的计划。' : store.can('mrp.create') ? '尚无计划。进入需求编排，安排日期后计算并保存草稿。' : '尚无固定计划，须由计划编制人员建立。' }}</template>
      </WorkspaceTable>
      <MrpEvidence @convert="openConversion" />
    </template>
    <MrpEditor v-else-if="mode==='input' && store.can('mrp.create')" @saved="mode='plans'" />
    <MrpPolicies v-else-if="mode==='policies'" />
    <DocumentApprovalDialog />
    <NModal :show="!!command" preset="card" :title="command ? mrpAction[command.action] : ''" :style="modalStyle" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)command=null}">
      <form v-if="command" class="mrp-editor" @submit.prevent="act">
        <p>{{ command.record.reference }} · {{ mrpStatus[command.record.status] }} · v{{ command.record.version }}</p>
        <p v-if="!check?.matched" role="alert">来源变化或起日已过期。取消仍须核对当前原单依赖；后续供给须新建计划重算。</p>
        <p>操作原因和账号会留入审计。编制及曾提交此计划的账号不能审核。</p>
        <label>操作依据<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy" /></label>
        <p v-if="operationError" role="alert">{{ operationError }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !reason.trim()">确认{{ mrpAction[command.action] }}</AppButton>
      </form>
    </NModal>
    <NModal :show="!!conversion" preset="card" title="建议转入原单" :style="modalStyle" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)conversion=null}">
      <form v-if="conversion" class="mrp-editor" @submit.prevent="convert">
        <p>{{ conversion.sku }} · {{ conversion.name }} · {{ conversion.quantity }} {{ conversion.unit }} · 需求日 {{ conversion.due_date }}</p>
        <p v-if="conversion.late" role="alert">提前期不足，应于 {{ conversion.required_release_date }} 投放。保存原单不保证按期交付，须另行核对可行交期。</p>
        <p>固定建议数量不能修改。{{ conversion.supply_mode==='buy' ? '建立采购申请草稿后，由采购流程审批、转订单和收货入库。' : '建立工单草稿后，须下达、核对目标仓库并领料报工。' }} 此操作不记库存。</p>
        <label>原单依据编号（可空，服务端生成）<AppInput v-model.trim="reference" maxlength="100" :disabled="busy" /></label>
        <label v-if="conversion.supply_mode==='make'">工单目标仓库<WorkspaceSelect v-model="warehouse" :options="warehouseOptions" required :disabled="busy" /></label>
        <label>转单依据<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy" /></label>
        <p v-if="operationError" role="alert">{{ operationError }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !reason.trim() || !check?.matched || (conversion.supply_mode==='make' && !warehouse)">确认建立{{ conversion.supply_mode==='buy' ? '采购申请' : '生产工单' }}草稿</AppButton>
      </form>
    </NModal>
  </section>
</template>
