import type { ReportQuery } from '../../../../shared/erp-api'
import type { AppState } from '../state'

// 采购报表继续导出查询快照；库存报表分页与完整导出由独立操作模块维护。
export function createReportActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const { purchaseReportQuery, purchaseReportResult, notice } = state

  async function run(): Promise<void> {
    if (!window.nexora) return
    const query = purchaseReportQuery
    const result = purchaseReportResult
    await perform(async () => {
      const filters: ReportQuery = { ...query.value,
        from_date: query.value.from_date || null,
        to_date: query.value.to_date || null }
      result.value = await window.nexora!.callApi('queryReport', filters)
    }, '报表已更新。')
  }

  async function exportResult(): Promise<void> {
    if (!window.nexora) return
    const result = purchaseReportResult.value
    if (!result) return
    let saved = false
    await perform(async () => {
      const fileName = `${result.kind}-${new Date().toISOString().slice(0, 10)}.csv`
      saved = Boolean(await window.nexora!.saveReportCsv(fileName, result.csv))
    }, 'CSV 已保存。')
    if (!saved && notice.value === 'CSV 已保存。') notice.value = ''
  }

  return { queryPurchaseReport: run, exportPurchaseReport: exportResult }
}
