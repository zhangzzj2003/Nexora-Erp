import { watch } from 'vue'
import type { AppState } from '../state'

// 银行凭据与勾对原因属于跨页面草稿；写入失败时保留，成功后由统一快照刷新。
export function createBankReconciliationActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  let owner = 0
  let previewKey = ''
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const available = (permission: string): boolean => !!window.nexora && !state.connectionLost.value && can(permission)
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.permissions.join('|')}`, () => {
    owner++
    previewKey = ''
    state.bankOverview.value = null
    state.bankAccountForm.value = { code: '', name: '' }
    state.bankCsvForm.value = { account_id: 0, file_name: '', content_base64: '' }
    state.bankCsvPreview.value = null
    state.bankLineForm.value = { account_id: 0, transaction_id: '', occurred_on: '', amount: '', counterparty: '', note: '' }
    state.bankMatchForm.value = { statement_line_id: 0, source_type: 'order_payment', source_id: 0, reason: '' }
    state.bankReverseReasons.value = {}
  }, { flush: 'sync' })

  async function createBankAccount(): Promise<void> {
    if (!available('bank_reconciliation.account')) return
    const session = owner
    const draft = { ...state.bankAccountForm.value }
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.account')) return
      await window.nexora!.callApi('createBankAccount', draft)
      if (session === owner) state.bankAccountForm.value = { code: '', name: '' }
    }, '银行账户已登记。')
  }

  async function importBankLine(): Promise<void> {
    if (!available('bank_reconciliation.record')) return
    const session = owner
    const { account_id, ...line } = state.bankLineForm.value
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.record')) return
      await window.nexora!.callApi('importBankLines', { account_id, lines: [line] })
      if (session === owner) state.bankLineForm.value = { account_id, transaction_id: '', occurred_on: '', amount: '', counterparty: '', note: '' }
    }, '银行流水已登记。')
  }

  async function previewBankCsv(): Promise<void> {
    if (!available('bank_reconciliation.record')) return
    const session = owner
    const draft = { ...state.bankCsvForm.value }
    state.bankCsvPreview.value = null
    previewKey = ''
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.record')) return
      const preview = await window.nexora!.callApi('previewBankCsv', draft)
      if (session === owner && !state.connectionLost.value
        && JSON.stringify(draft) === JSON.stringify(state.bankCsvForm.value)) {
        state.bankCsvPreview.value = preview
        previewKey = JSON.stringify(draft)
      }
    }, 'CSV 预检完成。')
  }

  async function importBankCsv(): Promise<void> {
    if (!available('bank_reconciliation.record') || !state.bankCsvPreview.value?.can_import
      || previewKey !== JSON.stringify(state.bankCsvForm.value)) return
    const session = owner
    const draft = { ...state.bankCsvForm.value }
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.record')
        || JSON.stringify(draft) !== JSON.stringify(state.bankCsvForm.value)) return
      await window.nexora!.callApi('importBankCsv', draft)
      if (session === owner) {
        previewKey = ''
        state.bankCsvForm.value = { account_id: 0, file_name: '', content_base64: '' }
        state.bankCsvPreview.value = null
      }
    }, '银行 CSV 已整批导入，来源摘要已记录。')
  }

  async function matchBankLine(): Promise<void> {
    if (!available('bank_reconciliation.match')) return
    const session = owner
    const draft = { ...state.bankMatchForm.value }
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.match')) return
      await window.nexora!.callApi('matchBankLine', draft)
      if (session === owner) state.bankMatchForm.value = { statement_line_id: 0, source_type: 'order_payment', source_id: 0, reason: '' }
    }, '银行流水与收付款记录已勾对。')
  }

  async function reverseBankMatch(matchId: number): Promise<void> {
    if (!available('bank_reconciliation.reverse')) return
    const session = owner
    const reason = state.bankReverseReasons.value[matchId] ?? ''
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.reverse')) return
      await window.nexora!.callApi('reverseBankMatch', { matchId, reason })
      if (session === owner) delete state.bankReverseReasons.value[matchId]
    }, `银行勾对 #${matchId} 已撤销，原证据保留。`)
  }

  return { createBankAccount, importBankLine, previewBankCsv, importBankCsv, matchBankLine, reverseBankMatch }
}
