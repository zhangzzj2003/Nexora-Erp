import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { createMemoryHistory } from 'vue-router'
import { createWorkspaceRouter, installWorkspaceAccessGuard } from '../src/renderer/src/router/index.ts'
import {
  canVisitRoute, nextExpandedGroup, resolveWorkspaceRoute, routeByKey, routeGroupByKey, visibleRouteGroups, workspaceRoutes
} from '../src/renderer/src/router/workspace-routes.ts'

test('每个工作台页面只有一个路由，且都对应实际页面', () => {
  const shell = readFileSync(new URL('../src/renderer/src/views/WorkspaceShell.vue', import.meta.url), 'utf8')
  const router = createWorkspaceRouter(createMemoryHistory())
  const registered = router.getRoutes().filter((route) => route.name)

  // 路由记录由同一张业务表生成，组件由 Vue Router 装载，避免侧栏出现空白页面。
  assert.equal(workspaceRoutes.length, 56)
  assert.deepEqual(new Set(registered.map(route => route.name)), new Set(workspaceRoutes.map(route => route.key)))
  assert.ok(registered.every((route) => route.components?.default))
  assert.match(shell, /<RouterView :key="`\$\{activeTab\}-\$\{workspacePageVersion\}`" \/>/)
  assert.equal(new Set(workspaceRoutes.map(route => route.path)).size, workspaceRoutes.length)
  assert.ok(workspaceRoutes.every(route => route.path.startsWith('/workspace/')))
})

test('顶部目录与侧栏从同一分类定义定位所有业务页', () => {
  assert.equal(routeGroupByKey('goodsReceipts').label, '采购管理')
  assert.equal(routeGroupByKey('suppliers').label, '基础资料')
  assert.equal(routeGroupByKey('home').label, '工作台')
  for (const route of workspaceRoutes) {
    assert.ok(routeGroupByKey(route.key).routes.some((entry) => entry === route))
  }
})

test('侧栏按查看权限分类，隐藏空分类及未授权页面', () => {
  const groups = visibleRouteGroups(['sales.view', 'production_cost.view'])
  assert.deepEqual(groups.map(group => group.label), ['工作台', '基础资料', '销售管理', '生产管理', '系统管理'])
  assert.deepEqual(groups.flatMap(group => group.routes.map(route => route.key)), [
    'home', 'customers', 'sales', 'shipments', 'salesReturns', 'productionCosts', 'settings'
  ])
  assert.equal(canVisitRoute(routeByKey('home'), []), true)
  assert.equal(canVisitRoute(routeByKey('stock'), ['sales.view']), false)
  assert.equal(canVisitRoute(routeByKey('inventoryValuation'), ['finance.view']), false)
  assert.equal(canVisitRoute(routeByKey('inventoryValuation'), ['inventory_valuation.view']), true)
  assert.equal(canVisitRoute(routeByKey('bankReconciliation'), ['finance.view']), false)
  assert.equal(canVisitRoute(routeByKey('bankReconciliation'), ['bank_reconciliation.view']), true)
  assert.equal(canVisitRoute(routeByKey('bankBalance'), ['finance.view']), false)
  assert.equal(canVisitRoute(routeByKey('bankBalance'), ['bank_reconciliation.view']), true)
  assert.equal(canVisitRoute(routeByKey('settings'), []), true)
})

test('首页是登录账号均可见的固定入口与默认页面', () => {
  const sidebar = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceSidebar.vue', import.meta.url), 'utf8')
  assert.equal(routeByKey('home').path, '/workspace/home')
  assert.match(sidebar, /v-if="group\.key === 'home'"[\s\S]*?@click="navigateToRoute\('home'\)"/)
  const store = readFileSync(new URL('../src/renderer/src/store/app-store.ts', import.meta.url), 'utf8')
  assert.match(store, /const activeTab = computed<WorkspaceRouteKey>/)
})

test('直接访问未授权或未知地址时回退到可访问页面', () => {
  const permissions = ['sales.view']
  assert.equal(resolveWorkspaceRoute('/workspace/shipments', permissions).key, 'shipments')
  assert.equal(resolveWorkspaceRoute('/workspace/users', permissions).key, 'home')
  assert.equal(resolveWorkspaceRoute('/workspace/roles', permissions).key, 'home')
  assert.equal(resolveWorkspaceRoute('/workspace/permission-catalog', permissions).key, 'home')
  assert.equal(resolveWorkspaceRoute('/workspace/missing', permissions).key, 'home')
  assert.equal(resolveWorkspaceRoute('/workspace/stock', []).key, 'home')
})

