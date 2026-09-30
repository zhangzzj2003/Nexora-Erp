<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker } from 'naive-ui'
import { datePickerString, vDateField } from '../../../utils/date-field'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import type { Journal, JournalAction, JournalLineInput } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { displayError } from '../../../utils/formatters'
import JournalHistory from './JournalHistory.vue'
import BusinessJournalPanel from './BusinessJournalPanel.vue'
import BusinessSourceEvidence from './BusinessSourceEvidence.vue'
import ProfitTransferPanel from './ProfitTransferPanel.vue'
import ProfitTransferEvidence from './ProfitTransferEvidence.vue'
import { journalActionLabels, journalStatusLabels, journalTotals } from './journal-display'
import './ledger-metadata.css'
import './journals.css'

const store = usePiniaAppStore()
const {
  journals,
  journalOptions,
  journalForm: form,
  busy,
  connectionLost,
  user,
  error
} = storeToRefs(store)
const { can, editJournal, saveJournal, changeJournalStatus, reverseJournal, loadJournalChanges } =
  store
const query = ref('')
const status = ref('')
const showBusiness = ref(false)
const showProfit = ref(false)
const showForm = ref(false)
const opening = ref(false)
const detailId = ref<number | null>(null)
const detail = computed(() => journals.value.find((item) => item.id === detailId.value))
const command = ref<{ record: Journal; action: JournalAction | 'reverse' } | null>(null)
const reason = ref('')
const reverseReference = ref('')
const reverseDate = ref('')
const rows = computed(() =>
  journals.value.filter(
    (item) =>
      (!status.value || item.status === status.value) &&
      [item.reference, item.note, item.created_by_name, String(item.id)]
        .join(' ')
        .toLowerCase()
        .includes(query.value.trim().toLowerCase())
  )
)
const totals = computed(() => journalTotals(form.value.lines))
const columns = [
  { key: 'id', title: '凭证号' },
  { key: 'journal_date', title: '凭证日期' },
  { key: 'reference', title: '依据编号' },
  { key: 'total_debit', title: '借贷各（人民币）' },
  { key: 'status', title: '状态' },
  { key: 'source', title: '来源' },
  { key: 'actions', title: '操作' }
]
const lineColumns = [
  { key: 'position', title: '序号' },
  { key: 'account', title: '科目快照' },
  { key: 'summary', title: '摘要' },
  { key: 'debit', title: '借方（元）' },
  { key: 'credit', title: '贷方（元）' }
]
const editColumns = [
  { key: 'position', title: '序号', width: '70' },
  { key: 'account_id', title: '科目', width: '230' },
  { key: 'summary', title: '摘要', width: '260' },
  { key: 'debit', title: '借方（元）', width: '160' },
  { key: 'credit', title: '贷方（元）', width: '160' },
  { key: 'auxiliary', title: '辅助核算', width: '250' },
  { key: 'actions', title: '操作', width: '90' }
]
const lineNumber = (row: JournalLineInput): number => form.value.lines.indexOf(row) + 1
const relatedStatus = (id: number): string => {
  const item = journals.value.find((record) => record.id === id)
  return item ? journalStatusLabels[item.status] : '请刷新列表'
}
const actionable = (item: Journal): JournalAction[] => {
  const actions: JournalAction[] = []
  if (['draft', 'rejected'].includes(item.status) && can('journal.submit')) actions.push('submit')
  if (
    item.status === 'submitted' &&
    can('journal.review') &&
    !item.author_ids.includes(user.value?.id ?? 0)
  )
    actions.push('approve', 'reject')
  if (item.status === 'approved' && can('journal.post')) actions.push('post')
  if (item.status !== 'posted' && item.status !== 'cancelled' && can('journal.cancel'))
    actions.push('cancel')
  return actions
}
async function edit(item?: Journal): Promise<void> {
  if (opening.value || busy.value || connectionLost.value) return
  opening.value = true
  try {
    await editJournal(item)
    showForm.value = true
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    opening.value = false
  }
}
async function save(): Promise<void> {
  if (!can('journal.create') || busy.value || connectionLost.value || !totals.value.balanced) return
  if (await saveJournal()) showForm.value = false
}
function ask(item: Journal, action: JournalAction | 'reverse'): void {
  command.value = { record: item, action }
  reason.value = ''
  reverseReference.value = ''
  reverseDate.value = ''
}
async function confirm(): Promise<void> {
  if (!command.value || busy.value || connectionLost.value) return
  const { record, action } = command.value
  const permission = ['approve', 'reject'].includes(action) ? 'journal.review' : `journal.${action}`
  if (!can(permission)) return
  const saved =
    action === 'reverse'
      ? await reverseJournal(record, reverseReference.value, reverseDate.value, reason.value)
      : await changeJournalStatus(record, action, reason.value)
  if (saved) command.value = null
}
</script>

