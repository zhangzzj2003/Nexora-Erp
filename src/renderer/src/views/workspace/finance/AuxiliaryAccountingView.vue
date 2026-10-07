<script setup lang="ts">
// 凭证与来源保留内部 ID，界面优先显示服务端保存的业务单号。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCheckbox, NCollapse, NDatePicker, NModal } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { datePickerString, vDateField } from '../../../utils/date-field'
import { localTime } from '../../../utils/formatters'
import type { AuxiliaryChange, AuxiliaryItem, AuxiliaryKind } from '../../../../../shared/erp-api'
import { auxiliaryKinds, auxiliaryLabels, auxiliaryText } from './auxiliary-display'
import { journalStatusLabels } from './journal-display'
import JournalHistory from './JournalHistory.vue'
import BusinessSourceEvidence from './BusinessSourceEvidence.vue'
import ProfitTransferEvidence from './ProfitTransferEvidence.vue'
import './ledger-metadata.css'
import './journals.css'

const store = usePiniaAppStore()
const { auxiliaryOptions: options, auxiliaryChanges: changes, auxiliaryQuery: filters,
  auxiliaryReport: report, auxiliaryLoading: loading, auxiliaryError: error, busy, user, connectionLost,
  error: operationError, ledgerReportJournal: journal, ledgerReportJournalLoading: journalLoading,
  ledgerReportJournalError: journalError } = storeToRefs(store)
const { can, loadAuxiliaryOptions, queryAuxiliary, exportAuxiliary, createAuxiliaryItem,
  updateAuxiliaryItem, saveAuxiliaryPolicy, openLedgerReportJournal, closeLedgerReportJournal, loadJournalChanges } = store
const mode = ref<'balances' | 'configuration'>('balances')
const periodId = ref<number | null>(null)
const selectedEntity = ref<number | null>(null)
const selectedRow = computed(() => report.value?.rows.find(row => row.entity_id === selectedEntity.value))
const editingItem = ref(false)
const itemForm = ref({ id: null as number | null, version: 0, kind: 'department' as 'department' | 'project', code: '', name: '', is_active: true, reason: '' })
const editingPolicy = ref(false)
const policyForm = ref({ account_id: 0, version: 0, start_date: '', required_kinds: [] as AuxiliaryKind[], reason: '' })
const accountOptions = computed(() => [{ value: 0, label: '选择科目', disabled: true }, ...(options.value?.accounts ?? []).map(item => ({ value: item.id, label: `${item.code} · ${item.name}${item.is_active ? '' : '（停用）'}` }))])
const entityOptions = computed(() => [{ value: null as number | null, label: '全部辅助对象' }, { value: 0, label: '未分配' },
  ...(options.value?.auxiliary_items ?? []).filter(item => item.kind === filters.value.kind).map(item => ({ value: item.id, label: `${item.code} · ${item.name}${item.is_active ? '' : '（停用）'}` }))])
const items = computed(() => options.value?.auxiliary_items.filter(item => item.kind === 'department' || item.kind === 'project') ?? [])
const rules = computed(() => (options.value?.accounts ?? []).map(account => ({ ...account,
  policy: options.value?.auxiliary_policies.find(item => item.account_id === account.id) })))
const balanceColumns = [{ key: 'name', title: '辅助对象', width: '220' }, { key: 'opening_debit', title: '期初借方（元）' },
  { key: 'opening_credit', title: '期初贷方（元）' }, { key: 'debit', title: '本期借方（元）' },
  { key: 'credit', title: '本期贷方（元）' }, { key: 'closing_debit', title: '期末借方（元）' },
  { key: 'closing_credit', title: '期末贷方（元）' }, { key: 'actions', title: '核对' }]
const itemColumns = [{ key: 'kind', title: '类型' }, { key: 'code', title: '编码' }, { key: 'name', title: '名称' }, { key: 'is_active', title: '状态' }, { key: 'version', title: '版本' }, { key: 'actions', title: '操作' }]
const ruleColumns = [{ key: 'account', title: '科目' }, { key: 'required', title: '必填维度' }, { key: 'date', title: '启用日' }, { key: 'version', title: '版本' }, { key: 'actions', title: '操作' }]
const entryColumns = [{ key: 'source', title: '来源' }, { key: 'date', title: '日期' }, { key: 'reference', title: '依据编号' },
  { key: 'summary', title: '摘要' }, { key: 'auxiliary', title: '原辅助快照', width: '290' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }, { key: 'range', title: '累计范围' }]
