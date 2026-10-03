import { watch } from 'vue'
import type { AppState } from '../state'

// 银行凭据与勾对原因属于跨页面草稿；写入失败时保留，成功后由统一快照刷新。
export function createBankReconciliationActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  let owner = 0
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const available = (permission: string): boolean => !!window.nexora && !state.connectionLost.value && can(permission)
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.permissions.join('|')}`, () => {
    owner++
    state.bankOverview.value = null
    state.bankAccountForm.value = { code: '', name: '' }
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

  return { createBankAccount, importBankLine, matchBankLine, reverseBankMatch }
}
