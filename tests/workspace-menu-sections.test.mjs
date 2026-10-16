import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  routeMenuSections,
  visibleRouteGroups,
  workspaceRouteGroups
} from '../src/renderer/src/router/workspace-routes.ts'

const warehouse = workspaceRouteGroups.find(group => group.key === 'warehouse')
const allWarehousePermissions = [...new Set(warehouse.routes.map(route => route.permission).filter(Boolean))]

// 使用真实权限过滤后的入口验证分段，防止分类绕过已有查看权限。
function visibleWarehouseSections(permissions) {
  const group = visibleRouteGroups(permissions).find(entry => entry.key === 'warehouse')
  return routeMenuSections(group?.routes ?? [])
}

test('仓库管理的 14 个入口按业务类型分段且不丢失、不重复', () => {
  const sections = visibleWarehouseSections(allWarehousePermissions)

  assert.deepEqual(sections.map(section => [section.key, section.label, section.routes.map(route => route.key)]), [
    ['inbound', '入库类', ['otherInbounds']],
    ['outbound', '出库类', ['warehouseOutbounds']],
    ['production', '生产类', ['productionDispatches', 'productionReceipts', 'productionExchanges', 'productionReturns']],
    ['reports', '报表类', ['stock', 'inventoryWarnings', 'physicalLots', 'inventoryLedger', 'inventoryReports']],
    ['tools', '功能类', ['transfers', 'stockAdjustments', 'stocktakes']]
  ])

  const routes = sections.flatMap(section => section.routes)
  assert.equal(routes.length, 14)
  assert.equal(new Set(routes.map(route => route.key)).size, 14)
  assert.deepEqual(new Set(routes), new Set(warehouse.routes))
})

test('查看权限只留下已授权入口，并隐藏没有入口的分段', () => {
  const sections = visibleWarehouseSections(['other_inbound.view', 'adjustment.view'])

  assert.deepEqual(sections.map(section => [section.label, section.routes.map(route => route.key)]), [
    ['入库类', ['otherInbounds']],
    ['功能类', ['stockAdjustments']]
  ])
  assert.ok(sections.every(section => section.routes.length > 0))
})

test('只拥有生产或报表查看权限时，不产生其他类型的空标题', () => {
  assert.deepEqual(visibleWarehouseSections(['material_flow.view']).map(section => [section.key, section.routes.map(route => route.key)]), [
    ['production', ['productionDispatches', 'productionReceipts', 'productionExchanges', 'productionReturns']]
  ])
  assert.deepEqual(visibleWarehouseSections(['inventory_report.view']).map(section => [section.key, section.routes.map(route => route.key)]), [
    ['reports', ['inventoryReports']]
  ])
})

test('没有仓库查看权限或入口为空时，不返回分段', () => {
  assert.deepEqual(visibleWarehouseSections([]), [])
  assert.deepEqual(visibleWarehouseSections(['sales.view']), [])
  assert.deepEqual(routeMenuSections([]), [])
})

test('所有业务菜单使用对应类型分类，分类及入口顺序符合业务用途', () => {
  const expected = {
    catalog: [
      ['物料类', ['catalog', 'materialCategoryManagement', 'materialUnits']],
      ['往来类', ['suppliers', 'customers']],
      ['产品类', ['products', 'boms']],
      ['功能类', ['warehouses']]
    ],
    purchase: [
      ['订单类', ['purchaseRequests', 'purchase']],
      ['入库类', ['goodsReceipts', 'receipts']],
      ['退货类', ['purchaseReturns']],
      ['报表类', ['purchaseReports']]
    ],
    sales: [
      ['业务类', ['customerRelations', 'sales']],
      ['出库类', ['shipments']],
      ['售后类', ['afterSales', 'salesReturns']]
    ],
    finance: [
      ['往来类', ['controlBalanceTransfers', 'finance', 'financeSources']],
      ['核算类', ['journals', 'openingBalances', 'subledgerOpenings', 'auxiliaryAccounting']],
      ['资金类', ['financePayments', 'bankReconciliation', 'bankBalance']],
      ['报表类', ['ledgerReports', 'financialStatements', 'inventoryValuation']],
      ['功能类', ['ledgerAccounts', 'accountingPeriods']]
    ],
    production: [
      ['计划类', ['materialPlanning']],
      ['生产类', ['workOrders', 'materialIssues', 'materialReturns']],
      ['质量类', ['productionCompletions', 'qualityDisposition']],
      ['功能类', ['productionCosts', 'equipmentMaintenance']]
    ],
    system: [
      ['权限类', ['users', 'roles', 'permissionCatalog']],
      ['功能类', ['menuManagement', 'settings']]
    ]
  }

  for (const [key, expectedSections] of Object.entries(expected)) {
    const group = workspaceRouteGroups.find(entry => entry.key === key)
    const sections = routeMenuSections(group.routes)
    assert.deepEqual(sections.map(section => [section.label, section.routes.map(route => route.key)]), expectedSections, group.label)
  }

  // 首页保留原固定入口，避免为了分类额外出现只有一个入口的标题。
  const home = workspaceRouteGroups.find(group => group.key === 'home')
  assert.deepEqual(routeMenuSections(home.routes), [{ key: 'default', label: null, routes: home.routes }])
})

