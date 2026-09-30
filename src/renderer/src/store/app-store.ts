import {
  computed,
  nextTick,
  ref,
  watch
} from 'vue'
import { defineStore } from 'pinia'
import { menuIconComponents } from '../utils/menu-icon-components'
import { resolveMenuIcon } from '../../../shared/menu-icons'
import type {
  ConnectionCandidate,
  DiscoveryResult,
  HostStatus,
  ServerProfile
} from '../../../shared/desktop-api'
import {
  canVisitRoute,
  closeRoute,
  nextExpandedGroup,
  openRoute,
  permittedOpenedRoutes,
  resolveWorkspaceRoute,
  routeByKey,
  workspaceRoutes,
  visibleRouteGroups
} from '../router/workspace-routes'
import { workspaceRouter } from '../router/browser-router'
import type {
  WorkspaceRouteGroupKey,
  WorkspaceRouteKey
} from '../router/workspace-routes'
import { scrollActiveTabIntoView } from '../utils/workspace-tab-strip'

import { createAppState } from './state'
import { createDataLoader } from './data-loader'
import { createConnectionActions } from './connection-actions'
import { createCatalogActions } from './modules/catalog-actions'
import { createPurchaseActions } from './modules/purchase-actions'
import { createWarehouseActions } from './modules/warehouse-actions'
import { createReportActions } from './modules/report-actions'
import { createFinanceActions } from './modules/finance-actions'
import { createLedgerActions } from './modules/ledger-actions'
import { createPeriodClosingActions } from './modules/period-closing-actions'
import { createOpeningBalanceActions } from './modules/opening-balance-actions'
import { createJournalActions } from './modules/journal-actions'
import { createBusinessJournalActions } from './modules/business-journal-actions'
import { createProfitTransferActions } from './modules/profit-transfer-actions'
import { createLedgerReportActions } from './modules/ledger-report-actions'
import { createValuationActions } from './modules/valuation-actions'
import { createTableActions } from './modules/table-actions'
import { createSalesActions } from './modules/sales-actions'
import { createProductionActions } from './modules/production-actions'
import { createMenuActions } from './modules/menu-actions'
import { createAccessActions } from './modules/access-actions'
import {
  displayError,
  localTime,
  movementSource,
  financialSource,
  paymentActionLabel
} from '../utils/formatters'

import type { Screen } from './types'
import { storeBindings } from './store-bindings'