test('用户、职务授权与权限目录分别有入口，且都要求用户管理权限', () => {
  const routes = visibleRouteGroups(['users.manage']).flatMap(group => group.routes)
  assert.deepEqual(routes.filter(route => ['users', 'roles', 'permissionCatalog'].includes(route.key)).map(route => route.label),
    ['用户管理', '权限管理', '权限目录'])
  assert.equal(resolveWorkspaceRoute('/workspace/roles', ['users.manage']).key, 'roles')
  assert.equal(resolveWorkspaceRoute('/workspace/permission-catalog', ['users.manage']).key, 'permissionCatalog')

  const userPage = readFileSync(new URL('../src/renderer/src/views/workspace/system/UserManagementView.vue', import.meta.url), 'utf8')
  const rolePage = readFileSync(new URL('../src/renderer/src/views/workspace/system/RolePermissionsView.vue', import.meta.url), 'utf8')
  const catalogPage = readFileSync(new URL('../src/renderer/src/views/workspace/system/PermissionCatalogView.vue', import.meta.url), 'utf8')
  // 用户、职务和名称维护分属三页，避免权限目录把职务表格重新撑成长页。
  assert.match(userPage ?? '', /<NModal\b/)
  assert.match(userPage ?? '', /@submit\.prevent="submitEditor"/)
  assert.match(userPage ?? '', /editingId.value === null \? createUser\(\) : updateUser/)
  // 用户列表已统一为表格，职务授权和权限名称维护仍保留独立入口。
  assert.match(userPage ?? '', /<WorkspaceTable/)
  assert.match(rolePage ?? '', /<WorkspaceTable/)
  assert.match(rolePage ?? '', /@submit\.prevent="submitNewRole"/)
  assert.doesNotMatch(rolePage ?? '', /@submit\.prevent="createUser"/)
  assert.doesNotMatch(rolePage ?? '', /savePermissionLabel/)
  assert.match(catalogPage ?? '', /savePermissionLabel/)
  // 新建角色不能在管理员勾选前就带有默认业务权限。
  const state = readFileSync(new URL('../src/renderer/src/store/state.ts', import.meta.url), 'utf8')
  assert.match(state, /const newRole = ref\(\{ label: '', permissions: \[\] as string\[\] \}\)/)
})

test('权限被撤销后，当前地址也必须重新核对', () => {
  const route = routeByKey('finance')
  assert.equal(canVisitRoute(route, ['finance.view']), true)
  assert.equal(canVisitRoute(route, []), false)
  assert.equal(resolveWorkspaceRoute('/workspace/finance', []).key, 'home')
})

test('Vue Router 保留登录前深链接，登录后拦截无权限页面和未知地址', async () => {
  // 测试替换真实页面组件，使内存路由验证权限与地址时无需加载 Vue 单文件组件。
  const component = { render: () => null }
  const overrides = Object.fromEntries(workspaceRoutes.map((route) => [route.key, component]))
  const router = createWorkspaceRouter(createMemoryHistory(), overrides)
  let permissions = null
  installWorkspaceAccessGuard(router, () => permissions)

  await router.push('/workspace/stock')
  await router.isReady()
  assert.equal(router.currentRoute.value.path, '/workspace/stock')

  permissions = []
  await router.push('/workspace/roles')
  assert.equal(router.currentRoute.value.path, '/workspace/home')
  await router.push('/workspace/permission-catalog')
  assert.equal(router.currentRoute.value.path, '/workspace/home')
  await router.push('/workspace/missing')
  assert.equal(router.currentRoute.value.path, '/workspace/home')

  permissions = ['users.manage']
  await router.push('/workspace/roles')
  assert.equal(router.currentRoute.value.path, '/workspace/roles')
  await router.push('/workspace/permission-catalog')
  assert.equal(router.currentRoute.value.path, '/workspace/permission-catalog')
})

test('工作台地址切换进入 Vue Router 历史，后退能恢复上一页面', async () => {
  const component = { render: () => null }
  const overrides = Object.fromEntries(workspaceRoutes.map((route) => [route.key, component]))
  const router = createWorkspaceRouter(createMemoryHistory(), overrides)
  installWorkspaceAccessGuard(router, () => ['inventory.view'])
  await router.push('/workspace/home')
  await router.isReady()
  await router.push('/workspace/stock')

  const restored = new Promise((resolve) => {
    // 历史移动没有返回 Promise，以路由完成钩子核对最终页面。
    const remove = router.afterEach((to) => {
      if (to.path === '/workspace/home') {
        remove()
        resolve(to.path)
      }
    })
  })
  router.back()
  assert.equal(await restored, '/workspace/home')
  assert.equal(router.currentRoute.value.path, '/workspace/home')
})

test('分类默认收起，同一时间只能展开一个分类', () => {
  let expanded = null
  expanded = nextExpandedGroup(expanded, 'warehouse')
  assert.equal(expanded, 'warehouse')
  expanded = nextExpandedGroup(expanded, 'finance')
  assert.equal(expanded, 'finance')
  expanded = nextExpandedGroup(expanded, 'finance')
  assert.equal(expanded, null)
})

