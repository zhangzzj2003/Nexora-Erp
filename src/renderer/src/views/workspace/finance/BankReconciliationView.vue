<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { submitCreateDialog } from '../../../utils/create-dialog'
import { usePiniaAppStore } from '../../../store/app-store'

const store = usePiniaAppStore()
const { bankOverview, bankAccountForm, bankLineForm, bankMatchForm, bankReverseReasons,
  busy, error, notice, connectionLost } = storeToRefs(store)
const { can, localTime, createBankAccount, importBankLine, matchBankLine, reverseBankMatch } = store
const accountOpen = ref(false)
const lineOpen = ref(false)
const matchOpen = ref(false)

const unmatchedLines = computed(() => bankOverview.value?.lines.filter(item => item.match_id === null) ?? [])
const unmatchedSources = computed(() => bankOverview.value?.sources.filter(item => item.match_id === null) ?? [])
const selectedLine = computed(() => unmatchedLines.value.find(item => item.id === bankMatchForm.value.statement_line_id))
const candidateSources = computed(() => unmatchedSources.value.filter(item =>
  selectedLine.value && item.bank_amount === selectedLine.value.amount))
const lineFor = (id: number) => bankOverview.value?.lines.find(item => item.id === id)
const sourceFor = (kind: string, id: number) => bankOverview.value?.sources.find(item => item.source_type === kind && item.source_id === id)
const sourceOptions = computed(() => candidateSources.value.map(item => ({
  value: `${item.source_type}:${item.source_id}`,
  label: `${item.label} · #${item.source_id} · ${item.reference} · ¥${item.bank_amount}`
})))
const selectedSourceKey = computed({
  get: () => `${bankMatchForm.value.source_type}:${bankMatchForm.value.source_id}`,
  set: (key: string) => {
    const [kind, id] = key.split(':')
    if ((kind === 'order_payment' || kind === 'subledger_payment') && Number.isSafeInteger(Number(id))) {
      bankMatchForm.value.source_type = kind
      bankMatchForm.value.source_id = Number(id)
    }
  }
})
function beginMatch(lineId: number): void {
  bankMatchForm.value.statement_line_id = lineId
  bankMatchForm.value.source_id = 0
  bankMatchForm.value.reason = ''
  matchOpen.value = true
}
async function submitAccount(): Promise<void> {
  if (connectionLost.value || !can('bank_reconciliation.account')) return
  await submitCreateDialog(createBankAccount, { busy, error, notice }, accountOpen)
}
async function submitLine(): Promise<void> {
  if (connectionLost.value || !can('bank_reconciliation.record')) return
  await submitCreateDialog(importBankLine, { busy, error, notice }, lineOpen)
}
async function submitMatch(): Promise<void> {
  if (connectionLost.value || !can('bank_reconciliation.match')) return
  await submitCreateDialog(matchBankLine, { busy, error, notice }, matchOpen)
}
const lineColumns = [{ key: 'document', title: '银行流水' }, { key: 'actions', title: '勾对', width: '170' }]
const matchColumns = [{ key: 'document', title: '勾对证据' }, { key: 'actions', title: '操作', width: '280' }]
</script>

