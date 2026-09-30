<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCheckbox, NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { ProfitTransferPolicy } from '../../../../../shared/erp-api'
import ProfitTransferEvidence from './ProfitTransferEvidence.vue'
import { journalStatusLabels } from './journal-display'
import { localTime } from '../../../utils/formatters'

const emit = defineEmits<{ openJournal: [id: number] }>()
const store = usePiniaAppStore()
const { profitTransferOptions: options, profitTransferPreview: preview, profitTransferPolicyChanges: changes,
  profitTransferLoading: loading, profitTransferError: loadError, busy, connectionLost, user } = storeToRefs(store)
const { can, loadProfitTransferOptions, loadProfitTransferPreview, saveProfitTransferPolicy, generateProfitTransfer } = store
const periodId = ref(0)
const configure = ref(false)
const configuration = ref<ProfitTransferPolicy & { reason: string }>({ version: 0, start_date: '', target_account_id: null, cost_account_ids: [], reason: '' })
const reference = ref('')
const reason = ref('')
const periodOptions = computed(() => (options.value?.periods ?? []).map(item => ({ value: item.id,
  label: `${item.code} · ${item.start_date} 至 ${item.end_date} · ${item.status === 'open' ? '开放' : '已结账'}` })))
const startOptions = computed(() => [{ value: '', label: '选择开放期间的开始日期', disabled: true },
  ...(options.value?.periods.filter(item => item.status === 'open' || item.start_date === configuration.value.start_date)
    .map(item => ({ value: item.start_date, label: `${item.code} · ${item.start_date}` })) ?? [])])
const targetOptions = computed(() => [{ value: 0, label: '选择本年利润科目', disabled: true },
  ...(options.value?.accounts.filter(item => item.is_active && item.category === 'equity' && item.normal_balance === 'credit')
    .map(item => ({ value: item.id, label: `${item.code} · ${item.name}` })) ?? [])])
const costs = computed(() => options.value?.accounts.filter(item => item.category === 'cost') ?? [])
const costColumns = [{ key: 'code', title: '科目编码' }, { key: 'name', title: '成本科目' }, { key: 'scope', title: '纳入损益结转' }]
const historyColumns = [{ key: 'created_at', title: '时间' }, { key: 'version', title: '配置版本' },
  { key: 'before_scope', title: '修改前范围' }, { key: 'after_scope', title: '修改后范围' },
  { key: 'reason', title: '依据' }, { key: 'changed_by_name', title: '操作者' }]
const scope = (policy: ProfitTransferPolicy | null): string => policy?.version
  ? `本年利润 #${policy.target_account_id}；成本 ${policy.cost_account_ids.map(id => `#${id}`).join('、') || '无'}；启用 ${policy.start_date}` : '未启用'
const historyRows = computed(() => changes.value.map(item => ({ ...item, version: item.after.version,
  created_at: localTime(item.created_at), before_scope: scope(item.before), after_scope: scope(item.after) })))
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => {
  configure.value = false; periodId.value = 0; reference.value = ''; reason.value = ''
}, { flush: 'sync' })
onMounted(() => { void reload() })
async function reload(): Promise<void> {
  if (!await loadProfitTransferOptions()) return
  if (!options.value?.periods.some(item => item.id === periodId.value)) {
    periodId.value = options.value?.periods.filter(item => item.status === 'open').at(-1)?.id ?? options.value?.periods[0]?.id ?? 0
  }
  if (periodId.value) await loadProfitTransferPreview(periodId.value)
}
function editPolicy(): void {
  const policy = options.value?.policy
  if (!policy) return
  configuration.value = { ...policy, cost_account_ids: [...policy.cost_account_ids], reason: '' }
  configure.value = true
}
function includeCost(id: number, included: boolean): void {
  configuration.value.cost_account_ids = included ? [...configuration.value.cost_account_ids, id]
    : configuration.value.cost_account_ids.filter(item => item !== id)
}
async function savePolicy(): Promise<void> {
  if (!configuration.value.target_account_id || loading.value) return
  if (await saveProfitTransferPolicy(configuration.value)) {
    configure.value = false
    if (periodId.value) await loadProfitTransferPreview(periodId.value)
  }
}
async function generate(): Promise<void> {
  const item = preview.value
  if (!item?.can_generate || loading.value || item.period.id !== periodId.value) return
  if (await generateProfitTransfer({ period_id: item.period.id, period_version: item.period.version,
    policy_version: item.policy_version, fingerprint: item.fingerprint, reference: reference.value, reason: reason.value })) {
    reference.value = ''; reason.value = ''
    await loadProfitTransferPreview(item.period.id)
  }
}
</script>

