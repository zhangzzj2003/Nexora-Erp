import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 实际编译三个销售页面并调用按钮绑定，验证待审保护、普通操作与冲销原因。
test('销售订单出库退货先审批，上游批准不代替本单，普通执行无需批次', async t => {
  const storeModule = `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    export const calls=[];export const usePiniaAppStore=defineStore('sales-approval-view',()=>{
      const state=createAppState();const actions={can:()=>true,localTime:v=>v,
        async openDocumentApproval(target){calls.push(['approval',target]);state.documentApprovalTarget.value=target;
          state.documentApprovalRecord.value={status:'approved',reversal_reason:'已批准原因'};return true},
        closeDocumentApproval(){state.documentApprovalTarget.value=null}};
      for(const [op,reasons] of [['reverseShipment','shipmentReversalReasons'],['reverseSalesReturn','salesReturnReversalReasons']])
        actions[op]=id=>calls.push([op,id,state[reasons].value[id]]);
      for(const name of ['confirmSalesOrder','postShipment','postSalesReturn','cancelSalesOrder','cancelShipment','cancelSalesReturn'])
        actions[name]=(...args)=>calls.push([name,...args]);return {...state,...actions};});`
  const buttonModule = `import {defineComponent,h} from 'vue';export const buttons=[];
    export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
      const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
      buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'sales-approval-fixture', enforce: 'pre', resolveId(id, importer) {
      if (importer?.includes('/views/workspace/') && id.endsWith('/store/app-store')) return '\0sales-approval-store'
      if (id.endsWith('/AppButton.vue')) return '\0sales-approval-button'
      if (id.endsWith('/DocumentApprovalDialog.vue')) return '\0sales-approval-dialog'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0sales-approval-table'
    }, load(id) {
      if (id === '\0sales-approval-store') return storeModule
      if (id === '\0sales-approval-button') return buttonModule
      if (id === '\0sales-approval-dialog') return `export default {render:()=>null}`
      if (id === '\0sales-approval-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, calls } = await server.ssrLoadModule('\0sales-approval-store')
  const { buttons } = await server.ssrLoadModule('\0sales-approval-button')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const record = { id: 1, document_no: 'DEMO-20261007-000001', warehouse_name: '主仓库', from_warehouse_name: '主仓库',
    to_warehouse_name: '第二仓', warehouse_id: 1, reason: '实盘差异', reference: '', created_at: '2026-10-07', created_by_name: '建单人员',
    lines: [{ id: 2, material_id: 8, quantity: '100', book_quantity: '0', counted_quantity: '100', difference: '100',
      unit: '个', sku: 'R', material_name: '电阻', physical_lots: [], warranty_days: null }], reversal_id: null }
  const cases = [
    ['SalesOrdersView', 'salesOrders', 'SalesOrder', 'draft', '确认订单', 'confirmSalesOrder', null, null],
    ['SalesShipmentsView', 'shipments', 'Shipment', 'draft', '确认出库', 'postShipment', 'reverseShipment', 'shipmentReversalReasons'],
    ['SalesReturnsView', 'salesReturns', 'SalesReturn', 'draft', '确认退货', 'postSalesReturn', 'reverseSalesReturn', 'salesReturnReversalReasons']
  ]
  for (const [file, state, kind, businessStatus, label, operation, reverse, reasonState] of cases) {
    const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/' + file + '.vue')
    let bindings
    const RealView = { ...View, setup(p, context) { bindings = View.setup(p, context); return bindings } }
    const render = async () => { buttons.length = 0; return renderToString(createSSRApp({ render: () => h(RealView) }).use(pinia)) }
    for (const approval of [undefined, { status: 'draft' }, { status: 'submitted' }]) {
      store[state] = [{ ...record, status: businessStatus, approval }]
      const html = await render()
      assert.ok(!buttons.some(b => b.label === label), file)
      assert.ok(!buttons.some(b => b.label === '指定实物批次（可选）'), file)
      if (approval?.status === 'submitted') assert.ok(!buttons.some(b => b.label === '取消'))
      assert.match(html, approval?.status === 'submitted' ? /审批中/ : /未送审/)
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
    bindings[kind === 'Shipment' ? 'activeShipmentId' : 'activeReturnId'].value = 1
    store[state][0].approval.status = 'withdrawn'
    calls.length = 0; await bindings.confirmLotPost(); assert.equal(calls.length, 0)
    store[state] = [{ ...record, status: 'posted', reversal_approval: { status: 'approved' } }]
    await render(); store[reasonState][1] = '未审核原因'; calls.length = 0
    await buttons.find(b => b.label === '执行已批准冲销').click()
    assert.deepEqual(calls.at(-1), [reverse, 1, '已批准原因'])
    // 已冲销只保留查询；不能再次执行，也不能丢失原冲销的人员记录。
    store[state][0].reversal_id = 9
    store[state][0].reversal_approval.status = 'executed'
    await render(); calls.length = 0
    assert.ok(!buttons.some(b => b.label === '执行已批准冲销'))
    await buttons.find(b => b.label === '冲销审批记录').click()
    assert.deepEqual(calls[0], ['approval', { document_type: kind, document_id: 1, intent: 'reverse' }])
  }
})
