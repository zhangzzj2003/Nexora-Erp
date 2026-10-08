<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse, NModal } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import type { SubledgerOrderSettlement, SubledgerOrderSettlementInput } from '../../../../../shared/erp-api'
import { amountText, cents, directionLabels, matchingGroup, matchingLimit } from './subledger-order-display'
import { settlementActions, canReverseSettlement } from './subledger-settlement-display'
import { auxiliaryText } from './auxiliary-display'
import { localTime } from '../../../utils/formatters'

const props = defineProps<{ search: string }>()
const store = usePiniaAppStore()
const { subledgerOrderSettlements: records, subledgerOrderOptions: options, subledgerOrderLoading: loading,
  subledgerOrderError: readError, busy, connectionLost, user, server, error } = storeToRefs(store)
const { can, loadSubledgerOrders, openDocumentApproval, createSubledgerOrderSettlement,
  changeSubledgerOrderSettlementStatus, reverseSubledgerOrderSettlement } = store
const disabled = computed(() => busy.value || connectionLost.value || loading.value)
const emptyForm = (): SubledgerOrderSettlementInput => ({ opening_line_id: 0, order_id: 0,
  direction: 'historical_credit', amount: '', reference: '', reason: '' })
const form = ref(emptyForm())
const editing = ref(false)
const detail = ref<SubledgerOrderSettlement | null>(null)
const command = ref<{ row: SubledgerOrderSettlement; action: 'post' | 'cancel' | 'reverse' } | null>(null)
const reason = ref('')
const modalStyle = { width: 'min(800px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
const columns = [{ key: 'id', title: '核销单号', width: '190' }, { key: 'party_name', title: '往来对象' },
  { key: 'direction', title: '方向', width: '180' }, { key: 'document_reference', title: '历史原单' },
  { key: 'order_id', title: '订单号', width: '190' }, { key: 'amount', title: '核销净额（元）' },
  { key: 'executed_at', title: '执行时间', width: '190' }, { key: 'status', title: '审批与执行', width: '190' },
  { key: 'actions', title: '操作', width: '370' }]
const filtered = computed(() => records.value.filter(row => [String(row.id), documentLabel(row), row.reference, row.party_name,
  row.document_reference, row.order_document_no, directionLabels[row.direction]].join(' ').toLowerCase().includes(props.search.trim().toLowerCase())))
const lines = computed(() => (options.value?.lines ?? []).filter(row => form.value.direction === 'historical_credit'
  ? cents(row.outstanding_amount) < 0n : cents(row.outstanding_amount) > 0n))
const line = computed(() => lines.value.find(row => row.id === form.value.opening_line_id))
const orders = computed(() => line.value ? (options.value?.orders ?? []).filter(row => matchingLimit(line.value!, row, form.value.direction) > 0n) : [])
const order = computed(() => orders.value.find(row => row.order_id === form.value.order_id && row.kind === line.value?.kind))
const group = computed(() => line.value && order.value ? matchingGroup(line.value, order.value) : undefined)
const limit = computed(() => line.value && order.value ? matchingLimit(line.value, order.value, form.value.direction) : 0n)
const lineOptions = computed(() => lines.value.map(row => ({ value: row.id,
  label: `${row.party_name} · ${row.document_reference} · ${row.account_code} · 未结 ${row.outstanding_amount} 元` })))
const orderOptions = computed(() => orders.value.map(row => ({ value: row.order_id,
  label: `${row.order_document_no || '#' + row.order_id} · 可核销 ${amountText(matchingLimit(line.value!, row, form.value.direction))} 元` })))
const blockers = computed(() => (options.value?.orders ?? []).filter(row => row.blockers.length))
const actions = (row: SubledgerOrderSettlement) => can('subledger_order_settlement.view') ? settlementActions(row, user.value?.permissions ?? []) : []
const caption = (row: SubledgerOrderSettlement) => row.status === 'cancelled' ? '已取消草稿' : row.status === 'executed' ? '已执行'
  : ({ draft: '未送审', submitted: '审批中', approved: '已批准待执行', rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }[row.approval?.status ?? 'draft'])
watch(() => form.value.direction, () => { form.value.opening_line_id = 0; form.value.order_id = 0 })
watch(() => form.value.opening_line_id, () => { form.value.order_id = 0 })
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}`, () => {
  editing.value = false; detail.value = null; command.value = null; form.value = emptyForm(); reason.value = ''
}, { flush: 'sync' })
onMounted(loadSubledgerOrders)
function start(): void {
  if (disabled.value || !can('subledger_order_settlement.view') || !can('finance.record')) return
  form.value = emptyForm(); error.value = ''; editing.value = true
}
async function save(): Promise<void> {
  if (disabled.value || !line.value || !order.value || cents(form.value.amount) <= 0n || cents(form.value.amount) > limit.value) return
  if (await createSubledgerOrderSettlement({ ...form.value })) { editing.value = false; form.value = emptyForm() }
}
function ask(row: SubledgerOrderSettlement, action: 'post' | 'cancel' | 'reverse'): void {
  if (disabled.value || !can('subledger_order_settlement.view') || (action === 'reverse'
    ? !can('finance.reverse') || !canReverseSettlement(row, records.value) : !actions(row).includes(action))) return
  command.value = { row, action }; reason.value = ''; error.value = ''
}
async function confirm(): Promise<void> {
  const pending = command.value
  if (!pending || disabled.value || !reason.value.trim() || reason.value.trim().length > 200) return
  const current = records.value.find(row => row.id === pending.row.id)
  // 弹窗固定业务及审批版本，刷新后必须重新核对原决定。
  if (!current || current.version !== pending.row.version || current.approval?.version !== pending.row.approval?.version
    || (pending.action === 'reverse' ? !can('finance.reverse') || !canReverseSettlement(current, records.value) : !actions(current).includes(pending.action))) {
    error.value = '核销或审批已变化，请关闭弹窗重新核对。'; return
  }
  const saved = pending.action === 'reverse' ? await reverseSubledgerOrderSettlement(current.id, reason.value)
    : await changeSubledgerOrderSettlementStatus(current, pending.action, reason.value)
  if (saved) command.value = null
}
</script>

<template>
  <p>历史贷方可抵订单待结款，订单贷方也可抵历史待结款。双方必须为同一对象、控制科目及完整辅助组合；草稿和批准不占额度，执行才更新余额。</p>
  <div class="ledger-actions">
    <AppButton :disabled="disabled" @click="loadSubledgerOrders">{{ loading ? '正在核对…' : '读取最新核销依据' }}</AppButton>
    <AppButton v-if="can('finance.record')" variant="primary" :disabled="disabled || !options?.active" @click="start">新增历史与订单核销</AppButton>
  </div>
  <p v-if="options && !options.active">请先确认并启用历史分户方案。</p>
  <p v-if="readError" role="alert">{{ readError }} 请重新读取核销依据。</p>
  <NCollapse v-if="blockers.length"><AppCollapseItem name="blockers" :title="`${blockers.length} 张订单暂不可核销，查看缺少的依据`">
    <p v-for="row in blockers" :key="`${row.kind}:${row.order_id}`">{{ row.order_document_no || '#' + row.order_id }} · {{ row.party_name }}：{{ row.blockers.join('；') }}。请先核对业务来源并完成凭证过账。</p>
  </AppCollapseItem></NCollapse>
  <WorkspaceTable title="历史与订单核销" :columns="columns" :data="filtered" :loading="loading" :min-table-width="1700">
    <template #cell-id="{ row }">{{ documentLabel(row) }}<small v-if="row.reverses_id">原核销 {{ relatedDocumentLabel(row, 'reverses') }}</small></template>
    <template #cell-direction="{ row }">{{ directionLabels[row.direction as keyof typeof directionLabels] }}</template>
    <template #cell-order_id="{ row }">{{ relatedDocumentLabel(row, 'order') }}</template>
    <template #cell-executed_at="{ row }">{{ row.executed_at ? localTime(row.executed_at) : '尚未执行' }}</template>
    <template #cell-status="{ row }">{{ caption(row) }} · v{{ row.version }}</template>
    <template #cell-actions="{ row }"><div class="row-actions">
      <AppButton variant="text" :disabled="disabled" @click="detail = row">组合与凭证依据</AppButton>
      <AppButton variant="text" :disabled="disabled" @click="openDocumentApproval({ document_type: 'SubledgerOrderSettlement', document_id: row.id, intent: 'execute' })">核销审批</AppButton>
      <AppButton v-for="action in actions(row)" :key="action" variant="text" :disabled="disabled" @click="ask(row, action)">{{ action === 'post' ? '执行核销' : '取消草稿' }}</AppButton>
      <AppButton v-if="can('finance.reverse') && canReverseSettlement(row, records)" variant="text" :disabled="disabled" @click="ask(row, 'reverse')">建立反向草稿</AppButton>
    </div></template>
    <template #empty>{{ options && !options.active ? '先启用历史分户方案，再核对历史原单与订单。' : '暂无核销记录。读取最新依据后，可建立双向核销草稿。' }}</template>
  </WorkspaceTable>
  <NModal :show="editing" preset="card" title="历史与订单核销草稿" :style="modalStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!busy) editing = value }">
    <form class="ledger-editor" @submit.prevent="save">
      <label>核销方向<WorkspaceSelect v-model="form.direction" :options="[{ value: 'historical_credit', label: directionLabels.historical_credit }, { value: 'order_credit', label: directionLabels.order_credit }]" :disabled="disabled" /></label>
      <label>历史原单<WorkspaceSelect v-model="form.opening_line_id" :options="lineOptions" :disabled="disabled" /></label>
      <p v-if="line">{{ line.account_code }} · {{ auxiliaryText(line.auxiliary) }}</p>
      <label>同归属订单<WorkspaceSelect v-model="form.order_id" :options="orderOptions" :disabled="disabled || !line" /></label>
      <p v-if="line && !orders.length">没有同科目、同完整辅助且方向相反的可用订单，请核对订单余额及过账凭证。</p>
      <p v-if="order && group">历史未结 {{ line?.outstanding_amount }} 元；订单未结 {{ order.outstanding_amount }} 元；匹配组合未结 {{ group.outstanding_amount }} 元。当前最多核销 {{ amountText(limit) }} 元，执行前还会重核。</p>
      <NCollapse v-if="group"><AppCollapseItem name="evidence" :title="`查看匹配组合的 ${group.evidence.length} 项过账及核销依据`">
        <p v-for="(item, index) in group.evidence" :key="index">{{ item.type === 'journal' ? `凭证 #${item.journal_id} · 订单 #${item.order_id} · ${item.source_key} · ${item.journal_date}` : `订单间核销 #${item.transfer_id}` }} · 分配 {{ item.amount }} 元</p>
      </AppCollapseItem></NCollapse>
      <label>核销金额（人民币）<AppInput v-model="form.amount" required inputmode="decimal" pattern="[0-9]{1,13}(\.[0-9]{1,2})?" :disabled="disabled" /></label>
      <p v-if="form.amount && cents(form.amount) > limit" role="alert">金额超过当前可用额度，请核对三项余额。</p>
      <label>参考号<AppInput v-model.trim="form.reference" required maxlength="100" :disabled="disabled" /></label>
      <label>核销依据<AppInput v-model.trim="form.reason" required maxlength="200" :disabled="disabled" /></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <AppButton type="submit" variant="primary" :disabled="disabled || !order || cents(form.amount) <= 0n || cents(form.amount) > limit || !form.reference || !form.reason">保存核销草稿</AppButton>
    </form>
  </NModal>
  <NModal :show="!!detail" preset="card" title="核销组合与凭证依据" :style="modalStyle" @update:show="value => { if (!value) detail = null }">
    <template v-if="detail"><p>{{ documentLabel(detail) }} · {{ detail.party_name }} · {{ detail.document_reference }} ↔ {{ relatedDocumentLabel(detail, 'order') }}</p>
      <p>{{ detail.account_code }} · {{ detail.account_name }} · {{ auxiliaryText(detail.auxiliary) }}</p>
      <p>参考号 {{ detail.reference }} · {{ detail.reason }}</p>
      <p v-for="(item, index) in detail.order_evidence" :key="index">{{ item.type === 'journal' ? `凭证 #${item.journal_id} · 订单 #${item.order_id} · ${item.source_key} · ${item.journal_date}` : `订单间核销 #${item.transfer_id}` }} · 分配 {{ item.amount }} 元</p>
    </template>
  </NModal>
  <NModal :show="!!command" preset="card" title="核销操作" :style="modalStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!value && !busy) command = null }">
    <form class="ledger-editor" @submit.prevent="confirm">
      <p v-if="command">{{ documentLabel(command.row) }} · {{ command.row.document_reference }} ↔ {{ relatedDocumentLabel(command.row, 'order') }} · {{ command.row.amount }} 元。</p>
      <p v-if="command?.action === 'reverse'">原记录保留。等额反向草稿须重新批准、执行后才恢复双方余额；撤销后才可冲销原凭证依据。</p>
      <label>操作依据<AppInput v-model.trim="reason" required maxlength="200" :disabled="disabled" /></label>
      <p v-if="error" role="alert">{{ error }}</p>
      <AppButton type="submit" variant="primary" :disabled="disabled || !reason">{{ command?.action === 'reverse' ? '保存反向草稿' : command?.action === 'post' ? '执行核销' : '取消草稿' }}</AppButton>
    </form>
  </NModal>
</template>
