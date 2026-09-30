import type { TableDataset, TableQuery, TableRow } from '../../../../shared/erp-api'
import type { AppState } from '../state'

// 列表和选择框共用服务端分页，跨页面业务操作仅持有已读取的有界快照。
export function createTableActions(state: AppState) {
  function hydrateDataset(dataset: TableDataset, rows: TableRow[], metadata?: Record<string, unknown> | null): void {
    switch (dataset) {
      case 'inventoryValuationMaterials':
        state.inventoryValuation.value = { ...(state.inventoryValuation.value ?? {currency: 'CNY', materials: [], movements: [], unpriced_movement_ids: []}), ...metadata, materials: rows } as unknown as typeof state.inventoryValuation.value; break
      case 'inventoryValuationMovements':
        state.inventoryValuation.value = { ...(state.inventoryValuation.value ?? {currency: 'CNY', materials: [], movements: [], unpriced_movement_ids: []}), ...metadata, movements: rows } as unknown as typeof state.inventoryValuation.value; break
      case 'productionCostOrders': case 'productionCostEntries': case 'productionMaterialSources': {
        const field = dataset === 'productionCostOrders' ? 'orders' : dataset === 'productionCostEntries' ? 'entries' : 'material_sources'
        state.productionCostReport.value = { ...(state.productionCostReport.value ?? { currency: 'CNY', orders: [], entries: [], material_sources: [], unpriced_lines: [] }), ...metadata, [field]: rows } as unknown as typeof state.productionCostReport.value; break
      }
      case 'financeAccounts': state.financeAccounts.value = rows as unknown as typeof state.financeAccounts.value;
        state.receivablesPayables.value = { ...metadata, entries: [] } as unknown as typeof state.receivablesPayables.value; break
      case 'financialSources': state.receivablesPayables.value = { ...metadata, entries: rows } as unknown as typeof state.receivablesPayables.value; break
      case 'periodClosingHistory': state.periodClosingHistory.value = rows as unknown as typeof state.periodClosingHistory.value; break
      case 'materials': state.materials.value = rows as unknown as typeof state.materials.value; break
      case 'suppliers': state.suppliers.value = rows as unknown as typeof state.suppliers.value; break
      case 'supplierMaterials': state.supplierMaterials.value = rows as unknown as typeof state.supplierMaterials.value; break
      case 'customers': state.customers.value = rows as unknown as typeof state.customers.value; break
      case 'warehouses': state.warehouses.value = rows as unknown as typeof state.warehouses.value; break
      case 'users': state.users.value = rows as unknown as typeof state.users.value; break
      case 'roles': state.roles.value = rows as unknown as typeof state.roles.value; break
      case 'purchaseRequests': state.purchaseRequests.value = rows as unknown as typeof state.purchaseRequests.value; break
      case 'purchaseOrders': state.purchaseOrders.value = rows as unknown as typeof state.purchaseOrders.value; break
      case 'goodsReceipts': state.goodsReceipts.value = rows as unknown as typeof state.goodsReceipts.value; break
      case 'receipts': state.receipts.value = rows as unknown as typeof state.receipts.value; break
      case 'purchaseReturns': state.purchaseReturns.value = rows as unknown as typeof state.purchaseReturns.value; break
      case 'otherInbounds': state.otherInbounds.value = rows as unknown as typeof state.otherInbounds.value; break
      case 'warehouseOutbounds': state.warehouseOutbounds.value = rows as unknown as typeof state.warehouseOutbounds.value; break
      case 'stockAdjustments': state.stockAdjustments.value = rows as unknown as typeof state.stockAdjustments.value; break
      case 'transfers': state.transfers.value = rows as unknown as typeof state.transfers.value; break
      case 'stocktakes': state.stocktakes.value = rows as unknown as typeof state.stocktakes.value; break
      case 'salesOrders': state.salesOrders.value = rows as unknown as typeof state.salesOrders.value; break
      case 'shipments': state.shipments.value = rows as unknown as typeof state.shipments.value; break
      case 'salesReturns': state.salesReturns.value = rows as unknown as typeof state.salesReturns.value; break
      case 'boms': state.boms.value = rows as unknown as typeof state.boms.value; break
      case 'workOrders': state.workOrders.value = rows as unknown as typeof state.workOrders.value; break
      case 'materialIssues': state.materialIssues.value = rows as unknown as typeof state.materialIssues.value; break
      case 'materialReturns': state.materialReturns.value = rows as unknown as typeof state.materialReturns.value; break
      case 'productionCompletions': state.productionCompletions.value = rows as unknown as typeof state.productionCompletions.value; break
      case 'productionCostSettlements': state.productionCostSettlements.value = rows as unknown as typeof state.productionCostSettlements.value; break
      case 'ledgerAccounts': state.ledgerAccounts.value = rows as unknown as typeof state.ledgerAccounts.value; break
      case 'accountingPeriods': state.accountingPeriods.value = rows as unknown as typeof state.accountingPeriods.value; break
      case 'journals': state.journals.value = rows as unknown as typeof state.journals.value; break
      case 'openingBalances': state.openingBalances.value = rows as unknown as typeof state.openingBalances.value; break
      case 'paymentRecords': state.paymentRecords.value = rows as unknown as typeof state.paymentRecords.value; break
      case 'inventoryCostInputs': state.inventoryCostInputs.value = rows as unknown as typeof state.inventoryCostInputs.value; break
      case 'movements': state.movements.value = rows as unknown as typeof state.movements.value; break
      case 'stock': state.stock.value = rows as unknown as typeof state.stock.value;
        if (metadata) state.stockSummary.value = metadata as unknown as typeof state.stockSummary.value; break
    }
    if (dataset === 'users') state.roleDrafts.value = Object.fromEntries(state.users.value.map(user => [user.id, [...user.roles]]))
    if (dataset === 'roles') {
      state.rolePermissionDrafts.value = Object.fromEntries(state.roles.value.map(role => [role.code, [...role.permissions]]))
      state.roleLabelDrafts.value = Object.fromEntries(state.roles.value.map(role => [role.code, role.label]))
    }
    if (dataset === 'productionCompletions') {
      // 分页或重查保留尚未保存的质检草稿，不用新结果覆盖用户输入。
      for (const row of state.productionCompletions.value) {
        if (row.status === 'draft' && !state.inspectionDrafts.value[row.id])
          state.inspectionDrafts.value[row.id] = { accepted_quantity: row.reported_quantity, qc_note: '' }
      }
    }
  }
  async function queryDataset(query: TableQuery) {
    if (!window.nexora) throw new Error('服务连接不可用，请重试。')
    const scope = `${state.user.value?.id}:${state.user.value?.permissions.join('|')}:${state.dataRevision.value}`
    const result = await window.nexora.callApi('queryTable', query)
    // 退出、切换账号或撤权后，旧请求不能重新填回共享业务快照。
    if (scope !== `${state.user.value?.id}:${state.user.value?.permissions.join('|')}:${state.dataRevision.value}`)
      throw new Error('账号或数据范围已变化，请重新查询。')
    return result
  }
  return { queryDataset, hydrateDataset }
}
