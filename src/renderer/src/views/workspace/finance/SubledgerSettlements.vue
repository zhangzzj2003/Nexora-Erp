<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import type { SubledgerSettlement, SubledgerSettlementInput } from '../../../../../shared/erp-api'
import { sameSubledgerScope, settlementActions, canReverseSettlement } from './subledger-settlement-display'
import { auxiliaryText } from './auxiliary-display'
import { localTime } from '../../../utils/formatters'

const props = defineProps<{ search: string }>()
const store = usePiniaAppStore()
const { subledgerSettlements: records, subledgerReport: report, subledgerQuery: filters,
  busy, connectionLost, subledgerLoading: loading, user, server, error } = storeToRefs(store)
const { can, openDocumentApproval, createSubledgerSettlement, changeSubledgerSettlementStatus,
  reverseSubledgerSettlement, querySubledger } = store
const disabled = computed(() => busy.value || connectionLost.value || loading.value)
const editing = ref(false)
const emptyForm = (): SubledgerSettlementInput => ({ from_line_id: 0, to_line_id: 0, amount: '', reference: '', reason: '' })
const form = ref(emptyForm())
const command = ref<{ record: SubledgerSettlement; action: 'post' | 'cancel' | 'reverse' } | null>(null)
const reason = ref('')
const smallStyle = { width: 'min(720px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
const columns = [{ key: 'id', title: '核销单号', width: '200' }, { key: 'party_name', title: '往来对象' },
  { key: 'from_document_reference', title: '贷方原单' }, { key: 'to_document_reference', title: '待结原单' },
  { key: 'amount', title: '核销净额（元）' }, { key: 'reference', title: '参考号' },
  { key: 'executed_at', title: '执行时间', width: '190' }, { key: 'status', title: '审批与执行', width: '190' },
  { key: 'actions', title: '操作', width: '330' }]
const filtered = computed(() => records.value.filter(row => [documentLabel(row), row.reference, row.party_name,
  row.from_document_reference, row.to_document_reference].join(' ').toLowerCase().includes(props.search.trim().toLowerCase())))
const sources = computed(() => (report.value?.rows ?? []).filter(row => Number(row.outstanding_amount) < 0))
const source = computed(() => sources.value.find(row => row.id === form.value.from_line_id))
const targets = computed(() => source.value ? (report.value?.rows ?? []).filter(row =>
  Number(row.outstanding_amount) > 0 && sameSubledgerScope(source.value!, row)) : [])
const sourceOptions = computed(() => sources.value.map(row => ({ value: row.id,
  label: `${row.party_name} · ${row.document_reference} · 可用 ${Math.abs(Number(row.outstanding_amount)).toFixed(2)} 元` })))
const targetOptions = computed(() => targets.value.map(row => ({ value: row.id,
  label: `${row.document_reference} · 待结 ${row.outstanding_amount} 元` })))
const actions = (row: SubledgerSettlement) => settlementActions(row, user.value?.permissions ?? [])
const caption = (row: SubledgerSettlement) => row.status === 'cancelled' ? '已取消草稿' : row.status === 'executed' ? '已执行'
  : ({ draft: '未送审', submitted: '审批中', approved: '已批准待执行', rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }[row.approval?.status ?? 'draft'])
watch(() => form.value.from_line_id, () => { form.value.to_line_id = 0 })
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}`, () => {
  editing.value = false; command.value = null; form.value = emptyForm(); reason.value = ''
}, { flush: 'sync' })
async function currentBalances(): Promise<void> {
  if (disabled.value) return
  filters.value = { to_date: new Date().toISOString().slice(0, 10), kind: null, party_id: null }
  await querySubledger()
}
function start(): void {
  if (disabled.value || !can('finance.record')) return
  form.value = emptyForm(); error.value = ''; editing.value = true
}
async function save(): Promise<void> {
  if (disabled.value || !source.value || !targets.value.some(row => row.id === form.value.to_line_id)) return
  if (await createSubledgerSettlement({ ...form.value })) { editing.value = false; form.value = emptyForm(); await querySubledger() }
}
function ask(row: SubledgerSettlement, action: 'post' | 'cancel' | 'reverse'): void {
  if (disabled.value || (action === 'reverse' ? !can('finance.reverse') || !canReverseSettlement(row, records.value)
    : !actions(row).includes(action))) return
  command.value = { record: row, action }; reason.value = ''; error.value = ''
}
async function confirm(): Promise<void> {
  const pending = command.value
  if (!pending || disabled.value || !reason.value.trim() || reason.value.trim().length > 200) return
  const current = records.value.find(row => row.id === pending.record.id)
  // 确认弹窗固定业务及审批版本，后台更新后必须重新核对。
  if (!current || current.version !== pending.record.version || current.approval?.version !== pending.record.approval?.version
    || (pending.action === 'reverse' ? !canReverseSettlement(current, records.value) : !actions(current).includes(pending.action))) {
    error.value = '核销或审批已变化，请关闭弹窗重新核对。'; return
  }
  const saved = pending.action === 'reverse' ? await reverseSubledgerSettlement(current.id, reason.value)
    : await changeSubledgerSettlementStatus(current, pending.action, reason.value)
  if (saved) { command.value = null; await querySubledger() }
}
</script>

<template>
  <p>将同一对象、同一控制科目和完整辅助组合的历史贷方余额用于另一张待结原单。草稿与批准不占用余额，执行后双方分别抵销；资金和总账金额保持原记录。</p>
  <div class="ledger-actions">
    <AppButton :disabled="disabled" @click="currentBalances">读取今日全部原单</AppButton>
    <AppButton v-if="can('finance.record')" variant="primary" :disabled="disabled || !report" @click="start">新增原单核销</AppButton>
  </div>
  <p v-if="report">可选原单依据截止 {{ report.to_date }} 的余额；服务端保存、审批与执行时均按最新余额校验。</p>
  <WorkspaceTable title="历史原单核销" :columns="columns" :data="filtered" :loading="loading" :min-table-width="1450">
    <template #cell-id="{ row }">{{ documentLabel(row) }}<small v-if="row.reverses_id">原核销 {{ relatedDocumentLabel(row, 'reverses') }}</small></template>
    <template #cell-executed_at="{ row }">{{ row.executed_at ? localTime(row.executed_at) : '尚未执行' }}</template>
    <template #cell-status="{ row }">{{ caption(row) }} · v{{ row.version }}</template>
    <template #cell-actions="{ row }"><div class="row-actions">
      <AppButton variant="text" :disabled="disabled" @click="openDocumentApproval({ document_type: 'SubledgerSettlement', document_id: row.id, intent: 'execute' })">核销审批与依据</AppButton>
      <AppButton v-for="action in actions(row)" :key="action" variant="text" :disabled="disabled" @click="ask(row, action)">{{ action === 'post' ? '执行核销' : '取消草稿' }}</AppButton>
      <AppButton v-if="can('finance.reverse') && canReverseSettlement(row, records)" variant="text" :disabled="disabled" @click="ask(row, 'reverse')">建立反向草稿</AppButton>
    </div></template>
    <template #empty>暂无历史原单核销。先读取余额，再选择贷方原单与待结原单。</template>
  </WorkspaceTable>
  <NModal :show="editing" preset="card" title="历史原单核销草稿" :style="smallStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!busy) editing = value }">
    <form class="ledger-editor" @submit.prevent="save">
      <label>贷方原单<WorkspaceSelect v-model="form.from_line_id" :options="sourceOptions" :disabled="disabled" /></label>
      <p v-if="source">{{ source.account_code }} · {{ auxiliaryText(source.auxiliary) }}</p>
      <label>待结原单<WorkspaceSelect v-model="form.to_line_id" :options="targetOptions" :disabled="disabled || !source" /></label>
      <p v-if="source && !targets.length">当前查询中没有同一完整归属的待结原单，可先读取今日全部原单。</p>
      <label>核销金额（人民币）<AppInput v-model="form.amount" required inputmode="decimal" pattern="[0-9]{1,13}(\.[0-9]{1,2})?" :disabled="disabled" /></label>
      <label>参考号<AppInput v-model.trim="form.reference" required maxlength="100" :disabled="disabled" /></label>
      <label>核销依据<AppInput v-model.trim="form.reason" required maxlength="200" :disabled="disabled" /></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <AppButton type="submit" variant="primary" :disabled="disabled || !form.to_line_id || !form.amount || !form.reference || !form.reason">保存核销草稿</AppButton>
    </form>
  </NModal>
  <NModal :show="!!command" preset="card" title="核销操作" :style="smallStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!value && !busy) command = null }">
    <form class="ledger-editor" @submit.prevent="confirm">
      <p v-if="command">{{ documentLabel(command.record) }} · {{ command.record.from_document_reference }} → {{ command.record.to_document_reference }} · {{ command.record.amount }} 元。</p>
      <p v-if="command?.action === 'reverse'">保存等额反向草稿，重新批准并执行后恢复双方余额；原核销保留。</p>
      <label>操作依据<AppInput v-model.trim="reason" required maxlength="200" :disabled="disabled" /></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <AppButton type="submit" variant="primary" :disabled="disabled || !reason">{{ command?.action === 'reverse' ? '保存反向草稿' : command?.action === 'post' ? '执行核销' : '取消草稿' }}</AppButton>
    </form>
  </NModal>
</template>
