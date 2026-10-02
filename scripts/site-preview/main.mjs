import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import App from '../../src/renderer/src/App.vue'
import { usePiniaAppStore } from '../../src/renderer/src/store/app-store'
import { useThemeStore } from '../../src/renderer/src/store/theme-store'
import { workspaceRouter } from '../../src/renderer/src/router/browser-router'
import { installWorkspaceAccessGuard } from '../../src/renderer/src/router'
import { workspaceRoutes, workspaceRouteGroups } from '../../src/renderer/src/router/workspace-routes'
import { previewRoutes, previewResponse, materials, warehouses, journals, productionCostReport, productionCostSettlements, receipts, receivablesPayables } from './fixtures.mjs'
import '../../src/renderer/src/style.css'
import '../../src/renderer/src/light-theme.css'
import '../../src/renderer/src/dark-theme.css'
import '../../src/renderer/src/theme-transitions.css'

// 独立浏览器会话模拟桌面桥接，只提供示例读取和窗口主题空操作，不包含网络访问。
window.nexora = { platform: 'darwin', callApi: async operation => previewResponse(operation), setWindowTheme: async () => {} }
const pinia = createPinia()
const app = createApp(App).use(pinia)
const store = usePiniaAppStore(pinia)
const permissions = [...new Set(workspaceRoutes.map(route => route.permission).filter(Boolean)), 'catalog.manage', 'journal.create', 'journal.submit', 'journal.review', 'journal.post', 'business_journal.view']
store.$patch({
  user: { id: 3, username: '示例管理员', roles: ['admin'], permissions, is_active: true },
  screen: 'app', server: { id: 'site-preview', name: '界面预览 · 示例数据', version: '0.1.0', fingerprint: 'sample-only' },
  version: '0.1.0', roles: [{ code: 'admin', label: '管理员' }], materials, warehouses,
  suppliers: [{ id: 1, name: '示例电子供应商' }], supplierMaterials: materials.map(item => ({ material_id: item.id, supplier_id: 1 })),
  materialCategories: [
    { code: 'EL', name: '电子类', children: [{ code: 'EL-IC', name: '集成电路 IC' }, { code: 'EL-SR', name: '贴片电阻' }, { code: 'EL-SC', name: '贴片电容' }, { code: 'EL-PC', name: 'PCB / 电路板' }] },
  ],
  ledgerQuery: { warehouse_id: null, material_id: null, source_type: null, from_date: '2026-09-25', to_date: '2026-10-01' },
  productionCostReport, productionCostSettlements, journals, receipts, receivablesPayables, openedRouteKeys: previewRoutes,
})
// 只替换本预览实例的生命周期，不启动发现、连接、轮询或修改真实应用状态。
store.initialize = async () => {}
store.dispose = () => {}
// 正式台账查询会连带刷新全部业务资料，取景只读取隔离快照，避免无关接口调用。
store.queryLedger = async () => { store.error = ''; store.ledgerResult = previewResponse('inventoryLedger') }
useThemeStore(pinia).setDarkTheme(false)
installWorkspaceAccessGuard(workspaceRouter, () => store.user.permissions)
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
