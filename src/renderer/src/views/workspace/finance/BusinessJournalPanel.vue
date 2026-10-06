<script setup lang="ts">
// 凭证与来源保留内部 ID，界面优先显示服务端保存的业务单号。
import { documentSearch, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import { NModal, NDatePicker, NCollapse } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { datePickerString, dateOutsideRange, vDateField } from '../../../utils/date-field'
import type { BusinessJournalCandidate, BusinessJournalMapping, BusinessJournalRole, AuxiliaryReference } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { businessRoleLabels, businessTotal } from './business-journal-display'
import { journalStatusLabels } from './journal-display'
import BusinessSourceEvidence from './BusinessSourceEvidence.vue'
import AuxiliarySelector from './AuxiliarySelector.vue'
const emit = defineEmits<{ openJournal: [id: number] }>()
const store = usePiniaAppStore()
const { businessJournalSources: sources, businessJournalOptions: options, businessJournalPolicyChanges: changes,
  businessJournalLoading: loading, businessJournalError: loadError, busy, connectionLost, user } = storeToRefs(store)
const { can, loadBusinessJournals, saveBusinessJournalPolicy, generateBusinessJournal } = store
const query = ref(''); const filter = ref('pending'); const configure = ref(false)
const configuration = ref<{ version: number; start_date: string; mapping: BusinessJournalMapping; reason: string }>({ version: 0, start_date: '', mapping: {}, reason: '' })
const selected = ref<BusinessJournalCandidate | null>(null)
const auxiliaryByRole = ref<Partial<Record<BusinessJournalRole, AuxiliaryReference[]>>>({})
const auxiliaryColumns = [{ key: 'role', title: '业务用途' }, { key: 'auxiliary', title: '部门与项目' }]
const selectedRoles = computed(() => selected.value ? Object.keys(selected.value.roles).map(role => ({ role: role as BusinessJournalRole })) : [])
const sourcePartners = computed(() => (selected.value?.auxiliary_defaults ?? []).map(ref => {
  const item = options.value?.auxiliary_items?.find(item => item.kind === ref.kind && item.id === ref.id)
  return item ? `${item.kind === 'customer' ? '客户' : '供应商'}：${item.name}` : `${ref.kind === 'customer' ? '客户' : '供应商'} #${ref.id}`
}).join('；'))
const reference = ref(''); const journalDate = ref(''); const reason = ref('')
const rows = computed(() => sources.value.filter(row =>
  [documentSearch(row), row.key, row.label, String(row.journal_id ?? '')].join(' ').includes(query.value.trim()) &&
  (!filter.value || (filter.value === 'pending' && !row.journal_id && !row.no_amount) ||
    (filter.value === 'generated' && row.journal_id) || (filter.value === 'blocked' && row.blockers.length) ||
    (filter.value === 'zero' && row.no_amount))))
const roles = Object.keys(businessRoleLabels) as BusinessJournalRole[]
const columns = [{ key: 'key', title: '业务来源' }, { key: 'source_date', title: '发生日期（UTC）' },
  { key: 'amount', title: '借贷各（人民币）' }, { key: 'state', title: '核对状态' }, { key: 'actions', title: '操作' }]
const roleColumns = [{ key: 'role', title: '业务用途' }, { key: 'account', title: '映射科目' }]
const policyRows = roles.map(role => ({ role, label: businessRoleLabels[role] }))
const accountOptions = computed(() => [{ value: 0, label: '未配置' }, ...(options.value?.accounts.filter(item => item.is_active).map(item => ({ value: item.id, label: `${item.code} · ${item.name}` })) ?? [])])
const filterOptions = [{value:'pending',label:'待生成'},{value:'generated',label:'已有凭证'},{value:'blocked',label:'需要处理'},{value:'zero',label:'无需金额凭证'},{value:'',label:'全部来源'}]
const changeColumns = [{ key: 'created_at', title: '时间' }, { key: 'version', title: '配置版本' }, { key: 'reason', title: '依据' }, { key: 'changed_by_name', title: '操作者' }]
const changeRows = computed(() => changes.value.map(item => ({ ...item, version: item.after.version })))
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => { configure.value = false; selected.value = null }, { flush: 'sync' })
onMounted(() => { void loadBusinessJournals() })
function editPolicy(): void {
  if (!options.value || !can('business_journal.configure')) return
  const policy = options.value.policy
  configuration.value = { version: policy.version, start_date: policy.start_date,
    mapping: Object.fromEntries(roles.map(role => [role, policy.mapping[role] ?? 0])), reason: '' }
  configure.value = true
}
async function savePolicy(): Promise<void> {
  const mapping = Object.fromEntries(Object.entries(configuration.value.mapping).filter(([, value]) => value && value > 0)) as BusinessJournalMapping
  if (await saveBusinessJournalPolicy({ ...configuration.value, mapping })) configure.value = false
}
function open(row: BusinessJournalCandidate): void {
  selected.value = row; reference.value = ''; journalDate.value = row.minimum_date; reason.value = ''
  auxiliaryByRole.value = Object.fromEntries(Object.keys(row.roles).map(role => [role, []]))
}
async function reloadSource(): Promise<void> {
  const key = selected.value?.key
  if (await loadBusinessJournals() && key) selected.value = sources.value.find(row => row.key === key) ?? null
}
async function generate(): Promise<void> {
  const row = selected.value
  if (!row?.can_generate || loading.value) return
  if (await generateBusinessJournal({ source_key: row.key, fingerprint: row.fingerprint,
    auxiliary_by_role: auxiliaryByRole.value,
    policy_version: row.policy_version, reference: reference.value, journal_date: journalDate.value, reason: reason.value })) selected.value = null
}
</script>