<template>
  <section class="stack profit-transfer-panel" aria-label="损益结转">
    <div class="journal-total">
      <p>损益结转 · 按已过账余额生成期间末草稿，提交后由另一账号审核过账。</p>
      <div class="ledger-actions">
        <AppButton variant="secondary" :disabled="loading || busy || connectionLost" @click="reload">{{ loading ? '正在读取…' : '刷新配置与预览' }}</AppButton>
        <AppButton v-if="can('profit_transfer.configure')" variant="secondary" :disabled="!options || loading || busy || connectionLost" @click="editPolicy">结转科目配置</AppButton>
      </div>
    </div>
    <p v-if="loadError" role="alert">{{ loadError }} 请刷新配置与预览，核对后重试。</p>
    <p v-if="loading" role="status">正在读取损益结转…</p>
    <template v-if="options">
      <p v-if="!options.policy.version">尚未启用损益结转。先核对科目分类、历史损益和公司的成本范围，再保存结转配置。</p>
      <p v-else class="muted">启用日期 {{ options.policy.start_date }} · 配置版本 {{ options.policy.version }} · 收入和费用统一纳管；成本类按明确选择的范围结转。</p>
      <form v-if="configure && can('profit_transfer.configure')" class="ledger-editor" @submit.prevent="savePolicy">
        <h3>结转科目配置</h3>
        <p class="muted">本年利润使用贷方方向的权益科目。启用日期保存后固定；生产成本、在制品不能未经核对纳入损益。</p>
        <div class="form-grid">
          <label>启用期间开始日期<WorkspaceSelect v-model="configuration.start_date" :options="startOptions" required aria-label="启用期间开始日期" :disabled="configuration.version > 0 || busy" /></label>
          <label>本年利润科目<WorkspaceSelect remote-dataset="ledgerAccounts" :remote-filters="{category:'equity',normal_balance:'credit',is_active:true}" :model-value="configuration.target_account_id ?? 0" :options="targetOptions" required aria-label="本年利润科目" :disabled="busy" @update:model-value="value => { configuration.target_account_id = value }" /></label>
          <label>配置依据 / 原因<AppInput v-model.trim="configuration.reason" required maxlength="200" :disabled="busy" /></label>
        </div>
        <WorkspaceTable title="成本科目范围" dataset="ledgerAccounts" :query-filters="{category:'cost'}" :columns="costColumns" :data="costs" :min-table-width="620">
          <template #cell-scope="{ row }"><NCheckbox :checked="configuration.cost_account_ids.includes(row.id)" :disabled="busy || (!row.is_active && !configuration.cost_account_ids.includes(row.id))" @update:checked="value => includeCost(row.id, value)">{{ row.is_active ? '纳入结转' : '已停用，可移出范围' }}</NCheckbox></template>
          <template #empty>暂无成本类科目。收入、费用仍会统一纳管。</template>
        </WorkspaceTable>
        <div class="form-actions"><AppButton variant="primary" type="submit" :disabled="busy || connectionLost || loading || !configuration.target_account_id">{{ busy ? '正在保存…' : '保存结转配置' }}</AppButton><AppButton variant="secondary" type="button" :disabled="busy" @click="configure = false">取消配置</AppButton></div>
      </form>
      <label class="ledger-search">结转期间<WorkspaceSelect v-model="periodId" :options="periodOptions" aria-label="结转期间" :disabled="busy || loading" @change="id => loadProfitTransferPreview(id)" /></label>
      <p v-if="!options.periods.length" class="muted">暂无会计期间。请先在“会计期间”建立公司使用的期间。</p>
    </template>
    <template v-if="preview && !loading && preview.period.id === periodId">
      <p v-if="preview.journal_id">本期间已有{{ journalStatusLabels[preview.journal_status!] }}结转：<AppButton variant="text" @click="emit('openJournal', preview!.journal_id!)">查看记-{{ preview.journal_id }}</AppButton>。取消未过账草稿或在原期间末过账冲销后，才能重建。</p>
      <p>{{ preview.can_generate ? '预览通过，可填写依据并生成草稿。' : '当前不能生成，请先核对以下事项。' }}</p>
      <ul v-if="preview.blockers.length"><li v-for="item in preview.blockers" :key="item">{{ item }}</li></ul>
      <ProfitTransferEvidence :evidence="preview.evidence" :can-open-journal="can('journal.view')" @open-journal="id => emit('openJournal', id)" />
      <ul class="muted"><li v-for="item in preview.warnings" :key="item">{{ item }}</li></ul>
      <form v-if="can('profit_transfer.generate') && !preview.journal_id" class="ledger-editor" @submit.prevent="generate">
        <div class="form-grid"><label>凭证依据编号<AppInput v-model.trim="reference" required maxlength="80" :disabled="busy" /></label><label>生成依据<AppInput v-model.trim="reason" required maxlength="200" :disabled="busy" /></label></div>
        <p class="muted">凭证日期固定为 {{ preview.period.end_date }}。生成时服务端重新核对金额、来源及配置版本，不能手工覆盖分录。</p>
        <div class="form-actions"><AppButton variant="primary" type="submit" :disabled="!preview.can_generate || busy || connectionLost || loading">{{ busy ? '正在生成…' : '生成损益结转草稿' }}</AppButton><AppButton variant="secondary" type="button" :disabled="loading || busy || connectionLost" @click="loadProfitTransferPreview(periodId)">重新核对余额</AppButton></div>
      </form>
    </template>
    <NCollapse ><AppCollapseItem name="history" :title="`结转配置历史（${changes.length} 次）`"><WorkspaceTable title="结转配置审计" dataset="profitPolicyHistory" :columns="historyColumns" :data="historyRows" :min-table-width="1100" /></AppCollapseItem></NCollapse>
  </section>
</template>

<style scoped>
/* 缩窄窗口或展开来源时，表格在自身容器滚动，不以旧列宽撑大页面。 */
.profit-transfer-panel { min-width: 0; grid-template-columns: minmax(0, 1fr); }
.profit-transfer-panel :deep(.n-collapse) { min-width: 0; }
</style>
