import type { BackendHealth } from '../shared/desktop-api'
import type { ErpOperations } from '../shared/erp-api'
import { request as httpsRequest } from 'node:https'

export interface BackendTarget {
  host: string
  port: number
  instanceId: string
  certificate: string
}

let sessionToken: string | null = null
let selectedTarget: BackendTarget | null = null

function sameBackendIdentity(left: BackendTarget | null, right: BackendTarget | null): boolean {
  // 地址可能因局域网变化而更新；实例编号和已信任证书同时一致才允许沿用会话。
  return !!left && !!right && left.instanceId === right.instanceId
    && left.certificate === right.certificate
}

// 令牌只跟随已经核验过的服务端身份，绝不因地址相同就信任另一张证书。
export function retainedSessionToken(token: string | null, current: BackendTarget | null,
                                     next: BackendTarget | null): string | null {
  return sameBackendIdentity(current, next) ? token : null
}

export function selectBackend(target: BackendTarget | null): void {
  // 刷新页面会重新选中同一服务端，只有真正切换实例或证书时才丢弃令牌。
  sessionToken = retainedSessionToken(sessionToken, selectedTarget, target)
  selectedTarget = target
}

function backendBase(): URL {
  const base = new URL(process.env.NEXORA_API_URL || 'http://127.0.0.1:8000')
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password
    || !['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname)) {
    throw new Error('后端地址配置无效，请检查 NEXORA_API_URL。')
  }
  return base
}

async function sendRequest(path: string, method: string, headers: Record<string, string>, body?: unknown,
                           timeout = 10000, targetOverride?: BackendTarget): Promise<Response> {
  const target = targetOverride ?? selectedTarget
  if (!target) {
    // 开发环境仍支持显式配置的旧地址，桌面向导连接一律走证书固定的 HTTPS。
    return fetch(new URL(path, backendBase()), {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeout), redirect: 'error'
    })
  }
  return new Promise((resolve, reject) => {
    const req = httpsRequest({
      hostname: target.host, port: target.port, path, method, headers,
      ca: target.certificate, servername: `nexora-${target.instanceId}.local`,
      rejectUnauthorized: true, timeout
    }, (incoming) => {
      const chunks: Buffer[] = []
      incoming.on('data', (chunk: Buffer) => chunks.push(chunk))
      incoming.on('end', () => resolve(new Response(incoming.statusCode === 204 ? null : Buffer.concat(chunks), {
        status: incoming.statusCode ?? 500
      })))
    })
    req.on('timeout', () => req.destroy(new Error('连接超时')))
    req.on('error', reject)
    if (body !== undefined) req.write(JSON.stringify(body))
    req.end()
  })
}

export async function getServerInfo(target?: BackendTarget): Promise<{ id: string; name: string; version: string; ready: boolean }> {
  const response = await sendRequest('/api/v1/server/info', 'GET', {}, undefined, 5000, target)
  if (!response.ok) throw new Error(`服务端身份检查失败（HTTP ${response.status}）`)
  const info: unknown = await response.json()
  if (!info || typeof info !== 'object' || !('id' in info) || typeof info.id !== 'string'
    || !('name' in info) || typeof info.name !== 'string'
    || !('version' in info) || typeof info.version !== 'string'
    || !('ready' in info) || typeof info.ready !== 'boolean') {
    throw new Error('服务端身份响应格式无效')
  }
  if ((target ?? selectedTarget) && info.id !== (target ?? selectedTarget)?.instanceId) throw new Error('服务端实例身份已变化')
  return info as { id: string; name: string; version: string; ready: boolean }
}

function positiveId(payload: unknown, key: string): number {
  const value = payload && typeof payload === 'object' ? (payload as Record<string, unknown>)[key] : undefined
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) {
    throw new Error('记录编号无效')
  }
  return value
}

function roleCode(payload: unknown): string {
  // 自定义角色代码写入 URL 前先按服务端规则校验，避免路径注入。
  const code = payload && typeof payload === 'object' ? (payload as Record<string, unknown>).code : undefined
  if (typeof code !== 'string' || !/^[a-z][a-z0-9_]{2,39}$/.test(code)) throw new Error('角色代码无效')
  return code
}

function permissionCode(payload: unknown): string {
  // 仅把合法的固定权限代码放入请求路径，不接受页面提供的任意 URL 片段。
  const code = payload && typeof payload === 'object' ? (payload as Record<string, unknown>).code : undefined
  if (typeof code !== 'string' || code.length > 80 || !/^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/.test(code)) {
    throw new Error('权限代码无效')
  }
  return code
}

