import { watch } from 'vue'
import type { ReportQuery } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

// 分页查询与全量导出分开读取，翻页响应不再夹带全部 CSV 数据。
export function createInventoryReportActions(state: AppState) {
  let ticket = 0
  let exportTicket = 0
  const allowed = (): boolean => !!window.nexora && !state.connectionLost.value
    && !!state.user.value?.permissions.includes('inventory_report.view')
  function filters(): ReportQuery {
    const { kind, warehouse_id, material_id, supplier_id, from_date, to_date } = state.inventoryReportQuery.value
    return { kind, warehouse_id, material_id, supplier_id, from_date: from_date || null, to_date: to_date || null }
  }
  function invalidate(): void {
    ticket++; exportTicket++
    state.inventoryReportResult.value = null
    state.inventoryReportLoading.value = false
    state.inventoryReportExporting.value = false
    state.inventoryReportError.value = ''
  }
  watch(() => JSON.stringify(filters()), () => {
    state.inventoryReportQuery.value.page = 1
    invalidate()
  }, { flush: 'sync' })
  // 同一账号刷新 me 快照不应清空当前页；仅真实会话边界变化使响应失效。
  watch(() => JSON.stringify([state.user.value?.id, state.user.value?.permissions.join('|'),
    state.connectionLost.value, state.server.value?.id]),
    invalidate, { flush: 'sync' })

  async function queryInventoryReport(page = 1, pageSize = state.inventoryReportQuery.value.page_size): Promise<void> {
    if (!allowed()) return
    const query = state.inventoryReportQuery.value
    query.page = pageSize === query.page_size ? page : 1
    query.page_size = pageSize
    const current = ++ticket
    state.inventoryReportLoading.value = true
    state.inventoryReportError.value = ''
    try {
      const result = await window.nexora!.callApi('queryInventoryReport', {
        ...query, from_date: query.from_date || null, to_date: query.to_date || null })
      if (current !== ticket || !allowed()) return
      state.inventoryReportResult.value = result
      query.page = result.page
      query.page_size = result.page_size
    } catch (cause) {
      if (current !== ticket) return
      invalidate()
      state.inventoryReportError.value = displayError(cause)
    } finally {
      if (current === ticket) state.inventoryReportLoading.value = false
    }
  }

  async function exportInventoryReport(): Promise<void> {
    if (!allowed() || !state.inventoryReportResult.value || state.inventoryReportLoading.value
        || state.inventoryReportExporting.value) return
    const current = ++exportTicket
    state.inventoryReportExporting.value = true
    state.inventoryReportError.value = ''
    try {
      // 去掉页码按当前筛选重新读取完整报表；条件或会话变化后，不弹出旧数据保存框。
      const result = await window.nexora!.callApi('queryReport', filters())
      if (current !== exportTicket || !allowed()) return
      const saved = await window.nexora!.saveReportCsv(
        `${result.kind}-${new Date().toISOString().slice(0, 10)}.csv`, result.csv)
      if (current === exportTicket && saved && allowed()) state.notice.value = '完整筛选结果 CSV 已保存。'
    } catch (cause) {
      if (current === exportTicket) state.inventoryReportError.value = displayError(cause)
    } finally {
      if (current === exportTicket) state.inventoryReportExporting.value = false
    }
  }
  return { queryInventoryReport, exportInventoryReport }
}
