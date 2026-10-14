import { watch } from 'vue'
import type { AppState } from '../state'
import type { LedgerRow, LedgerQuery, Stock } from '../../../../shared/erp-api'
import { validateInventoryLedgerDocument } from '../../../../shared/inventory-ledger-document.ts'
import { validateStockOverview } from '../../../../shared/stock-overview.ts'
import { displayError } from '../../utils/formatters.ts'

export function createInventoryLedgerDetailActions(state: AppState) {
  let materialRead = 0, rowsRead = 0, documentRead = 0, stockRead = 0
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
    materialRead++; rowsRead++; stockRead++
    state.stockMaterialMode.value = false
    state.stockMaterialSnapshot.value = null
    state.stockMaterialLoading.value = false
    state.stockMaterialError.value = ''
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
  watch(() => JSON.stringify([state.user.value?.id, state.user.value?.roles?.slice().sort(), state.user.value?.permissions.slice().sort(),
    state.server.value?.id, state.server.value?.fingerprint, state.connectionLost.value,
    state.ledgerQuery.value.warehouse_id, state.ledgerQuery.value.material_id,
    state.ledgerQuery.value.from_date, state.ledgerQuery.value.to_date, state.ledgerQuery.value.source_type,
    state.inventoryReportQuery.value.kind, state.inventoryReportQuery.value.warehouse_id,
    state.inventoryReportQuery.value.material_id, state.inventoryReportQuery.value.from_date, state.inventoryReportQuery.value.to_date,
    state.stockOverviewQuery.value.warehouse_id, state.stockOverviewQuery.value.keyword, state.stockOverviewQuery.value.category_group]),
  closeLedgerMaterial, { flush: 'sync' })

  async function loadLedgerMaterial(): Promise<boolean> {
    const target = state.ledgerMaterialTarget.value
    if (!available() || !target) return false
    const ticket = ++materialRead
    // 同一物料刷新时保留已展示资料，避免详情高度在请求期间归零。
    state.ledgerMaterialLoading.value = true
    state.ledgerMaterialError.value = ''
    try {
      const result = await window.nexora!.callApi('materialDetail', { id: target.material_id })
      if (ticket !== materialRead || !available()) return false
      if (result.id !== target.material_id) throw Error('物料详情与当前物料不一致，请重新读取。')
      state.ledgerMaterialDetail.value = result
      return true
    } catch (cause) {
      if (ticket === materialRead) state.ledgerMaterialError.value = displayError(cause)
      return false
    } finally { if (ticket === materialRead) state.ledgerMaterialLoading.value = false }
  }

  async function queryLedgerMaterial(page = 1, pageSize = state.ledgerMaterialQuery.value?.page_size ?? 20): Promise<boolean> {
    const query = state.ledgerMaterialQuery.value
    if (!available() || !query || !state.ledgerMaterialTarget.value) return false
    query.page = pageSize === query.page_size ? page : 1
    query.page_size = pageSize
    const snapshot = { ...query, from_date: query.from_date || null, to_date: query.to_date || null }
    const ticket = ++rowsRead
    state.ledgerMaterialRowsLoading.value = true
    state.ledgerMaterialRowsError.value = ''
    // 首屏与后续分页都以完整响应替换；等待或失败时保留上一页的呈现。
    try {
      const result = await window.nexora!.callApi('inventoryLedger', snapshot)
      if (ticket !== rowsRead || !available()) return false
      // 汇总必须来自同一物料和仓库范围；不能从当前页重算期初期末或混入其他物料。
      if (!Number.isInteger(result.total) || result.total < 0 || !Number.isInteger(result.page) || result.page < 1
          || result.page_size !== snapshot.page_size || !Array.isArray(result.rows) || !Array.isArray(result.groups)
          || [...result.rows, ...result.groups].some(row => row.material_id !== snapshot.material_id
            || snapshot.warehouse_id !== null && row.warehouse_id !== snapshot.warehouse_id)) {
        throw Error('物料台账返回范围或分页不匹配，请升级服务端后重新读取。')
      }
      state.ledgerMaterialResult.value = result
      query.page = result.page
      return true
    } catch (cause) {
      if (ticket === rowsRead) state.ledgerMaterialRowsError.value = displayError(cause)
      return false
    } finally { if (ticket === rowsRead) state.ledgerMaterialRowsLoading.value = false }
  }

  async function prepareMaterial(row: Pick<LedgerRow, 'material_id' | 'sku' | 'material_name'>,
    filters: Pick<LedgerQuery, 'warehouse_id' | 'from_date' | 'to_date' | 'source_type'>, stockMode: boolean): Promise<boolean> {
    if (!available()) return false
    // 新物料或不同入口模式不能沿用旧正文；同一目标的重读保留呈现数据。
    if (state.ledgerMaterialTarget.value?.material_id !== row.material_id || state.stockMaterialMode.value !== stockMode) closeLedgerMaterial()
    else closeLedgerDocument()
    state.ledgerMaterialTarget.value = { material_id: row.material_id, sku: row.sku, material_name: row.material_name }
    const target = state.ledgerMaterialTarget.value
    state.stockMaterialMode.value = stockMode
    // 固定打开时的筛选快照，详情使用独立分页，不修改主表筛选和当前页。
    state.ledgerMaterialQuery.value = { warehouse_id: filters.warehouse_id, from_date: filters.from_date,
      to_date: filters.to_date, source_type: filters.source_type, material_id: row.material_id, page: 1, page_size: 20 }
    const results = await Promise.all([loadLedgerMaterial(), queryLedgerMaterial(), ...(stockMode ? [loadStockMaterial()] : [])])
    // 只有所有首屏依据都成功、且仍属于这次打开，界面才能开始展开动画。
    return results.every(Boolean) && available() && state.ledgerMaterialTarget.value === target
  }
  function openLedgerMaterial(row: Pick<LedgerRow, 'material_id' | 'sku' | 'material_name'>,
    filters: Pick<LedgerQuery, 'warehouse_id' | 'from_date' | 'to_date' | 'source_type'> = state.ledgerQuery.value): Promise<boolean> {
    return prepareMaterial(row, filters, false)
  }

  async function loadStockMaterial(): Promise<boolean> {
    const target = state.ledgerMaterialTarget.value
    if (!available() || !target || !state.stockMaterialMode.value) return false
    const ticket = ++stockRead
    state.stockMaterialLoading.value = true
    state.stockMaterialError.value = ''
    try {
      // 全仓快照重新向服务端读取，不能沿用入口页的数量或当前流水页求和。
      const result = await window.nexora!.callApi('queryStock', {
        material_id: target.material_id, warehouse_id: null, page: 1, page_size: 1
      })
      if (ticket !== stockRead || !available()) return false
      validateStockOverview(result)
      if (result.total !== 1 || result.items[0]?.id !== target.material_id) throw Error('仓库分布与当前物料不一致，请重新读取。')
      state.stockMaterialSnapshot.value = result.items[0]
      return true
    } catch (cause) {
      if (ticket === stockRead) state.stockMaterialError.value = displayError(cause)
      return false
    } finally { if (ticket === stockRead) state.stockMaterialLoading.value = false }
  }
  function openStockMaterial(row: Stock): Promise<boolean> {
    // 全仓分布也是首屏必要数据；不能仅因资料和流水先完成就展开空的仓库区域。
    return prepareMaterial({ material_id: row.id, sku: row.sku, material_name: row.name }, {
      warehouse_id: state.stockOverviewQuery.value.warehouse_id, from_date: null, to_date: null, source_type: null
    }, true)
  }
  async function selectStockMaterialWarehouse(warehouseId: number | null): Promise<boolean> {
    const query = state.ledgerMaterialQuery.value
    if (!available() || !query || !state.stockMaterialMode.value) return false
    if (warehouseId !== null && !state.warehouses.value.some(row => row.id === warehouseId)
      && !state.stockMaterialSnapshot.value?.warehouses.some(row => row.warehouse_id === warehouseId)) return false
    closeLedgerDocument()
    query.warehouse_id = warehouseId
    return queryLedgerMaterial(1)
  }

  async function openReportMaterial(row: Record<string, string>): Promise<boolean> {
    if (!available() || !state.user.value?.permissions.includes('inventory_report.view')) return false
    const materialId = Number(row.material_id), warehouseId = Number(row.warehouse_id)
    // 使用响应中的稳定编号，不拆分展示文案或按物料名称猜测；旧服务端明确提示升级。
    if (!Number.isSafeInteger(materialId) || materialId <= 0 || !Number.isSafeInteger(warehouseId) || warehouseId <= 0
        || !row.sku || !row.material_name) {
      state.inventoryReportError.value = '服务端尚未提供报表物料详情，请升级服务端后重新查询。'
      return false
    }
    const filters = state.inventoryReportQuery.value
    return openLedgerMaterial({ material_id: materialId, sku: row.sku, material_name: row.material_name }, {
      warehouse_id: warehouseId, from_date: filters.kind === 'inventory_balance' ? null : filters.from_date,
      to_date: filters.to_date, source_type: null
    })
  }

  async function loadLedgerDocument(): Promise<boolean> {
    const target = state.ledgerDocumentTarget.value
    if (!available() || !target) return false
    const ticket = ++documentRead
    state.ledgerDocumentLoading.value = true
    state.ledgerDocumentError.value = ''
    try {
      const result = await window.nexora!.callApi('inventoryLedgerDocument', { movement_id: target.id })
      if (ticket !== documentRead || !available()) return false
      validateInventoryLedgerDocument(result, target.id)
      state.ledgerDocumentRecord.value = result.document
      return true
    } catch (cause) {
      if (ticket === documentRead) state.ledgerDocumentError.value = displayError(cause)
      return false
    } finally { if (ticket === documentRead) state.ledgerDocumentLoading.value = false }
  }
  async function openLedgerDocument(row: LedgerRow): Promise<boolean> {
    if (!available()) return false
    if (state.ledgerDocumentTarget.value?.id !== row.id) closeLedgerDocument()
    state.ledgerDocumentTarget.value = { ...row }
    return loadLedgerDocument()
  }
  return { openStockMaterial, loadStockMaterial, selectStockMaterialWarehouse, openLedgerMaterial, openReportMaterial, closeLedgerMaterial, loadLedgerMaterial, queryLedgerMaterial,
    openLedgerDocument, closeLedgerDocument, loadLedgerDocument }
}
