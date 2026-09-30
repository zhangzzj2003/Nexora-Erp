import type { AppState } from './state'

// 每次写入后重新读取有权访问的数据，避免各业务页面保留过期快照。
export function createDataLoader(
  state: AppState,
  can: (permission: string) => boolean,
  syncWorkspaceRoute: () => void
) {
  const {
    user,
    materials,
    suppliers,
    supplierMaterials,
    stock,
    inventoryValuation,
    inventoryCostInputs,
    movements,
    otherInbounds,
    warehouseOutbounds,
    stockAdjustments,
    receipts,
    goodsReceipts,
    purchaseOrders,
    purchaseRequests,
    purchaseReturns,
    receivablesPayables,
    financeAccounts,
    ledgerAccounts,
    journals,
    openingBalances,
    accountingPeriods,
    paymentRecords,
    boms,
    workOrders,
    materialIssues,
    materialReturns,
    productionCompletions,
    productionCostReport,
    productionCostSettlements,
    warehouses,
    transfers,
    stocktakes,
    customers,
    salesOrders,
    shipments,
    salesReturns,
    selectedWarehouseId,
    roles,
    permissions,
    permissionLabelDrafts,
    users,
    roleDrafts,
    rolePermissionDrafts,
    roleLabelDrafts,
    inspectionDrafts
  } = state
  async function loadPermissions(): Promise<void> {
    if (!window.nexora || !user.value) return
    if (!can('users.manage')) {
      // 授权被撤销时立即清除旧目录，不能依赖后续业务请求全部成功。
      permissions.value = []
      permissionLabelDrafts.value = {}
      return
    }
    // 权限目录独立读取，避免其他业务接口失败时连职务授权数据也无法展示。
    const entries = await window.nexora.callApi('permissions', undefined)
    permissions.value = entries
    permissionLabelDrafts.value = Object.fromEntries(
      entries.map((entry) => [entry.code, entry.label])
    )
  }

  async function refreshData(): Promise<void> {
    if (!window.nexora || !user.value) return
    // 每次写操作后重新读取服务端权限；角色变化立即反映到当前页面。
    user.value = await window.nexora.callApi('me', undefined)
    // 先清理已撤销查看授权的数据，避免其他模块读取失败留下旧的财务快照。
    if (!can('ledger_account.view')) ledgerAccounts.value = []
    if (!can('journal.view')) journals.value = []
    if (!can('business_journal.view')) {
      state.businessJournalSources.value = []
      state.businessJournalOptions.value = null
      state.businessJournalPolicyChanges.value = []
      state.businessJournalError.value = ''
    }
    if (!can('profit_transfer.view')) {
      state.profitTransferOptions.value = null
      state.profitTransferPreview.value = null
      state.profitTransferPolicyChanges.value = []
      state.profitTransferError.value = ''
    }
    if (!can('opening_balance.view')) openingBalances.value = []
    if (!can('opening_balance.create')) state.openingBalanceOptions.value = { accounts: [], period: null }
    if (!can('journal.create')) state.journalOptions.value = { accounts: [], periods: [] }
    if (!can('accounting_period.view')) accountingPeriods.value = []
    if (!can('accounting_period.closing_view')) {
      state.periodClosingCheck.value = null
      state.periodClosingHistory.value = []
      state.periodClosingError.value = ''
    }
    syncWorkspaceRoute()
    await loadPermissions()
    state.menuIcons.value = await window.nexora.callApi('menuIcons', undefined)
    // 保存后只失效有界快照，由当前打开的表格重新分页查询；不重新拉取全公司业务。
    materials.value = []
    suppliers.value = []
    supplierMaterials.value = []
    stock.value = []
    receipts.value = []
    movements.value = []
    warehouses.value = []
    transfers.value = []
    purchaseOrders.value = []
    stocktakes.value = []
    purchaseReturns.value = []
    purchaseRequests.value = []
    goodsReceipts.value = []
    otherInbounds.value = []
    warehouseOutbounds.value = []
    stockAdjustments.value = []
    customers.value = []
    salesOrders.value = []
    shipments.value = []
    salesReturns.value = []
    openingBalances.value = []
    journals.value = []
    ledgerAccounts.value = []
    accountingPeriods.value = []
    boms.value = []
    workOrders.value = []
    materialIssues.value = []
    materialReturns.value = []
    productionCompletions.value = []
    productionCostSettlements.value = []
    paymentRecords.value = []
    financeAccounts.value = []
    inventoryCostInputs.value = []
    roles.value = []
    users.value = []
    inventoryValuation.value = null
    receivablesPayables.value = null
    productionCostReport.value = null
    // 刷新版本触发当前挂载页面查询；未打开页面不产生业务请求。
    state.dataRevision.value += 1

  }
  return { refreshData, loadPermissions }
}
