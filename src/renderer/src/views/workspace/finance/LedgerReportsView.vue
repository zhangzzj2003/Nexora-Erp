<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker } from 'naive-ui'
import { datePickerString, vDateField, dateOutsideRange } from '../../../utils/date-field'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import JournalHistory from './JournalHistory.vue'
import OpeningHistory from './OpeningHistory.vue'
import { journalStatusLabels } from './journal-display'
import './ledger-reports.css'
import './journals.css'

const store = usePiniaAppStore()
const {
  ledgerReportQuery: query,
  ledgerReportResult: result,
  ledgerReportAccounts: accounts,
  ledgerReportLoading: loading,
  ledgerReportError: error,
  connectionLost,
  ledgerReportJournal: journal,
  ledgerReportJournalLoading: journalLoading,
  ledgerReportJournalError: journalError
} = storeToRefs(store)
const {
  can,
  loadLedgerReportOptions,
  queryLedgerReport,
  exportLedgerReport,
  openLedgerReportJournal,
  closeLedgerReportJournal,
  loadJournalChanges
} = store
const moneyKeys = [
  'opening_debit',
  'opening_credit',
  'debit',
  'credit',
  'closing_debit',
  'closing_credit',
  'balance'
]
const columns = computed(() =>
  (result.value?.columns ?? []).map((column) => ({
    ...column,
    width: moneyKeys.includes(column.key)
      ? '170'
      : ['summary', 'account', 'reference', 'name'].includes(column.key)
        ? '220'
        : '130'
  }))
)
const balanceRows = computed(() =>
  result.value
    ? [
        {
          phase: '期初余额',
          debit: result.value.totals.opening_debit,
          credit: result.value.totals.opening_credit
        },
        {
          phase: '本期发生额',
          debit: result.value.totals.debit,
          credit: result.value.totals.credit
        },
        {
          phase: '期末余额',
          debit: result.value.totals.closing_debit,
          credit: result.value.totals.closing_credit
        }
      ]
    : []
)
const balanceColumns = [
  { key: 'phase', title: '核对项目' },
  { key: 'debit', title: '借方合计（元）' },
  { key: 'credit', title: '贷方合计（元）' }
]
const journalColumns = [
  { key: 'position', title: '序号' },
  { key: 'account_name', title: '科目快照' },
  { key: 'summary', title: '摘要' },
  { key: 'debit', title: '借方（元）' },
  { key: 'credit', title: '贷方（元）' }
]
const showOpening = ref(false)
watch(result, () => {
  showOpening.value = false
})
const mayQuery = computed(
  () =>
    can('journal.view') &&
    !connectionLost.value &&
    !loading.value &&
    !!query.value.from_date &&
    !!query.value.to_date &&
    (query.value.kind === 'trial_balance' || !!query.value.account_id)
)
function changeKind(): void {
  query.value.account_id = null
}
async function drillAccount(id: string): Promise<void> {
  query.value = { ...query.value, kind: 'account_ledger', account_id: Number(id) }
  await queryLedgerReport()
}
async function trialBalance(): Promise<void> {
  query.value = { ...query.value, kind: 'trial_balance', account_id: null }
  await queryLedgerReport()
}
onMounted(() => {
  void loadLedgerReportOptions()
})
</script>

