import { watch } from 'vue'
import type { AccountingPeriod } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createPeriodClosingActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let ticket = 0
  let sessionTicket = 0
  let targetKey = ''
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  function clear(): void {
    state.periodClosingCheck.value = null
    state.periodClosingHistory.value = []
    state.periodClosingError.value = ''
  }
  function closePeriodClosing(): void {
    // 等待期间取消也递增代次，防止迟到检查恢复已关闭的弹窗。
    ticket++; targetKey = ''; clear(); state.periodClosingLoading.value = false
  }
  // 角色与权限按集合比较，副本排序不会修改用户快照，例行返回顺序变化也不取消读取。
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.slice().sort().join('|')}:${state.user.value?.permissions.slice().sort().join('|')}:${state.connectionLost.value}`, () => {
    sessionTicket++; closePeriodClosing()
  }, { flush: 'sync' })
  async function load(id: number, kind: 'check' | 'history'): Promise<boolean> {
    if (!window.nexora || !can('accounting_period.closing_view') || state.connectionLost.value) return false
    const request = ++ticket
    const nextTarget = `${kind}:${id}`
    // 同一期间刷新保留检查依据；换期间或切换检查类型才清空旧正文。
    if (targetKey !== nextTarget) clear()
    targetKey = nextTarget
    state.periodClosingError.value = ''; state.periodClosingLoading.value = true
    try {
      if (kind === 'check') {
        const result = await window.nexora.callApi('periodClosingCheck', { id })
        if (request !== ticket || !can('accounting_period.closing_view') || state.connectionLost.value) return false
        state.periodClosingCheck.value = result
      } else {
        const result = await window.nexora.callApi('periodClosingHistory', { id })
        if (request !== ticket || !can('accounting_period.closing_view') || state.connectionLost.value) return false
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
    if (!window.nexora || !can(`accounting_period.${action}`) || state.connectionLost.value || state.busy.value
      || state.periodClosingLoading.value || !!state.periodClosingError.value) return false
    let saved = false
    const session = sessionTicket
    await perform(async () => {
      if (session !== sessionTicket || state.connectionLost.value || !can(`accounting_period.${action}`)
        || state.periodClosingLoading.value || !!state.periodClosingError.value) throw Error('期间检查或会话已变化，请重新读取。')
      await window.nexora!.callApi('changePeriodClosingStatus', { id: period.id, version: period.version, action, reason })
      saved = session === sessionTicket && can(`accounting_period.${action}`)
    }, action === 'close' ? '期间已结账，结账证据已保存，历史成本来源已锁定。' : '期间已重开，原结账证据保留，请核对更正后重新结账。')
    return saved
  }
  return { loadPeriodClosingCheck: (id: number) => load(id, 'check'),
    loadPeriodClosingHistory: (id: number) => load(id, 'history'), closePeriodClosing, changePeriodClosingStatus }
}