const journalColumns = [{ key: 'position', title: '序号' }, { key: 'account_name', title: '科目快照' }, { key: 'summary', title: '摘要' },
  { key: 'auxiliary', title: '辅助快照', width: '290' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const changeColumns = [{ key: 'created_at', title: '时间' }, { key: 'target', title: '对象' }, { key: 'before', title: '变更前', width: '260' },
  { key: 'after', title: '变更后', width: '260' }, { key: 'reason', title: '依据' }, { key: 'changed_by_name', title: '操作者' }]
const modalStyle = { width: 'min(1100px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
watch(() => filters.value.kind, () => { filters.value.entity_id = null })
watch(filters, () => { selectedEntity.value = null; closeLedgerReportJournal() }, { deep: true, flush: 'sync' })
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => {
  selectedEntity.value = null; editingItem.value = false; editingPolicy.value = false; closeLedgerReportJournal()
}, { flush: 'sync' })
onMounted(async () => {
  if (await loadAuxiliaryOptions()) {
    if (!filters.value.account_id) filters.value.account_id = options.value?.accounts[0]?.id ?? 0
    if (!filters.value.from_date) {
      const first = options.value?.periods[0]
      filters.value.from_date = first?.start_date ?? ''; filters.value.to_date = first?.end_date ?? ''
    }
  }
})
onUnmounted(closeLedgerReportJournal)
function choosePeriod(): void {
  const period = options.value?.periods.find(item => item.id === periodId.value)
  if (period) { filters.value.from_date = period.start_date; filters.value.to_date = period.end_date }
}
function editItem(record?: AuxiliaryItem): void {
  if (!can('auxiliary.manage')) return
  itemForm.value = record ? { id: record.id, version: record.version ?? 0, kind: record.kind as 'department' | 'project', code: record.code,
    name: record.name, is_active: record.is_active, reason: '' } : { id: null, version: 0, kind: 'department', code: '', name: '', is_active: true, reason: '' }
  operationError.value = ''; editingItem.value = true
}
async function saveItem(): Promise<void> {
  const { id, version, kind, code, name, is_active, reason } = itemForm.value
  const saved = id === null ? await createAuxiliaryItem({ kind, code, name, reason }) : await updateAuxiliaryItem({ id, version, name, is_active, reason })
  if (saved) editingItem.value = false
}
function editRule(account_id: number): void {
  if (!can('auxiliary.configure')) return
  const policy = options.value?.auxiliary_policies.find(item => item.account_id === account_id)
  policyForm.value = { account_id, version: policy?.version ?? 0, start_date: policy?.start_date ?? filters.value.from_date,
    required_kinds: [...(policy?.required_kinds ?? [])], reason: '' }
  operationError.value = ''; editingPolicy.value = true
}
function required(kind: AuxiliaryKind, checked: boolean): void {
  policyForm.value.required_kinds = policyForm.value.required_kinds.filter(item => item !== kind)
  if (checked) policyForm.value.required_kinds.push(kind)
}
async function saveRule(): Promise<void> { if (await saveAuxiliaryPolicy(policyForm.value)) editingPolicy.value = false }
function description(value: AuxiliaryChange['after'] | null): string {
  if (!value) return '尚未建立'
  if ('required_kinds' in value) return `${value.required_kinds.map(item => auxiliaryLabels[item]).join('、') || '无必填维度'} · ${value.start_date} · 版本 ${value.version}`
  return `${value.code} · ${value.name} · ${value.is_active ? '启用' : '停用'} · 版本 ${value.version}`
}
function inspectJournal(id: number): void { selectedEntity.value = null; void openLedgerReportJournal(id) }
</script>

<template>
  <section class="stack auxiliary-accounting-page">
    <div class="ledger-actions" aria-label="辅助核算内容">
      <AppButton :variant="mode === 'balances' ? 'primary' : 'secondary'" @click="mode = 'balances'">辅助余额</AppButton>
      <AppButton :variant="mode === 'configuration' ? 'primary' : 'secondary'" @click="mode = 'configuration'">档案与科目规则</AppButton>
      <AppButton variant="secondary" :disabled="loading || busy || connectionLost" @click="loadAuxiliaryOptions">{{ loading ? '正在读取…' : '重新读取' }}</AppButton>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!options && !loading && !error">先读取辅助档案和科目，再查询余额或维护规则。</p>
    <template v-if="mode === 'balances'">
      <form class="ledger-editor" @submit.prevent="queryAuxiliary">
        <div class="form-grid">
          <label>科目<WorkspaceSelect v-model="filters.account_id" :options="accountOptions" required :disabled="!options || loading" /></label>
          <label>辅助维度<WorkspaceSelect v-model="filters.kind" :options="auxiliaryKinds.map(kind => ({ value: kind, label: auxiliaryLabels[kind] }))" :disabled="loading" /></label>
          <label>辅助对象<WorkspaceSelect v-model="filters.entity_id" :options="entityOptions" :disabled="!options || loading" /></label>
          <label>会计期间<WorkspaceSelect v-model="periodId" :options="[{ value: null, label: '自定日期范围' }, ...(options?.periods ?? []).map(item => ({ value: item.id, label: `${item.code} · ${item.start_date} 至 ${item.end_date}` }))]" :disabled="loading" @change="choosePeriod" /></label>
          <label>开始日期<NDatePicker :formatted-value="filters.from_date || null" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true }" :disabled="loading" @update:formatted-value="value => { periodId = null; filters.from_date = datePickerString(value) }" /></label>
          <label>结束日期<NDatePicker :formatted-value="filters.to_date || null" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true, min: filters.from_date }" :disabled="loading" @update:formatted-value="value => { periodId = null; filters.to_date = datePickerString(value) }" /></label>
        </div>
        <div class="form-actions"><AppButton type="submit" variant="primary" :disabled="!options || loading || connectionLost || !filters.account_id">{{ loading ? '正在核对…' : '查询辅助余额' }}</AppButton><AppButton type="button" variant="secondary" :disabled="!report || loading || connectionLost" @click="exportAuxiliary">导出 CSV</AppButton></div>
        <p class="muted">每条分录在所选维度累计一次。未分配保留原历史缺口，不推断客户或项目；金额以已确认期初和已过账分录为准。</p>
      </form>
      <template v-if="report">
        <p>{{ report.account.code }} · {{ report.account.name }} · {{ auxiliaryLabels[report.filters.kind] }} · {{ report.filters.from_date }} 至 {{ report.filters.to_date }} · 人民币 · 生成于 {{ localTime(report.generated_at) }}</p>
        <WorkspaceTable title="辅助余额" :show-title="false" :columns="balanceColumns" :data="report.rows" :min-table-width="1100">
          <template #cell-name="{ row }">{{ row.name }}<span v-if="row.code"> · {{ row.code }}</span></template>
          <template #cell-actions="{ row }"><AppButton variant="text" @click="selectedEntity = row.entity_id">核对明细</AppButton></template>
          <template #empty>所选科目、辅助对象和日期范围没有已确认期初或已过账分录。</template>
        </WorkspaceTable>
        <p>合计净额（借方为正）：期初 {{ report.totals.opening_net }} 元 · 本期借方 {{ report.totals.debit }} 元 · 本期贷方 {{ report.totals.credit }} 元 · 期末 {{ report.totals.closing_net }} 元。</p>
        <NCollapse><AppCollapseItem name="scope" title="辅助余额核对口径"><p v-for="warning in report.warnings" :key="warning">{{ warning }}</p></AppCollapseItem></NCollapse>
      </template>
      <p v-else-if="!loading && options">请选择科目和日期，查询辅助余额。修改查询条件后须重新查询。</p>
    </template>
    <template v-else>
      <WorkspaceTable title="部门与项目辅助档案" :columns="itemColumns" :data="items" :min-table-width="800">
        <template #actions><AppButton v-if="can('auxiliary.manage')" variant="primary" :disabled="!options || busy || loading || connectionLost" @click="editItem()">新增辅助档案</AppButton></template>
        <template #cell-kind="{ row }">{{ auxiliaryLabels[row.kind as AuxiliaryKind] }}</template><template #cell-is_active="{ row }">{{ row.is_active ? '启用' : '停用' }}</template>
        <template #cell-actions="{ row }"><AppButton v-if="can('auxiliary.manage')" variant="text" :disabled="busy || connectionLost" @click="editItem(row)">修改 / 启停</AppButton><span v-else>只读</span></template>
        <template #empty>{{ loading ? '正在读取档案…' : '暂无部门或项目辅助档案。客户和供应商复用基础资料，不在此重复建档。' }}</template>
      </WorkspaceTable>
      <p class="muted">客户与供应商请在基础资料中维护；部门与项目编码、类型保存后固定。名称和启停修改不会重写已过账快照。</p>
      <WorkspaceTable title="科目辅助规则" :columns="ruleColumns" :data="rules" :min-table-width="850">
        <template #cell-account="{ row }">{{ row.code }} · {{ row.name }}{{ row.is_active ? '' : '（停用）' }}</template>
        <template #cell-required="{ row }">{{ row.policy?.required_kinds.map((kind: AuxiliaryKind) => auxiliaryLabels[kind]).join('、') || '无必填维度' }}</template>
        <template #cell-date="{ row }">{{ row.policy?.start_date || '未配置' }}</template><template #cell-version="{ row }">{{ row.policy?.version ?? 0 }}</template>
        <template #cell-actions="{ row }"><AppButton v-if="can('auxiliary.configure')" variant="text" :disabled="busy || connectionLost || !row.is_active" @click="editRule(row.id)">配置必填维度</AppButton><span v-else>只读</span></template>
        <template #empty>{{ loading ? '正在读取科目…' : '暂无科目，请先建立总账科目。' }}</template>
      </WorkspaceTable>
      <NCollapse><AppCollapseItem name="changes" :title="`辅助档案与规则变更记录（${changes.length} 条）`">
        <WorkspaceTable title="辅助变更记录" :show-title="false" :columns="changeColumns" :data="changes" :min-table-width="1150">
          <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template><template #cell-target="{ row }">{{ row.category === 'item' ? '辅助档案' : '科目规则' }} #{{ row.target_id }}</template>
          <template #cell-before="{ row }">{{ description(row.before) }}</template><template #cell-after="{ row }">{{ description(row.after) }}</template>
          <template #empty>暂无变更记录。</template>
        </WorkspaceTable>
      </AppCollapseItem></NCollapse>
    </template>
    <NModal v-model:show="editingItem" preset="card" :title="itemForm.id === null ? '新增辅助档案' : '修改辅助档案'" :style="modalStyle" :mask-closable="!busy">
      <form v-if="can('auxiliary.manage')" class="ledger-editor" @submit.prevent="saveItem">
        <p v-if="operationError" role="alert">{{ operationError }}</p><div class="form-grid">
          <label>档案类型<WorkspaceSelect v-model="itemForm.kind" :options="[{ value: 'department', label: '部门' }, { value: 'project', label: '项目' }]" :disabled="itemForm.id !== null || busy" /></label>
          <label>编码<AppInput v-model.trim="itemForm.code" required maxlength="40" pattern="[A-Za-z0-9_-]+" :disabled="itemForm.id !== null || busy" /></label>
          <label>名称<AppInput v-model.trim="itemForm.name" required maxlength="80" :disabled="busy" /></label>
          <label>操作依据<AppInput v-model.trim="itemForm.reason" required maxlength="200" :disabled="busy" /></label>
        </div><NCheckbox v-if="itemForm.id !== null" v-model:checked="itemForm.is_active" :disabled="busy">启用此档案</NCheckbox>
        <div class="form-actions"><AppButton type="submit" variant="primary" :disabled="busy || connectionLost">{{ busy ? '正在保存…' : '保存档案' }}</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="editingItem = false">返回</AppButton></div>
      </form>
    </NModal>
    <NModal v-model:show="editingPolicy" preset="card" title="配置科目辅助规则" :style="modalStyle" :mask-closable="!busy">
      <form v-if="can('auxiliary.configure')" class="ledger-editor" @submit.prevent="saveRule">
        <p>科目：{{ options?.accounts.find(item => item.id === policyForm.account_id)?.code }} · {{ options?.accounts.find(item => item.id === policyForm.account_id)?.name }}</p>
        <p>启用日起，原始分录保存、提交、审核和过账均检查必填维度；旧过账记录及冲销保留原快照。</p>
        <p v-if="operationError" role="alert">{{ operationError }}</p>
        <label>启用日期<NDatePicker :formatted-value="policyForm.start_date || null" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true }" :disabled="busy || policyForm.version > 0" @update:formatted-value="value => { policyForm.start_date = datePickerString(value) }" /></label>
        <div class="auxiliary-required"><NCheckbox v-for="kind in auxiliaryKinds" :key="kind" :checked="policyForm.required_kinds.includes(kind)" :disabled="busy" @update:checked="value => required(kind, value)">{{ auxiliaryLabels[kind] }}必填</NCheckbox></div>
        <label>配置依据<AppInput v-model.trim="policyForm.reason" required maxlength="200" :disabled="busy" /></label>
        <div class="form-actions"><AppButton type="submit" variant="primary" :disabled="busy || connectionLost">{{ busy ? '正在保存…' : '保存辅助规则' }}</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="editingPolicy = false">返回</AppButton></div>
      </form>
    </NModal>
    <NModal :show="!!selectedRow" preset="card" :title="selectedRow ? `${selectedRow.name} · 辅助来源明细` : ''" :style="modalStyle" @update:show="value => { if (!value) selectedEntity = null }">
      <WorkspaceTable v-if="selectedRow" title="本次查询的来源快照" :columns="entryColumns" :data="selectedRow.entries" :min-table-width="1200">
        <template #cell-source="{ row }"><AppButton v-if="row.journal_id && can('journal.view')" variant="text" :disabled="connectionLost" @click="inspectJournal(row.journal_id)">{{ relatedDocumentLabel(row, 'journal') }}</AppButton><span v-else>{{ row.journal_id ? `${relatedDocumentLabel(row, 'journal')}` : `${relatedDocumentLabel(row, 'opening_balance')}` }}</span></template>
        <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template><template #cell-range="{ row }">{{ row.opening_contribution ? '期初累计' : '本期发生' }}</template>
      </WorkspaceTable>
    </NModal>
    <NModal :show="!!journal || journalLoading || !!journalError" preset="card" :title="journal ? `${documentLabel(journal)} · ${journalStatusLabels[journal.status]}` : '当前凭证详情'" :style="modalStyle" @update:show="value => { if (!value) closeLedgerReportJournal() }">
      <p v-if="journalLoading" role="status">正在读取当前凭证…</p><p v-if="journalError" role="alert">{{ journalError }}</p>
      <div v-if="journal" class="stack"><p>{{ journal.journal_date }} · {{ journal.reference }} · 当前版本 {{ journal.version }}；来源表保留本次查询快照。</p>
        <WorkspaceTable title="当前凭证分录" :columns="journalColumns" :data="journal.lines" :min-table-width="1100"><template #cell-account_name="{ row }">{{ row.account_code }} · {{ row.account_name }}</template><template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template></WorkspaceTable>
        <NCollapse><AppCollapseItem v-if="journal.business_source" name="business" title="生成时的业务来源"><BusinessSourceEvidence :source="journal.business_source.evidence" :mapping="journal.business_source.mapping" /></AppCollapseItem><AppCollapseItem v-if="journal.profit_transfer" name="transfer" title="生成时的损益结转来源"><ProfitTransferEvidence :evidence="journal.profit_transfer.evidence" :can-open-journal="can('journal.view')" @open-journal="inspectJournal" /></AppCollapseItem></NCollapse>
        <JournalHistory :key="`${journal.id}:${journal.version}`" :load="() => loadJournalChanges(journal!.id)" />
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.auxiliary-accounting-page { min-width: 0; }
.auxiliary-required { display: flex; flex-wrap: wrap; gap: 16px 24px; }
</style>
