import type { Ref } from 'vue'
import type { AppState } from './state'
import type { ErpOperations } from '../../../shared/erp-api'
import { captureSession, StaleSessionRead } from './session-state.ts'

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
    materialUnits,
    suppliers,
    supplierMaterials,
    stock,
    inventoryValuation,
    inventoryCostInputs,
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
    orderSettlements,
    bankOverview,
    bankBalanceOverview,
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
  let refreshRevision = 0, permissionRevision = 0
  async function loadPermissions(valid: () => boolean = () => true): Promise<void> {
    if (!window.nexora || !user.value) return
    const current = captureSession(state), ticket = ++permissionRevision
    if (!can('users.manage')) {
      // 授权被撤销时立即清除旧目录，不能依赖后续业务请求全部成功。
      permissions.value = []
      permissionLabelDrafts.value = {}
      return
    }
    // 权限目录独立读取，避免其他业务接口失败时连职务授权数据也无法展示。
    const entries = await window.nexora.callApi('permissions', undefined)
    if (!current() || !valid() || ticket !== permissionRevision || !can('users.manage')) throw new StaleSessionRead()
    permissions.value = entries
    permissionLabelDrafts.value = Object.fromEntries(
      entries.map((entry) => [entry.code, entry.label])
    )
  }

  async function refreshData(): Promise<void> {
    if (!window.nexora || !user.value) return
    let current = captureSession(state)
    const ticket = ++refreshRevision
    const valid = () => current() && ticket === refreshRevision
    const assertCurrent = () => { if (!valid()) throw new StaleSessionRead() }
    // 校验紧贴实际赋值，覆盖 Promise 已解决但调用方尚未恢复时发生的会话切换。
    function assign<T>(target: Ref<T>, value: T): void { assertCurrent(); target.value = value }
    // 在每次响应提交前核对会话及刷新代次，旧 Promise.all 结果也不能覆盖新账号。
    async function read<K extends keyof ErpOperations>(action: K, payload: ErpOperations[K]['input']): Promise<ErpOperations[K]['output']> {
      assertCurrent()
      try {
        const result = await window.nexora!.callApi(action, payload)
        assertCurrent()
        return result
      } catch (cause) { assertCurrent(); throw cause }
    }
    // 每次写操作后重新读取服务端权限；角色变化立即反映到当前页面。
    assign(user, await read('me', undefined))
    // 当前响应已通过旧会话检查；后续请求使用服务端刚核验的新授权范围。
    current = captureSession(state)
    // 先清除所有失去查看权限的旧共享列表，后续任何接口失败都不能留下这些数据。
    if (!can('inventory.view')) {
      materialUnits.value = []; materialCategories.value = []; materials.value = []
      suppliers.value = []; supplierMaterials.value = []; stock.value = []; receipts.value = []
      warehouses.value = []; transfers.value = []; purchaseOrders.value = []; stocktakes.value = []; purchaseReturns.value = []
    }
    if (!can('sales.view')) { customers.value = []; salesOrders.value = []; shipments.value = []; salesReturns.value = [] }
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
    const numbering = await read('documentNumbering', undefined)
    assign(state.documentNumbering, numbering)
    if (!numbering.configured && user.value?.roles.includes('admin')) {
      state.screen.value = 'numbering'
      return
    }
    syncWorkspaceRoute()
    await loadPermissions(valid)
    assertCurrent()
    assign(state.menuIcons, await read('menuIcons', undefined))
    // 页面只显示当前角色可访问的入口；数据访问仍以服务端授权为准。
    // 总览卡片已由分页接口返回统计，统一刷新不再下载全量库存流水。
    if (can('inventory.view')) {
      const values = await Promise.all([
        read('materials', undefined),
        read('materialCategories', undefined),
        read('materialUnits', undefined),
        read('suppliers', undefined),
        read('supplierMaterials', undefined),
        read(
          'stock',
          selectedWarehouseId.value
            ? { warehouseId: selectedWarehouseId.value }
            : undefined
        ),
        read('receipts', undefined),
        read('warehouses', undefined),
        read('transfers', undefined),
        read('purchaseOrders', undefined),
        read('stocktakes', undefined),
        read('purchaseReturns', undefined)
      ])
      assertCurrent()
      ;[
        materials.value,
        materialCategories.value,
        materialUnits.value,
        suppliers.value,
        supplierMaterials.value,
        stock.value,
        receipts.value,
        warehouses.value,
        transfers.value,
        purchaseOrders.value,
        stocktakes.value,
        purchaseReturns.value
      ] = values
    }
    assign(purchaseRequests, can('purchase_request.view')
      ? await read('purchaseRequests', undefined)
      : [])
    assign(goodsReceipts, can('purchase_receiving.view')
      ? await read('goodsReceipts', undefined)
      : [])
    assign(otherInbounds, can('other_inbound.view')
      ? await read('otherInbounds', undefined)
      : [])
    assign(warehouseOutbounds, can('other_outbound.view')
      ? await read('warehouseOutbounds', undefined)
      : [])
    assign(stockAdjustments, can('adjustment.view')
      ? await read('stockAdjustments', undefined)
      : [])
    if (can('inventory_valuation.view')) {
      const values = await Promise.all([
        read('inventoryValuation', undefined),
        read('inventoryCostInputs', undefined)
      ])
      assertCurrent()
      ;[inventoryValuation.value, inventoryCostInputs.value] = values
    } else {
      inventoryValuation.value = null
      inventoryCostInputs.value = []
    }
    if (can('sales.view')) {
      const values = await Promise.all([
        read('customers', undefined),
        read('salesOrders', undefined),
        read('shipments', undefined),
        read('salesReturns', undefined)
      ])
      assertCurrent()
      ;[
        customers.value,
        salesOrders.value,
        shipments.value,
        salesReturns.value
      ] = values
    }
    if (can('finance.view')) {
      // 单次服务端快照避免并发收付款时来源、余额和记录短暂不一致。
      const overview = await read('financeOverview', undefined)
      assertCurrent()
      receivablesPayables.value = overview.report
      financeAccounts.value = overview.accounts
      paymentRecords.value = overview.payments
      orderSettlements.value = overview.transfers
    } else {
      receivablesPayables.value = null
      financeAccounts.value = []
      paymentRecords.value = []
      orderSettlements.value = []
    }
    if (can('bank_reconciliation.view')) {
      const owner = `${state.server.value?.id}:${state.server.value?.fingerprint}:${user.value?.id}`
      const [overview, balance] = await Promise.all([
        read('bankReconciliationOverview', undefined),
        read('bankBalanceOverview', undefined)
      ])
      assertCurrent()
      if (owner === `${state.server.value?.id}:${state.server.value?.fingerprint}:${user.value?.id}`
        && can('bank_reconciliation.view')) {
        bankOverview.value = overview
        bankBalanceOverview.value = balance
      }
    } else {
      bankOverview.value = null
      bankBalanceOverview.value = null
    }
    assign(openingBalances, can('opening_balance.view') ? await read('openingBalances', undefined) : [])
    assign(journals, can('journal.view') ? await read('journals', undefined) : [])
    assign(ledgerAccounts, can('ledger_account.view')
      ? await read('ledgerAccounts', undefined) : [])
    assign(accountingPeriods, can('accounting_period.view')
      ? await read('accountingPeriods', undefined) : [])
    if (can('production.view')) {
      const values = await Promise.all([
        read('boms', undefined),
        read('workOrders', undefined),
        read('materialIssues', undefined),
        read('materialReturns', undefined),
        read('productionCompletions', undefined)
      ])
      assertCurrent()
      ;[
        boms.value,
        workOrders.value,
        materialIssues.value,
        materialReturns.value,
        productionCompletions.value
      ] = values
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
    assign(productionCostReport, can('production_cost.view')
      ? await read('productionCosts', undefined)
      : null)
    assign(productionCostSettlements, can('production_cost.view')
      ? await read('productionCostSettlements', undefined)
      : [])
    if (can('users.manage')) {
      const values = await Promise.all([
        read('roles', undefined),
        read('users', undefined)
      ])
      assertCurrent()
      ;[roles.value, users.value] = values
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
