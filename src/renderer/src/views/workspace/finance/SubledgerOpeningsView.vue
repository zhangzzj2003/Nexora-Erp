<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NDatePicker, NModal } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { datePickerString, vDateField } from '../../../utils/date-field'
import { displayError, localTime } from '../../../utils/formatters'
import type { OpeningBalanceAction, SubledgerOpening, SubledgerPayment, SubledgerBalanceRow, SubledgerPaymentInput } from '../../../../../shared/erp-api'
import { auxiliaryText } from './auxiliary-display'
import { openingActionLabels, openingStatusLabels } from './opening-display'
import { subledgerActions, subledgerKindLabels } from './subledger-display'
import SubledgerEditor from './SubledgerEditor.vue'
import SubledgerEvidence from './SubledgerEvidence.vue'
import './ledger-metadata.css'
import './journals.css'
import './subledger.css'

const store = usePiniaAppStore()
const { subledgerOpenings: records, subledgerPayments: payments, subledgerQuery: filters,
  subledgerReport: report, subledgerCheck: check, subledgerChanges: changes, subledgerLoading: loading,
  subledgerError: error, error: operationError, busy, connectionLost, user } = storeToRefs(store)
const { can, loadSubledger, querySubledger, exportSubledger, editSubledger, loadSubledgerDetail,
  clearSubledgerDetail, changeSubledgerStatus, createSubledgerPayment, reverseSubledgerPayment } = store
