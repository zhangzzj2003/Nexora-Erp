/** 工作台页面地址与查看权限统一在此登记，写操作仍由服务端逐项授权。 */
import type { MenuIconKey } from '../../../shared/menu-icons'
type RouteIcon = MenuIconKey

interface RouteEntry {
  key: string
  path: string
  label: string
  permission: string | null
  icon: RouteIcon
}

interface RouteGroup {
  icon: MenuIconKey
  key: string
  label: string
  routes: readonly RouteEntry[]
}

export const workspaceRouteGroups = [
  {
    key: 'home',
    icon: 'dashboard',
    label: '工作台',
    routes: [
      {
        key: 'home',
        path: '/workspace/home',
        label: '工作台首页',
        permission: null,
        icon: 'dashboard'
      }
    ]
  },
  {
    key: 'warehouse',
    icon: 'warehouse',
    label: '仓库管理',
    routes: [
      {
        key: 'otherInbounds',
        path: '/workspace/warehouse-inbounds',
        label: '其他入库',
        permission: 'other_inbound.view',
        icon: 'archive'
      },
      {
        key: 'warehouseOutbounds',
        path: '/workspace/warehouse-outbounds',
        label: '仓库出库',
        permission: 'other_outbound.view',
        icon: 'archive'
      },
      {
        key: 'stock',
        path: '/workspace/stock',
        label: '库存总览',
        permission: 'inventory.view',
        icon: 'stack'
      },
      {
        key: 'inventoryWarnings',
        path: '/workspace/inventory-warnings',
        label: '库存预警',
        permission: 'inventory.view',
        icon: 'stack'
      },
      {
        key: 'physicalLots',
        path: '/workspace/physical-lots',
        label: '实物批次',
        permission: 'inventory.view',
        icon: 'history'
      },
      {
        key: 'inventoryLedger',
        path: '/workspace/inventory-ledger',
        label: '库存台账',
        permission: 'inventory.view',
        icon: 'history'
      },
      {
        key: 'transfers',
        path: '/workspace/transfers',
        label: '仓库调拨',
        permission: 'inventory.view',
        icon: 'stack'
      },
      {
        key: 'stockAdjustments',
        path: '/workspace/stock-adjustments',
        label: '库存调整',
        permission: 'adjustment.view',
        icon: 'file'
      },
      {
        key: 'inventoryReports',
        path: '/workspace/inventory-reports',
        label: '库存报表',
        permission: 'inventory_report.view',
        icon: 'file'
      },
      {
        key: 'stocktakes',
        path: '/workspace/stocktakes',
        label: '库存盘点',
        permission: 'inventory.view',
        icon: 'file'
      }
    ]
  },
  {
    key: 'catalog',
    icon: 'catalog',
    label: '基础资料',
    routes: [
      {
        key: 'catalog',
        path: '/workspace/catalog',
        label: '物料管理',
        permission: 'inventory.view',
        icon: 'archive'
      },
      {
        key: 'suppliers',
        path: '/workspace/suppliers',
        label: '供应商管理',
        permission: 'inventory.view',
        icon: 'archive'
      },
      // 单位目录与物料共用查看权限，新增和编辑仍单独检查资料管理权限。
      {
        key: 'materialCategoryManagement', path: '/workspace/material-categories',
        label: '物料分类与规格', permission: 'inventory.view', icon: 'catalog'
      },
      {
        key: 'materialUnits',
        path: '/workspace/material-units',
        label: '单位管理',
        permission: 'inventory.view',
        icon: 'archive'
      },
      // BOM 归入基础资料，旧地址和生产查看权限保留以兼容工单与已打开标签。
      {
        key: 'boms',
        path: '/workspace/boms',
        label: '生产 BOM',
        permission: 'production.view',
        icon: 'stack'
      },
      // 客户列表沿用服务端销售查看权限，新增仍单独检查客户管理权限。
      {
        key: 'customers',
        path: '/workspace/customers',
        label: '客户资料',
        permission: 'sales.view',
        icon: 'team'
      },
      {
        key: 'warehouses',
        path: '/workspace/warehouses',
        label: '仓库管理',
        permission: 'inventory.view',
        icon: 'archive'
      }
    ]
  },
  {
    key: 'purchase',
    icon: 'purchase',
    label: '采购管理',
    routes: [
      {
        key: 'purchaseRequests',
        path: '/workspace/purchase-requests',
        label: '采购申请',
        permission: 'purchase_request.view',
        icon: 'file'
      },
      {
        key: 'purchase',
        path: '/workspace/purchase-orders',
        label: '采购订单',
        permission: 'inventory.view',
        icon: 'file'
      },
      {
        key: 'goodsReceipts',
        path: '/workspace/purchase-goods-receipts',
        label: '采购收货',
        permission: 'purchase_receiving.view',
        icon: 'file'
      },
      {
        key: 'receipts',
        path: '/workspace/receipts',
        label: '采购入库',
        permission: 'inventory.view',
        icon: 'file'
      },
      {
        key: 'purchaseReports',
        path: '/workspace/purchase-reports',
        label: '采购报表',
        permission: 'purchase_report.view',
        icon: 'file'
      },
      {
        key: 'purchaseReturns',
        path: '/workspace/purchase-returns',
        label: '采购退货',
        permission: 'inventory.view',
        icon: 'history'
      }
    ]
  },
  {
    key: 'sales',
    icon: 'sales',
    label: '销售管理',
    routes: [
      { key: 'customerRelations', path: '/workspace/customer-relations', label: '客户关系与报价', permission: 'crm.view', icon: 'team' },
      { key: 'afterSales', path: '/workspace/after-sales', label: '售后退换修', permission: 'after_sales.view', icon: 'history' },
      {
        key: 'sales',
        path: '/workspace/sales-orders',
        label: '销售订单',
        permission: 'sales.view',
        icon: 'file'
      },
      {
        key: 'shipments',
        path: '/workspace/shipments',
        label: '销售出库',
        permission: 'sales.view',
        icon: 'archive'
      },
      {
        key: 'salesReturns',
        path: '/workspace/sales-returns',
        label: '销售退货',
        permission: 'sales.view',
        icon: 'history'
      }
    ]
  },
  {
    key: 'finance',
    icon: 'finance',
    label: '财务管理',
    routes: [
      { key: 'journals', path: '/workspace/journals', label: '总账凭证', permission: 'journal.view', icon: 'file' },
      { key: 'openingBalances', path: '/workspace/opening-balances', label: '期初余额', permission: 'opening_balance.view', icon: 'file' },
      { key: 'subledgerOpenings', path: '/workspace/subledger-openings', label: '分户期初', permission: 'subledger_opening.view', icon: 'file' },
      { key: 'ledgerReports', path: '/workspace/ledger-reports', label: '总账报表', permission: 'journal.view', icon: 'chart' },
      { key: 'financialStatements', path: '/workspace/financial-statements', label: '财务报表', permission: 'financial_statement.view', icon: 'chart' },
      { key: 'auxiliaryAccounting', path: '/workspace/auxiliary-accounting', label: '辅助核算', permission: 'auxiliary.view', icon: 'file' },
      {
        key: 'ledgerAccounts',
        path: '/workspace/ledger-accounts',
        label: '总账科目',
        permission: 'ledger_account.view',
        icon: 'finance'
      },
      {
        key: 'accountingPeriods',
        path: '/workspace/accounting-periods',
        label: '会计期间',
        permission: 'accounting_period.view',
        icon: 'history'
      },
      {
        key: 'inventoryValuation',
        path: '/workspace/inventory-valuation',
        label: '库存计价',
        permission: 'inventory_valuation.view',
        icon: 'file'
      },
      {
        key: 'finance',
        path: '/workspace/finance',
        label: '应收应付',
        permission: 'finance.view',
        icon: 'file'
      },
      // 页面职责拆分，查看权限和服务端写操作权限继续保持原有边界。
      {
        key: 'financePayments',
        path: '/workspace/payment-records',
        label: '收付款记录',
        permission: 'finance.view',
        icon: 'history'
      },
      {
        key: 'bankReconciliation',
        path: '/workspace/bank-reconciliation',
        label: '银行勾对',
        permission: 'bank_reconciliation.view',
        icon: 'history'
      },
      {
        key: 'bankBalance',
        path: '/workspace/bank-balance',
        label: '银行余额调节',
        permission: 'bank_reconciliation.view',
        icon: 'file'
      },
      {
        key: 'financeSources',
        path: '/workspace/financial-sources',
        label: '应收应付来源',
        permission: 'finance.view',
        icon: 'file'
      }
    ]
  },
  {
    key: 'production',
    icon: 'production',
    label: '生产管理',
    routes: [
      {
        key: 'workOrders',
        path: '/workspace/work-orders',
        label: '生产工单',
        permission: 'production.view',
        icon: 'file'
      },
      {
        key: 'materialIssues',
        path: '/workspace/material-issues',
        label: '生产领料',
        permission: 'production.view',
        icon: 'archive'
      },
      {
        key: 'materialReturns',
        path: '/workspace/material-returns',
        label: '生产退料',
        permission: 'production.view',
        icon: 'history'
      },
      {
        key: 'productionCompletions',
        path: '/workspace/production-completions',
        label: '完工与质检',
        permission: 'production.view',
        icon: 'file'
      },
      {
        key: 'productionCosts',
        path: '/workspace/production-costs',
        label: '生产成本',
        permission: 'production_cost.view',
        icon: 'file'
      },
      { key: 'materialPlanning', path: '/workspace/material-planning', label: '物料需求计划', permission: 'mrp.view', icon: 'file' },
      { key: 'qualityDisposition', path: '/workspace/production-quality', label: '不合格品处置与返工', permission: 'quality.view', icon: 'file' },
      { key: 'equipmentMaintenance', path: '/workspace/equipment-maintenance', label: '设备维护', permission: 'equipment.view', icon: 'file' }
    ]
  },
  {
    key: 'system',
    icon: 'settings',
    label: '系统管理',
    routes: [
      // 管理入口沿用同一查看权限，页面写操作仍由服务端逐项校验。
      {
        key: 'menuManagement',
        path: '/workspace/menu-management',
        label: '菜单管理',
        permission: 'users.manage',
        icon: 'menu'
      },
      {
        key: 'users',
        path: '/workspace/users',
        label: '用户管理',
        permission: 'users.manage',
        icon: 'team'
      },
      {
        key: 'roles',
        path: '/workspace/roles',
        label: '权限管理',
        permission: 'users.manage',
        icon: 'settings'
      },
      {
        key: 'permissionCatalog',
        path: '/workspace/permission-catalog',
        label: '权限目录',
        permission: 'users.manage',
        icon: 'file'
      },
      {
        key: 'settings',
        path: '/workspace/settings',
        label: '连接与服务',
        permission: null,
        icon: 'settings'
      }
    ]
  }
] as const satisfies readonly RouteGroup[]

