import type { DocumentNumberingInput } from '../../../shared/document-numbering'
import { createDocumentApprovalCaseActions } from './modules/document-approval-case-actions'
import { createDocumentApprovalActions } from './modules/document-approval-actions'
import {createInventoryWarningActions} from './modules/inventory-warning-actions'
import {createInventoryWarningAlerts} from './modules/inventory-warning-alerts'
import {createPhysicalLotActions} from './modules/physical-lot-actions'
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
import { createWorkspaceRefresh } from './workspace-refresh'
import { createConnectionActions } from './connection-actions'
import { createCatalogActions } from './modules/catalog-actions'
import { createPurchaseActions } from './modules/purchase-actions'
import { createWarehouseActions } from './modules/warehouse-actions'
import { createReportActions } from './modules/report-actions'
import { createFinanceActions } from './modules/finance-actions'
import { createBankReconciliationActions } from './modules/bank-reconciliation-actions'
import { createBankBalanceActions } from './modules/bank-balance-actions'
import { createLedgerActions } from './modules/ledger-actions'
import { createPeriodClosingActions } from './modules/period-closing-actions'
import { createOpeningBalanceActions } from './modules/opening-balance-actions'
import { createJournalActions } from './modules/journal-actions'
import { createBusinessJournalActions } from './modules/business-journal-actions'
import { createProfitTransferActions } from './modules/profit-transfer-actions'
import { createStatementActions } from './modules/statement-actions'
import { createAuxiliaryActions } from './modules/auxiliary-actions'
import { createSubledgerActions } from './modules/subledger-actions'
import { createMrpActions } from './modules/mrp-actions'
import { createCrmActions } from './modules/crm-actions'
import { createQualityActions } from './modules/quality-actions'
import { createAfterSalesActions } from './modules/after-sales-actions'
import { createEquipmentActions } from './modules/equipment-actions'
import { createDashboardActions } from './modules/dashboard-actions'
import { createLedgerReportActions } from './modules/ledger-report-actions'
import { createValuationActions } from './modules/valuation-actions'
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

  const can = (permission: string): boolean => {
    // 未配置时保留原有查看与账号管理权限；写入仍由后端统一拦截。
    if (state.documentNumbering.value && !state.documentNumbering.value.configured
      && !permission.endsWith('.view') && !['users.manage'].includes(permission)) return false
    return user.value?.permissions.includes(permission) ?? false
  }
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
      if (!user.value) state.documentNumbering.value = null
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
  const { refreshData, loadPermissions } = createDataLoader(state, can, syncWorkspaceRoute)
  const workspacePageVersion = ref(0)
  const refreshingWorkspace = ref(false)
  const workspaceRefresh = createWorkspaceRefresh({
    context: () => screen.value === 'app' && user.value && activeRouteAllowed.value ? {
      session: `${state.server.value?.id ?? ''}:${state.server.value?.fingerprint ?? ''}:${user.value.id}`,
      path: workspaceRouter.currentRoute.value.fullPath
    } : undefined,
    blocked: () => busy.value || connectionLost.value || !window.nexora,
    setLoading: (loading) => {
      // 刷新期间沿用全局忙碌状态，业务按钮不会和同一批读取并发提交。
      refreshingWorkspace.value = loading
      busy.value = loading
    },
    reloadData: async () => {
      error.value = ''
      notice.value = ''
      await refreshData()
    },
    remountPage: async () => {
      // 共享列表已重新读取；重建页面使独立分页和首页统计也重新加载。
      workspacePageVersion.value += 1
      await nextTick()
    },
    reportError: (cause) => { error.value = displayError(cause) }
  })
  const refreshWorkspacePage = workspaceRefresh.refresh
  async function loadDocumentNumbering(): Promise<void> {
    if (!window.nexora || !user.value) return
    const serverId = state.server.value?.id, userId = user.value.id
    const confirmed = await window.nexora.callApi('documentNumbering', undefined)
    // 切换实例、退出或保存后的旧轮询响应不能覆盖当前服务端规则。
    if (state.server.value?.id !== serverId || user.value?.id !== userId
      || (state.documentNumbering.value?.version ?? -1) > confirmed.version
      || state.documentNumbering.value?.locked && !confirmed.locked) return
    state.documentNumbering.value = confirmed
    // 其他管理员已配置或超时请求已提交时，按已确认的服务端状态解除首次引导。
    if (state.documentNumbering.value.configured && screen.value === 'numbering') {
      screen.value = 'app'
      await refreshData()
    }
  }
  // 设置成功后才进入工作台；失败保留组件中的风格与时区草稿。
  async function saveDocumentNumbering(input: DocumentNumberingInput): Promise<boolean> {
    if (!window.nexora || busy.value || connectionLost.value) return false
    busy.value = true
    error.value = ''
    try {
      state.documentNumbering.value = await window.nexora.callApi('saveDocumentNumbering', input)
      screen.value = 'app'
      await refreshData()
      notice.value = '单据编号规则已保存。'
      return true
    } catch (cause) {
      error.value = displayError(cause)
      // 并发设置或请求超时可能已有提交；重读服务器状态，不能误用旧配置版本。
      try { await loadDocumentNumbering() } catch { /* 断网时保留草稿供重试。 */ }
      return false
    } finally { busy.value = false }
  }
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
  const bankReconciliationActions = createBankReconciliationActions(state, perform)
  const bankBalanceActions = createBankBalanceActions(state, perform)
  const ledgerActions = createLedgerActions(state, perform)
  const periodClosingActions = createPeriodClosingActions(state, perform)
  const openingBalanceActions = createOpeningBalanceActions(state, perform)
  const journalActions = createJournalActions(state, perform)
  const businessJournalActions = createBusinessJournalActions(state, perform)
  const profitTransferActions = createProfitTransferActions(state, perform)
  const statementActions = createStatementActions(state, perform)
  const auxiliaryActions = createAuxiliaryActions(state, perform)
  const subledgerActions = createSubledgerActions(state, perform)
  const mrpActions = createMrpActions(state, perform)
  const crmActions = createCrmActions(state, perform)
  const qualityActions = createQualityActions(state, perform)
  const afterSalesActions = createAfterSalesActions(state, perform)
  const inventoryWarningActions = createInventoryWarningActions(state, perform)
  const inventoryWarningAlerts = createInventoryWarningAlerts(state)
  const physicalLotActions = createPhysicalLotActions(state)
  const documentApprovalActions = { ...createDocumentApprovalActions(state),
    ...createDocumentApprovalCaseActions(state, refreshData, async target => {
      // CRM、售后、处置和计划有独立列表和详情，审批变化后同步业务版本与可执行动作。
      if (target.document_type === 'CrmQuote') await crmActions.refreshCrmApproval(target.document_id)
      if (target.document_type === 'AfterSalesCase') await afterSalesActions.refreshAfterSalesApproval(target.document_id)
      if (target.document_type === 'MrpPlan') await mrpActions.refreshMrpApproval(target.document_id)
      if (target.document_type === 'QualityDisposition') await qualityActions.refreshQualityApproval(target.document_id)
    }) }
  const equipmentActions = createEquipmentActions(state, perform)
  const dashboardActions = createDashboardActions(state)
  const ledgerReportActions = createLedgerReportActions(state)
  const valuationActions = createValuationActions(state, perform)

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
    if (initialized) inventoryWarningAlerts.start()
    // 窗口可能在异步连接检查期间关闭，关闭后不再启动轮询。
    if (initialized)
      healthTimer = setInterval(() => {
        void monitorConnection()
      }, 5000)
  }

  function dispose(): void {
    initialized = false
    workspaceRefresh.dispose()
    inventoryWarningAlerts.stop()
    void stopScan()
    if (healthTimer) clearInterval(healthTimer)
    healthTimer = null
    removeRouteHook?.()
    removeRouteHook = null
    window.removeEventListener('resize', revealCurrentTab)
  }
  return {
    ...documentApprovalActions,
    ...state,
    activeTab,
    workspacePageVersion,
    refreshingWorkspace,
    refreshWorkspacePage,
    ...connectionActions,
    ...catalogActions,
    ...purchaseActions,
    ...warehouseActions,
    ...reportActions,
    ...financeActions,
    ...bankReconciliationActions,
    ...bankBalanceActions,
    ...ledgerActions,
    ...periodClosingActions,
    ...journalActions,
    ...businessJournalActions,
    ...profitTransferActions,
    ...statementActions,
    ...auxiliaryActions,
    ...subledgerActions,
    ...mrpActions,
    ...crmActions,
    ...qualityActions,
    ...afterSalesActions,
    ...equipmentActions,
    ...inventoryWarningActions,
    ...physicalLotActions,
    ...dashboardActions,
    ...openingBalanceActions,
    ...ledgerReportActions,
    ...valuationActions,
    ...salesActions,
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
    loadDocumentNumbering,
    saveDocumentNumbering,
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