<template>
  <section class="stack ledger-reports-page">
    <form @submit.prevent="queryLedgerReport">
      <WorkspaceTable
        class="ledger-report-table"
        title="总账报表"
        :show-title="false"
        :columns="columns"
        :data="result?.rows ?? []"
        :loading="loading"
        :error="error"
        :min-table-width="query.kind === 'trial_balance' ? 1370 : 1910"
      >
        <template #filters>
          <label
            >报表<WorkspaceSelect
              v-model="query.kind"
              @change="changeKind"
              :options="[
                { label: '试算平衡', value: 'trial_balance' },
                { label: '科目明细', value: 'account_ledger' }
              ]"
          /></label>
          <label v-if="query.kind === 'account_ledger'"
            >科目<WorkspaceSelect
              v-model="query.account_id"
              required
              :options="[
                { label: '选择科目', value: null, disabled: true },
                ...accounts.map((account) => ({
                  label: (
                    account.code +
                    ' · ' +
                    account.name +
                    (account.is_active ? '' : '（停用）')
                  ).trim(),
                  value: account.id
                }))
              ]"
          /></label>
          <label
            >开始日期<NDatePicker
              to="body"
              :formatted-value="query.from_date || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{ required: true }"
              @update:formatted-value="
                (value) => {
                  query.from_date = datePickerString(value)
                }
              "
          /></label>
          <label
            >结束日期<NDatePicker
              to="body"
              :formatted-value="query.to_date || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{ required: true, min: query.from_date || undefined }"
              @update:formatted-value="
                (value) => {
                  query.to_date = datePickerString(value)
                }
              "
              :is-date-disabled="
                (timestamp: number) =>
                  dateOutsideRange(timestamp, query.from_date || undefined, undefined)
              "
          /></label>
        </template>
        <template #filterActions
          ><AppButton :disabled="!mayQuery" variant="primary" type="submit">{{
            loading ? '正在查询…' : '查询'
          }}</AppButton></template
        >
        <template #actions
          ><AppButton
            type="button"
            :disabled="connectionLost || loading || !result"
            @click="exportLedgerReport"
            variant="secondary"
            >导出 CSV</AppButton
          ><AppButton
            v-if="query.kind === 'account_ledger'"
            type="button"
            :disabled="connectionLost || loading"
            @click="loadLedgerReportOptions"
            variant="secondary"
            >重新读取科目</AppButton
          ></template
        >
        <template #beforeTable>
          <p class="muted ledger-report-note">
            期初为已确认启用余额加开始日前的已过账分录；本期仅计已过账凭证，草稿、待审核及已批准凭证不计入。未结账数据可随后续过账变化。
          </p>
          <p v-if="result?.opening_balance">
            正式期初来源：<AppButton type="button" @click="showOpening = true" variant="text"
              >{{ documentLabel(result.opening_balance) }} ·
              {{ result.opening_balance.reference }}</AppButton
            >
            · 启用日 {{ result.opening_balance.effective_date }}
          </p>
          <p v-else-if="result" class="ledger-report-note">
            尚未录入正式期初；当前期初仅来自历史已过账金额累计。
          </p>
          <p v-if="result" class="ledger-report-caption">
            {{ result.filters.from_date }} 至 {{ result.filters.to_date }} ·
            {{
              result.kind === 'trial_balance'
                ? '全科目 · 人民币'
                : `${result.totals.code} · ${result.totals.name} · 人民币`
            }}
            · {{ result.rows.length }} 行 · 生成于
            {{ new Date(result.generated_at).toLocaleString() }}
          </p>
          <p
            v-if="result?.kind === 'trial_balance'"
            :role="result.totals.balanced ? undefined : 'alert'"
          >
            {{
              result.totals.balanced
                ? '期初、本期发生额与期末借贷合计均相等。'
                : '借贷合计不相等，请核对凭证和数据完整性。'
            }}
          </p>
          <AppButton
            v-if="result?.kind === 'account_ledger'"
            type="button"
            :disabled="loading || connectionLost"
            @click="trialBalance"
            variant="text"
            >返回同日期试算平衡</AppButton
          >
        </template>
        <template #cell-code="{ row }"
          ><AppButton
            type="button"
            :disabled="loading || connectionLost"
            @click="drillAccount(row.account_id!)"
            variant="text"
            >{{ row.code }}</AppButton
          ></template
        >
        <template #cell-journal_id="{ row }"
          ><AppButton
            type="button"
            :disabled="connectionLost"
            @click="openLedgerReportJournal(Number(row.journal_id))"
            variant="text"
            >{{ relatedDocumentLabel(row, 'journal') }}</AppButton
          ></template
        >
        <template #cell-source="{ row }"
          ><AppButton
            v-if="row.reversal_of_id"
            type="button"
            :disabled="connectionLost"
            @click="openLedgerReportJournal(Number(row.reversal_of_id))"
            variant="text"
            >{{ row.source }}</AppButton
          ><span v-else>{{ row.source }}</span></template
        >
        <template v-for="key in moneyKeys" :key="key" #[`cell-${key}`]="{ row }"
          ><span class="ledger-report-money">{{ row[key] }}</span></template
        >
        <template #empty>{{
          result
            ? '此范围内暂无记录；期初与期末余额见下方核对。'
            : '选择日期范围并查询。科目明细须先选择科目。'
        }}</template>
        <template #errorActions
          ><AppButton
            type="button"
            :disabled="connectionLost || loading"
            @click="queryLedgerReport"
            variant="secondary"
            >重试查询</AppButton
          ></template
        >
        <template #footer
          ><p v-if="result" class="muted ledger-report-note">
            覆盖期间：{{
              result.periods
                .map(
                  (period) => `${period.code}（${period.status === 'open' ? '开放' : '已关闭'}）`
                )
                .join('、') || '无对应期间'
            }}。当前尚无期间结账或业务自动凭证。
          </p></template
        >
      </WorkspaceTable>
    </form>
    <WorkspaceTable
      v-if="result"
      class="ledger-report-table"
      title="余额核对"
      :columns="balanceColumns"
      :data="balanceRows"
      :min-table-width="600"
    >
      <template #cell-debit="{ row }"
        ><span class="ledger-report-money">{{ row.debit }}</span></template
      ><template #cell-credit="{ row }"
        ><span class="ledger-report-money">{{ row.credit }}</span></template
      >
    </WorkspaceTable>
    <NModal
      :show="!!journal || journalLoading || !!journalError"
      preset="card"
      :title="journal ? `${documentLabel(journal)} · ${journalStatusLabels[journal.status]}` : '凭证详情'"
      :style="{
        width: 'min(1100px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
      @update:show="
        (value) => {
          if (!value) closeLedgerReportJournal()
        }
      "
    >
      <p v-if="journalLoading" role="status">正在读取凭证…</p>
      <p v-if="journalError" role="alert">{{ journalError }}</p>
      <div v-if="journal" class="stack">
        <p>
          {{ journal.journal_date }} · 期间 {{ journal.period_code }} · 依据
          {{ journal.reference }} · 建单人 {{ journal.created_by_name }} · 版本
          {{ journal.version }}
        </p>
        <p v-if="journal.note">备注：{{ journal.note }}</p>
        <p v-if="journal.reversal_of_id">
          冲销原凭证：<AppButton
            type="button"
            :disabled="connectionLost"
            @click="openLedgerReportJournal(journal.reversal_of_id)"
            variant="text"
            >{{ relatedDocumentLabel(journal, 'reversal_of') }}</AppButton
          >
        </p>
        <p v-if="journal.reversal_journal_id">
          关联冲销：<AppButton
            type="button"
            :disabled="connectionLost"
            @click="openLedgerReportJournal(journal.reversal_journal_id)"
            variant="text"
            >{{ relatedDocumentLabel(journal, 'reversal_journal') }}</AppButton
          >（须过账后才抵销）。
        </p>
        <WorkspaceTable
          class="ledger-report-table"
          title="凭证分录"
          :columns="journalColumns"
          :data="journal.lines"
          :min-table-width="800"
          ><template #cell-account_name="{ row }"
            >{{ row.account_code }} · {{ row.account_name }}</template
          ></WorkspaceTable
        >
        <JournalHistory
          :key="`${journal.id}:${journal.version}`"
          :load="() => loadJournalChanges(journal!.id)"
        />
      </div>
    </NModal>
    <NModal
      v-model:show="showOpening"
      preset="card"
      title="正式期初来源"
      :style="{
        width: 'min(1100px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <div v-if="result?.opening_balance" class="stack">
        <p>
          {{ documentLabel(result.opening_balance) }} · 依据 {{ result.opening_balance.reference }} ·
          启用日 {{ result.opening_balance.effective_date }} · 已确认 · 版本
          {{ result.opening_balance.version }}
        </p>
        <p>
          借贷各 ¥{{
            result.opening_balance.total_debit
          }}，只计期初，不计本期发生额。此详情与当前报表来自同一读取快照。
        </p>
        <WorkspaceTable
          title="启用科目余额"
          :columns="journalColumns"
          :data="result.opening_balance.lines"
          :min-table-width="800"
          ><template #cell-account_name="{ row }"
            >{{ row.account_code }} · {{ row.account_name }}</template
          ><template #empty>已明确确认全部科目期初为零。</template></WorkspaceTable
        >
        <OpeningHistory
          :key="`${result.opening_balance.id}:${result.opening_balance.version}`"
          :load="async () => result!.opening_balance!.changes"
        />
      </div>
    </NModal>
  </section>
</template>
