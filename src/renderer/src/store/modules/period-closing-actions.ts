import { watch } from 'vue'
import type { AccountingPeriod } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createPeriodClosingActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let ticket = 0
  let sessionTicket = 0
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  function clear(): void {
    state.periodClosingCheck.value = null
    state.periodClosingHistory.value = []
    state.periodClosingError.value = ''
  }
  watch(() => `${state.user.value?.id}:${state.user.value?.permissions.join('|')}`, () => {
    ticket++; sessionTicket++
    clear(); state.periodClosingLoading.value = false
  }, { flush: 'sync' })
  async function load(id: number, kind: 'check' | 'history'): Promise<boolean> {
    if (!window.nexora || !can('accounting_period.closing_view') || state.connectionLost.value) return false
    const request = ++ticket
    clear(); state.periodClosingLoading.value = true
    try {
      if (kind === 'check') {
        const result = await window.nexora.callApi('periodClosingCheck', { id })
        if (request !== ticket || !can('accounting_period.closing_view')) return false
        state.periodClosingCheck.value = result
      } else {
        state.periodClosingHistoryId.value = id
        const page = await window.nexora.callApi('queryTable', { dataset: 'periodClosingHistory', query: '', page: 1, page_size: 20, filters: { period_id: id } })
        const result = page.items as unknown as typeof state.periodClosingHistory.value
        if (request !== ticket || !can('accounting_period.closing_view')) return false
        state.periodClosingHistory.value = result
      }
      return true
    } catch (error) {
      if (request === ticket) state.periodClosingError.value = displayError(error)
      return false
    } finally {
      if (request === ticket) state.periodClosingLoading.value = false
    }
  }
  async function changePeriodClosingStatus(period: AccountingPeriod, action: 'close' | 'reopen', reason: string): Promise<boolean> {
    if (!window.nexora || !can(`accounting_period.${action}`) || state.connectionLost.value || state.busy.value) return false
    let saved = false
    const session = sessionTicket
    await perform(async () => {
      await window.nexora!.callApi('changePeriodClosingStatus', { id: period.id, version: period.version, action, reason })
      saved = session === sessionTicket && can(`accounting_period.${action}`)
    }, action === 'close' ? '期间已结账，结账证据已保存，历史成本来源已锁定。' : '期间已重开，原结账证据保留，请核对更正后重新结账。')
    return saved
  }
  return { loadPeriodClosingCheck: (id: number) => load(id, 'check'),
    loadPeriodClosingHistory: (id: number) => load(id, 'history'), changePeriodClosingStatus }
}
