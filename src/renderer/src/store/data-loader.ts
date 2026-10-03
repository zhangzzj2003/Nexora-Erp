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
    materialCategories,
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
    bankOverview,
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
    if (!can('financial_statement.view')) {
      state.statementOptions.value = null; state.statementReport.value = null; state.statementArchive.value = null
      state.statementArchives.value = []; state.statementPolicyChanges.value = []; state.statementError.value = ''
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
    // 页面只显示当前角色可访问的入口；数据访问仍以服务端授权为准。
    if (can('inventory.view')) {
      ;[
        materials.value,
        materialCategories.value,
        suppliers.value,
        supplierMaterials.value,
        stock.value,
        receipts.value,
        movements.value,
        warehouses.value,
        transfers.value,
        purchaseOrders.value,
        stocktakes.value,
        purchaseReturns.value
      ] = await Promise.all([
        window.nexora.callApi('materials', undefined),
        window.nexora.callApi('materialCategories', undefined),
        window.nexora.callApi('suppliers', undefined),
        window.nexora.callApi('supplierMaterials', undefined),
        window.nexora.callApi(
          'stock',
          selectedWarehouseId.value
            ? { warehouseId: selectedWarehouseId.value }
            : undefined
        ),
        window.nexora.callApi('receipts', undefined),
        window.nexora.callApi('movements', undefined),
        window.nexora.callApi('warehouses', undefined),
        window.nexora.callApi('transfers', undefined),
        window.nexora.callApi('purchaseOrders', undefined),
        window.nexora.callApi('stocktakes', undefined),
        window.nexora.callApi('purchaseReturns', undefined)
      ])
    }
    purchaseRequests.value = can('purchase_request.view')
      ? await window.nexora.callApi('purchaseRequests', undefined)
      : []
    goodsReceipts.value = can('purchase_receiving.view')
      ? await window.nexora.callApi('goodsReceipts', undefined)
      : []
    otherInbounds.value = can('other_inbound.view')
      ? await window.nexora.callApi('otherInbounds', undefined)
      : []
    warehouseOutbounds.value = can('other_outbound.view')
      ? await window.nexora.callApi('warehouseOutbounds', undefined)
      : []
    stockAdjustments.value = can('adjustment.view')
      ? await window.nexora.callApi('stockAdjustments', undefined)
      : []
    if (can('inventory_valuation.view')) {
      ;[inventoryValuation.value, inventoryCostInputs.value] = await Promise.all([
        window.nexora.callApi('inventoryValuation', undefined),
        window.nexora.callApi('inventoryCostInputs', undefined)
      ])
    } else {
      inventoryValuation.value = null
      inventoryCostInputs.value = []
    }
    if (can('sales.view')) {
      ;[
        customers.value,
        salesOrders.value,
        shipments.value,
        salesReturns.value
      ] = await Promise.all([
        window.nexora.callApi('customers', undefined),
        window.nexora.callApi('salesOrders', undefined),
        window.nexora.callApi('shipments', undefined),
        window.nexora.callApi('salesReturns', undefined)
      ])
    }
    if (can('finance.view')) {
      // 单次服务端快照避免并发收付款时来源、余额和记录短暂不一致。
      const overview = await window.nexora.callApi('financeOverview', undefined)
      receivablesPayables.value = overview.report
      financeAccounts.value = overview.accounts
      paymentRecords.value = overview.payments
    } else {
      receivablesPayables.value = null
      financeAccounts.value = []
      paymentRecords.value = []
    }
    if (can('bank_reconciliation.view')) {
      const owner = `${state.server.value?.id}:${state.server.value?.fingerprint}:${user.value?.id}`
      const overview = await window.nexora.callApi('bankReconciliationOverview', undefined)
      if (owner === `${state.server.value?.id}:${state.server.value?.fingerprint}:${user.value?.id}`
        && can('bank_reconciliation.view')) bankOverview.value = overview
    } else bankOverview.value = null
    openingBalances.value = can('opening_balance.view') ? await window.nexora.callApi('openingBalances', undefined) : []
    journals.value = can('journal.view') ? await window.nexora.callApi('journals', undefined) : []
    ledgerAccounts.value = can('ledger_account.view')
      ? await window.nexora.callApi('ledgerAccounts', undefined) : []
    accountingPeriods.value = can('accounting_period.view')
      ? await window.nexora.callApi('accountingPeriods', undefined) : []
    if (can('production.view')) {
      ;[
        boms.value,
        workOrders.value,
        materialIssues.value,
        materialReturns.value,
        productionCompletions.value
      ] = await Promise.all([
        window.nexora.callApi('boms', undefined),
        window.nexora.callApi('workOrders', undefined),
        window.nexora.callApi('materialIssues', undefined),
        window.nexora.callApi('materialReturns', undefined),
        window.nexora.callApi('productionCompletions', undefined)
      ])
      // 刷新列表时保留尚未提交的质检输入，避免其他业务操作意外清空填写内容。
      const previousInspections = inspectionDrafts.value
      inspectionDrafts.value = Object.fromEntries(
        productionCompletions.value
          .filter((item) => item.status === 'draft')
          .map((item) => [
            item.id,
            previousInspections[item.id] ?? {
              accepted_quantity: item.reported_quantity,
              qc_note: ''
            }
          ])
      )
    } else {
      boms.value = []
      workOrders.value = []
      materialIssues.value = []
      materialReturns.value = []
      productionCompletions.value = []
      inspectionDrafts.value = {}
    }
    productionCostReport.value = can('production_cost.view')
      ? await window.nexora.callApi('productionCosts', undefined)
      : null
    productionCostSettlements.value = can('production_cost.view')
      ? await window.nexora.callApi('productionCostSettlements', undefined)
      : []
    if (can('users.manage')) {
      ;[roles.value, users.value] = await Promise.all([
        window.nexora.callApi('roles', undefined),
        window.nexora.callApi('users', undefined)
      ])
      roleDrafts.value = Object.fromEntries(
        users.value.map((entry) => [entry.id, [...entry.roles]])
      )
      rolePermissionDrafts.value = Object.fromEntries(
        roles.value.map((entry) => [entry.code, [...entry.permissions]])
      )
      roleLabelDrafts.value = Object.fromEntries(
        roles.value.map((entry) => [entry.code, entry.label])
      )
    } else {
      permissions.value = []
      permissionLabelDrafts.value = {}
      roles.value = []
      users.value = []
    }
  }
  return { refreshData, loadPermissions }
}
