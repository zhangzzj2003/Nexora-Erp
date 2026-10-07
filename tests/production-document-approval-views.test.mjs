import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 实际编译四个生产页面并调用按钮绑定，验证待审保护、普通操作与冲销原因。
test('生产四类先独立审批，完工保留质检，普通执行无需批次', async t => {
  const storeModule = `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    export const calls=[];export const usePiniaAppStore=defineStore('production-approval-view',()=>{
      const state=createAppState();const actions={can:()=>true,localTime:v=>v,
        async openProductionAssociations(target){calls.push(['associations',target]);return true},
        async openDocumentApproval(target){calls.push(['approval',target]);state.documentApprovalTarget.value=target;
          state.documentApprovalRecord.value={status:'approved',reversal_reason:'已批准原因'};return true},
        closeDocumentApproval(){state.documentApprovalTarget.value=null}};
      for(const [op,reasons] of [['reverseProductionCompletion','completionReversalReasons']])
        actions[op]=id=>calls.push([op,id,state[reasons].value[id]]);
      for(const name of ['releaseWorkOrder','postMaterialIssue','postMaterialReturn','postProductionCompletion','cancelWorkOrder','cancelMaterialIssue','cancelMaterialReturn','cancelProductionCompletion','reverseMaterialIssue','reverseMaterialReturn'])
        actions[name]=(...args)=>calls.push([name,...args]);return {...state,...actions};});`
  const buttonModule = `import {defineComponent,h} from 'vue';export const buttons=[];
    export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
      const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
      buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'production-approval-fixture', enforce: 'pre', resolveId(id, importer) {
      if (importer?.includes('/views/workspace/') && id.endsWith('/store/app-store')) return '\0production-approval-store'
      if (id.endsWith('/AppButton.vue')) return '\0production-approval-button'
      if (id.endsWith('/DocumentApprovalDialog.vue') || id.endsWith('/ProductionAssociationDialog.vue')) return '\0production-approval-dialog'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0production-approval-table'
    }, load(id) {
      if (id === '\0production-approval-store') return storeModule
      if (id === '\0production-approval-button') return buttonModule
      if (id === '\0production-approval-dialog') return `export default {render:()=>null}`
      if (id === '\0production-approval-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, calls } = await server.ssrLoadModule('\0production-approval-store')
  const { buttons } = await server.ssrLoadModule('\0production-approval-button')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const record = { id: 1, document_no: 'DEMO-20261007-000001', warehouse_name: '主仓库', from_warehouse_name: '主仓库',
    to_warehouse_name: '第二仓', warehouse_id: 1, reason: '实盘差异', reference: '', accepted_quantity: '100',reported_quantity:'100',rejected_quantity:'0',remaining_output_quantity:'100', product_name:'成品',product_unit:'件',created_at: '2026-10-07', created_by_name: '建单人员',
    lines: [{ id: 2, material_id: 8, quantity: '100', book_quantity: '0', counted_quantity: '100', difference: '100',
      unit: '个', sku: 'R', material_name: '电阻', physical_lots: [], warranty_days: null }], reversal_id: null }
  const cases = [
    ['ProductionWorkOrdersView', 'workOrders', 'WorkOrder', 'draft', '下达', 'releaseWorkOrder', null, null],
    ['MaterialIssuesView', 'materialIssues', 'MaterialIssue', 'draft', '确认领料', 'postMaterialIssue', 'reverseMaterialIssue', null],
    ['MaterialReturnsView', 'materialReturns', 'MaterialReturn', 'draft', '确认退料', 'postMaterialReturn', 'reverseMaterialReturn', null],
    ['ProductionCompletionsView', 'productionCompletions', 'ProductionCompletion', 'inspected', '确认完工', 'postProductionCompletion', 'reverseProductionCompletion', 'completionReversalReasons']
  ]
  for (const [file, state, kind, businessStatus, label, operation, reverse, reasonState] of cases) {
    const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/production/' + file + '.vue')
    let bindings
    const RealView = { ...View, setup(p, context) { bindings = View.setup(p, context); return bindings } }
    const render = async () => { buttons.length = 0; return renderToString(createSSRApp({ render: () => h(RealView) }).use(pinia)
      .component('RouterLink', { setup: (_, { slots }) => () => h('a', slots.default?.()) })) }
    if (kind === 'ProductionCompletion') {
      // 待质检不能直接入库；整批不合格完成审批后仍可普通确认，但没有实物入库批次。
      store[state] = [{ ...record, status: 'draft', accepted_quantity: null, rejected_quantity: null }]
      store.inspectionDrafts[1] = { accepted_quantity: '', qc_note: '' }
      const draftHtml = await render()
      assert.match(draftHtml, /待质检/)
      assert.ok(buttons.some(b => b.label === '记录质检结果'))
      assert.ok(!buttons.some(b => b.label === label))
      store[state] = [{ ...record, status: businessStatus, accepted_quantity: '0', approval: { status: 'approved' } }]
      await render(); calls.length = 0
      assert.ok(!buttons.some(b => b.label === '指定实物批次（可选）'))
      await buttons.find(b => b.label === label).click()
      assert.deepEqual(calls[0], [operation, 1])
    }
    if (['WorkOrder','ProductionCompletion'].includes(kind)) {
      store[state]=[{...record,status:businessStatus}]
      await render(); calls.length=0
      await buttons.find(button=>button.label==='关联单据').click()
      assert.deepEqual(calls[0],['associations',{kind:kind==='WorkOrder'?'work_order':'completion',id:1}])
    }
    for (const approval of [undefined, { status: 'draft' }, { status: 'submitted' }]) {
      store[state] = [{ ...record, status: businessStatus, approval }]
      const html = await render()
      assert.ok(!buttons.some(b => b.label === label), file)
      assert.ok(!buttons.some(b => b.label === '指定实物批次（可选）'), file)
      if (approval?.status === 'submitted') assert.ok(!buttons.some(b => b.label === '取消'))
      assert.match(html, approval?.status === 'submitted' ? /审批中/ : /未送审/)
      if (kind === 'MaterialIssue') {
        assert.match(html, /领料数量/)
        assert.doesNotMatch(html.replace(/<!--[\s\S]*?-->/g, ''), /已领|可退/)
      }
      calls.length = 0; await buttons.find(b => b.label === '单据审批').click()
      assert.deepEqual(calls[0], ['approval', { document_type: kind, document_id: 1, intent: 'execute' }])
    }
    store[state] = [{ ...record, status: businessStatus, approval: { status: 'approved' } }]
    await render(); calls.length = 0
    await buttons.find(b => b.label === label).click()
    assert.deepEqual(calls[0], [operation, 1], '普通执行不附带批次载荷')
    if (!reverse) continue
    assert.ok(buttons.some(b => b.label === '指定实物批次（可选）'))
    // 审批撤回后，即使批次弹窗先前打开，提交也必须失效。
    bindings[kind === 'MaterialIssue' ? 'activeIssueId' : kind === 'MaterialReturn' ? 'activeReturnId' : 'activeCompletionId'].value = 1
    store[state][0].approval.status = 'withdrawn'
    calls.length = 0; await bindings.confirmLotPost(); assert.equal(calls.length, 0)
    store[state] = [{ ...record, status: 'posted', reversal_approval: { status: 'approved' } }]
    await render(); if(reasonState) store[reasonState][1] = '未审核原因'; calls.length = 0
    await buttons.find(b => b.label === '执行已批准冲销').click()
    assert.deepEqual(calls.at(-1), [reverse, 1, '已批准原因'])
    // 已冲销只保留查询；不能再次执行，也不能丢失原冲销的人员记录。
    store[state][0].reversal_id = 9
    store[state][0].status = 'reversed'
    store[state][0].reversal_approval.status = 'executed'
    await render(); calls.length = 0
    assert.ok(!buttons.some(b => b.label === '执行已批准冲销'))
    await buttons.find(b => b.label === '冲销审批记录').click()
    assert.deepEqual(calls[0], ['approval', { document_type: kind, document_id: 1, intent: 'reverse' }])
  }
})
