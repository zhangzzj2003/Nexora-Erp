import type { ReportQuery } from '../../../../shared/erp-api'
import type { AppState } from '../state'

// 报表查询和导出都只使用服务端返回的同一个结果快照。
export function createReportActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const { purchaseReportQuery, inventoryReportQuery,
    purchaseReportResult, inventoryReportResult, notice } = state

  async function run(domain: 'purchase' | 'inventory'): Promise<void> {
    if (!window.nexora) return
    const query = domain === 'purchase' ? purchaseReportQuery : inventoryReportQuery
    const result = domain === 'purchase' ? purchaseReportResult : inventoryReportResult
    await perform(async () => {
      const filters: ReportQuery = { ...query.value, paged: true,
        from_date: query.value.from_date || null,
        to_date: query.value.to_date || null }
      result.value = await window.nexora!.callApi('queryReport', filters)
    }, '报表已更新。')
  }

  async function exportResult(domain: 'purchase' | 'inventory'): Promise<void> {
    if (!window.nexora) return
    const result = (domain === 'purchase' ? purchaseReportResult : inventoryReportResult).value
    if (!result) return
    let saved = false
    await perform(async () => {
      const fileName = `${result.kind}-${new Date().toISOString().slice(0, 10)}.csv`
      const csv = result.snapshot_id ? (await window.nexora!.callApi('snapshotCsv', { snapshot_id: result.snapshot_id })).csv : result.csv
      saved = Boolean(await window.nexora!.saveReportCsv(fileName, csv))
    }, 'CSV 已保存。')
    if (!saved && notice.value === 'CSV 已保存。') notice.value = ''
  }

  return {
    queryPurchaseReport: () => run('purchase'),
    queryInventoryReport: () => run('inventory'),
    exportPurchaseReport: () => exportResult('purchase'),
    exportInventoryReport: () => exportResult('inventory')
  }
}