// Pinia 为每个渲染窗口创建独立会话，所有业务页面共用同一份响应式状态。
function createAppStore() {
  const state = createAppState()
  const {
    screen,
    openedRouteKeys,
    expandedGroupKey,
    version,
    notice,
    error,
    busy,
    user,
    permissions,
    hostForm,
    connectionLost
  } = state
  let healthTimer: ReturnType<typeof setInterval> | null = null
  let removeRouteHook: (() => void) | null = null

  // 当前页面以 Vue Router 为唯一来源，避免标签高亮与地址栏各保存一份状态。
  const activeTab = computed<WorkspaceRouteKey>(() =>
    workspaceRoutes.find(
      (route) => route.path === workspaceRouter.currentRoute.value.path
    )?.key ?? 'home'
  )

  const can = (permission: string): boolean =>
    user.value?.permissions.includes(permission) ?? false
  // 分类和权限来自同一张路由表，避免侧栏与地址访问使用两套规则。
  const visibleGroups = computed(() =>
    visibleRouteGroups(user.value?.permissions ?? []).map((group) => ({
      ...group,
      icon: menuIconComponents[resolveMenuIcon(state.menuIcons.value, `group:${group.key}`, group.icon)],
      routes: group.routes.map((route) => ({
        ...route,
        icon: menuIconComponents[resolveMenuIcon(state.menuIcons.value, `route:${route.key}`, route.icon)]
      }))
    }))
  )
  const visibleTabs = computed(() =>
    visibleGroups.value.flatMap((group) => group.routes)
  )
  const openedTabs = computed(() => openedRouteKeys.value.map(routeByKey))
  function revealCurrentTab(): void {
    // 路由先更新页面和标签，再在 Vue 完成 DOM 更新后调整横向滚动位置。
    void nextTick(() => {
      const strip = document.querySelector<HTMLElement>('.workspace-tabs')
      if (strip) scrollActiveTabIntoView(strip)
    })
  }
  watch(screen, (current) => {
    // 再次登录时从全部收起开始，不保留上个账号的侧栏状态。
    if (current !== 'app') {
      state.menuIcons.value = []
      expandedGroupKey.value = null
      // 页面栏只属于当前登录会话，退出后不向下一个账号展示访问记录。
      openedRouteKeys.value = []
    }
  })
  watch(visibleGroups, (groups) => {
    // 当前账号失去某分类的查看权限后，清除其展开状态。
    if (
      expandedGroupKey.value &&
      !groups.some((group) => group.key === expandedGroupKey.value)
    )
      expandedGroupKey.value = null
  })
  // 用户切换或权限被撤销时，页面内容必须和入口使用同一条权限规则。
  const activeRouteAllowed = computed(
    () =>
      user.value !== null &&
      canVisitRoute(routeByKey(activeTab.value), user.value.permissions)
  )

  function toggleRouteGroup(key: WorkspaceRouteGroupKey): void {
    expandedGroupKey.value = nextExpandedGroup(expandedGroupKey.value, key)
  }

  function syncWorkspaceRoute(): void {
    if (screen.value !== 'app' || !user.value) return
    const route = resolveWorkspaceRoute(
      workspaceRouter.currentRoute.value.path,
      user.value.permissions
    )
    openedRouteKeys.value = openRoute(
      permittedOpenedRoutes(openedRouteKeys.value, user.value.permissions),
      route.key
    )
    if (workspaceRouter.currentRoute.value.path !== route.path) {
      // 权限被撤销后替换当前历史项，避免后退再次进入无权页面。
      void workspaceRouter.replace(route.path)
      return
    }
    revealCurrentTab()
  }

  function navigateToRoute(key: WorkspaceRouteKey): void {
    if (!user.value) return
    const route = routeByKey(key)
    if (!canVisitRoute(route, user.value.permissions)) return
    // 导航成功后由路由钩子登记页面标签，避免被守卫拒绝的地址留下入口。
    void workspaceRouter.push(route.path).catch((cause: unknown) => {
      error.value = displayError(cause)
    })
  }

  function closeOpenedRoute(key: WorkspaceRouteKey): void {
    const result = closeRoute(openedRouteKeys.value, key, activeTab.value)
    openedRouteKeys.value = result.opened
    if (result.active !== activeTab.value) navigateToRoute(result.active)
  }
  watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => {
    // 跨账号不保留客户联系人、商务价格或编辑草稿；同账号切换页面仍保留草稿。
    state.customerForm.value = { name: '' }
    state.customerEdit.value = null
    state.customerHistory.value = []
    state.customers.value = []
    state.salesOrders.value = []
    state.salesReturns.value = []
    state.salesForm.value = { customer_id: 0, reference: '', lines: [{ material_id: 0, quantity: '1', unit_price: '0' }] }
    state.paymentRecords.value = []
    state.financeAccounts.value = []
    state.journals.value = []
    state.openingBalances.value = []
    state.periodClosingHistory.value = []
    state.customerHistory.value = []
    state.inventoryValuation.value = null
    state.receivablesPayables.value = null
    state.productionCostReport.value = null
    state.dataRevision.value += 1
  }, { flush: 'sync' })
  const { refreshData, loadPermissions } = createDataLoader(state, can, syncWorkspaceRoute)
  const connectionActions = createConnectionActions(state, refreshData)
  const { checkConnection, stopScan, monitorConnection } = connectionActions

  async function perform(
    action: () => Promise<unknown>,
    success: string
  ): Promise<void> {
    if (busy.value) return
    if (connectionLost.value) {
      error.value = '服务端连接已中断，恢复连接后才能保存更改。'
      return
    }
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      await action()
      await refreshData()
      notice.value = success
    } catch (cause) {
      error.value = displayError(cause)
    } finally {
      busy.value = false
    }
  }

  const catalogActions = createCatalogActions(state, perform)
  const purchaseActions = createPurchaseActions(state, perform)
  const warehouseActions = createWarehouseActions(state, perform)
  const reportActions = createReportActions(state, perform)
  const financeActions = createFinanceActions(state, perform)
  const ledgerActions = createLedgerActions(state, perform)
  const periodClosingActions = createPeriodClosingActions(state, perform)
  const openingBalanceActions = createOpeningBalanceActions(state, perform)
  const journalActions = createJournalActions(state, perform)
  const businessJournalActions = createBusinessJournalActions(state, perform)
  const profitTransferActions = createProfitTransferActions(state, perform)
  const ledgerReportActions = createLedgerReportActions(state)
  const valuationActions = createValuationActions(state, perform)

  const tableActions = createTableActions(state)
  const salesActions = createSalesActions(state, perform)

  const productionActions = createProductionActions(
    state,
    perform,
    navigateToRoute
  )

  const menuActions = createMenuActions(state)
  const accessActions = createAccessActions(state, perform)

  let initialized = false
  async function initialize(): Promise<void> {
    // 启动资源仍由根组件控制，避免 Pinia store 在首次读取时自行注册窗口监听。
    if (initialized) return
    initialized = true
    removeRouteHook = workspaceRouter.afterEach((_to, _from, failure) => {
      if (!failure) syncWorkspaceRoute()
    })
    window.addEventListener('resize', revealCurrentTab)
    if (window.nexora)
      version.value = await window.nexora.getVersion().catch(() => '')
    if (window.nexora)
      hostForm.value.dataDir = await window.nexora
        .defaultDataDir()
        .catch(() => '')
    if (!initialized) return
    await checkConnection()
    // 窗口可能在异步连接检查期间关闭，关闭后不再启动轮询。
    if (initialized)
      healthTimer = setInterval(() => {
        void monitorConnection()
      }, 5000)
  }

  function dispose(): void {
    initialized = false
    void stopScan()
    if (healthTimer) clearInterval(healthTimer)
    healthTimer = null
    removeRouteHook?.()
    removeRouteHook = null
    window.removeEventListener('resize', revealCurrentTab)
  }
  return {
    ...state,
    activeTab,
    ...connectionActions,
    ...catalogActions,
    ...purchaseActions,
    ...warehouseActions,
    ...reportActions,
    ...financeActions,
    ...ledgerActions,
    ...periodClosingActions,
    ...journalActions,
    ...businessJournalActions,
    ...profitTransferActions,
    ...openingBalanceActions,
    ...ledgerReportActions,
    ...valuationActions,
    ...salesActions,
    ...tableActions,
    ...productionActions,
    ...accessActions,
    ...menuActions,
    can,
    visibleGroups,
    visibleTabs,
    openedTabs,
    revealCurrentTab,
    activeRouteAllowed,
    toggleRouteGroup,
    syncWorkspaceRoute,
    navigateToRoute,
    closeOpenedRoute,
    displayError,
    localTime,
    movementSource,
    financialSource,
    refreshData,
    loadPermissions,
    perform,
    paymentActionLabel,
    initialize,
    dispose
  }
}

export const usePiniaAppStore = defineStore('app', createAppStore)

// 现有页面解构 ref 的写法由此统一兼容；状态与计算值来自 Pinia，操作仍取自同一个 store。
export function useAppStore() {
  return storeBindings(usePiniaAppStore())
}

export type AppStore = ReturnType<typeof useAppStore>