export type WorkspaceRoute =
  (typeof workspaceRouteGroups)[number]['routes'][number]
export type WorkspaceRouteKey = WorkspaceRoute['key']
export type WorkspaceRouteGroupKey =
  (typeof workspaceRouteGroups)[number]['key']
export const workspaceRoutes: readonly WorkspaceRoute[] =
  workspaceRouteGroups.flatMap<WorkspaceRoute>((group) => group.routes)

export function nextExpandedGroup(
  current: WorkspaceRouteGroupKey | null,
  selected: WorkspaceRouteGroupKey
): WorkspaceRouteGroupKey | null {
  // 只保存一个展开项；再次选择同一分类时恢复全部收起状态。
  return current === selected ? null : selected
}

export function canVisitRoute(
  route: WorkspaceRoute,
  permissions: readonly string[]
): boolean {
  return route.permission === null || permissions.includes(route.permission)
}

export function routeByKey(key: WorkspaceRouteKey): WorkspaceRoute {
  return workspaceRoutes.find((route) => route.key === key)!
}

export function routeGroupByKey(key: WorkspaceRouteKey) {
  // 顶部目录与侧栏共用分类定义，页面移动分类后不需要维护第二份路径文案。
  return workspaceRouteGroups.find((group) => group.routes.some((route) => route.key === key))!
}

