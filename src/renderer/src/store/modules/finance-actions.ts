import type { AppState } from '../state'

// 收付款操作独立维护；写入后由统一入口刷新服务端快照。
export function createFinanceActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const { paymentForm, reversalReasons, orderSettlementForm, orderSettlementReversalReasons } = state

  async function createPaymentRecord(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createPaymentRecord', {
        ...paymentForm.value
      })
      // 保存后清空金额和流水号，避免重复点击复用同一银行凭据。
      paymentForm.value.amount = ''
      paymentForm.value.reference = ''
      paymentForm.value.note = ''
    }, '收付款记录已保存，订单余额已更新。')
  }

  async function reversePaymentRecord(paymentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('reversePaymentRecord', {
        paymentId,
        reason: reversalReasons.value[paymentId] ?? ''
      })
      delete reversalReasons.value[paymentId]
    }, `收付款记录 #${paymentId} 已冲销，原记录已保留。`)
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

  return { createPaymentRecord, reversePaymentRecord, createOrderSettlement, reverseOrderSettlement }
}