<template>
  <section class="stack ledger-metadata-page">
    <div v-if="(showBusiness && can('business_journal.view')) || (showProfit && can('profit_transfer.view'))" class="ledger-actions"><AppButton variant="secondary" @click="showBusiness = false; showProfit = false">返回总账凭证</AppButton></div>
    <BusinessJournalPanel v-if="showBusiness && can('business_journal.view')" @open-journal="id => { showBusiness = false; detailId = id }" />
    <ProfitTransferPanel v-else-if="showProfit && can('profit_transfer.view')" @open-journal="id => { showProfit = false; detailId = id }" />
    <WorkspaceTable dataset="journals" :query="query" v-else
      class="journal-list-table"
      title="总账凭证"
      :show-title="false"
      :columns="columns"
      :data="rows"
      :min-table-width="1000"
    >
      <template #actions
        ><AppButton v-if="can('profit_transfer.view')" variant="secondary" @click="showProfit = true; showBusiness = false">损益结转</AppButton><AppButton v-if="can('business_journal.view')" variant="secondary" @click="showBusiness = true; showProfit = false">业务来源与科目配置</AppButton><AppButton
          v-if="can('journal.create')"
          :disabled="busy || connectionLost || opening"
          @click="edit()"
          variant="primary"
          type="button"
          >{{ opening ? '正在读取科目…' : '新增凭证' }}</AppButton
        ></template
      >
      <template #filters
        ><label class="ledger-search"
          >搜索凭证<AppInput v-model="query" placeholder="凭证号、依据编号或备注" /></label
        ><label
          >状态<WorkspaceSelect
            v-model="status"
            :options="[
              { label: '全部状态', value: '' },
              ...Object.entries(journalStatusLabels).map(([value, label]) => ({
                label: label,
                value
              }))
            ]" /></label
      ></template>
      <template #cell-id="{ row }">记-{{ row.id }}</template>
      <template #cell-total_debit="{ row }">¥{{ row.total_debit }}</template>
      <template #cell-status="{ row }">{{
        journalStatusLabels[row.status as keyof typeof journalStatusLabels]
      }}</template>
      <template #cell-source="{ row }"
        ><AppButton
          v-if="row.reversal_of_id"
          @click="detailId = row.reversal_of_id"
          variant="text"
          type="button"
          >原凭证记-{{ row.reversal_of_id }}</AppButton
        ><span v-else-if="row.profit_transfer">损益结转 · {{ row.period_code }}</span><span v-else-if="row.business_source">{{ row.business_source.evidence.label }} #{{ row.business_source.evidence.source_id }}</span><span v-else>手工录入</span
        ><AppButton
          v-if="row.reversal_journal_id"
          @click="detailId = row.reversal_journal_id"
          variant="text"
          type="button"
          >冲销凭证记-{{ row.reversal_journal_id }}</AppButton
        ></template
      >
      <template #cell-actions="{ row }"
        ><div class="ledger-actions">
          <AppButton @click="detailId = row.id" variant="text" type="button">详情</AppButton>
          <AppButton
            v-if="
              can('journal.create') &&
              !row.reversal_of_id && !row.business_source && !row.profit_transfer &&
              ['draft', 'rejected'].includes(row.status)
            "
            :disabled="busy || connectionLost || opening"
            @click="edit(row)"
            variant="text"
            type="button"
            >编辑</AppButton
          >
          <AppButton
            v-for="action in actionable(row)"
            :key="action"
            :disabled="busy || connectionLost"
            @click="ask(row, action)"
            variant="text"
            type="button"
            >{{ journalActionLabels[action] }}</AppButton
          >
          <AppButton
            v-if="
              can('journal.reverse') &&
              row.status === 'posted' &&
              !row.reversal_of_id &&
              !row.reversal_journal_id
            "
            :disabled="busy || connectionLost"
            @click="ask(row, 'reverse')"
            variant="text"
            type="button"
            >建立冲销</AppButton
          >
        </div></template
      >
      <template #empty>{{
        query || status
          ? '没有匹配的凭证。'
          : '暂无凭证。先建立科目和开放期间，再录入借贷平衡的手工凭证。'
      }}</template>
    </WorkspaceTable>
    <NModal
      v-model:show="showForm"
      preset="card"
      :title="form.id === null ? '新增手工凭证' : `编辑记-${form.id}`"
      :mask-closable="!busy"
      :style="{
        width: 'min(1100px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <form v-if="showForm && can('journal.create')" class="ledger-editor" @submit.prevent="save">
        <p class="muted">
          每行只填写一方正金额，另一方填写 0。保存后仍是草稿，提交和审核不会计入已过账金额。
        </p>
        <p v-if="!journalOptions.accounts.length || !journalOptions.periods.length" role="alert">
          缺少启用科目或开放期间，请联系有基础资料维护权限的人员建立。
        </p>
        <div class="form-grid">
          <label
            >依据编号<AppInput
              v-model.trim="form.reference"
              required
              maxlength="80"
              placeholder="填写唯一的票据或凭证依据编号"
          /></label>
          <label
            >凭证日期<NDatePicker
              to="body"
              :formatted-value="form.journal_date || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{ required: true }"
              @update:formatted-value="
                (value) => {
                  form.journal_date = datePickerString(value)
                }
              "
            /><small class="muted"
              >须属于开放期间：{{
                journalOptions.periods.map((p) => `${p.start_date} 至 ${p.end_date}`).join('；')
              }}</small
            ></label
          >
          <label
            >备注<AppInput v-model.trim="form.note" maxlength="500" placeholder="选填"
          /></label>
          <label
            >建立依据 / 修改原因<AppInput v-model.trim="form.reason" required maxlength="200"
          /></label>
        </div>
        <WorkspaceTable
          class="journal-line-editor"
          title="凭证分录"
          :columns="editColumns"
          :data="form.lines"
          :min-table-width="970"
        >
          <template #cell-position="{ row }">{{ lineNumber(row) }}</template>
          <template #cell-account_id="{ row }"
            ><WorkspaceSelect remote-dataset="ledgerAccounts"
              v-model="row.account_id"
              :aria-label="`第 ${lineNumber(row)} 行科目`"
              required
              :disabled="busy"
              :options="[
                { label: '选择科目', value: 0, disabled: true },
                ...journalOptions.accounts.map((account) => ({
                  label: (account.code + ' · ' + account.name).trim(),
                  value: account.id
                }))
              ]"
          /></template>
          <template #cell-summary="{ row }"
            ><AppInput
              v-model.trim="row.summary"
              :aria-label="`第 ${lineNumber(row)} 行摘要`"
              required
              maxlength="200"
              :disabled="busy"
          /></template>
          <template #cell-debit="{ row }"
            ><AppInput
              v-model="row.debit"
              :aria-label="`第 ${lineNumber(row)} 行借方金额`"
              inputmode="decimal"
              required
              pattern="[0-9]{1,12}(\.[0-9]{1,2})?"
              :disabled="busy"
          /></template>
          <template #cell-credit="{ row }"
            ><AppInput
              v-model="row.credit"
              :aria-label="`第 ${lineNumber(row)} 行贷方金额`"
              inputmode="decimal"
              required
              pattern="[0-9]{1,12}(\.[0-9]{1,2})?"
              :disabled="busy"
          /></template>
          <template #cell-auxiliary="{ row }"><label>客户编号<AppInput v-model.number="row.customer_id" type="number" min="1" :disabled="busy" /></label><label>供应商编号<AppInput v-model.number="row.supplier_id" type="number" min="1" :disabled="busy" /></label><label>部门<AppInput v-model.trim="row.department" maxlength="80" :disabled="busy" /></label><label>项目<AppInput v-model.trim="row.project" maxlength="80" :disabled="busy" /></label></template>
          <template #cell-actions="{ row }"
            ><AppButton
              type="button"
              :disabled="busy || form.lines.length <= 2"
              :aria-label="`删除第 ${lineNumber(row)} 行`"
              @click="form.lines.splice(lineNumber(row) - 1, 1)"
              variant="text"
              >删除</AppButton
            ></template
          >
        </WorkspaceTable>
        <div class="journal-total" aria-live="polite">
          <AppButton
            type="button"
            :disabled="busy || form.lines.length >= 100"
            @click="form.lines.push({ account_id: 0, summary: '', debit: '0', credit: '0' })"
            variant="secondary"
            >增加分录</AppButton
          ><span
            >借方 ¥{{ totals.debit }} · 贷方 ¥{{ totals.credit }} ·
            {{ totals.balanced ? '借贷平衡' : '请核对金额与借贷平衡' }}</span
          >
        </div>
        <div class="form-actions">
          <AppButton
            :disabled="
              busy ||
              connectionLost ||
              !totals.balanced ||
              !journalOptions.accounts.length ||
              !journalOptions.periods.length
            "
            variant="primary"
            type="submit"
            >{{ busy ? '正在保存…' : '保存草稿' }}</AppButton
          ><AppButton type="button" :disabled="busy" @click="showForm = false" variant="secondary"
            >取消</AppButton
          >
        </div>
      </form>
    </NModal>
    <NModal
      :show="command !== null"
      preset="card"
      :title="command ? `${journalActionLabels[command.action]} · 记-${command.record.id}` : ''"
      :mask-closable="!busy"
      :style="{ width: 'min(640px, calc(100vw - 32px))' }"
      @update:show="
        (value) => {
          if (!value) command = null
        }
      "
    >
      <form v-if="command" class="ledger-editor" @submit.prevent="confirm">
        <p v-if="command.action === 'reverse'">
          将按原凭证快照交换借贷建立冲销草稿，需由另一账号审核并过账。原凭证保留。
        </p>
        <p v-else-if="command.action === 'post'">
          审核已通过，过账后分录金额固定；错误只能建立冲销凭证更正。
        </p>
        <p v-else-if="command.action === 'cancel'">取消后凭证不再执行后续操作，记录仍保留。</p>
        <p v-else>
          依据编号 {{ command.record.reference }} · 借贷各 ¥{{ command.record.total_debit }} · 版本
          {{ command.record.version }}
        </p>
        <div v-if="command.action === 'reverse'" class="form-grid">
          <label
            >冲销依据编号<AppInput v-model.trim="reverseReference" required maxlength="80" /></label
          ><label
            >冲销日期<NDatePicker
              to="body"
              :formatted-value="reverseDate || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{ required: true }"
              @update:formatted-value="
                (value) => {
                  reverseDate = datePickerString(value)
                }
              "
          /></label>
        </div>
        <label>操作依据 / 原因<AppInput v-model.trim="reason" required maxlength="200" /></label>
        <div class="form-actions">
          <AppButton :disabled="busy || connectionLost" variant="primary" type="submit">{{
            busy ? '正在处理…' : journalActionLabels[command.action]
          }}</AppButton
          ><AppButton type="button" :disabled="busy" @click="command = null" variant="secondary"
            >返回</AppButton
          >
        </div>
      </form>
    </NModal>
    <NModal
      :show="!!detail"
      preset="card"
      :title="detail ? `记-${detail.id} · ${journalStatusLabels[detail.status]}` : ''"
      :style="{
        width: 'min(1100px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
      @update:show="
        (value) => {
          if (!value) detailId = null
        }
      "
    >
      <div v-if="detail" class="stack">
        <p>
          依据 {{ detail.reference }} · {{ detail.journal_date }} · 期间 {{ detail.period_code }} ·
          建单人 {{ detail.created_by_name }} · 版本 {{ detail.version }}
        </p>
        <p v-if="detail.note">备注：{{ detail.note }}</p>
        <p v-if="detail.reversal_of_id">
          冲销原凭证：<AppButton
            @click="detailId = detail.reversal_of_id"
            variant="text"
            type="button"
            >查看原凭证记-{{ detail.reversal_of_id }}</AppButton
          >
        </p>
        <p v-if="detail.reversal_journal_id">
          关联冲销：<AppButton
            @click="detailId = detail.reversal_journal_id"
            variant="text"
            type="button"
            >查看冲销凭证记-{{ detail.reversal_journal_id }}</AppButton
          >（{{ relatedStatus(detail.reversal_journal_id) }}）；冲销凭证过账后才抵销原凭证。
        </p>
        <WorkspaceTable dataset="journalLines" :query-filters="{ journal_id: detail.id }"
          title="凭证分录"
          :columns="lineColumns"
          :data="detail.lines"
          :min-table-width="800"
          ><template #cell-account="{ row }"
            >{{ row.account_code }} · {{ row.account_name }}</template
          ></WorkspaceTable
        >
        <NCollapse v-if="detail.business_source"><AppCollapseItem name="business" :title="`生成时的业务来源与科目配置（版本 ${detail.business_source.policy_version}）`"><BusinessSourceEvidence :source="detail.business_source.evidence" :mapping="detail.business_source.mapping" /></AppCollapseItem></NCollapse>
        <NCollapse v-if="detail.profit_transfer"><AppCollapseItem name="profit" title="生成时的损益余额、凭证来源与结转范围"><ProfitTransferEvidence :evidence="detail.profit_transfer.evidence" :can-open-journal="can('journal.view')" @open-journal="id => { detailId = id }" /></AppCollapseItem></NCollapse>
        <JournalHistory
          :key="`${detail.id}:${detail.version}`"
          :record-id="detail!.id" :load="() => loadJournalChanges(detail!.id)"
        />
      </div>
    </NModal>
  </section>
</template>
