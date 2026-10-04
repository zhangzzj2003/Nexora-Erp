import { watch } from 'vue'
import type { AppState } from '../state'

// 调节预览与输入绑定同一会话和草稿，避免复核期间切换账号后复用旧证据。
export function createBankBalanceActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  let owner = 0
  let previewKey = ''
  const available = (permission: string): boolean => !!window.nexora && !state.connectionLost.value
    && (state.user.value?.permissions.includes(permission) ?? false)
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.permissions.join('|')}`, () => {
    owner++
    previewKey = ''
    state.bankBalanceOverview.value = null
    state.bankBalancePreview.value = null
    state.bankBindingForm.value = { accountId: 0, ledger_account_id: 0, opening_balance: '', effective_date: '', version: 0, reason: '', opening_items: [] }
    state.bankBalanceForm.value = { account_id: 0, as_of_date: '', declared_bank_closing: '', reason: '' }
    state.bankLedgerMatchForm.value = { account_id: 0, bank_line_ids: [], journal_line_ids: [], reason: '' }
    state.bankLedgerReverseReasons.value = {}
    state.bankOpeningClearanceForm.value = { opening_item_id: 0, source_ids: [], reason: '' }
    state.bankOpeningReverseReasons.value = {}
    state.bankReportDecisionReasons.value = {}
  }, { flush: 'sync' })

  async function bindBankLedgerAccount(): Promise<void> {
    if (!available('bank_reconciliation.account')) return
    const session = owner
    const draft = { ...state.bankBindingForm.value,
      opening_items: state.bankBindingForm.value.opening_items.map(item => ({ ...item })) }
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.account')) return
      await window.nexora!.callApi('bindBankLedgerAccount', draft)
      if (session === owner) {
        state.bankBindingForm.value = { accountId: 0, ledger_account_id: 0, opening_balance: '', effective_date: '', version: 0, reason: '', opening_items: [] }
        state.bankBalancePreview.value = null
        previewKey = ''
      }
    }, '银行账户与总账科目已绑定，期初依据已留存。')
  }

  async function previewBankBalance(): Promise<void> {
    if (!available('bank_reconciliation.view')) return
    const session = owner
    const draft = { ...state.bankBalanceForm.value }
    const input = { account_id: draft.account_id, as_of_date: draft.as_of_date,
      declared_bank_closing: draft.declared_bank_closing }
    state.bankBalancePreview.value = null
    previewKey = ''
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.view')) return
      const result = await window.nexora!.callApi('previewBankBalance', input)
      if (session === owner && !state.connectionLost.value
        && JSON.stringify(input) === JSON.stringify({ account_id: state.bankBalanceForm.value.account_id,
          as_of_date: state.bankBalanceForm.value.as_of_date,
          declared_bank_closing: state.bankBalanceForm.value.declared_bank_closing })) {
        state.bankBalancePreview.value = result
        previewKey = JSON.stringify(input)
      }
    }, '银行余额调节预览已更新。')
  }

  async function matchBankLedger(): Promise<void> {
    if (!available('bank_reconciliation.match')) return
    const session = owner
    const draft = { ...state.bankLedgerMatchForm.value,
      bank_line_ids: [...state.bankLedgerMatchForm.value.bank_line_ids],
      journal_line_ids: [...state.bankLedgerMatchForm.value.journal_line_ids] }
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.match')) return
      await window.nexora!.callApi('matchBankLedger', draft)
      if (session === owner) {
        state.bankLedgerMatchForm.value = { account_id: draft.account_id, bank_line_ids: [], journal_line_ids: [], reason: '' }
        state.bankBalancePreview.value = null
        previewKey = ''
      }
    }, '银行流水与已过账分录已勾对。')
  }

  async function clearBankOpeningItem(): Promise<void> {
    if (!available('bank_reconciliation.match')) return
    const session = owner
    const form = state.bankOpeningClearanceForm.value
    const draft = { openingItemId: form.opening_item_id, source_ids: [...form.source_ids], reason: form.reason }
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.match')) return
      await window.nexora!.callApi('clearBankOpeningItem', draft)
      if (session === owner) {
        state.bankOpeningClearanceForm.value = { opening_item_id: 0, source_ids: [], reason: '' }
        state.bankBalancePreview.value = null
        previewKey = ''
      }
    }, '期初未达项已核销，证据已留存。')
  }

  async function reverseBankOpeningClearance(clearanceId: number): Promise<void> {
    if (!available('bank_reconciliation.reverse')) return
    const session = owner
    const reason = state.bankOpeningReverseReasons.value[clearanceId] ?? ''
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.reverse')) return
      await window.nexora!.callApi('reverseBankOpeningClearance', { clearanceId, reason })
      if (session === owner) {
        delete state.bankOpeningReverseReasons.value[clearanceId]
        state.bankBalancePreview.value = null
        previewKey = ''
      }
    }, `期初未达项核销 #${clearanceId} 已撤销。`)
  }

  async function reverseBankLedgerMatch(groupId: number): Promise<void> {
    if (!available('bank_reconciliation.reverse')) return
    const session = owner
    const reason = state.bankLedgerReverseReasons.value[groupId] ?? ''
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.reverse')) return
      await window.nexora!.callApi('reverseBankLedgerMatch', { groupId, reason })
      if (session === owner) {
        delete state.bankLedgerReverseReasons.value[groupId]
        state.bankBalancePreview.value = null
        previewKey = ''
      }
    }, `总账勾对 #${groupId} 已撤销。`)
  }

  async function createBankBalanceReport(): Promise<void> {
    if (!available('bank_reconciliation.reconcile')) return
    const session = owner
    const draft = { ...state.bankBalanceForm.value }
    const key = JSON.stringify({ account_id: draft.account_id, as_of_date: draft.as_of_date,
      declared_bank_closing: draft.declared_bank_closing })
    if (!state.bankBalancePreview.value || previewKey !== key) return
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.reconcile')
        || key !== JSON.stringify({ account_id: state.bankBalanceForm.value.account_id,
          as_of_date: state.bankBalanceForm.value.as_of_date,
          declared_bank_closing: state.bankBalanceForm.value.declared_bank_closing })) return
      await window.nexora!.callApi('createBankBalanceReport', draft)
      if (session === owner) {
        state.bankBalanceForm.value.reason = ''
        state.bankBalancePreview.value = null
        previewKey = ''
      }
    }, '银行余额调节草稿已留存，等待独立复核。')
  }

  async function decideBankBalanceReport(reportId: number, action: 'approve' | 'reject'): Promise<void> {
    if (!available('bank_reconciliation.review')) return
    const session = owner
    const reason = state.bankReportDecisionReasons.value[reportId] ?? ''
    await perform(async () => {
      if (session !== owner || !available('bank_reconciliation.review')) return
      await window.nexora!.callApi('decideBankBalanceReport', { reportId, action, reason })
      if (session === owner) delete state.bankReportDecisionReasons.value[reportId]
    }, action === 'approve' ? '银行余额调节表已复核。' : '银行余额调节表已驳回。')
  }

  return { bindBankLedgerAccount, previewBankBalance, matchBankLedger,
    clearBankOpeningItem, reverseBankOpeningClearance,
    reverseBankLedgerMatch, createBankBalanceReport, decideBankBalanceReport }
}