function operation(action: keyof ErpOperations, payload: unknown): { method: string; path: string; body?: unknown } {
  // 明确列出可调用的接口，禁止页面拼接任意后端路径。
  switch (action) {
    case 'setupStatus': return { method: 'GET', path: '/api/v1/setup/status' }
    case 'bootstrap': return { method: 'POST', path: '/api/v1/setup/admin', body: payload }
    case 'login': return { method: 'POST', path: '/api/v1/auth/login', body: payload }
    case 'logout': return { method: 'POST', path: '/api/v1/auth/logout' }
    case 'me': return { method: 'GET', path: '/api/v1/auth/me' }
    case 'changePassword': return { method: 'POST', path: '/api/v1/auth/change-password', body: payload }
    // 使用固定地址，菜单标识和图标由服务端白名单再次校验。
    case 'menuIcons': return { method: 'GET', path: '/api/v1/menu-icons' }
    case 'saveMenuIcon': return { method: 'PUT', path: '/api/v1/menu-icons', body: payload }
    case 'permissions': return { method: 'GET', path: '/api/v1/permissions' }
    case 'updatePermissionLabel': return {
      method: 'PUT', path: `/api/v1/permissions/${permissionCode(payload)}/label`,
      body: { label: (payload as { label: unknown }).label }
    }
    case 'roles': return { method: 'GET', path: '/api/v1/roles' }
    case 'createRole': return { method: 'POST', path: '/api/v1/roles', body: payload }
    case 'updateRole': return {
      method: 'PUT', path: `/api/v1/roles/${roleCode(payload)}`,
      body: { label: (payload as { label: unknown }).label, permissions: (payload as { permissions: unknown }).permissions }
    }
    case 'users': return { method: 'GET', path: '/api/v1/users' }
    case 'createUser': return { method: 'POST', path: '/api/v1/users', body: payload }
    // 路径只能使用经过校验的用户编号，业务字段由后端再次校验。
    case 'updateUser': return { method: 'PUT', path: `/api/v1/users/${positiveId(payload, 'userId')}`, body: payload }
    case 'setUserRoles': return {
      method: 'PUT', path: `/api/v1/users/${positiveId(payload, 'userId')}/roles`,
      body: { roles: (payload as { roles: unknown }).roles }
    }
    case 'setUserStatus': return {
      method: 'PUT', path: `/api/v1/users/${positiveId(payload, 'userId')}/status`,
      body: { is_active: (payload as { is_active: unknown }).is_active }
    }
    case 'resetUserPassword': return {
      method: 'POST', path: `/api/v1/users/${positiveId(payload, 'userId')}/reset-password`,
      body: { password: (payload as { password: unknown }).password }
    }
    case 'updateMaterial': return { method: 'PUT', path: `/api/v1/materials/${positiveId(payload, 'id')}`, body: payload }
    case 'deleteMaterial': return { method: 'DELETE', path: `/api/v1/materials/${positiveId(payload, 'id')}` }
    case 'updateSupplier': return { method: 'PUT', path: `/api/v1/suppliers/${positiveId(payload, 'id')}`, body: payload }
    case 'deleteSupplier': return { method: 'DELETE', path: `/api/v1/suppliers/${positiveId(payload, 'id')}` }
    case 'updateWarehouse': return { method: 'PUT', path: `/api/v1/warehouses/${positiveId(payload, 'id')}`, body: payload }
    case 'deleteWarehouse': return { method: 'DELETE', path: `/api/v1/warehouses/${positiveId(payload, 'id')}` }
    case 'supplierMaterials': return { method: 'GET', path: '/api/v1/supplier-materials' }
    case 'bindSupplierMaterial': return { method: 'PUT', path: `/api/v1/suppliers/${positiveId(payload, 'supplierId')}/materials/${positiveId(payload, 'materialId')}` }
    case 'unbindSupplierMaterial': return { method: 'DELETE', path: `/api/v1/suppliers/${positiveId(payload, 'supplierId')}/materials/${positiveId(payload, 'materialId')}` }
    // 分页搜索经由受限 IPC 转发，权限和参数范围由服务端再次校验。
    case 'snapshotCsv': return { method: 'POST', path: '/api/v1/tables/snapshot-csv', body: payload }
    case 'queryTable': return { method: 'POST', path: '/api/v1/tables/query', body: payload }
    case 'querySuppliers': return { method: 'POST', path: '/api/v1/suppliers/query', body: payload }
    case 'suppliers': return { method: 'GET', path: '/api/v1/suppliers' }
    case 'createSupplier': return { method: 'POST', path: '/api/v1/suppliers', body: payload }
    case 'customers': return { method: 'GET', path: '/api/v1/customers' }
    // 资料修改和订单移交使用固定白名单路径，编号必须为正整数。
    case 'updateCustomer': return { method: 'PUT', path: `/api/v1/customers/${positiveId(payload, 'id')}`, body: payload }
    case 'customerHistory': return { method: 'GET', path: `/api/v1/customers/${positiveId(payload, 'id')}/history` }
    case 'transferSalesOwner': return { method: 'PUT', path: `/api/v1/customers/orders/${positiveId(payload, 'orderId')}/owner`, body: payload }
    case 'createCustomer': return { method: 'POST', path: '/api/v1/customers', body: payload }
    case 'materials': return { method: 'GET', path: '/api/v1/materials' }
    case 'createMaterial': return { method: 'POST', path: '/api/v1/materials', body: payload }
    case 'warehouses': return { method: 'GET', path: '/api/v1/warehouses' }
    case 'otherInbounds': return { method: 'GET', path: '/api/v1/warehouse-inbounds' }
    case 'createOtherInbound': return { method: 'POST', path: '/api/v1/warehouse-inbounds', body: payload }
    case 'postOtherInbound': return { method: 'POST', path: `/api/v1/warehouse-inbounds/${positiveId(payload, 'inboundId')}/post` }
    case 'cancelOtherInbound': return { method: 'POST', path: `/api/v1/warehouse-inbounds/${positiveId(payload, 'inboundId')}/cancel` }
    case 'reverseOtherInbound': {
      const inboundId = positiveId(payload, 'inboundId')
      const fields = payload as ErpOperations['reverseOtherInbound']['input']
      return { method: 'POST', path: `/api/v1/warehouse-inbounds/${inboundId}/reverse`, body: { reason: fields.reason } }
    }
    case 'warehouseOutbounds': return { method: 'GET', path: '/api/v1/warehouse-outbounds' }
    case 'createOtherOutbound': return { method: 'POST', path: '/api/v1/warehouse-outbounds', body: payload }
    case 'postWarehouseOutbound': return { method: 'POST', path: `/api/v1/warehouse-outbounds/${positiveId(payload, 'outboundId')}/post` }
    case 'cancelOtherOutbound': return { method: 'POST', path: `/api/v1/warehouse-outbounds/${positiveId(payload, 'outboundId')}/cancel` }
    case 'reverseOtherOutbound': {
      const outboundId = positiveId(payload, 'outboundId')
      const fields = payload as ErpOperations['reverseOtherOutbound']['input']
      return { method: 'POST', path: `/api/v1/warehouse-outbounds/${outboundId}/reverse`, body: { reason: fields.reason } }
    }
    case 'stockAdjustments': return { method: 'GET', path: '/api/v1/stock-adjustments' }
    case 'createStockAdjustment': return { method: 'POST', path: '/api/v1/stock-adjustments', body: payload }
    case 'submitStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/submit` }
    case 'approveStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/approve` }
    case 'rejectStockAdjustment': {
      const adjustmentId = positiveId(payload, 'adjustmentId')
      const fields = payload as ErpOperations['rejectStockAdjustment']['input']
      return { method: 'POST', path: `/api/v1/stock-adjustments/${adjustmentId}/reject`, body: { reason: fields.reason } }
    }
    case 'cancelStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/cancel` }
    case 'postStockAdjustment': return { method: 'POST', path: `/api/v1/stock-adjustments/${positiveId(payload, 'adjustmentId')}/post` }
    case 'reverseStockAdjustment': {
      const adjustmentId = positiveId(payload, 'adjustmentId')
      const fields = payload as ErpOperations['reverseStockAdjustment']['input']
      return { method: 'POST', path: `/api/v1/stock-adjustments/${adjustmentId}/reverse`, body: { reason: fields.reason } }
    }
    case 'createWarehouse': return { method: 'POST', path: '/api/v1/warehouses', body: payload }
    case 'receipts': return { method: 'GET', path: '/api/v1/receipts' }
    case 'goodsReceipts': return { method: 'GET', path: '/api/v1/purchase-goods-receipts' }
    case 'createGoodsReceipt': return { method: 'POST', path: '/api/v1/purchase-goods-receipts', body: payload }
    case 'confirmGoodsReceipt': return { method: 'POST', path: `/api/v1/purchase-goods-receipts/${positiveId(payload, 'goodsReceiptId')}/confirm` }
    case 'cancelGoodsReceipt': return { method: 'POST', path: `/api/v1/purchase-goods-receipts/${positiveId(payload, 'goodsReceiptId')}/cancel` }
    case 'createReceipt': return { method: 'POST', path: '/api/v1/receipts', body: payload }
    case 'postReceipt': return { method: 'POST', path: `/api/v1/receipts/${positiveId(payload, 'receiptId')}/post` }
    case 'reverseReceipt': {
      const receiptId = positiveId(payload, 'receiptId')
      const fields = payload as ErpOperations['reverseReceipt']['input']
      return { method: 'POST', path: `/api/v1/receipts/${receiptId}/reverse`, body: { reason: fields.reason } }
    }
    // 采购退货单编号只能通过正整数校验后进入固定路径。
    case 'purchaseReturns': return { method: 'GET', path: '/api/v1/purchase-returns' }
    case 'receivablesPayables': return { method: 'GET', path: '/api/v1/finance/receivables-payables' }
    case 'financeOverview': return { method: 'GET', path: '/api/v1/finance/overview' }
    case 'inventoryValuation': return { method: 'GET', path: '/api/v1/inventory/valuation' }
    case 'inventoryCostInputs': return { method: 'GET', path: '/api/v1/inventory/valuation/inputs' }
    case 'recordInventoryCost': return { method: 'POST', path: '/api/v1/inventory/valuation/inputs', body: payload }
    case 'financeAccounts': return { method: 'GET', path: '/api/v1/finance/accounts' }
    case 'ledgerAccounts': return { method: 'GET', path: '/api/v1/finance/ledger-accounts' }
    case 'createLedgerAccount': return { method: 'POST', path: '/api/v1/finance/ledger-accounts', body: payload }
    case 'ledgerAccountChanges': return { method: 'GET', path: `/api/v1/finance/ledger-accounts/${positiveId(payload, 'id')}/changes` }
    case 'updateLedgerAccount': {
      const id = positiveId(payload, 'id')
      const fields = payload as ErpOperations['updateLedgerAccount']['input']
      return { method: 'PUT', path: `/api/v1/finance/ledger-accounts/${id}`,
        body: { name: fields.name, is_active: fields.is_active, version: fields.version, reason: fields.reason } }
    }
    case 'accountingPeriods': return { method: 'GET', path: '/api/v1/finance/accounting-periods' }
    case 'createAccountingPeriod': return { method: 'POST', path: '/api/v1/finance/accounting-periods', body: payload }
    case 'accountingPeriodChanges': return { method: 'GET', path: `/api/v1/finance/accounting-periods/${positiveId(payload, 'id')}/changes` }
    case 'periodClosingCheck': return { method: 'GET', path: `/api/v1/finance/accounting-periods/${positiveId(payload, 'id')}/closing-check` }
    case 'periodClosingHistory': return { method: 'GET', path: `/api/v1/finance/accounting-periods/${positiveId(payload, 'id')}/closings` }
    case 'changePeriodClosingStatus': {
      const id = positiveId(payload, 'id')
      const fields = payload as ErpOperations['changePeriodClosingStatus']['input']
      if (!['close', 'reopen'].includes(fields.action)) throw new Error('结账操作无效。')
      return { method: 'POST', path: `/api/v1/finance/accounting-periods/${id}/${fields.action}`,
        body: { version: fields.version, reason: fields.reason } }
    }
    case 'updateAccountingPeriod': {
      const id = positiveId(payload, 'id')
      const fields = payload as ErpOperations['updateAccountingPeriod']['input']
      return { method: 'PUT', path: `/api/v1/finance/accounting-periods/${id}`,
        body: { name: fields.name, version: fields.version, reason: fields.reason } }
    }
    case 'journals': return { method: 'GET', path: '/api/v1/finance/journals' }
    case 'businessJournalSources': return { method: 'GET', path: '/api/v1/finance/business-journals' }
    case 'profitTransferOptions': return { method: 'GET', path: '/api/v1/finance/profit-transfers/policy' }
    case 'profitTransferPolicyChanges': return { method: 'GET', path: '/api/v1/finance/profit-transfers/policy/changes' }
    case 'profitTransferPreview': return { method: 'GET', path: `/api/v1/finance/profit-transfers/periods/${positiveId(payload, 'id')}?paged=${payload && typeof payload === 'object' && 'paged' in payload && payload.paged === true}` }
    case 'saveProfitTransferPolicy': {
      const { version, start_date, target_account_id, cost_account_ids, reason } = payload as ErpOperations['saveProfitTransferPolicy']['input']
      return { method: 'PUT', path: '/api/v1/finance/profit-transfers/policy', body: { version, start_date, target_account_id, cost_account_ids, reason } }
    }
    case 'generateProfitTransfer': {
      const { period_id, period_version, policy_version, fingerprint, reference, reason } = payload as ErpOperations['generateProfitTransfer']['input']
      return { method: 'POST', path: '/api/v1/finance/profit-transfers/generate', body: { period_id, period_version, policy_version, fingerprint, reference, reason } }
    }
    case 'businessJournalOptions': return { method: 'GET', path: '/api/v1/finance/business-journals/policy' }
    case 'businessJournalPolicyChanges': return { method: 'GET', path: '/api/v1/finance/business-journals/policy/changes' }
    case 'saveBusinessJournalPolicy': {
      const { version, start_date, mapping, reason } = payload as ErpOperations['saveBusinessJournalPolicy']['input']
      return { method: 'PUT', path: '/api/v1/finance/business-journals/policy', body: { version, start_date, mapping, reason } }
    }
    case 'generateBusinessJournal': {
      const { source_key, fingerprint, policy_version, reference, journal_date, reason } = payload as ErpOperations['generateBusinessJournal']['input']
      return { method: 'POST', path: '/api/v1/finance/business-journals/generate', body: { source_key, fingerprint, policy_version, reference, journal_date, reason } }
    }
    case 'openingBalances': return { method: 'GET', path: '/api/v1/finance/opening-balances' }
    case 'openingBalanceOptions': return { method: 'GET', path: '/api/v1/finance/opening-balances/options' }
    case 'openingBalanceChanges': return { method: 'GET', path: `/api/v1/finance/opening-balances/${positiveId(payload, 'id')}/changes` }
    case 'createOpeningBalance':
    case 'updateOpeningBalance': {
      const { reference, effective_date, note, reason, lines, ...rest } = payload as ErpOperations['updateOpeningBalance']['input']
      const path = '/api/v1/finance/opening-balances'
      return action === 'createOpeningBalance'
        ? { method: 'POST', path, body: { reference, effective_date, note, reason, lines } }
        : { method: 'PUT', path: `${path}/${positiveId(payload, 'id')}`, body: { version: rest.version, reference, effective_date, note, reason, lines } }
    }
    case 'changeOpeningBalanceStatus': {
      const { action: command, version, reason } = payload as ErpOperations['changeOpeningBalanceStatus']['input']
      if (!['submit','approve','reject','confirm','cancel','reverse'].includes(command)) throw new Error('不允许的期初状态操作')
      return { method: 'POST', path: `/api/v1/finance/opening-balances/${positiveId(payload, 'id')}/${command}`, body: { version, reason } }
    }
    case 'journalDetail': return { method: 'GET', path: `/api/v1/finance/journals/${positiveId(payload, 'id')}?paged=${payload && typeof payload === 'object' && 'paged' in payload && payload.paged === true}` }
    case 'ledgerReportOptions': return { method: 'GET', path: '/api/v1/finance/ledger-reports/options' }
    case 'queryLedgerReport': {
      const { kind, from_date, to_date, account_id } = payload as ErpOperations['queryLedgerReport']['input']
      return { method: 'POST', path: '/api/v1/finance/ledger-reports/query', body: { kind, from_date, to_date, account_id } }
    }
    case 'journalOptions': return { method: 'GET', path: '/api/v1/finance/journals/options' }
    case 'journalChanges': return { method: 'GET', path: `/api/v1/finance/journals/${positiveId(payload, 'id')}/changes` }
    case 'createJournal': return { method: 'POST', path: '/api/v1/finance/journals', body: payload }
    case 'updateJournal': {
      const id = positiveId(payload, 'id')
      const { version, reference, journal_date, note, reason, lines } = payload as ErpOperations['updateJournal']['input']
      return { method: 'PUT', path: `/api/v1/finance/journals/${id}`, body: { version, reference, journal_date, note, reason, lines } }
    }
    case 'changeJournalStatus': {
      const id = positiveId(payload, 'id')
      const { action, version, reason } = payload as ErpOperations['changeJournalStatus']['input']
      if (!['submit', 'approve', 'reject', 'post', 'cancel'].includes(action)) throw new Error('不允许的凭证状态操作')
      return { method: 'POST', path: `/api/v1/finance/journals/${id}/${action}`, body: { version, reason } }
    }
    case 'reverseJournal': {
      const id = positiveId(payload, 'id')
      const { version, reference, journal_date, reason } = payload as ErpOperations['reverseJournal']['input']
      return { method: 'POST', path: `/api/v1/finance/journals/${id}/reverse`, body: { version, reference, journal_date, reason } }
    }
    case 'paymentRecords': return { method: 'GET', path: '/api/v1/finance/payment-records' }
    case 'queryTrace': return { method:'POST', path:'/api/v1/trace/query',body:payload }
    case 'allocateSalesWork': return { method:'PUT',path:'/api/v1/trace/allocations',body:payload }
    case 'financeTools': return { method: 'POST', path: '/api/v1/finance/tools', body: payload }
    case 'createPaymentRecord': return { method: 'POST', path: '/api/v1/finance/payment-records', body: payload }
    case 'reversePaymentRecord': return {
      method: 'POST', path: `/api/v1/finance/payment-records/${positiveId(payload, 'paymentId')}/reverse`,
      body: { reason: (payload as { reason: unknown }).reason }
    }
    // BOM 的生命周期操作只接受经校验的单据编号。
    case 'boms': return { method: 'GET', path: '/api/v1/boms' }
    case 'createBom': return { method: 'POST', path: '/api/v1/boms', body: payload }
    case 'activateBom': return { method: 'POST', path: `/api/v1/boms/${positiveId(payload, 'bomId')}/activate` }
    case 'retireBom': return { method: 'POST', path: `/api/v1/boms/${positiveId(payload, 'bomId')}/retire` }
    case 'cancelBom': return { method: 'POST', path: `/api/v1/boms/${positiveId(payload, 'bomId')}/cancel` }
    case 'workOrders': return { method: 'GET', path: '/api/v1/work-orders' }
    case 'createWorkOrder': return { method: 'POST', path: '/api/v1/work-orders', body: payload }
    case 'releaseWorkOrder': return { method: 'POST', path: `/api/v1/work-orders/${positiveId(payload, 'orderId')}/release` }
    case 'cancelWorkOrder': return { method: 'POST', path: `/api/v1/work-orders/${positiveId(payload, 'orderId')}/cancel` }
    case 'materialIssues': return { method: 'GET', path: '/api/v1/material-issues' }
    case 'createMaterialIssue': return { method: 'POST', path: '/api/v1/material-issues', body: payload }
    case 'postMaterialIssue': return { method: 'POST', path: `/api/v1/material-issues/${positiveId(payload, 'issueId')}/post` }
    case 'cancelMaterialIssue': return { method: 'POST', path: `/api/v1/material-issues/${positiveId(payload, 'issueId')}/cancel` }
    case 'materialReturns': return { method: 'GET', path: '/api/v1/material-returns' }
    case 'createMaterialReturn': return { method: 'POST', path: '/api/v1/material-returns', body: payload }
    case 'postMaterialReturn': return { method: 'POST', path: `/api/v1/material-returns/${positiveId(payload, 'returnId')}/post` }
    case 'cancelMaterialReturn': return { method: 'POST', path: `/api/v1/material-returns/${positiveId(payload, 'returnId')}/cancel` }
    case 'productionCompletions': return { method: 'GET', path: '/api/v1/production-completions' }
    case 'createProductionCompletion': return { method: 'POST', path: '/api/v1/production-completions', body: payload }
    case 'inspectProductionCompletion': {
      const completionId = positiveId(payload, 'completionId')
      const fields = payload as ErpOperations['inspectProductionCompletion']['input']
      // 路径编号只用于定位单据，请求体仅发送质检接口确认的正式字段。
      return { method: 'POST', path: `/api/v1/production-completions/${completionId}/inspect`,
        body: { accepted_quantity: fields.accepted_quantity, qc_note: fields.qc_note } }
    }
    case 'postProductionCompletion': return { method: 'POST', path: `/api/v1/production-completions/${positiveId(payload, 'completionId')}/post` }
    case 'cancelProductionCompletion': return { method: 'POST', path: `/api/v1/production-completions/${positiveId(payload, 'completionId')}/cancel` }
    case 'reverseProductionCompletion': {
      const completionId = positiveId(payload, 'completionId')
      const fields = payload as ErpOperations['reverseProductionCompletion']['input']
      // 单据编号只用于受限路径，请求体只传冲销原因。
      return { method: 'POST', path: `/api/v1/production-completions/${completionId}/reverse`,
        body: { reason: fields.reason } }
    }
    case 'productionCosts': return { method: 'GET', path: '/api/v1/production-costs' }
    case 'productionCostSettlements': return { method: 'GET', path: '/api/v1/production-costs/settlements' }
    case 'settleProductionCost': return { method: 'POST', path: '/api/v1/production-costs/settlements', body: payload }
    case 'reverseProductionSettlement': {
      const settlementId = positiveId(payload, 'settlementId')
      const fields = payload as ErpOperations['reverseProductionSettlement']['input']
      return { method: 'POST', path: `/api/v1/production-costs/settlements/${settlementId}/reverse`, body: { reason: fields.reason } }
    }
    case 'recordMaterialValuation': return { method: 'POST', path: '/api/v1/production-costs/material-valuations', body: payload }
    case 'recordProductionCharge': return { method: 'POST', path: '/api/v1/production-costs/charges', body: payload }
    case 'reverseProductionCost': {
      const entryId = positiveId(payload, 'entryId')
      const fields = payload as ErpOperations['reverseProductionCost']['input']
      // 记录编号只进入固定路径，请求体仅包含冲销原因。
      return { method: 'POST', path: `/api/v1/production-costs/${entryId}/reverse`, body: { reason: fields.reason } }
    }
    case 'createPurchaseReturn': return { method: 'POST', path: '/api/v1/purchase-returns', body: payload }
    case 'submitPurchaseReturn': return { method: 'POST', path: `/api/v1/purchase-returns/${positiveId(payload, 'returnId')}/submit` }
    case 'postPurchaseReturn': return { method: 'POST', path: `/api/v1/purchase-returns/${positiveId(payload, 'returnId')}/post` }
    case 'cancelPurchaseReturn': return { method: 'POST', path: `/api/v1/purchase-returns/${positiveId(payload, 'returnId')}/cancel` }
    case 'reversePurchaseReturn': {
      const returnId = positiveId(payload, 'returnId')
      const fields = payload as ErpOperations['reversePurchaseReturn']['input']
      return { method: 'POST', path: `/api/v1/purchase-returns/${returnId}/reverse`, body: { reason: fields.reason } }
    }
    case 'purchaseOrders': return { method: 'GET', path: '/api/v1/purchase-orders' }
    case 'purchaseRequests': return { method: 'GET', path: '/api/v1/purchase-requests' }
    case 'createPurchaseRequest': return { method: 'POST', path: '/api/v1/purchase-requests', body: payload }
    case 'updatePurchaseRequest': {
      const requestId = positiveId(payload, 'requestId')
      const fields = payload as ErpOperations['updatePurchaseRequest']['input']
      return { method: 'PUT', path: `/api/v1/purchase-requests/${requestId}`,
        body: { reference: fields.reference, note: fields.note, lines: fields.lines } }
    }
    case 'submitPurchaseRequest': return { method: 'POST', path: `/api/v1/purchase-requests/${positiveId(payload, 'requestId')}/submit` }
    case 'approvePurchaseRequest': return { method: 'POST', path: `/api/v1/purchase-requests/${positiveId(payload, 'requestId')}/approve` }
    case 'rejectPurchaseRequest': {
      const requestId = positiveId(payload, 'requestId')
      const fields = payload as ErpOperations['rejectPurchaseRequest']['input']
      return { method: 'POST', path: `/api/v1/purchase-requests/${requestId}/reject`, body: { reason: fields.reason } }
    }
    case 'cancelPurchaseRequest': return { method: 'POST', path: `/api/v1/purchase-requests/${positiveId(payload, 'requestId')}/cancel` }
    case 'createPurchaseOrder': return { method: 'POST', path: '/api/v1/purchase-orders', body: payload }
    case 'confirmPurchaseOrder': return { method: 'POST', path: `/api/v1/purchase-orders/${positiveId(payload, 'orderId')}/confirm` }
    case 'cancelPurchaseOrder': return { method: 'POST', path: `/api/v1/purchase-orders/${positiveId(payload, 'orderId')}/cancel` }
    case 'salesOrders': return { method: 'GET', path: '/api/v1/sales-orders' }
    case 'createSalesOrder': return { method: 'POST', path: '/api/v1/sales-orders', body: payload }
    case 'confirmSalesOrder': return { method: 'POST', path: `/api/v1/sales-orders/${positiveId(payload, 'orderId')}/confirm` }
    case 'cancelSalesOrder': return { method: 'POST', path: `/api/v1/sales-orders/${positiveId(payload, 'orderId')}/cancel` }
    case 'shipments': return { method: 'GET', path: '/api/v1/shipments' }
    case 'createShipment': return { method: 'POST', path: '/api/v1/shipments', body: payload }
    case 'postShipment': return { method: 'POST', path: `/api/v1/shipments/${positiveId(payload, 'shipmentId')}/post` }
    case 'cancelShipment': return { method: 'POST', path: `/api/v1/shipments/${positiveId(payload, 'shipmentId')}/cancel` }
    case 'reverseShipment': {
      const shipmentId = positiveId(payload, 'shipmentId')
      const fields = payload as ErpOperations['reverseShipment']['input']
      return { method: 'POST', path: `/api/v1/shipments/${shipmentId}/reverse`, body: { reason: fields.reason } }
    }
    // 退货只能调用固定路径，单据编号先校验再拼接，避免渲染层指定任意 URL。
    case 'salesReturns': return { method: 'GET', path: '/api/v1/sales-returns' }
    case 'createSalesReturn': return { method: 'POST', path: '/api/v1/sales-returns', body: payload }
    case 'postSalesReturn': return { method: 'POST', path: `/api/v1/sales-returns/${positiveId(payload, 'returnId')}/post` }
    case 'cancelSalesReturn': return { method: 'POST', path: `/api/v1/sales-returns/${positiveId(payload, 'returnId')}/cancel` }
    case 'reverseSalesReturn': {
      const returnId = positiveId(payload, 'returnId')
      const fields = payload as ErpOperations['reverseSalesReturn']['input']
      return { method: 'POST', path: `/api/v1/sales-returns/${returnId}/reverse`, body: { reason: fields.reason } }
    }
    case 'transfers': return { method: 'GET', path: '/api/v1/transfers' }
    case 'createTransfer': return { method: 'POST', path: '/api/v1/transfers', body: payload }
    case 'postTransfer': return { method: 'POST', path: `/api/v1/transfers/${positiveId(payload, 'transferId')}/post` }
    case 'reverseTransfer': {
      const transferId = positiveId(payload, 'transferId')
      const fields = payload as ErpOperations['reverseTransfer']['input']
      // 调拨冲销只接收原因，目标路径固定且单据编号必须为正整数。
      return { method: 'POST', path: `/api/v1/transfers/${transferId}/reverse`, body: { reason: fields.reason } }
    }
    case 'stocktakes': return { method: 'GET', path: '/api/v1/stocktakes' }
    case 'createStocktake': return { method: 'POST', path: '/api/v1/stocktakes', body: payload }
    case 'postStocktake': return { method: 'POST', path: `/api/v1/stocktakes/${positiveId(payload, 'stocktakeId')}/post` }
    case 'cancelStocktake': return { method: 'POST', path: `/api/v1/stocktakes/${positiveId(payload, 'stocktakeId')}/cancel` }
    case 'reverseStocktake': {
      const stocktakeId = positiveId(payload, 'stocktakeId')
      const fields = payload as ErpOperations['reverseStocktake']['input']
      // 冲销只允许发送原因，单据编号由主进程校验后拼接到固定路径。
      return { method: 'POST', path: `/api/v1/stocktakes/${stocktakeId}/reverse`, body: { reason: fields.reason } }
    }
    case 'stock': return { method: 'GET', path: payload && typeof payload === 'object' && 'warehouseId' in payload && payload.warehouseId !== undefined
      ? `/api/v1/stock?warehouse_id=${positiveId(payload, 'warehouseId')}` : '/api/v1/stock' }
    case 'movements': return { method: 'GET', path: '/api/v1/movements' }
    case 'inventoryLedger': return { method: 'POST', path: '/api/v1/inventory-ledger/query', body: payload }
    case 'queryReport': return { method: 'POST', path: '/api/v1/reports/query', body: payload }
    default: throw new Error('不允许的业务操作')
  }
}

