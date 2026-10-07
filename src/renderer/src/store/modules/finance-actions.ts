import type { AppState } from '../state'
import { watch } from 'vue'
import type { PaymentRecord } from '../../../../shared/erp-api'

// 收付款操作独立维护；写入后由统一入口刷新服务端快照。
export function createFinanceActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const { paymentForm, reversalReasons, orderSettlementForm, orderSettlementReversalReasons } = state
  let owner = 0
  const connected = () => !!window.nexora && !state.connectionLost.value
  const can = (permission: string) => state.user.value?.permissions.includes(permission) ?? false
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`, () => { owner++ }, { flush: 'sync' })
  function guard(session: number, permission: string): void {
    // 排队期间切换服务端、账号或授权后，原动作不得写入另一实例或新会话。
    if (session !== owner || !connected() || !can(permission)) throw Error('资金操作会话或连接已变化，请重新读取。')
  }

  async function createPaymentRecord(): Promise<void> {
    if (!connected() || !can('finance.record')) return
    const session = owner; const input = { ...paymentForm.value }
    await perform(async () => {
      guard(session, 'finance.record')
      await window.nexora!.callApi('createPaymentRecord', input)
      if (session !== owner) return
      // 保存后清空金额和流水号，避免重复点击复用同一银行凭据。
      paymentForm.value.amount = ''
      paymentForm.value.reference = ''
      paymentForm.value.note = ''
    }, '收付款草稿已保存，独立批准执行后才更新订单余额。')
  }

  async function reversePaymentRecord(paymentId: number): Promise<void> {
    if (!connected() || !can('finance.reverse')) return
    const session = owner; const reason = reversalReasons.value[paymentId] ?? ''
    await perform(async () => {
      guard(session, 'finance.reverse')
      await window.nexora!.callApi('reversePaymentRecord', {
        paymentId,
        reason
      })
      if (session !== owner) return
      delete reversalReasons.value[paymentId]
    }, `反向收付款草稿已建立，须独立批准执行；原记录已保留。`)
  }

  async function changePaymentRecordStatus(item: PaymentRecord, action: 'post' | 'cancel', reason: string): Promise<void> {
    const permission = item.reverses_id ? 'finance.reverse' : 'finance.record'
    if (!connected() || !can(permission) || item.status !== 'draft'
      || action === 'post' && item.approval?.status !== 'approved'
      || action === 'cancel' && ['submitted', 'approved'].includes(item.approval?.status ?? '')) return
    const session = owner
    await perform(async () => {
      guard(session, permission)
      await window.nexora!.callApi('changePaymentRecordStatus', { id: item.id, version: item.version, action, reason })
    }, action === 'post' ? '资金已批准执行，订单余额已更新。' : '资金草稿已取消，未改变订单余额。')
  }

  async function createOrderSettlement(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createOrderSettlement', { ...orderSettlementForm.value })
      orderSettlementForm.value.amount = ''
      orderSettlementForm.value.reference = ''
      orderSettlementForm.value.reason = ''
    }, '订单间核销已登记，双方未结余额已更新。')
  }

  async function reverseOrderSettlement(transferId: number): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('reverseOrderSettlement', {
        transferId, reason: orderSettlementReversalReasons.value[transferId] ?? ''
      })
      delete orderSettlementReversalReasons.value[transferId]
    }, `订单核销 #${transferId} 已撤销，原记录已保留。`)
  }

  return { createPaymentRecord, reversePaymentRecord, changePaymentRecordStatus, createOrderSettlement, reverseOrderSettlement }
}