const mode = ref<'balances' | 'plans' | 'payments'>('balances')
const editing = ref(false)
const preparing = ref(false)
const detail = ref<SubledgerOpening | null>(null)
const detailLoading = ref(false)
let detailTicket = 0
const source = ref<SubledgerBalanceRow | null>(null)
const command = ref<{ record: SubledgerOpening; action: OpeningBalanceAction } | null>(null)
const reversal = ref<SubledgerPayment | null>(null)
const reason = ref('')
const payment = ref<SubledgerBalanceRow | null>(null)
const paymentForm = ref<SubledgerPaymentInput>({ line_id: 0, action: 'settlement', amount: '', reference: '', reason: '' })
const modalStyle = { width: 'min(1100px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
const smallStyle = { width: 'min(600px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
const disabled = computed(() => busy.value || connectionLost.value || loading.value)
const active = computed(() => records.value.some(item => item.active_key === 1))
const partyOptions = computed(() => {
  const parties = new Map<number, string>()
  records.value.flatMap(item => item.lines).filter(item => item.kind === filters.value.kind)
    .forEach(item => parties.set(item.party_id, item.party_name))
  return [{ value: null as number | null, label: '全部往来对象' }, ...[...parties].map(([value, label]) => ({ value, label }))]
})
const balances = [{ key: 'kind', title: '类别' }, { key: 'party_name', title: '往来对象', width: '200' },
  { key: 'document_reference', title: '原单编号', width: '170' }, { key: 'document_date', title: '原单日期' },
  { key: 'auxiliary', title: '完整辅助快照', width: '300' }, { key: 'opening_amount', title: '期初（元）' },
  { key: 'settled_amount', title: '资金净额（元）' }, { key: 'outstanding_amount', title: '未结（元）' }, { key: 'actions', title: '核对 / 登记', width: '190' }]
// 方案与资金记录沿用参考号检索，同时支持稳定业务单号和内部 ID。
const documentQuery = ref('')
const matchesDocument = (row: object) => [documentSearch(row), ...Object.values(row).filter(value => typeof value === 'string' || typeof value === 'number')].join(' ').toLowerCase().includes(documentQuery.value.trim().toLowerCase())
const filteredPlans = computed(() => records.value.filter(matchesDocument))
const filteredFunds = computed(() => payments.value.filter(matchesDocument))
const plans = [{ key: 'id', title: '方案' }, { key: 'effective_date', title: '启用日' }, { key: 'reference', title: '依据编号' },
  { key: 'count', title: '未结单据数' }, { key: 'status', title: '状态' }, { key: 'actions', title: '操作', width: '330' }]
const funds = [{ key: 'id', title: '记录' }, { key: 'kind', title: '类别' }, { key: 'party_name', title: '往来快照', width: '180' },
  { key: 'document_reference', title: '原单编号' }, { key: 'action', title: '资金操作' }, { key: 'amount', title: '净额（元）' },
  { key: 'reference', title: '参考号' }, { key: 'created_at', title: '登记时间', width: '190' },
  { key: 'created_by_name', title: '操作者' }, { key: 'actions', title: '操作' }]
const paymentLabels = { settlement: '收款 / 付款', refund: '退款 / 收退', reversal: '冲销登记' }
function paymentLabel(row: SubledgerPayment | SubledgerPaymentInput): string {
  const kind = 'kind' in row ? row.kind : payment.value?.kind
  return row.action === 'settlement' ? (kind === 'receivable' ? '客户收款' : '供应商付款')
    : row.action === 'refund' ? (kind === 'receivable' ? '退给客户' : '收供应商退款') : paymentLabels.reversal
}
function actions(item: SubledgerOpening): OpeningBalanceAction[] {
  return subledgerActions(item, user.value?.permissions ?? [], user.value?.id ?? 0)
}
function alreadyReversed(row: SubledgerPayment): boolean {
  return row.action === 'reversal' || payments.value.some(item => item.reverses_id === row.id)
}
watch(() => filters.value.kind, () => { filters.value.party_id = null })
watch(filters, () => { source.value = null }, { deep: true, flush: 'sync' })
function closeDetail(): void { detailTicket++; detailLoading.value = false; detail.value = null; clearSubledgerDetail() }
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => {
  editing.value = false; command.value = null; reversal.value = null; payment.value = null; source.value = null; closeDetail()
}, { flush: 'sync' })
watch(connectionLost, () => { source.value = null; closeDetail() }, { flush: 'sync' })
onMounted(async () => {
  if (!filters.value.to_date) filters.value.to_date = new Date().toISOString().slice(0, 10)
  if (await loadSubledger() && records.value.some(item => item.status === 'confirmed' && item.active_key === 1)) await querySubledger()
})
onUnmounted(closeDetail)
async function reload(): Promise<void> { source.value = null; closeDetail(); if (await loadSubledger() && mode.value === 'balances') await querySubledger() }
async function edit(item?: SubledgerOpening): Promise<void> {
  if (preparing.value || disabled.value) return
  preparing.value = true; operationError.value = ''
  try { if (await editSubledger(item)) editing.value = true }
  catch (cause) { operationError.value = displayError(cause) }
  finally { preparing.value = false }
}
async function inspect(item: SubledgerOpening): Promise<void> {
  closeDetail(); const ticket = ++detailTicket; detail.value = item; detailLoading.value = true
  await loadSubledgerDetail(item)
  if (ticket === detailTicket) detailLoading.value = false
}
function ask(item: SubledgerOpening, action: OpeningBalanceAction): void {
  command.value = { record: item, action }; reversal.value = null; reason.value = ''; operationError.value = ''
}
function askReverse(item: SubledgerPayment): void {
  reversal.value = item; command.value = null; reason.value = ''; operationError.value = ''
}
async function confirm(): Promise<void> {
  if (disabled.value || !reason.value.trim()) return
  const saved = command.value ? await changeSubledgerStatus(command.value.record, command.value.action, reason.value)
    : reversal.value ? await reverseSubledgerPayment(reversal.value.id, reason.value) : false
  if (saved) { command.value = null; reversal.value = null; closeDetail() }
}
function register(row: SubledgerBalanceRow): void {
  payment.value = row; operationError.value = ''
  paymentForm.value = { line_id: row.id, action: Number(row.outstanding_amount) > 0 ? 'settlement' : 'refund', amount: '', reference: '', reason: '' }
}
async function savePayment(): Promise<void> {
  if (disabled.value || !payment.value) return
  if (await createSubledgerPayment({ ...paymentForm.value })) { payment.value = null; source.value = null; await querySubledger() }
}
</script>

<template>
  <section class="stack ledger-metadata-page subledger-page">
    <div class="ledger-actions" aria-label="分户期初内容">
      <AppButton :variant="mode === 'balances' ? 'primary' : 'secondary'" @click="mode = 'balances'">未结余额</AppButton>
      <AppButton :variant="mode === 'plans' ? 'primary' : 'secondary'" @click="mode = 'plans'">分户方案</AppButton>
      <AppButton :variant="mode === 'payments' ? 'primary' : 'secondary'" @click="mode = 'payments'">资金记录</AppButton>
      <AppButton :disabled="disabled" @click="reload">{{ loading ? '正在读取…' : '重新读取' }}</AppButton>
    </div>
    <label v-if="mode !== 'balances'">搜索单据<AppInput v-model.trim="documentQuery" placeholder="单号、参考号或原 ID" /></label>
    <p v-if="connectionLost" role="status">连接已断开，查询和写入暂停；未保存的输入保留，恢复连接后请重新读取。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="operationError && !editing && !command && !reversal && !payment" role="alert">{{ operationError }}</p>
    <template v-if="mode === 'balances'">
      <form class="ledger-editor" @submit.prevent="querySubledger">
        <div class="form-grid">
          <label>截止日（按 UTC）<NDatePicker :formatted-value="filters.to_date || null" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true }" :disabled="disabled" @update:formatted-value="value => { filters.to_date = datePickerString(value) }" /></label>
          <label>往来类别<WorkspaceSelect v-model="filters.kind" :options="[{ value: null, label: '全部类别' }, { value: 'receivable', label: '客户应收' }, { value: 'payable', label: '供应商应付' }]" :disabled="disabled" /></label>
          <label>往来对象<WorkspaceSelect v-model="filters.party_id" :options="partyOptions" :disabled="disabled || !filters.kind" /></label>
        </div>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="disabled || !filters.to_date">{{ loading ? '正在核对…' : '查询未结余额' }}</AppButton>
          <AppButton type="button" :disabled="!report || disabled" @click="exportSubledger">导出 CSV</AppButton>
        </div>
      </form>
      <p>仅核对导入的历史未结单据；现有订单余额请在“应收应付”查看。正数为待收 / 待付，负数为可退 / 可收退。收付款登记不代替凭证审核过账。</p>
      <template v-if="report">
        <p>{{ report.opening ? `${report.opening.reference} · 启用日 ${report.opening.effective_date}` : '尚无已启用分户期初' }} · 截止 {{ report.to_date }}（UTC）· 生成于 {{ localTime(report.generated_at) }} · 人民币</p>
        <p v-for="kind in (['receivable', 'payable'] as const)" :key="kind" class="subledger-totals">{{ subledgerKindLabels[kind] }}：期初 {{ report.totals[kind].opening_amount }}；资金净额 {{ report.totals[kind].settled_amount }}；未结 {{ report.totals[kind].outstanding_amount }} 元</p>
      </template>
      <WorkspaceTable class="journal-list-table" title="历史单据未结余额" :columns="balances" :data="report?.rows ?? []" :min-table-width="1400" :loading="loading">
        <template #cell-kind="{ row }">{{ subledgerKindLabels[row.kind] }}</template>
        <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
        <template #cell-actions="{ row }"><div class="row-actions">
          <AppButton variant="text" :disabled="disabled" @click="source = row">来源与资金</AppButton>
          <AppButton v-if="can('finance.record')" variant="text" :disabled="disabled || Number(row.outstanding_amount) === 0" @click="register(row)">登记资金</AppButton>
        </div></template>
        <template #empty>{{ !report ? '选择截止日后查询。没有已确认方案时，请先查看分户方案。' : report.opening ? '当前条件下没有历史未结单据。已结清单据仍保留在结果中。' : '尚无已启用分户期初；可在分户方案中逐笔建立历史未结来源。' }}</template>
      </WorkspaceTable>
    </template>
    <template v-else-if="mode === 'plans'">
      <p>先确认总账期初，再逐对象及完整辅助组合核对分户。首次启用前不得已有业务往来来源、订单资金登记或已过账凭证；错误方案可取消后重建。</p>
      <WorkspaceTable class="journal-list-table" title="分户期初方案" :show-title="false" :columns="plans" :data="filteredPlans" :min-table-width="1030" :loading="loading">
        <template #actions><AppButton v-if="can('subledger_opening.create')" variant="primary" :disabled="disabled || active || preparing" @click="edit()">{{ preparing ? '正在读取…' : '新增分户方案' }}</AppButton></template>
        <template #cell-id="{ row }">{{ documentLabel(row) }}</template>
        <template #cell-count="{ row }">{{ row.lines.length }}</template>
        <template #cell-status="{ row }">{{ openingStatusLabels[row.status] }} · v{{ row.version }}</template>
        <template #cell-actions="{ row }"><div class="row-actions">
          <AppButton variant="text" :disabled="disabled" @click="inspect(row)">核对与审计</AppButton>
          <AppButton v-if="can('subledger_opening.create') && ['draft', 'rejected'].includes(row.status)" variant="text" :disabled="disabled || preparing" @click="edit(row)">编辑</AppButton>
          <AppButton v-for="action in actions(row)" :key="action" variant="text" :disabled="disabled" @click="ask(row, action)">{{ openingActionLabels[action] }}</AppButton>
        </div></template>
        <template #empty>暂无分户方案。请先独立审核并确认总账期初，再建立历史未结明细。</template>
      </WorkspaceTable>
    </template>
    <template v-else>
      <p>历史单据的资金登记与冲销全部保留，时间显示为本地时间。金额符号用于未结余额计算；退款为负，冲销追加相反金额。</p>
      <AppButton v-if="can('journal.view') && can('business_journal.view')" :disabled="disabled" @click="store.navigateToRoute('journals')">到凭证管理生成业务凭证</AppButton>
      <WorkspaceTable class="journal-list-table" title="分户资金记录" :columns="funds" :data="filteredFunds" :min-table-width="1350" :loading="loading">
        <template #cell-kind="{ row }">{{ subledgerKindLabels[row.kind] }}</template>
        <template #cell-id="{ row }">{{ documentLabel(row) }}</template>
        <template #cell-action="{ row }">{{ paymentLabel(row) }}{{ row.reverses_id ? ` · 原记录 ${relatedDocumentLabel(row, 'reverses')}` : '' }}</template>
        <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
        <template #cell-actions="{ row }"><AppButton v-if="can('finance.reverse') && !alreadyReversed(row)" variant="text" :disabled="disabled" @click="askReverse(row)">冲销</AppButton><span v-else>{{ alreadyReversed(row) ? '已保留冲销关系' : '只读' }}</span></template>
        <template #empty>暂无历史单据的资金登记。在未结余额中选择单据登记收付款。</template>
      </WorkspaceTable>
    </template>

    <NModal :show="editing" preset="card" :title="store.subledgerForm.id === null ? '新增分户期初' : '编辑分户期初'" :style="modalStyle" :mask-closable="false" :close-on-esc="!busy" :closable="!busy" @update:show="value => { if (!busy) editing = value }">
      <SubledgerEditor @saved="editing = false; mode = 'plans'" />
    </NModal>
    <NModal :show="!!detail" preset="card" title="分户核对与审计" :style="modalStyle" @update:show="value => { if (!value) closeDetail() }">
      <p v-if="error" role="alert">{{ error }}</p>
      <SubledgerEvidence v-if="detail" :record="detail" :check="check" :changes="changes" :loading="detailLoading" />
    </NModal>
    <NModal :show="!!source" preset="card" title="历史来源与资金" :style="modalStyle" @update:show="value => { if (!value) source = null }">
      <div v-if="source" class="ledger-editor">
        <p>{{ subledgerKindLabels[source.kind] }} · {{ source.party_name }} · 原单 {{ source.document_reference }} · {{ source.document_date }}</p>
        <p>控制科目 {{ source.account_code }} · {{ source.account_name }}；{{ auxiliaryText(source.auxiliary) }}</p>
        <p>截至 {{ report?.to_date }}（UTC）：期初 {{ source.opening_amount }}；资金净额 {{ source.settled_amount }}；未结 {{ source.outstanding_amount }} 元。</p>
        <WorkspaceTable title="截止日内资金记录" :columns="funds.filter(item => item.key !== 'actions')" :data="source.payments" :min-table-width="1250">
          <template #cell-kind="{ row }">{{ subledgerKindLabels[row.kind] }}</template>
          <template #cell-id="{ row }">{{ documentLabel(row) }}</template>
        <template #cell-action="{ row }">{{ paymentLabel(row) }}{{ row.reverses_id ? ` · 原记录 ${relatedDocumentLabel(row, 'reverses')}` : '' }}</template>
          <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
          <template #empty>截至所选 UTC 日期没有资金登记。</template>
        </WorkspaceTable>
        <p v-for="row in source.payments" :key="row.id">资金 {{ documentLabel(row) }} · 依据：{{ row.note }} · {{ auxiliaryText(row.auxiliary) }}</p>
      </div>
    </NModal>
    <NModal :show="!!command || !!reversal" preset="card" :title="command ? openingActionLabels[command.action] : '冲销分户资金'" :style="smallStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!value && !busy) { command = null; reversal = null } }">
      <form class="ledger-editor" @submit.prevent="confirm">
        <p v-if="command">方案 {{ command.record.reference }} · 版本 {{ command.record.version }}。提交、审核与确认均须逐组合一致；建单、编辑或提交人员不能审核。</p>
        <p v-if="command?.action === 'reverse'">仅未过账且从未登记分户资金的期初可撤销，即使资金已冲销也不能重设历史。</p>
        <p v-if="reversal">原记录 {{ documentLabel(reversal) }} · {{ reversal.party_name }} · {{ reversal.document_reference }} · {{ reversal.amount }} 元。追加等额反向记录，保留原始记录；相应凭证更正仍须在凭证管理处理。</p>
        <label>依据 / 原因<AppInput v-model.trim="reason" required maxlength="200" :disabled="disabled" /></label>
        <p v-if="operationError" role="alert">{{ operationError }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !reason">{{ busy ? '正在处理…' : command ? openingActionLabels[command.action] : '追加冲销记录' }}</AppButton>
      </form>
    </NModal>
    <NModal :show="!!payment" preset="card" title="登记历史单据资金" :style="smallStyle" :mask-closable="false" :closable="!busy" :close-on-esc="!busy" @update:show="value => { if (!value && !busy) payment = null }">
      <form v-if="payment" class="ledger-editor" @submit.prevent="savePayment">
        <p>{{ payment.party_name }} · 原单 {{ payment.document_reference }}。所查截止日未结 {{ payment.outstanding_amount }} 元；服务端按登记时最新余额校验，历史查询金额仅供参考。</p>
        <p>{{ paymentLabel(paymentForm) }}；登记时间由服务端记录（UTC），不能倒签。金额填正数；超出可收付或可退金额时会拒绝。</p>
        <label>金额（人民币）<AppInput v-model="paymentForm.amount" required inputmode="decimal" pattern="[0-9]{1,12}(\.[0-9]{1,2})?" :disabled="disabled" /></label>
        <label>资金参考号<AppInput v-model.trim="paymentForm.reference" required maxlength="80" :disabled="disabled" /></label>
        <label>登记依据<AppInput v-model.trim="paymentForm.reason" required maxlength="200" :disabled="disabled" /></label>
        <p v-if="operationError" role="alert">{{ operationError }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !paymentForm.amount || !paymentForm.reference || !paymentForm.reason">{{ busy ? '正在登记…' : paymentLabel(paymentForm) }}</AppButton>
      </form>
    </NModal>
  </section>
</template>
