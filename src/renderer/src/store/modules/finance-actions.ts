import { createRequestScope } from '../../utils/request-scope.ts'
import type { AppState } from '../state'

// 收付款操作独立维护；写入后由统一入口刷新服务端快照。
export function createFinanceActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const requestScope = state.user ? createRequestScope(state) : null
  const { paymentForm, reversalReasons } = state

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

  async function runFinanceTool(action: import('../../../../shared/erp-api').FinanceToolAction, payload: Record<string, unknown>): Promise<void> {
    if (!window.nexora) return
    const owner = requestScope!.capture()
    await perform(async () => {
      const result = await window.nexora!.callApi('financeTools', { action, payload })
      // 账号变化后不能把旧账户的财务结果填回页面。
      if (requestScope!.current(owner)) state.financeToolResult.value = result
    }, '财务处理完成，查询结果已保留。')
  }
  async function exportFinanceTool(): Promise<void> {
    const result = state.financeToolResult.value
    if (!window.nexora || !result) return
    await perform(async () => {
      const { csv } = await window.nexora!.callApi('snapshotCsv', { snapshot_id: result.snapshot_id })
      await window.nexora!.saveReportCsv('财务核对.csv', csv)
    }, '财务核对结果已导出。')
  }
  return { createPaymentRecord, reversePaymentRecord, runFinanceTool, exportFinanceTool }
}