test('全部业务组每个可见入口只出现一次，保留原对象且没有未分类业务入口', () => {
  const permissions = [...new Set(workspaceRouteGroups.flatMap(group => group.routes.map(route => route.permission)).filter(Boolean))]
  const groups = visibleRouteGroups(permissions)

  for (const group of groups) {
    const sections = routeMenuSections(group.routes)
    const routes = sections.flatMap(section => section.routes)
    assert.equal(routes.length, group.routes.length, group.label)
    assert.equal(new Set(routes.map(route => route.key)).size, group.routes.length, group.label)
    assert.deepEqual(new Set(routes), new Set(group.routes), group.label)
    assert.ok(sections.every(section => section.routes.length > 0), group.label)
    if (group.key !== 'home') {
      assert.ok(sections.every(section => section.label && section.key !== 'default'), group.label)
    }
  }
})

test('逐项授予独立查看权限后分类无空段，且不增加任何未授权入口', () => {
  const originalRoutes = workspaceRouteGroups.flatMap(group => group.routes)
  const permissions = [...new Set(originalRoutes.map(route => route.permission).filter(Boolean))]

  // 每次只授予一个权限，覆盖共享查看权限及独立财务、管理权限的边界。
  for (const permission of permissions) {
    const groups = visibleRouteGroups([permission])
    const displayed = groups.flatMap(group => {
      const sections = routeMenuSections(group.routes)
      assert.ok(sections.every(section => section.routes.length > 0), permission)
      const routes = sections.flatMap(section => section.routes)
      assert.equal(new Set(routes.map(route => route.key)).size, routes.length, permission)
      assert.ok(routes.every(route => route.permission === null || route.permission === permission), permission)
      assert.deepEqual(new Set(routes), new Set(group.routes), permission)
      return routes
    })
    const allowed = originalRoutes.filter(route => (route.permission === null || route.permission === permission)
      && !(route.key === 'boms' && permission === 'inventory.view'))
    assert.deepEqual(new Set(displayed), new Set(allowed), permission)
  }
})

test('无业务权限时仅保留首页和连接设置，生产旧权限仍能找到产品类 BOM', () => {
  const groups = visibleRouteGroups([])
  assert.deepEqual(groups.map(group => group.key), ['home', 'system'])
  assert.deepEqual(groups.flatMap(group => routeMenuSections(group.routes).map(section => [section.label, section.routes.map(route => route.key)])), [
    [null, ['home']],
    ['功能类', ['settings']]
  ])

  const catalog = visibleRouteGroups(['production.view']).find(group => group.key === 'catalog')
  assert.deepEqual(routeMenuSections(catalog.routes).map(section => [section.label, section.routes.map(route => route.key)]), [
    ['产品类', ['boms']]
  ])
})

test('分段保留自定义菜单图标、额外数据和原路由对象身份', () => {
  // 冻结输入会让意外原地排序或写回图标直接失败，也能保护菜单管理的覆盖值。
  const routes = Object.freeze(warehouse.routes.map(route => Object.freeze({
    ...route,
    icon: 'truck',
    customData: Object.freeze({ origin: route.key })
  })))
  const sections = routeMenuSections(routes)
  const result = sections.flatMap(section => section.routes)

  assert.deepEqual(new Set(result), new Set(routes))
  for (const route of result) {
    const original = routes.find(entry => entry.key === route.key)
    assert.equal(route, original)
    assert.equal(route.icon, 'truck')
    assert.equal(route.customData, original.customData)
    assert.equal(route.permission, original.permission)
    assert.equal(route.path, original.path)
  }
})

test('未分类的新入口保留在末尾默认分段，既有分段与段内入口保持稳定顺序', () => {
  const firstFallback = Object.freeze({ key: 'futureWarehouseTool', label: '未来功能', icon: 'settings' })
  const secondFallback = Object.freeze({ key: 'futureWarehouseReport', label: '未来报表', icon: 'chart' })
  const byKey = key => warehouse.routes.find(route => route.key === key)
  const routes = Object.freeze([
    firstFallback,
    byKey('stocktakes'),
    byKey('productionReturns'),
    secondFallback,
    byKey('otherInbounds'),
    byKey('productionDispatches'),
    byKey('transfers')
  ])
  const sections = routeMenuSections(routes)

  assert.deepEqual(sections.map(section => [section.key, section.label, section.routes.map(route => route.key)]), [
    ['inbound', '入库类', ['otherInbounds']],
    ['production', '生产类', ['productionReturns', 'productionDispatches']],
    ['tools', '功能类', ['stocktakes', 'transfers']],
    ['default', null, ['futureWarehouseTool', 'futureWarehouseReport']]
  ])
  assert.equal(sections.at(-1).routes[0], firstFallback)
  assert.equal(sections.at(-1).routes[1], secondFallback)
})
