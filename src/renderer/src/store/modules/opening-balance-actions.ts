import { watch } from 'vue'
import type { OpeningBalance, OpeningBalanceAction } from '../../../../shared/erp-api'
import type { AppState } from '../state'

export function createOpeningBalanceActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let optionsTicket = 0
  let sessionTicket = 0
  const identity = () => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`
  let owner = identity()
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const emptyForm = () => ({ id: null, version: 1, reference: '', effective_date: '', note: '', reason: '', lines: [] })
  watch(identity, () => {
    optionsTicket++
    sessionTicket++
    const changedOwner = owner !== identity()
    owner = identity()
    if (changedOwner || !can('opening_balance.view')) state.openingBalances.value = []
    if (changedOwner || !can('opening_balance.create')) {
      state.openingBalanceOptions.value = { accounts: [], period: null }
      state.openingBalanceForm.value = emptyForm()
    }
  }, { flush: 'sync' })
  async function editOpeningBalance(item?: OpeningBalance): Promise<boolean> {
    if (!window.nexora || !can('opening_balance.create') || state.connectionLost.value) return false
    const ticket = ++optionsTicket
    const options = await window.nexora.callApi('openingBalanceOptions', undefined)
    if (ticket !== optionsTicket || !can('opening_balance.create')) return false
    state.openingBalanceOptions.value = options
    state.openingBalanceForm.value = item ? {
      id: item.id, version: item.version, reference: item.reference, effective_date: item.effective_date, note: item.note,
      reason: '', lines: item.lines.map(({ account_id, summary, debit, credit, auxiliary }) => ({ account_id, summary, debit, credit, ...(auxiliary ? { auxiliary: auxiliary.map(({ kind, id }) => ({ kind, id })) } : {}) }))
    } : { ...emptyForm(), effective_date: options.period?.start_date ?? '',
      lines: [1,2].map(() => ({ account_id: 0, summary: '', debit: '0', credit: '0' })) }
    return true
  }
  async function saveOpeningBalance(): Promise<boolean> {
    if (!window.nexora || !can('opening_balance.create') || state.connectionLost.value) return false
    let saved = false
    const ticket = sessionTicket
    await perform(async () => {
      // 排队中的写入不能在服务端、账号或权限改变后发送到另一个会话。
      if (ticket !== sessionTicket || !can('opening_balance.create') || state.connectionLost.value) throw new Error('会话或连接已变化，请重新打开期初方案。')
      const { id, version, reference, effective_date, note, reason, lines } = state.openingBalanceForm.value
      const input = { reference, effective_date, note, reason,
        lines: lines.map(({ account_id, summary, debit, credit, auxiliary }) => ({ account_id, summary, debit, credit, ...(auxiliary ? { auxiliary: auxiliary.map(({ kind, id }) => ({ kind, id })) } : {}) })) }
      if (id === null) await window.nexora!.callApi('createOpeningBalance', input)
      else await window.nexora!.callApi('updateOpeningBalance', { ...input, id, version })
      if (ticket === sessionTicket && can('opening_balance.create')) {
        state.openingBalanceForm.value = emptyForm()
        saved = true
      }
    }, '期初草稿已保存，须由另一账号审核并确认后才进入总账。')
    return saved
  }
  async function changeOpeningBalanceStatus(item: OpeningBalance, action: OpeningBalanceAction, reason: string): Promise<boolean> {
    if (['submit', 'approve', 'reject'].includes(action)) return false
    if (action === 'confirm' && item.approval?.status !== 'approved') return false
    if (action === 'reverse' && item.reversal_approval?.status !== 'approved') return false
    if (action === 'cancel' && ['submitted', 'approved'].includes(item.approval?.status ?? '')) return false
    const permission = ['approve','reject'].includes(action) ? 'opening_balance.review' : `opening_balance.${action}`
    if (!window.nexora || !can(permission) || state.connectionLost.value) return false
    let saved = false
    const ticket = sessionTicket
    await perform(async () => {
      if (ticket !== sessionTicket || !can(permission) || state.connectionLost.value) throw new Error('会话或连接已变化，请重新打开期初方案。')
      await window.nexora!.callApi('changeOpeningBalanceStatus', { id: item.id, version: item.version, action, reason })
      saved = ticket === sessionTicket && can(permission)
    }, '期初余额状态已更新。')
    return saved
  }
  async function loadOpeningBalanceChanges(id: number) {
    if (!window.nexora || !can('opening_balance.view')) throw new Error('没有查看期初记录的权限。')
    return window.nexora.callApi('openingBalanceChanges', { id })
  }
  return { editOpeningBalance, saveOpeningBalance, changeOpeningBalanceStatus, loadOpeningBalanceChanges }
}
