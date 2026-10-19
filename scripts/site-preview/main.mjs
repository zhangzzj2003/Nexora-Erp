import { productPreviewResponse, productPreviewOperations, productPreviewBoms } from './product-fixtures.mjs'
import { productionPlanPreviewResponse, productionPlanPreviewOperations, productionPlanPreviewPermissions } from './production-plan-fixtures.mjs'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import App from '../../src/renderer/src/App.vue'
import { usePiniaAppStore } from '../../src/renderer/src/store/app-store'
import { useThemeStore } from '../../src/renderer/src/store/theme-store'
import { workspaceRouter } from '../../src/renderer/src/router/browser-router'
import { installWorkspaceAccessGuard } from '../../src/renderer/src/router'
import { workspaceRoutes, workspaceRouteGroups } from '../../src/renderer/src/router/workspace-routes'
import { previewRoutes, previewResponse, supplyPreviewInbounds, materials, warehouses, journals, productionCostReport, productionCostSettlements, receipts, receivablesPayables } from './fixtures.mjs'
import { dialogPreviewResponse, dialogPreviewPermissions, dialogPreviewInbounds, dialogPreviewWorkOrders, dialogPreviewCompletions, dialogPreviewBoms } from './dialog-fixtures.mjs'
import '../../src/renderer/src/style.css'
import '../../src/renderer/src/light-theme.css'
import '../../src/renderer/src/dark-theme.css'
import '../../src/renderer/src/theme-transitions.css'