// 页面栏保存本次登录打开过的页面顺序，同一页面只出现一次。
export function openRoute(
  opened: readonly WorkspaceRouteKey[],
  key: WorkspaceRouteKey
): WorkspaceRouteKey[] {
  return opened.includes(key) ? [...opened] : [...opened, key]
}

// 服务端权限变化后立即清理无权访问的页面，不能让旧入口继续留在页面栏。
export function permittedOpenedRoutes(
  opened: readonly WorkspaceRouteKey[],
  permissions: readonly string[]
): WorkspaceRouteKey[] {
  return opened.filter((key) => canVisitRoute(routeByKey(key), permissions))
}

export function closeRoute(
  opened: readonly WorkspaceRouteKey[],
  closing: WorkspaceRouteKey,
  active: WorkspaceRouteKey
): { opened: WorkspaceRouteKey[]; active: WorkspaceRouteKey } {
  const index = opened.indexOf(closing)
  // 当前页面是唯一入口时保留它，避免出现没有可显示页面的工作台。
  if (index < 0 || opened.length === 1) return { opened: [...opened], active }
  const remaining = opened.filter((key) => key !== closing)
  return {
    opened: remaining,
    active: closing === active ? remaining[Math.max(0, index - 1)] : active
  }
}

export function resolveWorkspaceRoute(
  path: string,
  permissions: readonly string[]
): WorkspaceRoute {
  const requested = workspaceRoutes.find((route) => path === route.path)
  if (requested && canVisitRoute(requested, permissions)) return requested
  // 首页不依赖业务查看权限，未知地址或权限变化时都能安全回到工作台。
  return workspaceRoutes.find((route) => canVisitRoute(route, permissions))!
}

export function visibleRouteGroups(permissions: readonly string[]) {
  return workspaceRouteGroups
    .map((group) => ({
      key: group.key,
      label: group.label,
      icon: group.icon,
      routes: group.routes.filter((route) => canVisitRoute(route, permissions))
    }))
    .filter((group) => group.routes.length > 0)
}
