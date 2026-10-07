import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 渲染真实采购页面并调用真实按钮绑定，只替换控件绘制和网络，避免用源码匹配代替行为验证。
test('采购与退货出库分别送审，批准后执行，普通收发无需批次，冲销沿用批准原因', async t => {
  const storeModule = `import {defineStore,storeToRefs} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    export const calls=[];export const usePiniaAppStore=defineStore('purchase-approval-view',()=>{
      const state=createAppState();const actions={can:()=>true,localTime:v=>v,
        async openDocumentApproval(target){calls.push(['approval',target]);state.documentApprovalTarget.value=target;
          state.documentApprovalRecord.value={status:'approved',reversal_reason:'已批准的冲销原因'};return true},
        closeDocumentApproval(){state.documentApprovalTarget.value=null},
        async reverseReceipt(id){calls.push(['reverse',id,state.receiptReversalReasons.value[id]])},
        async reversePurchaseReturn(id){calls.push(['reverse',id,state.purchaseReturnReversalReasons.value[id]])},
        async reverseOtherOutbound(id){calls.push(['reverse',id,state.otherOutboundReversalReasons.value[id]])},
        async loadAvailableOutboundLots(id){return {outbound_id:id,warehouse_id:1,lines:[{outbound_line_id:2,material_id:8,quantity:'100',lots:[{lot_id:8,quantity:'100',code:'R1'}]}]}}};
      for(const name of ['confirmPurchaseOrder','cancelPurchaseOrder','confirmGoodsReceipt','cancelGoodsReceipt','postReceipt',
        'submitPurchaseReturn','cancelPurchaseReturn','postWarehouseOutbound','cancelOtherOutbound'])
        actions[name]=(...args)=>calls.push([name,...args]);
      return {...state,...actions};
    });export const useAppStore=()=>{const s=usePiniaAppStore();return {...storeToRefs(s),...Object.fromEntries(Object.entries(s).filter(([,v])=>typeof v==='function'))}};`
  const buttonModule = `import {defineComponent,h} from 'vue';export const buttons=[];
    export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
      const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
      buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'purchase-approval-fixture', enforce: 'pre', resolveId(id, importer) {
      if (importer?.includes('/views/workspace/') && id.endsWith('/store/app-store')) return '\0purchase-approval-store'
      if (id.endsWith('/AppButton.vue')) return '\0purchase-approval-button'
      if (id.endsWith('/DocumentApprovalDialog.vue')) return '\0purchase-approval-dialog'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0purchase-approval-table'
    }, load(id) {
      if (id === '\0purchase-approval-store') return storeModule
      if (id === '\0purchase-approval-button') return buttonModule
      if (id === '\0purchase-approval-dialog') return `export default {render:()=>null}`
      if (id === '\0purchase-approval-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, calls } = await server.ssrLoadModule('\0purchase-approval-store')
  const { buttons } = await server.ssrLoadModule('\0purchase-approval-button')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const record = { id: 1, document_no: 'DEMO-20261007-000001', status: 'draft', supplier_name: '采购供应商', warehouse_name: '主仓库',
    warehouse_id: 1, source_kind: 'other', reason: 'sample', reference: '', created_at: '2026-10-07', created_by_name: '建单人员', lines: [{ id: 2, material_id: 8, quantity: '100', unit: '个',
      sku: 'R', material_name: '电阻', physical_lots: [], returned_quantity: '0' }], reversal_id: null }
  const cases = [
    ['purchase/PurchaseOrdersView.vue', 'purchaseOrders', 'PurchaseOrder', '确认订单', 'confirmPurchaseOrder', '取消订单'],
    ['purchase/PurchaseGoodsReceiptsView.vue', 'goodsReceipts', 'PurchaseGoodsReceipt', '确认收货', 'confirmGoodsReceipt', '取消草稿'],
    ['purchase/PurchaseReceiptsView.vue', 'receipts', 'Receipt', '确认入库', 'postReceipt', null],
    ['purchase/PurchaseReturnsView.vue', 'purchaseReturns', 'PurchaseReturn', '生成出库草稿', 'submitPurchaseReturn', '取消'],
    ['warehouse/WarehouseOutboundsView.vue', 'warehouseOutbounds', 'WarehouseOutbound', '确认出库', 'postWarehouseOutbound', '取消']
  ]
  for (const [file, state, kind, label, operation, cancel] of cases) {
    const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/' + file)
    let bindings
    const RealView = { ...View, setup(p, context) { bindings = View.setup(p, context); return bindings } }
    const render = async () => { buttons.length = 0; return renderToString(createSSRApp({ render: () => h(RealView) }).use(pinia)) }
    for (const approval of [undefined, { status: 'draft' }, { status: 'submitted' }]) {
      store[state] = [{ ...record, approval }]
      const html = await render()
      assert.doesNotMatch(html, new RegExp('>' + label + '<'), file)
      const entry = buttons.find(b => b.label === '单据审批')
      assert.ok(entry, file)
      calls.length = 0; await entry.click()
      assert.deepEqual(calls[0], ['approval', { document_type: kind, document_id: 1, intent: 'execute' }])
      if (cancel && approval?.status === 'submitted') assert.equal(buttons.some(b => b.label === cancel), false)
    }
    store[state] = [{ ...record, approval: { status: 'approved' } }]
    await render(); calls.length = 0
    await buttons.find(b => b.label === label).click()
    assert.deepEqual(calls[0], [operation, 1], '普通执行不附带批次载荷')
    if (cancel) assert.equal(buttons.some(b => b.label === cancel), false)
    if (['Receipt', 'WarehouseOutbound'].includes(kind)) {
      await bindings.startLotPost(store[state][0])
      assert.equal(bindings.lotDrafts.value[0].lots[0].quantity, '100')
      store[state][0].approval.status = 'withdrawn'
      calls.length = 0; await bindings.confirmLotPost()
      assert.equal(calls.length, 0, '审批撤回后不能提交已经打开的批次草稿')
    }
    if (['Receipt', 'PurchaseReturn', 'WarehouseOutbound'].includes(kind)) {
      store[state] = [{ ...record, status: 'posted', reversal_approval: { status: 'approved' } }]
      const reasonState = { Receipt: 'receiptReversalReasons', PurchaseReturn: 'purchaseReturnReversalReasons', WarehouseOutbound: 'otherOutboundReversalReasons' }[kind]
      await render(); store[reasonState][1] = '未送审的临时原因'; calls.length = 0
      await buttons.find(b => b.label === '执行已批准冲销').click()
      assert.deepEqual(calls.at(-1), ['reverse', 1, '已批准的冲销原因'])
    }
    if (kind === 'WarehouseOutbound') {
      // 父采购退货的冲销不会伪装为其他出库冲销，仓库仍显示原记录与真实关联。
      store[state] = [{ ...record, status: 'posted', source_kind: 'purchase_return', purchase_return_id: 7, purchase_return_reversal_id: 9 }]
      assert.match(await render(), /采购退货已冲销/)
      assert.equal(buttons.some(b => b.label === '执行已批准冲销'), false)
    }
    if (kind === 'PurchaseReturn') {
      // 升级前已有关联草稿仍须先审批父单，不能显示成已经完成转单。
      store[state] = [{ ...record, outbound_id: 3, approval: { status: 'draft' } }]
      const legacyHtml = await render()
      assert.match(legacyHtml, /待送审/)
      assert.doesNotMatch(legacyHtml, /待仓库出库/)
      assert.ok(buttons.some(b => b.label === '单据审批'))
      // 退货取消会影响子单；子单正在审批时也不显示取消入口。
      store[state] = [{ ...record, approval: { status: 'executed' }, outbound_id: 3, outbound_approval: { status: 'approved' } }]
      await render()
      assert.equal(buttons.some(b => b.label === '取消'), false)
    }
  }
})
