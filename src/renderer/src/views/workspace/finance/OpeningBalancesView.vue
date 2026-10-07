<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker, NCheckbox } from 'naive-ui'
import { datePickerString, vDateField, dateOutsideRange } from '../../../utils/date-field'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import type {
  OpeningBalance,
  OpeningBalanceAction,
  JournalLineInput
} from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { displayError } from '../../../utils/formatters'
import OpeningHistory from './OpeningHistory.vue'
import AuxiliarySelector from './AuxiliarySelector.vue'
import { auxiliaryText } from './auxiliary-display'
import { openingActionLabels, openingStatusLabels, openingTotals } from './opening-display'
import './ledger-metadata.css'
import './journals.css'
import './opening-balances.css'

const store = usePiniaAppStore()
const {
  openingBalances: records,
  openingBalanceOptions: options,
  openingBalanceForm: form,
  busy,
  connectionLost,
  user,
  error
} = storeToRefs(store)
const {
  can,
  editOpeningBalance,
  saveOpeningBalance,
  changeOpeningBalanceStatus,
  loadOpeningBalanceChanges
} = store
const query = ref('')
const status = ref('')
const showForm = ref(false)
const opening = ref(false)
const zero = ref(false)
const detailId = ref<number | null>(null)
const detail = computed(() => records.value.find((r) => r.id === detailId.value))
const command = ref<{ record: OpeningBalance; action: OpeningBalanceAction } | null>(null)
const reason = ref('')
const totals = computed(() => openingTotals(form.value.lines))
const rows = computed(() =>
  records.value.filter(
    (r) =>
      (!status.value || r.status === status.value) &&
      [documentSearch(r), r.reference, r.note, String(r.id)]
        .join(' ')
        .toLowerCase()
        .includes(query.value.trim().toLowerCase())
  )
)
const active = computed(() => records.value.some((r) => r.active_key === 1))
const columns = [
  { key: 'id', title: '期初方案' },
  { key: 'effective_date', title: '启用日' },
  { key: 'reference', title: '依据编号' },
  { key: 'total_debit', title: '借贷各（人民币）' },
  { key: 'status', title: '状态' },
  { key: 'actions', title: '操作' }
]
const lines = [
  { key: 'position', title: '序号', width: '70' },
  { key: 'account', title: '科目快照', width: '230' },
  { key: 'summary', title: '余额依据', width: '260' },
  { key: 'auxiliary', title: '辅助快照', width: '290' },
  { key: 'debit', title: '借方（元）', width: '160' },
  { key: 'credit', title: '贷方（元）', width: '160' }
]
const editColumns = [
  { key: 'position', title: '序号', width: '70' },
  { key: 'account_id', title: '科目', width: '230' },
  { key: 'summary', title: '余额依据', width: '260' },
  { key: 'auxiliary', title: '辅助信息', width: '290' },
  { key: 'debit', title: '借方（元）', width: '160' },
  { key: 'credit', title: '贷方（元）', width: '160' },
  { key: 'actions', title: '操作', width: '90' }
]
const number = (line: JournalLineInput) => form.value.lines.indexOf(line) + 1
function changeZero(): void {
  form.value.lines = zero.value
    ? []
    : [1, 2].map(() => ({ account_id: 0, summary: '', debit: '0', credit: '0' }))
}
function actions(record: OpeningBalance): OpeningBalanceAction[] {
  const result: OpeningBalanceAction[] = []
  if (['draft', 'rejected'].includes(record.status) && can('opening_balance.submit'))
    result.push('submit')
  if (
    record.status === 'submitted' &&
    can('opening_balance.review') &&
    !record.author_ids.includes(user.value?.id ?? 0)
  )
    result.push('approve', 'reject')
  if (record.status === 'approved' && can('opening_balance.confirm')) result.push('confirm')
  if (
    ['draft', 'rejected', 'submitted', 'approved'].includes(record.status) &&
    can('opening_balance.cancel')
  )
    result.push('cancel')
  if (record.status === 'confirmed' && can('opening_balance.reverse')) result.push('reverse')
  return result
}
async function edit(item?: OpeningBalance): Promise<void> {
  if (opening.value || busy.value || connectionLost.value) return
  opening.value = true
  try {
    if (await editOpeningBalance(item)) {
      zero.value = form.value.lines.length === 0
      showForm.value = true
    }
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    opening.value = false
  }
}
async function save(): Promise<void> {
  if (
    !can('opening_balance.create') ||
    busy.value ||
    connectionLost.value ||
    !totals.value.balanced
  )
    return
  if (await saveOpeningBalance()) showForm.value = false
}
async function confirm(): Promise<void> {
  if (!command.value || busy.value || connectionLost.value) return
  if (await changeOpeningBalanceStatus(command.value.record, command.value.action, reason.value))
    command.value = null
}
function ask(record: OpeningBalance, action: OpeningBalanceAction): void {
  command.value = { record, action }
  reason.value = ''
}
</script>

