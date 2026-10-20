import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { planFixture, planOptionsFixture, planInputFixture } from './production-plan-fixture.mjs'

test('生产计划复用筛选操作区和标题统计，重置筛选保留草稿，权限及离线禁用继续生效', async t => {
  // 保留真实页面、按钮和筛选控件；表格只展开插槽，避免服务端测试依赖浏览器布局。
  const server = await createServer({ configFile: false, plugins: [{
    name: 'plan-toolbar-test', enforce: 'pre',
    resolveId(id, importer) {
      if (!importer?.includes('/src/renderer/')) return
      if (id.endsWith('/store/app-store')) return '\0toolbar-store'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0toolbar-table'
      if (['/ProductionPlanEditor.vue', '/WorkspaceDocumentDialog.vue', '/DocumentApprovalDialog.vue', '/AppModal.vue'].some(name => id.endsWith(name))) return '\0toolbar-empty'
    },
    load(id) {
      if (id === '\0toolbar-empty') return 'export default {render:()=>null}'
      if (id === '\0toolbar-table') return `import {h} from 'vue';export default {setup:(_,{slots})=>()=>h('section',{class:'tested-table'},[
        h('div',{class:'tested-filters'},slots.filters?.()),h('div',{class:'tested-actions'},slots.actions?.())])}`
      if (id === '\0toolbar-store') return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
        export const usePiniaAppStore=defineStore('toolbar-test',()=>{const s=createAppState();return {...s,
          can:p=>s.user.value?.permissions.includes(p)??false,clearProductionPlanDetail(){},
          resetProductionPlanForm(){},navigateToRoute(){},localTime:v=>v}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore } = await server.ssrLoadModule('\0toolbar-store')
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/production/ProductionPlansView.vue')
  async function render(permissions, offline = false) {
    const pinia = createPinia(), store = usePiniaAppStore(pinia)
    store.user = { id: 1, roles: [], permissions }
    store.productionPlans = [planFixture()]
    store.productionPlanOptions = planOptionsFixture()
    store.productionPlanForm = planInputFixture()
    store.connectionLost = offline
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: View }] })
    await router.push('/')
    let vnode
    const app = createSSRApp({ render: () => (vnode = h(View)) }).use(pinia).use(router)
    setupSsrStyles(app)
    const context = {}, html = await renderToString(app, context)
    return { html, context, store, state: vnode.component.setupState }
  }
  const full = await render(['production_plan.view', 'production_plan.create', 'production.view', 'mrp.view'])
  assert.match(full.context.teleports['#workspace-page-summary'], /全部计划|待审批/)
  assert.doesNotMatch(full.html, /workspace-summary|summary-filter/)
  const actions = full.html.slice(full.html.indexOf('class="tested-actions"'))
  for (const label of ['刷新计划', '物料需求计划', '生产工单', '清空未保存输入', '继续编制计划']) assert.ok(actions.includes(label), label)
  assert.ok(actions.indexOf('继续编制计划') > actions.indexOf('清空未保存输入'))
  assert.match(full.html, /class="tested-filters".*搜索计划.*重置/s)
  const draft = JSON.stringify(full.store.productionPlanForm)
  full.state.query = '不存在'; full.state.filter = 'overdue'
  assert.equal(full.state.filtered.length, 0)
  full.state.resetFilters()
  assert.equal(full.state.query, ''); assert.equal(full.state.filter, 'all')
  assert.equal(full.state.filtered.length, 1)
  assert.equal(JSON.stringify(full.store.productionPlanForm), draft)
  const readonly = await render(['production_plan.view'])
  assert.doesNotMatch(readonly.html, /继续编制计划|清空未保存输入|物料需求计划|>生产工单</)
  const offline = await render(['production_plan.view', 'production_plan.create'], true)
  const offlineCreate = [...offline.html.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(match => match[0]).find(button => button.includes('继续编制计划'))
  assert.match(offlineCreate, /^<button[^>]*disabled/)
  offline.state.newPlan()
  assert.equal(offline.state.editor, false)
})