export async function callBackend(action: keyof ErpOperations, payload: unknown): Promise<unknown> {
  const request = operation(action, payload)
  const publicAction = action === 'setupStatus' || action === 'bootstrap' || action === 'login'
  if (!publicAction && !sessionToken) throw new Error('请先登录')
  const activeToken = sessionToken
  // 即使本地服务暂时不可达，退出时也立刻丢弃桌面进程持有的令牌。
  if (action === 'logout') sessionToken = null
  let response: Response
  try {
    response = await sendRequest(request.path, request.method, {
        ...(request.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(publicAction ? {} : { Authorization: `Bearer ${activeToken}` })
      }, request.body)
  } catch {
    throw new Error('无法连接服务端，请检查网络、服务状态和证书。')
  }
  const data: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined)
  if (!response.ok) {
    if (response.status === 401 && !publicAction) sessionToken = null
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined
    // FastAPI 的默认 404 文案没有操作语境，提示用户核对桌面端与服务端版本。
    if (response.status === 404 && detail === 'Not Found') {
      throw new Error('服务端未找到此功能（HTTP 404）。请确认桌面端与服务端版本一致。')
    }
    throw new Error(typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}）`)
  }
  if (action === 'login') {
    if (!data || typeof data !== 'object' || !('token' in data) || typeof data.token !== 'string'
      || !('user' in data) || !data.user) throw new Error('登录响应格式不匹配')
    sessionToken = data.token
    return data.user
  }
  if (action === 'logout' || action === 'changePassword') sessionToken = null
  return data
}

export async function getBackendHealth(): Promise<BackendHealth> {
  try {
    // 地址只由主进程环境配置，页面不能传入任意 URL。
    const response = await sendRequest('/api/v1/health', 'GET', {}, undefined, 5000)
    if (!response.ok) {
      return { connected: false, message: `后端返回 HTTP ${response.status}，请检查服务后重试。` }
    }
    const data: unknown = await response.json()
    if (!data || typeof data !== 'object' || !('status' in data) || data.status !== 'ok'
      || !('service' in data) || data.service !== 'nexora-api'
      || !('version' in data) || typeof data.version !== 'string' || !data.version.trim()) {
      return { connected: false, message: '后端响应格式不匹配，请确认运行的是 Nexora API。' }
    }
    return { connected: true, version: data.version }
  } catch (error) {
    return { connected: false, message: error instanceof Error && error.message.includes('配置无效')
      ? error.message : '无法连接后端，请确认服务已启动、地址正确，然后重试。' }
  }
}