<template>
  <section class="stack ledger-metadata-page opening-balances-page">
    <WorkspaceTable
      class="journal-list-table"
      title="期初余额"
      :show-title="false"
      :columns="columns"
      :data="rows"
      :min-table-width="1000"
    >
      <template #actions
        ><AppButton
          v-if="can('opening_balance.create')"
          :disabled="active || busy || connectionLost || opening"
          @click="edit()"
          variant="primary"
          type="button"
          >{{ opening ? '正在读取科目…' : '新增期初方案' }}</AppButton
        ></template
      >
      <template #filters
        ><label class="ledger-search"
          >搜索期初方案<AppInput v-model="query" placeholder="方案号、依据编号或备注" /></label
        ><label
          >状态<WorkspaceSelect
            v-model="status"
            :options="[
              { label: '全部状态', value: '' },
              ...Object.entries(openingStatusLabels).map(([value, label]) => ({
                label: label,
                value
              }))
            ]" /></label
      ></template>
      <template #beforeTable
        ><p class="opening-note">
          用于首次启用总账。每个科目录入一方期初余额，借贷须平衡；另一账号审核并确认后进入报表，不计入本期发生额。存在未确认方案时不能过账凭证；已有过账凭证后不能重设期初。
        </p></template
      >
      <template #cell-id="{ row }">{{ documentLabel(row) }}</template>
      <template #cell-total_debit="{ row }"
        ><span class="journal-amount">¥{{ row.total_debit }}</span></template
      >
      <template #cell-status="{ row }">{{
        openingStatusLabels[row.status as keyof typeof openingStatusLabels]
      }}</template>
      <template #cell-actions="{ row }"
        ><div class="ledger-actions">
          <AppButton @click="detailId = row.id" variant="text" type="button">详情</AppButton
          ><AppButton
            v-if="can('opening_balance.create') && ['draft', 'rejected'].includes(row.status)"
            :disabled="busy || connectionLost || opening"
            @click="edit(row)"
            variant="text"
            type="button"
            >编辑</AppButton
          ><AppButton
            v-for="action in actions(row)"
            :key="action"
            :disabled="busy || connectionLost"
            @click="ask(row, action)"
            variant="text"
            type="button"
            >{{ openingActionLabels[action] }}</AppButton
          >
        </div></template
      >
      <template #empty>{{
        query || status
          ? '没有匹配的期初方案。'
          : '暂无正式期初。先建立科目及最早开放期间，再新增期初方案；零余额公司也须明确确认零期初。'
      }}</template>
    </WorkspaceTable>
    <NModal
      v-model:show="showForm"
      preset="card"
      :title="form.id === null ? '新增期初方案' : `编辑${documentLabel(form, records)}`"
      :mask-closable="!busy"
      :style="{
        width: 'min(1100px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <form
        v-if="showForm && can('opening_balance.create')"
        class="ledger-editor"
        @submit.prevent="save"
      >
        <p>
          以业务方核对的启用试算表为依据，不自动推断库存、往来或银行余额。每行只填一方正金额，另一方填
          0；未列出的科目视为零。
        </p>
        <p v-if="!options.period || options.period.status !== 'open'" role="alert">
          须先建立最早开放会计期间。
        </p>
        <div class="form-grid">
          <label>依据编号<AppInput v-model.trim="form.reference" required maxlength="80" /></label
          ><label
            >总账启用日<NDatePicker
              to="body"
              :formatted-value="form.effective_date || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{
                required: true,
                min: options.period?.start_date,
                max: options.period?.start_date
              }"
              @update:formatted-value="
                (value) => {
                  form.effective_date = datePickerString(value)
                }
              "
              :is-date-disabled="
                (timestamp: number) =>
                  dateOutsideRange(
                    timestamp,
                    options.period?.start_date,
                    options.period?.start_date
                  )
              "
            /><small
              >须为最早期间开始日：{{ options.period?.start_date ?? '尚未建立' }}</small
            ></label
          ><label>备注<AppInput v-model.trim="form.note" maxlength="500" /></label
          ><label
            >建立依据 / 修改原因<AppInput v-model.trim="form.reason" required maxlength="200"
          /></label>
        </div>
        <NCheckbox
          class="opening-zero"
          :checked="zero"
          :disabled="busy"
          @update:checked="
            (checked) => {
              zero = checked
              changeZero()
            }
          "
          >全部科目期初为零（不录入明细）</NCheckbox
        >
        <WorkspaceTable
          v-if="!zero"
          class="journal-line-editor"
          title="科目期初余额"
          :columns="editColumns"
          :data="form.lines"
          :min-table-width="1260"
        >
          <template #cell-position="{ row }">{{ number(row) }}</template>
          <template #cell-account_id="{ row }"
            ><WorkspaceSelect
              v-model="row.account_id"
              :aria-label="`第 ${number(row)} 行科目`"
              required
              :disabled="busy"
              :options="[
                { label: '选择科目', value: 0, disabled: true },
                ...options.accounts.map((account) => ({
                  label: (account.code + ' · ' + account.name).trim(),
                  value: account.id
                }))
              ]"
          /></template>
          <template #cell-summary="{ row }"
            ><AppInput
              v-model.trim="row.summary"
              :aria-label="`第 ${number(row)} 行余额依据`"
              required
              maxlength="200"
              :disabled="busy"
          /></template>
          <template #cell-auxiliary="{ row }"><AuxiliarySelector v-model="row.auxiliary"
            :items="options.auxiliary_items" :policy="options.auxiliary_policies?.find(item => item.account_id === row.account_id)"
            :date="form.effective_date" :disabled="busy || connectionLost" :label-prefix="`第 ${number(row)} 行`" /></template>
          <template #cell-debit="{ row }"
            ><AppInput
              v-model="row.debit"
              :aria-label="`第 ${number(row)} 行借方金额`"
              inputmode="decimal"
              required
              pattern="[0-9]{1,12}(\.[0-9]{1,2})?"
              :disabled="busy"
          /></template>
          <template #cell-credit="{ row }"
            ><AppInput
              v-model="row.credit"
              :aria-label="`第 ${number(row)} 行贷方金额`"
              inputmode="decimal"
              required
              pattern="[0-9]{1,12}(\.[0-9]{1,2})?"
              :disabled="busy"
          /></template>
          <template #cell-actions="{ row }"
            ><AppButton
              type="button"
              :disabled="busy || form.lines.length <= 2"
              :aria-label="`删除第 ${number(row)} 行`"
              @click="form.lines.splice(number(row) - 1, 1)"
              variant="text"
              >删除</AppButton
            ></template
          >
        </WorkspaceTable>
        <div class="journal-total" aria-live="polite">
          <AppButton
            v-if="!zero"
            type="button"
            :disabled="busy || form.lines.length >= 100"
            @click="form.lines.push({ account_id: 0, summary: '', debit: '0', credit: '0' })"
            variant="secondary"
            >增加科目</AppButton
          ><span
            >借方 ¥{{ totals.debit }} · 贷方 ¥{{ totals.credit }} ·
            {{ totals.balanced ? '借贷平衡' : '请核对金额、重复科目与借贷平衡' }}</span
          >
        </div>
        <div class="form-actions">
          <AppButton
            :disabled="
              busy ||
              connectionLost ||
              !totals.balanced ||
              !options.period ||
              options.period.status !== 'open'
            "
            variant="primary"
            type="submit"
            >保存草稿</AppButton
          ><AppButton type="button" :disabled="busy" @click="showForm = false" variant="secondary"
            >取消</AppButton
          >
        </div>
      </form>
    </NModal>
    <NModal
      :show="command !== null"
      preset="card"
      :title="command ? `${openingActionLabels[command.action]} · ${documentLabel(command.record)}` : ''"
      :mask-closable="!busy"
      :style="{ width: 'min(640px, calc(100vw - 32px))' }"
      @update:show="
        (value) => {
          if (!value) command = null
        }
      "
    >
      <form v-if="command" class="ledger-editor" @submit.prevent="confirm">
        <p>
          依据 {{ command.record.reference }} · 启用日 {{ command.record.effective_date }} · 借贷各
          ¥{{ command.record.total_debit }} · 版本 {{ command.record.version }}
        </p>
        <p v-if="command.action === 'confirm'">
          确认后进入总账期初，不增加本期发生额。首次凭证过账后不可重设期初。
        </p>
        <p v-if="command.action === 'reverse'">
          仅在尚无过账凭证时允许撤销。原方案和明细保留，须另建并审核新方案；已有过账金额应使用更正凭证。
        </p>
        <label>操作依据 / 原因<AppInput v-model.trim="reason" required maxlength="200" /></label>
        <div class="form-actions">
          <AppButton :disabled="busy || connectionLost" variant="primary" type="submit">{{
            busy ? '正在处理…' : openingActionLabels[command.action]
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
      :title="detail ? `${documentLabel(detail)} · ${openingStatusLabels[detail.status]}` : ''"
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
          依据 {{ detail.reference }} · 启用日 {{ detail.effective_date }} · 期间
          {{ detail.period_code }} · 建单人 {{ detail.created_by_name }} · 版本 {{ detail.version }}
        </p>
        <p v-if="detail.note">备注：{{ detail.note }}</p>
        <WorkspaceTable
          title="科目期初余额"
          :columns="lines"
          :data="detail.lines"
          :min-table-width="880"
          ><template #cell-account="{ row }"
            >{{ row.account_code }} · {{ row.account_name }}</template
          ><template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template><template #empty>此方案为全部科目零余额。</template></WorkspaceTable
        ><OpeningHistory
          :key="`${detail.id}:${detail.version}`"
          :load="() => loadOpeningBalanceChanges(detail!.id)"
        />
      </div>
    </NModal>
  </section>
</template>
