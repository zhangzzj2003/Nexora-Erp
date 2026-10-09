<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse, NDatePicker, NModal } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import AuxiliarySelector from './AuxiliarySelector.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { datePickerString, vDateField } from '../../../utils/date-field'
import { documentLabel } from '../../../../../shared/document-numbering'
import type { AuxiliaryReference } from '../../../../../shared/erp-api'
import type { ControlBalanceTransfer, ControlScopeGroup, ControlTransferInput } from '../../../../../shared/control-balance-api'
import { controlCaption, controlChoice, controlCombinationKey, controlEvidenceText, controlGroupKey, controlKindLabels, controlOperationLabels, controlTransferLimit } from './control-balance-display'
import { journalStatusLabels } from './journal-display'
import { amountText, cents } from './subledger-order-display'
import { auxiliaryText } from './auxiliary-display'
import { localTime } from '../../../utils/formatters'
import './ledger-metadata.css'

const store = usePiniaAppStore()
const { controlBalanceTransfers: records, controlBalanceOptions: options, controlBalanceReport: report,
  controlBalanceDetail: detail, controlBalanceChanges: changes, controlBalanceJournal: journal,
  controlBalanceLoading: loading, controlBalanceReportLoading: reportLoading, controlBalanceError: readError, busy, connectionLost, user, server, error } = storeToRefs(store)
const { can, loadControlBalances, loadControlBalanceDetail, closeControlBalanceDetail, queryControlBalances,
  loadControlBalanceJournal, closeControlBalanceJournal, openDocumentApproval, createControlBalanceTransfer,
  generateControlBalanceJournal, reverseControlBalanceTransfer, cancelControlBalanceTransfer, postControlBalanceJournal, cancelControlBalanceJournal } = store
const disabled = computed(() => busy.value || connectionLost.value || loading.value)
const query = ref(''), mode = ref<'records' | 'balances'>('records'), cutoff = ref(new Date().toISOString().slice(0, 10))
const editing = ref(false), showDetail = ref(false), detailLoading = ref(false), showJournal = ref(false), journalLoading = ref(false)
const fresh = () => ({ kind: 'receivable' as const, operation: 'reclassify' as 'reclassify' | 'allocate', business_date: new Date().toISOString().slice(0, 10),
  source: '', target: '', newTarget: true, account_id: 0, amount: '', reference: '', reason: '' })