<template>
  <section class="stack business-journal-panel" aria-label="业务凭证来源">
    <div class="journal-total"><p>按已确认业务生成凭证草稿。金额和来源由服务端核对，提交后由另一账号审核。</p>
      <div class="ledger-actions"><AppButton variant="secondary" :disabled="loading || busy || connectionLost" @click="loadBusinessJournals()">{{ loading ? '正在读取…' : '刷新来源' }}</AppButton>
        <AppButton v-if="can('business_journal.configure')" variant="secondary" :disabled="!options || loading || busy || connectionLost" @click="editPolicy">科目配置</AppButton></div>
    </div>
    <p v-if="loadError" role="alert">{{ loadError }} 请重新读取来源。</p>
    <p v-else-if="options && !options.policy.version">尚未启用业务凭证。配置前先核对已有手工账务，避免重复记账。</p>
    <p v-else-if="options" class="muted">启用日期 {{ options.policy.start_date }} · 科目配置版本 {{ options.policy.version }}。公司内部调拨不生成总账凭证；库存分位净额为零的来源无需生成。</p>
    <form v-if="configure && can('business_journal.configure')" class="ledger-editor" @submit.prevent="savePolicy">
      <h3>业务科目配置</h3><p class="muted">按公司核对后的科目表选择。未配置的用途会阻止对应来源生成；启用日期保存后固定，之前的业务仍需人工核对。</p>
      <div class="form-grid"><label>启用日期<NDatePicker to="body" :formatted-value="configuration.start_date || null" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true }" :disabled="configuration.version > 0 || busy" @update:formatted-value="value => { configuration.start_date = datePickerString(value) }" /></label>
        <label>配置依据 / 原因<AppInput v-model.trim="configuration.reason" required maxlength="200" :disabled="busy" /></label></div>
      <WorkspaceTable title="科目映射" :columns="roleColumns" :data="policyRows" :min-table-width="560">
        <template #cell-role="{ row }">{{ row.label }}</template>
        <template #cell-account="{ row }"><WorkspaceSelect :model-value="configuration.mapping[row.role as BusinessJournalRole] ?? 0" :options="accountOptions" :aria-label="`${row.label}科目`" :disabled="busy" @update:model-value="value => { configuration.mapping[row.role as BusinessJournalRole] = value }" /></template>
      </WorkspaceTable>
      <div class="form-actions"><AppButton variant="primary" type="submit" :disabled="busy || connectionLost || loading">{{ busy ? '正在保存…' : '保存配置' }}</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="configure = false">返回来源</AppButton></div>
    </form>
    <WorkspaceTable title="业务来源" :columns="columns" :data="rows" :min-table-width="920">
      <template #filters><label>搜索来源<AppInput v-model="query" placeholder="单据类别、来源号或凭证号" /></label><label>来源状态<WorkspaceSelect v-model="filter" :options="filterOptions" aria-label="来源状态" /></label></template>
      <template #cell-key="{ row }">{{ row.label }} {{ relatedDocumentLabel(row, 'source') }}</template><template #cell-amount="{ row }">{{ row.blockers.some((item: string) => item.includes('核价') || item.includes('单价')) ? '待核价' : `¥${businessTotal(row)}` }}</template>
      <template #cell-state="{ row }"><span v-if="row.journal_id">{{ journalStatusLabels[row.journal_status as keyof typeof journalStatusLabels] }} · {{ relatedDocumentLabel(row, 'journal') }}</span><span v-else-if="row.blockers.length">{{ row.blockers.join('；') }}</span><span v-else>{{ row.no_amount ? '分位净额为零' : '可生成草稿' }}</span></template>
      <template #cell-actions="{ row }"><div class="ledger-actions"><AppButton variant="text" :disabled="loading" @click="open(row)">核对来源</AppButton><AppButton v-if="row.journal_id" variant="text" @click="emit('openJournal', row.journal_id)">查看凭证</AppButton><AppButton v-else-if="can('business_journal.generate')" variant="text" :disabled="!row.can_generate || busy || connectionLost || loading" @click="open(row)">生成草稿</AppButton></div></template>
      <template #empty>{{ loading ? '正在读取业务来源…' : query || filter ? '没有匹配的业务来源。可切换到全部来源查看。' : '暂无已确认的业务来源。' }}</template>
    </WorkspaceTable>
    <NCollapse v-if="changes.length"><AppCollapseItem name="history" :title="`科目配置历史（${changes.length} 次）`"><WorkspaceTable title="配置审计" :columns="changeColumns" :data="changeRows" :min-table-width="760" /></AppCollapseItem></NCollapse>
    <NModal :show="selected !== null" preset="card" :title="selected ? `${selected.label} ${relatedDocumentLabel(selected, 'source')} · 来源核对` : ''" :mask-closable="!busy" :style="{ width: 'min(1050px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' }" @update:show="value => { if (!value) selected = null }">
      <div v-if="selected" class="stack">
        <BusinessSourceEvidence :source="selected" :mapping="options?.policy.mapping" :accounts="options?.accounts" />
        <AppButton variant="secondary" :disabled="loading || busy || connectionLost" @click="reloadSource">重新核对来源</AppButton>
        <form v-if="can('business_journal.generate') && !selected.journal_id && !selected.no_amount" class="ledger-editor" @submit.prevent="generate">
          <div class="form-grid"><label>凭证依据编号<AppInput v-model.trim="reference" required maxlength="80" :disabled="busy" /></label><label>凭证日期<NDatePicker to="body" :formatted-value="journalDate || null" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true, min: selected.minimum_date }" :is-date-disabled="(timestamp: number) => dateOutsideRange(timestamp, selected?.minimum_date)" :disabled="busy" @update:formatted-value="value => { journalDate = datePickerString(value) }" /></label><label>生成依据<AppInput v-model.trim="reason" required maxlength="200" :disabled="busy" /></label></div>
          <p class="muted">首次生成使用来源发生日期；已过账关联冲销后的重建，不得早于冲销日期。缺价或金额变化时先重新核对，不手工覆盖分录。</p>
          <p v-if="sourcePartners">真实往来对象自动带入各分录：{{ sourcePartners }}。</p>
          <WorkspaceTable title="业务分录辅助信息" :columns="auxiliaryColumns" :data="selectedRoles" :min-table-width="540">
            <template #cell-role="{ row }">{{ businessRoleLabels[row.role as BusinessJournalRole] }}</template>
            <template #cell-auxiliary="{ row }"><AuxiliarySelector :model-value="auxiliaryByRole[row.role as BusinessJournalRole]"
              :kinds="['department', 'project']" :items="options?.auxiliary_items" :date="journalDate" :disabled="busy || loading || connectionLost"
              :policy="options?.auxiliary_policies?.find(item => item.account_id === options?.policy.mapping[row.role as BusinessJournalRole])"
              :label-prefix="businessRoleLabels[row.role as BusinessJournalRole]"
              @update:model-value="values => { auxiliaryByRole[row.role as BusinessJournalRole] = values }" /></template>
          </WorkspaceTable>
          <div class="form-actions"><AppButton variant="primary" type="submit" :disabled="!selected.can_generate || loading || busy || connectionLost">{{ busy ? '正在生成…' : '生成凭证草稿' }}</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="selected = null">返回</AppButton></div>
        </form>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.business-journal-panel { min-width: 0; }
.business-journal-panel .journal-total { align-items: flex-start; }
.business-journal-panel select { width: 100%; }
.business-journal-panel summary { cursor: pointer; padding-block: 8px; }
.business-journal-panel :deep(.vxe-table--viewport-wrapper) { overflow: clip; }
</style>
