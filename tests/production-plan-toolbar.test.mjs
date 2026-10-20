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
      if (id.endsWith('/WorkspaceDocumentDialog.vue')) return '\0toolbar-detail'
      if (['/ProductionPlanEditor.vue', '/DocumentApprovalDialog.vue', '/AppModal.vue'].some(name => id.endsWith(name))) return '\0toolbar-empty'
    },
    load(id) {
      if (id === '\0toolbar-detail') return `import {h} from 'vue';export default {props:['columns','data'],setup:(p,{slots})=>()=>h('section',{class:'tested-detail'},[
        h('div',{class:'detail-basic'},slots.basicInfo?.()),h('div',{class:'detail-actions'},slots.documentActions?.()),
        ...p.data.flatMap(row=>p.columns.map(col=>h('div',{'data-detail-column':col.key},[h('h3',col.title),slots['cell-'+col.key]?.({row})])))])}`
      if (id === '\0toolbar-empty') return 'export default {render:()=>null}'
      if (id === '\0toolbar-table') return `import {h} from 'vue';export default {props:['columns','data'],setup:(p,{slots})=>()=>h('section',{class:'tested-table'},[
        h('div',{class:'tested-filters'},slots.filters?.()),h('div',{class:'tested-actions'},slots.actions?.()),
        ...p.data.flatMap(row=>p.columns.map(col=>h('div',{'data-column':col.key},[h('h3',col.title),slots['cell-'+col.key]?.({row})])))])}`
      if (id === '\0toolbar-store') return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
        export const detailReads=[],releaseWrites=[];
        export const usePiniaAppStore=defineStore('toolbar-test',()=>{const s=createAppState();return {...s,
          can:p=>s.user.value?.permissions.includes(p)??false,clearProductionPlanDetail(){},async loadProductionPlanDetail(id){detailReads.push(id);return true},
          async releaseProductionPlan(request){releaseWrites.push(request);return true},resetProductionPlanForm(){},navigateToRoute(){},localTime:v=>v}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, detailReads, releaseWrites } = await server.ssrLoadModule('\0toolbar-store')
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/production/ProductionPlansView.vue')
  async function render(permissions, offline = false, record = planFixture()) {
    const pinia = createPinia(), store = usePiniaAppStore(pinia)
    store.user = { id: 1, roles: [], permissions }
    store.productionPlans = [record]
    store.productionPlanDetail = record
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
  assert.match(readonly.html, /查看生产计划 SCJH-20261019-000001 详情/)
  const offline = await render(['production_plan.view', 'production_plan.create'], true)
  const offlineCreate = [...offline.html.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(match => match[0]).find(button => button.includes('继续编制计划'))
  assert.match(offlineCreate, /^<button[^>]*disabled/)
  offline.state.newPlan()
  assert.equal(offline.state.editor, false)
  // 编号与名称必须出现在不同列；编号使用真实文本按钮而非不可操作的文字。
  const numberCell = full.html.slice(full.html.indexOf('data-column="plan"'), full.html.indexOf('data-column="reference"'))
  const nameCell = full.html.slice(full.html.indexOf('data-column="reference"'), full.html.indexOf('data-column="products"'))
  assert.match(numberCell, /<button[^>]*aria-label="查看生产计划 SCJH-20261019-000001 详情"/)
  assert.doesNotMatch(numberCell, /十月智能控制器备货/)
  assert.match(nameCell, /计划名称[\s\S]*十月智能控制器备货/)
  const approvalCell = full.html.slice(full.html.indexOf('data-column="status"'), full.html.indexOf('data-column="execution"'))
  const executionCell = full.html.slice(full.html.indexOf('data-column="execution"'), full.html.indexOf('data-column="actions"'))
  assert.match(approvalCell, /审批状态：已批准/)
  assert.doesNotMatch(approvalCell, /执行状态/)
  assert.match(executionCell, /执行状态：待下达/)
  assert.doesNotMatch(executionCell, /审批状态/)
  assert.match(full.html, /app-status-tag--ready/)
  assert.match(full.html, /app-status-tag--pending/)
  await readonly.state.openDetail(planFixture())
  assert.deepEqual(detailReads, [1])
  assert.equal(readonly.state.showDetail, true)
  assert.equal(readonly.state.pending, false)
  await offline.state.openDetail(planFixture())
  readonly.store.user.permissions = []
  await readonly.state.openDetail(planFixture())
  assert.deepEqual(detailReads, [1])
  const cancelled = await render(['production_plan.view'], false, { ...planFixture(), status: 'cancelled', progress: 'completed' })
  assert.match(cancelled.html, /app-status-tag--neutral/)
  assert.match(cancelled.html, /已取消/)
  assert.doesNotMatch(cancelled.html, /app-status-tag--success|执行状态：报工完成/)

  // 明细保留独立字段与审批入口，去掉行内操作后仍可选择合格产品下达。
  const detailHtml = full.html.slice(full.html.indexOf('class="tested-detail"'))
  assert.doesNotMatch(full.html.slice(0,full.html.indexOf('class="tested-detail"')), /单据审批/)
  assert.match(detailHtml, /class="detail-actions"[\s\S]*单据审批/)
  assert.deepEqual([...detailHtml.matchAll(/data-detail-column="([^"]+)"/g)].map(match => match[1]), ['sku','product','dates','priority','quantity','release','progress'])
  assert.match(detailHtml, /data-detail-column="priority"[\s\S]*app-status-tag--pending/)
  const multi = planFixture(), line = multi.lines[0]
  multi.lines.push({...line,id:2,sku:'CTRL-002',quantity:'20.000',unreleased_quantity:'20.000'}, {...line,id:3,unreleased_quantity:'0.000'}, {...line,id:4,plan_id:99})
  const releaseView = await render(['production_plan.view','production_plan.release','work_order.create'], false, multi)
  assert.deepEqual(releaseView.state.releasableLines.map(row => row.id), [1,2])
  releaseView.state.openRelease(multi.lines[0])
  const firstRequest = releaseView.state.release.request_id
  releaseView.state.reason = '按交付安排分批'
  releaseView.state.openRelease(multi.lines[1])
  assert.equal(releaseView.state.release.line_id, 2)
  assert.equal(releaseView.state.release.quantity, '20.000')
  assert.notEqual(releaseView.state.release.request_id, firstRequest)
  assert.equal(releaseView.state.reason, '按交付安排分批')
  releaseView.state.openRelease(multi.lines[3])
  assert.equal(releaseView.state.release.line_id, 2)
  releaseView.state.release.quantity = '21.000'
  await releaseView.state.execute()
  assert.equal(releaseWrites.length, 0)
  releaseView.state.release.quantity = '5.000'
  await releaseView.state.execute()
  assert.equal(releaseWrites[0].line_id, 2)
  assert.equal(releaseWrites[0].reason, '按交付安排分批')
  assert.equal(releaseView.state.command, null)
  releaseView.state.openRelease(multi.lines[0])
  assert.equal(releaseView.state.reason, '')
  releaseView.state.reason = '过期版本不可下达'
  releaseView.store.productionPlanDetail.version++
  await releaseView.state.execute()
  assert.match(releaseView.store.error, /计划或审批已变化/)
  assert.equal(releaseWrites.length, 1)
  assert.deepEqual(readonly.state.releasableLines, [])
  offline.state.openRelease(multi.lines[0])
  assert.equal(offline.state.command, null)
})