const form = ref< Omit<ReturnType<typeof fresh>, 'kind'> & { kind: 'receivable' | 'payable' }>(fresh())
const extraAuxiliary = ref<AuxiliaryReference[]>([])
type CommandAction = 'generate' | 'reverse' | 'cancel' | 'post' | 'cancelJournal'
const command = ref<{ row: ControlBalanceTransfer; action: CommandAction; journalVersion?: number; journalApprovalVersion?: number } | null>(null)
const commandReason = ref(''), commandReference = ref(''), commandDate = ref('')
const modalStyle = { width: 'min(960px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
const groups = computed(() => (options.value?.origins ?? []).flatMap(row => row.groups))
const sources = computed(() => groups.value.filter(row => row.kind === form.value.kind && !row.blockers.length
  && (form.value.operation === 'allocate' ? cents(row.outstanding_amount) < 0n : cents(row.outstanding_amount) !== 0n)))
const source = computed(() => sources.value.find(row => controlGroupKey(row) === form.value.source))
const targets = computed(() => source.value ? groups.value.filter(row => row.kind === source.value!.kind && row.party_id === source.value!.party_id
  && !row.blockers.length && controlGroupKey(row) !== controlGroupKey(source.value!)
  && (form.value.operation === 'reclassify' ? row.source_type === source.value!.source_type && row.source_id === source.value!.source_id
    : (row.source_type !== source.value!.source_type || row.source_id !== source.value!.source_id) && cents(row.outstanding_amount) > 0n)
  && controlCombinationKey(row) !== controlCombinationKey(source.value!)) : [])
const target = computed(() => targets.value.find(row => controlGroupKey(row) === form.value.target))
const newTarget = computed(() => form.value.operation === 'reclassify' && form.value.newTarget)
const limit = computed(() => controlTransferLimit(source.value, target.value, form.value.operation))
const accountOptions = computed(() => (options.value?.accounts ?? []).filter(row => options.value?.control_accounts.some(item => item.kind === form.value.kind && item.account_id === row.id))
  .map(row => ({ value: row.id, label: `${row.code} · ${row.name}` })))
const scopeLabel = (row: ControlScopeGroup) => `${row.source_type === 'historical' ? '历史原单' : '订单'} ${row.reference || '#' + row.source_id} · ${row.party_name} · ${accountName(row.account_id)} · ${auxiliaryText(row.auxiliary)} · ${row.outstanding_amount} 元`
const accountName = (id: number) => options.value?.accounts.find(row => row.id === id)?.code ?? '#' + id
const sourceOptions = computed(() => sources.value.map(row => ({ value: controlGroupKey(row), label: scopeLabel(row) })))
const targetOptions = computed(() => targets.value.map(row => ({ value: controlGroupKey(row), label: scopeLabel(row) })))
const filtered = computed(() => records.value.filter(row => [documentLabel(row), row.reference, row.reason, row.evidence.source.party_name,
  row.evidence.source.reference, row.evidence.target.reference].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const balanceRows = computed(() => (report.value?.origins ?? []).flatMap(row => row.groups))
const blockedOrigins = computed(() => (options.value?.origins ?? []).filter(row => row.blockers.length))
const transferPermission = (row: ControlBalanceTransfer) => row.reverses_id ? 'control_transfer.reverse' : 'control_transfer.post'
function available(row: ControlBalanceTransfer, action: CommandAction): boolean {
  if (!can('control_transfer.view')) return false
  if (action === 'reverse') return can('control_transfer.reverse') && row.status === 'executed' && !row.reverses_id && !row.reversal_id
  if (row.status !== 'draft') return false
  if (action === 'cancelJournal') return can(row.reverses_id ? 'control_transfer.reverse' : 'control_transfer.create') && can('journal.cancel')
    && journal.value?.id === row.journal_id && ['draft','rejected','submitted','approved'].includes(journal.value.status)
    && !['submitted','approved'].includes(journal.value.approval?.status ?? '')
  if (action === 'cancel') return can(row.reverses_id ? 'control_transfer.reverse' : 'control_transfer.create')
    && !['submitted','approved'].includes(row.approval?.status ?? '') && (!row.journal_id || row.journal_status === 'cancelled')
  if (!can(transferPermission(row)) || row.approval?.status !== 'approved') return false
  if (action === 'generate') return can('journal.create') && (!row.journal_id || row.journal_status === 'cancelled')
  return can('journal.post') && journal.value?.id === row.journal_id && journal.value?.status === 'approved' && journal.value?.approval?.status === 'approved'
}
watch(() => `${form.value.kind}:${form.value.operation}`, () => { form.value.source = ''; form.value.target = ''; extraAuxiliary.value = [] })
watch(source, row => { form.value.target = ''; form.value.account_id = 0; extraAuxiliary.value = row?.auxiliary.filter(item => !['customer','supplier'].includes(item.kind)).map(({ kind, id }) => ({ kind, id })) ?? [] })
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}`, () => {
  editing.value = false; showDetail.value = false; showJournal.value = false; command.value = null; form.value = fresh(); extraAuxiliary.value = []
}, { flush: 'sync' })
onMounted(loadControlBalances)
onUnmounted(() => { closeControlBalanceDetail(); closeControlBalanceJournal() })
function start(): void {
  if (disabled.value || !can('control_transfer.create') || !options.value) return
  form.value = fresh(); extraAuxiliary.value = []; error.value = ''; editing.value = true
}
async function save(): Promise<void> {
  if (disabled.value || !source.value || cents(form.value.amount) <= 0n || cents(form.value.amount) > limit.value) return
  const from_scope = controlChoice(source.value)
  const to_scope = newTarget.value ? { ...from_scope, account_id: form.value.account_id, fingerprint: null,
    auxiliary: [...source.value.auxiliary.filter(item => ['customer','supplier'].includes(item.kind)).map(({ kind, id }) => ({ kind, id })), ...extraAuxiliary.value] }
    : target.value ? controlChoice(target.value) : null
  if (!to_scope) return
  const input: ControlTransferInput = { kind: form.value.kind, operation: form.value.operation, business_date: form.value.business_date,
    from_scope, to_scope, amount: form.value.amount, reference: form.value.reference, reason: form.value.reason }
  if (await createControlBalanceTransfer(input)) editing.value = false
}
async function inspect(id: number): Promise<void> {
  showDetail.value = true; detailLoading.value = true
  await loadControlBalanceDetail(id); detailLoading.value = false
}
async function inspectJournal(id: number): Promise<void> {
  if (!can('journal.view') || disabled.value) return
  showJournal.value = true; journalLoading.value = true
  await loadControlBalanceJournal(id); journalLoading.value = false
}
function ask(row: ControlBalanceTransfer, action: CommandAction): void {
  if (disabled.value || !available(row, action)) return
  command.value = { row, action, journalVersion: journal.value?.version, journalApprovalVersion: journal.value?.approval?.version }; commandReason.value = ''; commandReference.value = ''
  commandDate.value = new Date().toISOString().slice(0, 10); error.value = ''
}
async function confirm(): Promise<void> {
  const pending = command.value
  if (!pending || disabled.value || !commandReason.value.trim()) return
  const current = records.value.find(row => row.id === pending.row.id)
  if (!current || current.version !== pending.row.version || current.approval?.version !== pending.row.approval?.version || !available(current, pending.action)
    || ['post','cancelJournal'].includes(pending.action) && (journal.value?.version !== pending.journalVersion || journal.value?.approval?.version !== pending.journalApprovalVersion)) { error.value = '转账或凭证审批已变化，请关闭弹窗重新读取。'; return }
  const saved = pending.action === 'generate' ? await generateControlBalanceJournal(current, commandReference.value, commandReason.value)
    : pending.action === 'reverse' ? await reverseControlBalanceTransfer(current, commandDate.value, commandReference.value, commandReason.value)
      : pending.action === 'cancel' ? await cancelControlBalanceTransfer(current, commandReason.value)
        : journal.value ? pending.action === 'cancelJournal' ? await cancelControlBalanceJournal(current, journal.value, commandReason.value)
          : await postControlBalanceJournal(current, journal.value, commandReason.value) : false
  if (saved) {
    command.value = null
    if (showDetail.value) await loadControlBalanceDetail(current.id)
    if (showJournal.value && current.journal_id) await loadControlBalanceJournal(current.journal_id)
  }
}
</script>

<template>
  <section class="stack ledger-metadata-page">
    <p>同一往来对象的余额可重分配控制科目或部门、项目；也可把贷方余额分配给另一原单的借方组合。转账和凭证分别批准，凭证过账时才同步更新余额。</p>
    <div class="ledger-actions">
      <AppButton :aria-pressed="mode === 'records'" :variant="mode === 'records' ? 'primary' : 'secondary'" @click="mode = 'records'">转账记录</AppButton>
      <AppButton :aria-pressed="mode === 'balances'" :variant="mode === 'balances' ? 'primary' : 'secondary'" @click="mode = 'balances'">截止日组合余额</AppButton>
      <AppButton :disabled="disabled" @click="loadControlBalances">{{ loading ? '正在核对…' : '读取最新依据' }}</AppButton>
      <AppButton v-if="can('control_transfer.create')" :disabled="disabled || !options" variant="primary" @click="start">新增余额转账</AppButton>
    </div>
    <p v-if="readError" role="alert">{{ readError }}</p>
    <NCollapse v-if="blockedOrigins.length"><AppCollapseItem name="blocked" :title="`${blockedOrigins.length} 个原单存在组合依据缺口`">
      <p v-for="row in blockedOrigins" :key="`${row.kind}:${row.source_type}:${row.source_id}`">{{ row.reference || '#' + row.source_id }} · {{ row.party_name }}：{{ row.blockers.join('；') }}。请核对来源及已过账凭证。</p>
    </AppCollapseItem></NCollapse>
    <WorkspaceTable v-if="mode === 'records'" title="往来余额转账" :data="filtered" :loading="loading" :min-table-width="1460" :columns="[
      { key: 'id', title: '转账单号', width: '190' }, { key: 'party', title: '往来与用途', width: '210' }, { key: 'scopes', title: '来源 / 目标原单', width: '280' },
      { key: 'amount', title: '金额（元）' }, { key: 'business_date', title: '生效日期' }, { key: 'status', title: '审批与过账', width: '230' }, { key: 'actions', title: '操作', width: '420' } ]">
      <template #filters><label class="ledger-search">搜索单号、原单或往来对象<AppInput v-model="query" /></label></template>
      <template #cell-id="{ row }">{{ documentLabel(row) }}<p v-if="row.reverses_id">反向原转账 #{{ row.reverses_id }}</p></template>
      <template #cell-party="{ row }">{{ row.evidence.source.party_name }}<p>{{ controlKindLabels[row.kind] }} · {{ controlOperationLabels[row.operation] }}</p></template>
      <template #cell-scopes="{ row }"><p>来源：{{ row.evidence.source.reference || '#' + row.from_scope.source_id }}</p><p>目标：{{ row.evidence.target.reference || '#' + row.to_scope.source_id }}</p></template>
      <template #cell-status="{ row }">{{ controlCaption(row) }}<p v-if="row.journal_id && row.journal_status">凭证 #{{ row.journal_id }} · {{ journalStatusLabels[row.journal_status] }}</p></template>
      <template #cell-actions="{ row }"><div class="ledger-actions">
        <AppButton variant="text" :disabled="disabled" @click="inspect(row.id)">组合、来源与审计</AppButton>
        <AppButton variant="text" :disabled="disabled" @click="openDocumentApproval({ document_type: 'ControlBalanceTransfer', document_id: row.id, intent: 'execute' })">转账审批</AppButton>
        <AppButton v-if="available(row, 'generate')" variant="text" :disabled="disabled" @click="ask(row, 'generate')">生成固定凭证</AppButton>
        <AppButton v-if="row.journal_id && can('journal.view')" variant="text" :disabled="disabled" @click="inspectJournal(row.journal_id)">关联凭证</AppButton>
        <AppButton v-if="available(row, 'reverse')" variant="text" :disabled="disabled" @click="ask(row, 'reverse')">建立反向转账</AppButton>
        <AppButton v-if="available(row, 'cancel')" variant="text" :disabled="disabled" @click="ask(row, 'cancel')">取消草稿</AppButton>
      </div></template>
      <template #empty>暂无往来余额转账。读取最新依据后，可选择已核对的原单组合建立草稿。</template>
    </WorkspaceTable>
    <template v-else>
      <form class="ledger-actions" @submit.prevent="queryControlBalances(cutoff)"><label>截止日（UTC）<NDatePicker v-date-field="{ required: true }" :formatted-value="cutoff" value-format="yyyy-MM-dd" type="date" :disabled="disabled || reportLoading" @update:formatted-value="value => cutoff = datePickerString(value)" /></label><AppButton type="submit" :disabled="disabled || reportLoading || !cutoff">核对截止日组合</AppButton></form>
      <section v-if="reportLoading" class="stack" aria-busy="true"><h2>截止日完整组合余额</h2><p role="status">正在核对截止日组合…</p></section>
      <template v-else>
      <p v-if="report">以下余额按业务日期截至 {{ report.to_date }}（UTC），不含业务日期晚于截止日的转账和更正。</p>
      <WorkspaceTable title="截止日完整组合余额" :data="balanceRows" :min-table-width="1200" :columns="[{ key: 'reference', title: '原单 / 订单' }, { key: 'party_name', title: '往来对象' }, { key: 'account_id', title: '控制科目' }, { key: 'auxiliary', title: '完整辅助', width: '300' }, { key: 'outstanding_amount', title: '未结（元）' }, { key: 'blockers', title: '依据缺口' }]">
        <template #cell-reference="{ row }">{{ row.source_type === 'historical' ? '历史原单' : '订单' }} {{ row.reference || '#' + row.source_id }}</template>
        <template #cell-account_id="{ row }">{{ accountName(row.account_id) }}</template><template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template><template #cell-blockers="{ row }">{{ row.blockers.join('；') || '已核对' }}</template>
        <template #empty>选择截止日并核对后，显示各原单按科目和完整辅助分开的余额。</template>
      </WorkspaceTable>
      </template>
    </template>
    <NModal :show="editing" preset="card" title="往来余额转账草稿" :style="modalStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!busy) editing = value }">
      <form class="ledger-editor" @submit.prevent="save">
        <label>往来类别<WorkspaceSelect v-model="form.kind" :disabled="disabled" :options="[{ value: 'receivable', label: controlKindLabels.receivable }, { value: 'payable', label: controlKindLabels.payable }]" /></label>
        <label>转账用途<WorkspaceSelect v-model="form.operation" :disabled="disabled" :options="[{ value: 'reclassify', label: controlOperationLabels.reclassify }, { value: 'allocate', label: controlOperationLabels.allocate }]" /></label>
        <p>{{ form.operation === 'reclassify' ? '保留同一原单总额，把借方或贷方余额移入另一控制科目或完整辅助组合。' : '同一真实往来对象的不同原单，按来源贷方及目标借方组合的额度分配；不产生银行收付款。' }}</p>
        <label>来源原单与实际组合<WorkspaceSelect v-model="form.source" :disabled="disabled" :options="sourceOptions" /></label>
        <p v-if="!sources.length">没有当前可用的已过账组合，请核对真实业务来源和凭证。</p>
        <label v-if="form.operation === 'reclassify'">目标组合<WorkspaceSelect v-model="form.newTarget" :disabled="disabled" :options="[{ value: true, label: '建立新科目 / 辅助组合' }, { value: false, label: '转入本原单已有组合' }]" /></label>
        <template v-if="newTarget"><label>目标控制科目<WorkspaceSelect v-model="form.account_id" :disabled="disabled || !source" :options="accountOptions" /></label>
          <p v-if="source">实际往来固定为 {{ source.party_name }}；目标部门、项目可重新选择。</p>
          <AuxiliarySelector v-model="extraAuxiliary" :items="options?.auxiliary_items" :kinds="['department','project']" :policy="options?.auxiliary_policies.find(row => row.account_id === form.account_id)" :date="form.business_date" :disabled="disabled || !source" label-prefix="目标组合" />
        </template><label v-else>目标原单与实际组合<WorkspaceSelect v-model="form.target" :disabled="disabled || !source" :options="targetOptions" /></label>
        <p v-if="source">来源余额 {{ source.outstanding_amount }} 元；当前最多办理 {{ amountText(limit) }} 元。批准不占用余额，实际过账会复核两侧最新依据。</p>
        <label>转账生效日（UTC）<NDatePicker v-date-field="{ required: true }" :formatted-value="form.business_date" value-format="yyyy-MM-dd" type="date" :disabled="disabled" @update:formatted-value="value => form.business_date = datePickerString(value)" /></label>
        <label>金额（人民币）<AppInput v-model="form.amount" required inputmode="decimal" pattern="[0-9]{1,13}(\.[0-9]{1,2})?" :disabled="disabled" /></label>
        <p v-if="form.amount && cents(form.amount) > limit" role="alert">金额超过所选实际组合额度，请核对后修改。</p>
        <label>参考号<AppInput v-model.trim="form.reference" required maxlength="80" :disabled="disabled" /></label><label>转账依据<AppInput v-model.trim="form.reason" required maxlength="200" :disabled="disabled" /></label>
        <p v-if="error" role="alert">{{ error }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !source || (newTarget ? !form.account_id : !target) || cents(form.amount) <= 0n || cents(form.amount) > limit || !form.reference || !form.reason">保存转账草稿</AppButton>
      </form>
    </NModal>
    <NModal :show="showDetail" preset="card" title="固定组合、来源与审计" :style="modalStyle" @update:show="value => { showDetail = value; if (!value) closeControlBalanceDetail() }">
      <p v-if="detailLoading" role="status">正在读取转账原始依据…</p><p v-if="readError" role="alert">{{ readError }}</p>
      <template v-if="detail"><p>{{ documentLabel(detail) }} · {{ controlCaption(detail) }} · {{ detail.amount }} 元 · {{ detail.business_date }}（UTC）</p><p>参考号 {{ detail.reference }} · {{ detail.reason }}</p>
        <NCollapse :default-expanded-names="['source','target']"><AppCollapseItem v-for="side in ['source','target'] as const" :key="side" :name="side" :title="side === 'source' ? '来源固定组合' : '目标固定组合'">
          <p>{{ scopeLabel(detail.evidence[side]) }}</p><p v-for="(item, index) in detail.evidence[side].evidence" :key="index">{{ controlEvidenceText(item) }} <AppButton v-if="'journal_id' in item && item.journal_id && can('journal.view')" variant="text" :disabled="disabled" @click="inspectJournal(item.journal_id)">查看来源凭证</AppButton></p>
        </AppCollapseItem><AppCollapseItem name="audit" :title="`${changes.length} 条不可覆盖的转账审计`"><p v-for="item in changes" :key="item.id">{{ localTime(item.created_at) }} · 操作者 #{{ item.changed_by }} · {{ item.action }} · v{{ item.snapshot.version }} · {{ item.reason }}</p></AppCollapseItem></NCollapse>
      </template>
    </NModal>
    <NModal :show="showJournal" preset="card" title="关联及来源凭证" :style="modalStyle" @update:show="value => { showJournal = value; if (!value) closeControlBalanceJournal() }">
      <p v-if="journalLoading" role="status">正在读取真实凭证…</p><p v-if="readError" role="alert">{{ readError }}</p>
      <template v-if="journal"><p>{{ documentLabel(journal) }} · {{ journal.journal_date }} · {{ journalStatusLabels[journal.status] }} · 参考号 {{ journal.reference }}</p>
        <WorkspaceTable title="实际凭证分录" :data="journal.lines" :min-table-width="1000" :columns="[{ key: 'account_code', title: '控制科目' }, { key: 'summary', title: '摘要' }, { key: 'auxiliary', title: '完整辅助', width: '300' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]">
          <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
        </WorkspaceTable>
        <AppButton :disabled="disabled" @click="openDocumentApproval({ document_type: 'Journal', document_id: journal.id, intent: 'execute' })">凭证审批</AppButton>
        <template v-for="row in records.filter(row => row.journal_id === journal?.id)" :key="row.id"><p>本凭证关联 {{ documentLabel(row) }}。实际过账将再次核对转账批准、来源额度与开放期间，并同时生效余额。</p>
          <AppButton v-if="available(row, 'post')" :disabled="disabled" variant="primary" @click="ask(row, 'post')">过账凭证并生效转账</AppButton>
          <AppButton v-if="available(row, 'cancelJournal')" :disabled="disabled" @click="ask(row, 'cancelJournal')">取消未过账凭证</AppButton>
        </template>
      </template>
    </NModal>
    <NModal :show="!!command" preset="card" title="确认转账操作" :style="modalStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!value && !busy) command = null }">
      <form class="ledger-editor" @submit.prevent="confirm"><p v-if="command">{{ documentLabel(command.row) }} · {{ command.row.amount }} 元 · {{ command.row.reference }}</p>
        <p v-if="command?.action === 'reverse'">原转账与凭证保留。下游转账、资金及凭证须先倒序更正，反向转账和新凭证都须重新批准；过账后才恢复归属。</p>
        <p v-if="command?.action === 'post'">确认把已批准的固定凭证过账，并在同一事务中生效转账；失败不会留下单边变动。</p>
        <p v-if="command?.action === 'cancelJournal'">只取消未过账的固定凭证，原凭证和审计保留。随后可重新生成凭证；若要取消转账草稿，先撤回转账审批。</p>
        <label v-if="command?.action === 'generate' || command?.action === 'reverse'">{{ command.action === 'generate' ? '凭证参考号' : '反向转账参考号' }}<AppInput v-model.trim="commandReference" required maxlength="80" :disabled="disabled" /></label>
        <label v-if="command?.action === 'reverse'">反向生效日期（UTC）<NDatePicker v-date-field="{ required: true }" :formatted-value="commandDate" value-format="yyyy-MM-dd" type="date" :disabled="disabled" @update:formatted-value="value => commandDate = datePickerString(value)" /></label>
        <label>操作依据<AppInput v-model.trim="commandReason" required maxlength="200" :disabled="disabled" /></label><p v-if="error" role="alert">{{ error }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !commandReason">{{ command?.action === 'generate' ? '生成固定凭证' : command?.action === 'reverse' ? '保存反向转账草稿' : command?.action === 'post' ? '过账并生效转账' : command?.action === 'cancelJournal' ? '取消未过账凭证' : '取消未生效草稿' }}</AppButton>
      </form>
    </NModal>
    <DocumentApprovalDialog />
  </section>
</template>