// 独立浏览器会话模拟桌面桥接，只提供示例读取和窗口主题空操作，不包含网络访问。
const previewQuery = new URLSearchParams(location.search)
const productQa = previewQuery.get('qa') === 'products'
const productionPlanQa = previewQuery.get('qa') === 'productionPlans'
// 登录取景沿用真实 AuthView，可单独切换管理员初始化阶段，不启动真实服务连接。
const authQa = previewQuery.get('qa') === 'auth'
// 目录压力样例只在显式参数下启用，不增加默认预览中的产品或接触正式业务数据。
const productPreviewOptions = {scroll:productQa && previewQuery.get('directory') === 'scroll'}
const dialogQa = previewQuery.get('qa') === 'dialogs' || productQa
const previewReadCounts = new Map()
// 显式 browser 参数模拟没有融合标题栏的环境，默认桌面预览保持原样。
window.nexora = { platform: previewQuery.get('platform') === 'browser' ? 'linux' : 'darwin', callApi: async (operation, payload) => {
  if (productionPlanQa && (productionPlanPreviewOperations.includes(operation) || operation === 'documentApproval' && payload?.document_type === 'ProductionPlan')) return productionPlanPreviewResponse(operation, payload)
  if (productionPlanQa) return dialogPreviewResponse(operation, payload, store)
  if (!dialogQa) return previewResponse(operation, payload)
  if (productQa && productPreviewOperations.includes(operation)) return productPreviewResponse(operation,payload,productPreviewOptions)
  // 延迟和失败仅作用于此隔离示例桥，真实页面与 Pinia 仍走完整读取链路。
  if (['documentApproval', 'materialSupply', 'materialFlowDetail', 'workOrderMaterialFlow', 'materialFlowLots'].includes(operation)) {
    await new Promise(resolve => setTimeout(resolve, Math.min(10000, Math.max(0, Number(previewQuery.get('delay')) || 0))))
    const count = (previewReadCounts.get(operation) ?? 0) + 1
    previewReadCounts.set(operation, count)
    if (previewQuery.get('fail') === operation && count >= Math.max(1, Number(previewQuery.get('failAfter')) || 1)) throw new Error('弹窗验收：模拟读取失败')
  }
  return dialogPreviewResponse(operation, payload, store)
}, setWindowTheme: async () => {} }
const pinia = createPinia()
const app = createApp(App).use(pinia)
const store = usePiniaAppStore(pinia)
const permissions = [...new Set(workspaceRoutes.map(route => route.permission).filter(Boolean)), 'catalog.manage', 'journal.create', 'journal.submit', 'journal.review', 'journal.post', 'business_journal.view', 'other_inbound.create', 'purchase_order.create', 'purchase_request.create', 'mrp.create']
store.$patch({
  user: { id: 3, username: '示例管理员', roles: ['admin'], permissions: productionPlanQa ? ['production.view', 'mrp.view', ...productionPlanPreviewPermissions] : productQa ? [...dialogPreviewPermissions,'catalog.manage','bom.create','bom.activate','bom.retire','bom.cancel'] : dialogQa ? dialogPreviewPermissions : permissions, is_active: true },
  screen: 'app', server: { id: 'site-preview', name: '界面预览 · 示例数据', version: '0.1.0', fingerprint: 'sample-only' },
  version: '0.1.0', roles: [{ code: 'admin', label: '管理员' }], materials: productQa ? productPreviewResponse('materials',undefined,productPreviewOptions) : materials, warehouses,
  materialUnits: productQa ? productPreviewResponse('materialUnits',undefined,productPreviewOptions) : [],
  boms: productQa ? productPreviewBoms : dialogQa ? dialogPreviewBoms : [],
  workOrders: dialogQa ? dialogPreviewWorkOrders : [],
  productionCompletions: dialogQa ? dialogPreviewCompletions : [],
  otherInbounds: dialogQa ? dialogPreviewInbounds : supplyPreviewInbounds,
  suppliers: [{ id: 1, name: '示例电子供应商' }], supplierMaterials: materials.map(item => ({ material_id: item.id, supplier_id: 1 })),
  materialCategories: [
    { code: 'EL', name: '电子类', children: [{ code: 'EL-IC', name: '集成电路 IC' }, { code: 'EL-SR', name: '贴片电阻' }, { code: 'EL-SC', name: '贴片电容' }, { code: 'EL-PC', name: 'PCB / 电路板' }] },
  ],
  ledgerQuery: { warehouse_id: null, material_id: null, source_type: null, from_date: '2026-09-25', to_date: '2026-10-01' },
  productionCostReport, productionCostSettlements, journals, receipts, receivablesPayables, openedRouteKeys: previewRoutes,
})
if (authQa) {
  // 只覆盖本实例的登录状态；业务示例、默认预览和正式服务端完全独立。
  store.$patch({
    user: null,
    screen: previewQuery.get('stage') === 'setup' ? 'setup' : 'login',
    server: { id: 'auth-preview', name: previewQuery.get('serverName') || '我的 Nexora ERP', version: '0.1.0', fingerprint: 'sample-only' },
    username: '', password: '', busy: false, connectionLost: false, connectionNotice: '',
  })
}
// 只替换本预览实例的生命周期，不启动发现、连接、轮询或修改真实应用状态。
store.initialize = async () => {}
store.dispose = () => {}
// 正式台账查询会连带刷新全部业务资料，取景只读取隔离快照，避免无关接口调用。
store.queryLedger = async () => { store.error = ''; store.ledgerResult = previewResponse('inventoryLedger') }
useThemeStore(pinia).setDarkTheme(previewQuery.get('theme') === 'dark')
// 登录前没有账号，保留地址而不触发工作台权限跳转。
installWorkspaceAccessGuard(workspaceRouter, () => store.user?.permissions ?? null)
workspaceRouter.afterEach(to => {
  const route = workspaceRoutes.find(route => route.path === to.path)
  store.expandedGroupKey = workspaceRouteGroups.find(group => group.routes.some(item => item.key === route?.key))?.key ?? null
})
app.use(workspaceRouter)
// 暴露就绪 Promise 而不是阻塞整个模块；生产分包的路由组件仍可读取共享导出。
export const previewReady = (async () => {
  await workspaceRouter.isReady()
  app.mount('#app')
  await nextTick()
  document.documentElement.dataset.preview = 'sample-data'
})()