test('收起的页面入口不可聚焦，动效遵循减少动态效果设置', () => {
  const sidebar = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceSidebar.vue', import.meta.url), 'utf8')
  const style = readFileSync(new URL('../src/renderer/src/style.css', import.meta.url), 'utf8')

  // 内容保留在 DOM 中完成收起动画时，必须同步关闭交互与辅助技术访问。
  assert.match(sidebar, /class="nav-panel"[\s\S]*?:aria-hidden="expandedGroupKey !== group\.key"[\s\S]*?:inert="expandedGroupKey !== group\.key \? true : undefined"/)
  assert.match(style, /\.nav-panel \{[^}]*grid-template-rows: 0fr;[^}]*transition: grid-template-rows/)
  assert.match(style, /\.nav-panel\.expanded \{ grid-template-rows: 1fr;/)
  assert.match(style, /@media \(prefers-reduced-motion: reduce\) \{[^}]*\}[^}]*\.nav-panel[^}]*transition: none;/)
})


test('基础资料包含独立单位管理，沿用查看权限与旧物料地址', () => {
  const group = visibleRouteGroups(['inventory.view']).find(group => group.key === 'catalog')
  assert.deepEqual(group.routes.map(route => route.label), ['物料管理', '供应商管理', '物料分类与规格', '单位管理', '仓库管理'])
  assert.equal(routeByKey('catalog').path, '/workspace/catalog')
  for (const key of ['catalog', 'suppliers', 'materialCategoryManagement', 'materialUnits', 'warehouses']) {
    assert.equal(canVisitRoute(routeByKey(key), []), false)
    assert.equal(resolveWorkspaceRoute(routeByKey(key).path, ['inventory.view']).key, key)
  }
})

test('采购申请入口只向有申请查看权限的账号开放', () => {
  assert.equal(routeByKey('purchaseRequests').path, '/workspace/purchase-requests')
  assert.equal(canVisitRoute(routeByKey('purchaseRequests'), ['inventory.view']), false)
  assert.equal(canVisitRoute(routeByKey('purchaseRequests'), ['purchase_request.view']), true)
  assert.equal(resolveWorkspaceRoute('/workspace/purchase-requests', []).key, 'home')
})

test('采购收货与入库分别有入口和独立权限', () => {
  assert.equal(routeByKey('goodsReceipts').path, '/workspace/purchase-goods-receipts')
  assert.equal(canVisitRoute(routeByKey('goodsReceipts'), ['inventory.view']), false)
  assert.equal(canVisitRoute(routeByKey('goodsReceipts'), ['purchase_receiving.view']), true)
  assert.equal(routeByKey('receipts').path, '/workspace/receipts')
})

test('其他入库在仓库管理下使用独立查看权限', () => {
  assert.equal(routeByKey('otherInbounds').path, '/workspace/warehouse-inbounds')
  assert.equal(routeByKey('warehouseOutbounds').path, '/workspace/warehouse-outbounds')
  assert.equal(routeByKey('inventoryLedger').path, '/workspace/inventory-ledger')
  assert.equal(routeByKey('physicalLots').path, '/workspace/physical-lots')
  assert.equal(canVisitRoute(routeByKey('physicalLots'), ['inventory.view']), true)
  assert.equal(canVisitRoute(routeByKey('physicalLots'), ['inventory_report.view']), false)
  assert.equal(routeByKey('stockAdjustments').path, '/workspace/stock-adjustments')
  assert.equal(routeByKey('purchaseReports').path, '/workspace/purchase-reports')
  assert.equal(routeByKey('inventoryReports').path, '/workspace/inventory-reports')
  assert.equal(canVisitRoute(routeByKey('warehouseOutbounds'), ['other_outbound.view']), true)
  assert.equal(canVisitRoute(routeByKey('otherInbounds'), ['inventory.view']), false)
  assert.equal(canVisitRoute(routeByKey('otherInbounds'), ['other_inbound.view']), true)
})

// 分类迁移必须同时影响侧栏和顶部目录，同时兼容旧标签地址与生产授权。
test('生产 BOM 属于基础资料，旧地址与生产权限保持兼容', async () => {
  assert.equal(routeGroupByKey('boms').key, 'catalog')
  assert.equal(routeByKey('boms').path, '/workspace/boms')
  assert.equal(routeByKey('boms').permission, 'production.view')
  const groups = visibleRouteGroups(['production.view'])
  assert.ok(groups.find(group => group.key === 'catalog').routes.some(route => route.key === 'boms'))
  assert.ok(!groups.find(group => group.key === 'production').routes.some(route => route.key === 'boms'))
  assert.equal(resolveWorkspaceRoute('/workspace/boms', ['inventory.view']).key, 'home')
  assert.equal(resolveWorkspaceRoute('/workspace/boms', ['production.view']).key, 'boms')
  const router = createWorkspaceRouter(createMemoryHistory(), Object.fromEntries(workspaceRoutes.map(route => [route.key, { render: () => null }])))
  installWorkspaceAccessGuard(router, () => ['production.view'])
  await router.push('/workspace/boms')
  assert.equal(router.currentRoute.value.name, 'boms')
  assert.equal(routeGroupByKey('workOrders').key, 'production')
})
