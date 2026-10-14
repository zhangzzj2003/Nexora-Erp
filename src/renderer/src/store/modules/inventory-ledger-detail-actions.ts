import { watch } from 'vue'
import type { AppState } from '../state'
import type { LedgerRow, LedgerQuery } from '../../../../shared/erp-api'
import { validateInventoryLedgerDocument } from '../../../../shared/inventory-ledger-document.ts'
import { displayError } from '../../utils/formatters.ts'

export function createInventoryLedgerDetailActions(state: AppState) {
  let materialRead = 0, rowsRead = 0, documentRead = 0
  const available = () => !!window.nexora && !state.connectionLost.value
    && !!state.user.value?.permissions.includes('inventory.view')
  const emptyResult = () => ({ groups: [], rows: [], total: 0, page: 1, page_size: 20 })

  function closeLedgerDocument(): void {
    documentRead++
    state.ledgerDocumentTarget.value = null
    state.ledgerDocumentRecord.value = null
    state.ledgerDocumentLoading.value = false
    state.ledgerDocumentError.value = ''
  }
  function closeLedgerMaterial(): void {
    materialRead++; rowsRead++
    state.ledgerMaterialTarget.value = null
    state.ledgerMaterialDetail.value = null
    state.ledgerMaterialQuery.value = null
    state.ledgerMaterialResult.value = emptyResult()
    state.ledgerMaterialLoading.value = false
    state.ledgerMaterialRowsLoading.value = false
    state.ledgerMaterialError.value = ''
    state.ledgerMaterialRowsError.value = ''
    closeLedgerDocument()
  }
  // 同账号的常规刷新保留窗口；切换实例、账号、权限或查询范围立即撤销在途响应。
  watch(() => JSON.stringify([state.user.value?.id, state.user.value?.roles, state.user.value?.permissions,
    state.server.value?.id, state.server.value?.fingerprint, state.connectionLost.value,
    state.ledgerQuery.value.warehouse_id, state.ledgerQuery.value.material_id,
    state.ledgerQuery.value.from_date, state.ledgerQuery.value.to_date, state.ledgerQuery.value.source_type,
    state.inventoryReportQuery.value.kind, state.inventoryReportQuery.value.warehouse_id,
    state.inventoryReportQuery.value.material_id, state.inventoryReportQuery.value.from_date, state.inventoryReportQuery.value.to_date]),
  closeLedgerMaterial, { flush: 'sync' })

  async function loadLedgerMaterial(): Promise<void> {
    const target = state.ledgerMaterialTarget.value
    if (!available() || !target) return
    const ticket = ++materialRead
    state.ledgerMaterialDetail.value = null
    state.ledgerMaterialLoading.value = true
    state.ledgerMaterialError.value = ''
    try {
      const result = await window.nexora!.callApi('materialDetail', { id: target.material_id })
      if (ticket !== materialRead || !available()) return
      if (result.id !== target.material_id) throw Error('物料详情与当前物料不一致，请重新读取。')
      state.ledgerMaterialDetail.value = result
    } catch (cause) {
      if (ticket === materialRead) state.ledgerMaterialError.value = displayError(cause)
    } finally { if (ticket === materialRead) state.ledgerMaterialLoading.value = false }
  }

  async function queryLedgerMaterial(page = 1, pageSize = state.ledgerMaterialQuery.value?.page_size ?? 20): Promise<void> {
    const query = state.ledgerMaterialQuery.value
    if (!available() || !query || !state.ledgerMaterialTarget.value) return
    query.page = pageSize === query.page_size ? page : 1
    query.page_size = pageSize
    const snapshot = { ...query, from_date: query.from_date || null, to_date: query.to_date || null }
    const ticket = ++rowsRead
    state.ledgerMaterialRowsLoading.value = true
    state.ledgerMaterialRowsError.value = ''
    state.ledgerMaterialResult.value = emptyResult()
    try {
      const result = await window.nexora!.callApi('inventoryLedger', snapshot)
      if (ticket !== rowsRead || !available()) return
      // 汇总必须来自同一物料和仓库范围；不能从当前页重算期初期末或混入其他物料。
      if (!Number.isInteger(result.total) || result.total < 0 || !Number.isInteger(result.page) || result.page < 1
          || result.page_size !== snapshot.page_size || !Array.isArray(result.rows) || !Array.isArray(result.groups)
          || [...result.rows, ...result.groups].some(row => row.material_id !== snapshot.material_id
            || snapshot.warehouse_id !== null && row.warehouse_id !== snapshot.warehouse_id)) {
        throw Error('物料台账返回范围或分页不匹配，请升级服务端后重新读取。')
      }
      state.ledgerMaterialResult.value = result
      query.page = result.page
    } catch (cause) {
      if (ticket === rowsRead) state.ledgerMaterialRowsError.value = displayError(cause)
    } finally { if (ticket === rowsRead) state.ledgerMaterialRowsLoading.value = false }
  }

  async function openLedgerMaterial(row: Pick<LedgerRow, 'material_id' | 'sku' | 'material_name'>,
    filters: Pick<LedgerQuery, 'warehouse_id' | 'from_date' | 'to_date' | 'source_type'> = state.ledgerQuery.value): Promise<void> {
    if (!available()) return
    closeLedgerMaterial()
    state.ledgerMaterialTarget.value = { material_id: row.material_id, sku: row.sku, material_name: row.material_name }
    // 固定打开时的筛选快照，详情使用独立分页，不修改主表筛选和当前页。
    state.ledgerMaterialQuery.value = { warehouse_id: filters.warehouse_id, from_date: filters.from_date,
      to_date: filters.to_date, source_type: filters.source_type, material_id: row.material_id, page: 1, page_size: 20 }
    await Promise.all([loadLedgerMaterial(), queryLedgerMaterial()])
  }

  async function openReportMaterial(row: Record<string, string>): Promise<void> {
    if (!available() || !state.user.value?.permissions.includes('inventory_report.view')) return
    const materialId = Number(row.material_id), warehouseId = Number(row.warehouse_id)
    // 使用响应中的稳定编号，不拆分展示文案或按物料名称猜测；旧服务端明确提示升级。
    if (!Number.isSafeInteger(materialId) || materialId <= 0 || !Number.isSafeInteger(warehouseId) || warehouseId <= 0
        || !row.sku || !row.material_name) {
      state.inventoryReportError.value = '服务端尚未提供报表物料详情，请升级服务端后重新查询。'
      return
    }
    const filters = state.inventoryReportQuery.value
    await openLedgerMaterial({ material_id: materialId, sku: row.sku, material_name: row.material_name }, {
      warehouse_id: warehouseId, from_date: filters.kind === 'inventory_balance' ? null : filters.from_date,
      to_date: filters.to_date, source_type: null
    })
  }

  async function loadLedgerDocument(): Promise<void> {
    const target = state.ledgerDocumentTarget.value
    if (!available() || !target) return
    const ticket = ++documentRead
    state.ledgerDocumentRecord.value = null
    state.ledgerDocumentLoading.value = true
    state.ledgerDocumentError.value = ''
    try {
      const result = await window.nexora!.callApi('inventoryLedgerDocument', { movement_id: target.id })
      if (ticket !== documentRead || !available()) return
      validateInventoryLedgerDocument(result, target.id)
      state.ledgerDocumentRecord.value = result.document
    } catch (cause) {
      if (ticket === documentRead) state.ledgerDocumentError.value = displayError(cause)
    } finally { if (ticket === documentRead) state.ledgerDocumentLoading.value = false }
  }
  async function openLedgerDocument(row: LedgerRow): Promise<void> {
    if (!available()) return
    closeLedgerDocument()
    state.ledgerDocumentTarget.value = { ...row }
    await loadLedgerDocument()
  }
  return { openLedgerMaterial, openReportMaterial, closeLedgerMaterial, loadLedgerMaterial, queryLedgerMaterial,
    openLedgerDocument, closeLedgerDocument, loadLedgerDocument }
}
