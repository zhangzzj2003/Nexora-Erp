import { watch } from 'vue'
import type { SubledgerOrderSettlement, SubledgerOrderSettlementInput } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createSubledgerOrderActions(state: AppState, perform: (run: () => Promise<unknown>, success: string) => Promise<void>,
  refreshHistory: () => Promise<void>) {
  let owner = 0; let ticket = 0
  const can = (permission: string) => state.user.value?.permissions.includes(permission) ?? false
  const connected = () => !!window.nexora && !state.connectionLost.value
  function clear(): void {
    ticket++; state.subledgerOrderSettlements.value = []; state.subledgerOrderOptions.value = null
    state.subledgerOrderLoading.value = false; state.subledgerOrderError.value = ''
  }
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`,
    () => { owner++; clear() }, { flush: 'sync' })
  watch(state.connectionLost, clear, { flush: 'sync' })
  async function loadSubledgerOrders(): Promise<boolean> {
    if (!can('subledger_order_settlement.view') || !connected()) return false
    const current = ++ticket; const session = owner
    state.subledgerOrderLoading.value = true; state.subledgerOrderError.value = ''
    state.subledgerOrderSettlements.value = []; state.subledgerOrderOptions.value = null
    try {
      const [records, options] = await Promise.all([window.nexora!.callApi('subledgerOrderSettlements', undefined),
        window.nexora!.callApi('subledgerOrderOptions', undefined)])
      if (current !== ticket || session !== owner || !can('subledger_order_settlement.view')) return false
      state.subledgerOrderSettlements.value = records; state.subledgerOrderOptions.value = options; return true
    } catch (cause) {
      if (current === ticket && session === owner) state.subledgerOrderError.value = displayError(cause)
      return false
    } finally { if (current === ticket && session === owner) state.subledgerOrderLoading.value = false }
  }
  async function write(permission: string, run: () => Promise<unknown>, message: string): Promise<boolean> {
    if (!can('subledger_order_settlement.view') || !can(permission) || !connected() || state.busy.value) return false
    const session = owner; let saved = false
    await perform(async () => {
      // 排队发送时复核实例、证书、账号及两类权限，避免跨会话写入。
      if (session !== owner || !can(permission) || !can('subledger_order_settlement.view') || !connected()) throw Error('会话或权限已变化，请重新打开历史与订单核销。')
      await run(); saved = session === owner
    }, message)
    if (!saved || session !== owner || !can(permission) || !can('subledger_order_settlement.view')) return false
    await loadSubledgerOrders()
    if (session !== owner) return false
    await refreshHistory()
    return session === owner
  }
  return { loadSubledgerOrders,
    createSubledgerOrderSettlement: (input: SubledgerOrderSettlementInput) => write('finance.record',
      () => window.nexora!.callApi('createSubledgerOrderSettlement', { ...input }), '核销草稿已保存，批准执行后更新历史原单与订单余额。'),
    changeSubledgerOrderSettlementStatus: (row: SubledgerOrderSettlement, action: 'post' | 'cancel', reason: string) => {
      if (row.status !== 'draft' || action === 'post' && row.approval?.status !== 'approved'
        || action === 'cancel' && ['submitted', 'approved'].includes(row.approval?.status ?? '')) return Promise.resolve(false)
      return write(row.reverses_id ? 'finance.reverse' : 'finance.record',
        () => window.nexora!.callApi('changeSubledgerOrderSettlementStatus', { id: row.id, version: row.version, action, reason }),
        action === 'post' ? '历史与订单核销已执行。' : '核销草稿已取消。')
    },
    reverseSubledgerOrderSettlement: (id: number, reason: string) => write('finance.reverse',
      () => window.nexora!.callApi('reverseSubledgerOrderSettlement', { id, reason }), '等额反向草稿已保存，批准执行后恢复双方余额。') }
}
