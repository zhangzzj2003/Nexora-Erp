<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker } from 'naive-ui'
import { datePickerString, vDateField, dateOutsideRange } from '../../../utils/date-field'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import type { AccountingPeriod } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import MetadataHistory from './MetadataHistory.vue'
import PeriodClosingHistory from './PeriodClosingHistory.vue'
import './ledger-metadata.css'

const store = usePiniaAppStore()
const { busy, connectionLost, accountingPeriods, accountingPeriodForm: form,
  periodClosingCheck: closingCheck, periodClosingLoading: checking, periodClosingError: closingError } = storeToRefs(store)
const { can, editAccountingPeriod, saveAccountingPeriod, loadAccountingPeriodChanges } = store
const query = ref('')
const showForm = ref(false)
const history = ref<AccountingPeriod | null>(null)
const closingTarget = ref<AccountingPeriod | null>(null)
const closingMode = ref<'close' | 'reopen' | 'history'>('close')
const reason = ref('')
const laterClosed = computed(() => accountingPeriods.value.filter(item => item.status === 'closed' && closingTarget.value && item.end_date > closingTarget.value.end_date))
const filtered = computed(() => accountingPeriods.value.filter(item =>
  [item.code, item.name, item.start_date, item.end_date].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const columns = [
  { key: 'code', title: '期间编码' },
  { key: 'name', title: '名称' },
  { key: 'start_date', title: '开始日期' },
  { key: 'end_date', title: '结束日期' },
  { key: 'status', title: '状态' },
  { key: 'version', title: '版本' },
  { key: 'actions', title: '操作' }
]
function edit(item?: AccountingPeriod): void {
  editAccountingPeriod(item)
  showForm.value = true
}
async function save(): Promise<void> {
  if (busy.value || connectionLost.value || !can('accounting_period.manage')) return
  if (await saveAccountingPeriod()) showForm.value = false
}
async function openClosing(item: AccountingPeriod, mode: 'close' | 'reopen' | 'history'): Promise<void> {
  closingTarget.value = item; closingMode.value = mode; reason.value = ''
  if (mode === 'close') await store.loadPeriodClosingCheck(item.id)
  else await store.loadPeriodClosingHistory(item.id)
}
async function retryClosing(): Promise<void> {
  if (!closingTarget.value) return
  if (closingMode.value === 'close') await store.loadPeriodClosingCheck(closingTarget.value.id)
  else await store.loadPeriodClosingHistory(closingTarget.value.id)
}
async function confirmClosing(): Promise<void> {
  const item = closingMode.value === 'close' ? closingCheck.value?.period : closingTarget.value
  if (!item || closingMode.value === 'history' || busy.value || checking.value || !reason.value.trim()) return
  if (await store.changePeriodClosingStatus(item, closingMode.value, reason.value.trim())) closingTarget.value = null
}
</script>

<template>
  <section class="stack ledger-metadata-page">
    <WorkspaceTable dataset="accountingPeriods" :query="query"
      title="会计期间"
      :show-title="false"
      :columns="columns"
      :data="filtered"
      :min-table-width="900"
    >
      <template #actions
        ><AppButton
          v-if="can('accounting_period.manage')"
          :disabled="busy || connectionLost"
          @click="edit()"
          variant="primary"
          type="button"
          >新增期间</AppButton
        ></template
      >
      <template #filters>
        <label class="ledger-search"
          >搜索期间<AppInput v-model="query" placeholder="输入编码、名称或日期"
        /></label>
        <span class="muted">共 {{ accountingPeriods.length }} 个期间</span>
      </template>
      <template #cell-status="{ row }">{{ row.status === 'open' ? '开放' : '已结账' }}</template>
      <template #cell-actions="{ row }">
        <div class="ledger-actions">
          <AppButton v-if="can('accounting_period.manage') && row.status === 'open'" :disabled="busy || connectionLost" @click="edit(row)" variant="text" type="button">编辑名称</AppButton>
          <AppButton v-if="can('accounting_period.closing_view') && row.status === 'open'" :disabled="busy || connectionLost" @click="openClosing(row, 'close')" variant="text" type="button">结账检查</AppButton>
          <AppButton v-if="can('accounting_period.closing_view') && can('accounting_period.reopen') && row.status === 'closed'" :disabled="busy || connectionLost" @click="openClosing(row, 'reopen')" variant="text" type="button">重开期间</AppButton>
          <AppButton v-if="can('accounting_period.closing_view')" :disabled="connectionLost" @click="openClosing(row, 'history')" variant="text" type="button">结账记录</AppButton>
          <AppButton :disabled="connectionLost" @click="history = row" variant="text" type="button">变更记录</AppButton>
        </div>
      </template>
      <template #empty>{{
        query ? '没有匹配的期间。' : '暂无会计期间。请先确定公司使用的日期范围。'
      }}</template>
    </WorkspaceTable>
    <NModal
      v-model:show="showForm"
      preset="card"
      :title="form.id === null ? '新增会计期间' : '编辑期间名称'"
      :mask-closable="!busy"
      :style="{
        width: 'min(760px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <form
        v-if="showForm && can('accounting_period.manage')"
        class="ledger-editor"
        @submit.prevent="save"
      >
        <p class="muted">范围包含开始和结束日期，不可与其他期间重叠。编码及日期保存后固定。</p>
        <div class="form-grid">
          <label
            >期间编码<AppInput
              v-model.trim="form.code"
              required
              maxlength="32"
              :disabled="form.id !== null"
              placeholder="例如 2026-01"
          /></label>
          <label>期间名称<AppInput v-model.trim="form.name" required maxlength="100" /></label>
          <label
            >开始日期<NDatePicker
              to="body"
              :formatted-value="form.start_date || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{ required: true }"
              @update:formatted-value="
                (value) => {
                  form.start_date = datePickerString(value)
                }
              "
              :disabled="form.id !== null"
          /></label>
          <label
            >结束日期<NDatePicker
              to="body"
              :formatted-value="form.end_date || null"
              type="date"
              format="yyyy-MM-dd"
              value-format="yyyy-MM-dd"
              v-date-field="{ required: true, min: form.start_date }"
              @update:formatted-value="
                (value) => {
                  form.end_date = datePickerString(value)
                }
              "
              :disabled="form.id !== null"
              :is-date-disabled="
                (timestamp: number) => dateOutsideRange(timestamp, form.start_date, undefined)
              "
          /></label>
          <label
            >建立依据 / 修改原因<AppInput
              v-model.trim="form.reason"
              required
              maxlength="200"
              placeholder="填写期间方案依据或修改原因"
          /></label>
        </div>
        <div class="form-actions">
          <AppButton :disabled="busy || connectionLost" variant="primary" type="submit">{{
            busy ? '正在保存…' : '保存期间'
          }}</AppButton
          ><AppButton type="button" :disabled="busy" @click="showForm = false" variant="secondary"
            >取消</AppButton
          >
        </div>
      </form>
    </NModal>
    <NModal
      :show="history !== null"
      preset="card"
      :title="history ? `${history.code} · 变更记录` : '变更记录'"
      :style="{ width: 'min(1000px, calc(100vw - 32px))' }"
      @update:show="
        (value) => {
          if (!value) history = null
        }
      "
    >
      <MetadataHistory
        v-if="history"
        :key="history.id"
        :record-id="history!.id" dataset="periodHistory" :load="() => loadAccountingPeriodChanges(history!.id)"
      />
    </NModal>
    <NModal :show="closingTarget !== null" preset="card" :title="`${closingTarget?.code ?? ''} · ${closingMode === 'close' ? '结账检查' : closingMode === 'reopen' ? '重开期间' : '结账记录'}`" :mask-closable="!busy" :style="{ width: 'min(1180px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' }" @update:show="value => { if (!value) closingTarget = null }">
      <div v-if="closingTarget && can('accounting_period.closing_view')" class="stack">
        <p v-if="checking" role="status">正在读取期间检查与证据…</p>
        <p v-if="closingError" role="alert">{{ closingError }} <AppButton :disabled="checking || connectionLost" @click="retryClosing" variant="text" type="button">重新读取</AppButton></p>
        <template v-if="closingMode === 'close' && closingCheck && !checking">
          <p>{{ closingCheck.period.start_date }} 至 {{ closingCheck.period.end_date }} · 业务按 UTC 日期归属</p>
          <p>{{ closingCheck.can_close ? '检查通过，可填写核对依据并结账。' : '尚不能结账，请先处理以下事项，再重新检查。' }}</p>
          <ul v-if="closingCheck.blockers.length"><li v-for="item in closingCheck.blockers" :key="item.code">{{ item.message }}<span v-if="item.ids.length">（记录编号：{{ item.ids.join('、') }}）</span></li></ul>
          <p>期末借方 / 贷方：{{ closingCheck.ledger_totals.closing_debit }} / {{ closingCheck.ledger_totals.closing_credit }} 元；库存金额：{{ closingCheck.inventory_total ?? '待核价' }} 元；库存流水 {{ closingCheck.movement_count }} 笔。</p>
          <ul><li v-for="warning in closingCheck.warnings" :key="warning">{{ warning }}</li></ul>
          <p class="muted">结账将锁定截至期末的凭证和历史成本来源。确认时服务端会重新核对，后续期间的收发与追加式更正继续可用。</p>
          <AppButton :disabled="checking || busy || connectionLost" @click="retryClosing" variant="secondary" type="button">重新检查</AppButton>
        </template>
        <template v-if="closingMode === 'reopen' && !checking && !closingError">
          <p>重开 {{ closingTarget.code }} 后可更正凭证和历史成本来源。原结账快照保留，更正后需要重新检查并结账。</p>
          <p v-if="laterClosed.length" role="alert">请先倒序重开：{{ laterClosed.map(item => item.code).join('、') }}。</p>
        </template>
        <form v-if="closingMode !== 'history' && !checking && !closingError && can(`accounting_period.${closingMode}`)" class="ledger-editor" @submit.prevent="confirmClosing">
          <label>核对依据 / 操作原因<AppInput v-model.trim="reason" required maxlength="200" :disabled="busy" placeholder="填写结账核对依据或重开更正原因" /></label>
          <div class="form-actions"><AppButton :disabled="busy || connectionLost || !reason.trim() || (closingMode === 'close' ? !closingCheck?.can_close : laterClosed.length > 0)" variant="primary" type="submit">{{ busy ? '正在处理…' : closingMode === 'close' ? '确认结账' : '确认重开' }}</AppButton><AppButton type="button" :disabled="busy" @click="closingTarget = null" variant="secondary">取消</AppButton></div>
        </form>
        <PeriodClosingHistory v-if="closingMode === 'history' && !checking && !closingError" />
        <p v-if="closingMode === 'close' && !can('accounting_period.close')" class="muted">当前账号可查看检查结果；结账需另行获得“结账会计期间”权限。</p>
      </div>
    </NModal>
  </section>
</template>