<template>
  <section class="stack">
    <div class="section-heading">
      <div><p class="eyebrow">BANK RECONCILIATION</p><h2>银行流水勾对</h2></div>
    </div>
    <p class="muted">将人工取得的银行流水逐笔登记，再与订单或历史分户收付款按金额和方向勾对。登记内容需与银行原始凭据核实；本页不连接银行，也不生成会计凭证。</p>
    <div class="form-grid">
      <div>银行账户：{{ bankOverview?.accounts.length ?? 0 }} 个</div>
      <div>待勾对流水：{{ unmatchedLines.length }} 笔</div>
      <div>待勾对收付款：{{ unmatchedSources.length }} 笔</div>
    </div>

    <NModal v-if="can('bank_reconciliation.account')" v-model:show="accountOpen" preset="card"
      :mask-closable="!busy" :style="{ width: 'min(640px, calc(100vw - 32px))' }">
      <h2>登记银行账户</h2>
      <form @submit.prevent="submitAccount">
        <div class="form-grid">
          <label>账户编码<AppInput v-model.trim="bankAccountForm.code" required maxlength="32" pattern="[A-Z0-9][A-Z0-9_-]*" /></label>
          <label>账户名称<AppInput v-model.trim="bankAccountForm.name" required maxlength="80" /></label>
        </div>
        <AppButton type="submit" variant="primary" :disabled="busy || connectionLost">保存账户</AppButton>
      </form>
    </NModal>

    <NModal v-if="can('bank_reconciliation.record')" v-model:show="lineOpen" preset="card"
      :mask-closable="!busy" :style="{ width: 'min(800px, calc(100vw - 32px))' }">
      <h2>登记银行流水</h2>
      <form @submit.prevent="submitLine">
        <div class="form-grid">
          <label>银行账户<WorkspaceSelect v-model="bankLineForm.account_id" required
            :options="(bankOverview?.accounts ?? []).map(item => ({ value: item.id, label: `${item.code} · ${item.name}` }))" /></label>
          <label>银行交易号<AppInput v-model.trim="bankLineForm.transaction_id" required maxlength="100" /></label>
          <label>交易日期<AppInput v-model.trim="bankLineForm.occurred_on" required maxlength="10" placeholder="YYYY-MM-DD" /></label>
          <label>收支金额（入账为正，出账为负）<AppInput v-model.trim="bankLineForm.amount" required placeholder="例如 125.00 或 -125.00" /></label>
          <label>对方户名<AppInput v-model.trim="bankLineForm.counterparty" maxlength="120" /></label>
          <label>备注<AppInput v-model.trim="bankLineForm.note" maxlength="200" /></label>
        </div>
        <AppButton type="submit" variant="primary" :disabled="busy || connectionLost">登记流水</AppButton>
      </form>
    </NModal>

    <NModal v-if="can('bank_reconciliation.match')" v-model:show="matchOpen" preset="card"
      :mask-closable="!busy" :style="{ width: 'min(800px, calc(100vw - 32px))' }">
      <h2>逐笔勾对</h2>
      <p class="muted">银行流水 #{{ selectedLine?.id }} · {{ selectedLine?.account_code }} · ¥{{ selectedLine?.amount }}</p>
      <form @submit.prevent="submitMatch">
        <div class="form-grid">
          <label>同金额、同方向的收付款<WorkspaceSelect v-model="selectedSourceKey" required :options="sourceOptions" /></label>
          <label>勾对依据<AppInput v-model.trim="bankMatchForm.reason" required maxlength="200" placeholder="填写核对的银行凭据或原因" /></label>
        </div>
        <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !candidateSources.length">确认勾对</AppButton>
      </form>
    </NModal>

    <WorkspaceTable title="待勾对银行流水" :columns="lineColumns" :data="unmatchedLines" :min-table-width="850">
      <template #actions>
        <AppButton v-if="can('bank_reconciliation.account')" type="button" @click="accountOpen = true">登记账户</AppButton>
        <AppButton v-if="can('bank_reconciliation.record')" type="button" variant="primary" :disabled="!bankOverview?.accounts.length" @click="lineOpen = true">登记流水</AppButton>
      </template>
      <template #cell-document="{ row: item }">
        <strong>#{{ item.id }} · {{ item.account_code }} · ¥{{ item.amount }}</strong>
        <p class="muted">{{ item.occurred_on }} · 交易号 {{ item.transaction_id }} · {{ item.counterparty }} · 登记人 {{ item.created_by_name }}<span v-if="item.note"> · {{ item.note }}</span></p>
      </template>
      <template #cell-actions="{ row: item }">
        <AppButton v-if="can('bank_reconciliation.match')" type="button" :disabled="busy || connectionLost" @click="beginMatch(item.id)">选择收付款</AppButton>
      </template>
    </WorkspaceTable>

    <WorkspaceTable title="勾对与撤销历史" :columns="matchColumns" :data="bankOverview?.matches ?? []" :min-table-width="900">
      <template #cell-document="{ row: item }">
        <strong>#{{ item.id }} · 流水 #{{ item.statement_line_id }} ↔ {{ item.source_type === 'order_payment' ? '订单收付款' : '历史分户收付款' }} #{{ item.source_id }}</strong>
        <p class="muted">{{ lineFor(item.statement_line_id)?.account_code }} · 交易号 {{ lineFor(item.statement_line_id)?.transaction_id }} · ¥{{ lineFor(item.statement_line_id)?.amount }} · {{ sourceFor(item.source_type, item.source_id)?.reference }}</p>
        <p class="muted">{{ localTime(item.created_at) }} · {{ item.created_by_name }} · 依据：{{ item.reason }}</p>
        <p v-if="item.reversal" class="muted">已撤销 · {{ localTime(item.reversal.created_at) }} · {{ item.reversal.created_by_name }} · {{ item.reversal.reason }}</p>
      </template>
      <template #cell-actions="{ row: item }">
        <form v-if="!item.reversal && can('bank_reconciliation.reverse')" @submit.prevent="reverseBankMatch(item.id)">
          <AppInput v-model.trim="bankReverseReasons[item.id]" required maxlength="200" placeholder="撤销原因" />
          <AppButton type="submit" :disabled="busy || connectionLost">撤销勾对</AppButton>
        </form>
      </template>
    </WorkspaceTable>
  </section>
</template>
