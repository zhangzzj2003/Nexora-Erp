import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 实际编译采购申请页面：旧批准标志不能放行转单，撤回后的打开表单也不能继续执行。
test('采购申请共用独立审批，拆单保留授权且撤回使弹窗失效', async t => {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'purchase-request-approval-fixture', enforce: 'pre',
    resolveId(id, importer) {
      if (importer?.includes('/PurchaseRequestsView.vue') && id.endsWith('/store/app-store')) return '\0request-approval-store'
      if (id.endsWith('/AppButton.vue')) return '\0request-approval-button'
      if (id.endsWith('/DocumentApprovalDialog.vue')) return '\0request-approval-dialog'
      if (id.endsWith('/WorkspaceDocumentDialog.vue')) return '\0request-conversion-dialog'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0request-approval-table'
    }, load(id) {
      if (id === '\0request-approval-store') return `import {ref} from 'vue';import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
        export const calls=[];const permission=ref(true);
        export const setPermission=v=>permission.value=v;
        export const usePiniaAppStore=defineStore('request-approval-view',()=>{const state=createAppState();return {...state,
          can:op=>permission.value && op!=='purchase_request.cancel',localTime:v=>v,openDocumentApproval:target=>calls.push(['approval',target]),
          editPurchaseRequest:()=>{},savePurchaseRequest:()=>{},cancelPurchaseRequest:()=>{},
          selectRequestConversion(id){state.requestConversionForm.value.requestId=id;calls.push(['select',id])},
          async convertPurchaseRequest(){calls.push(['convert']);state.notice.value='转单成功'}}});`
      if (id === '\0request-approval-button') return `import {defineComponent,h} from 'vue';export const buttons=[];
        export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{const children=slots.default?.();
          const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
          buttons.push({label,click:attrs.onClick,disabled:p.disabled});return h('button',attrs,children)}}});`
      if (id === '\0request-approval-dialog' || id === '\0request-conversion-dialog') return 'export default {render:()=>null}'
      if (id === '\0request-approval-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, calls, setPermission } = await server.ssrLoadModule('\0request-approval-store')
  const { buttons } = await server.ssrLoadModule('\0request-approval-button')
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/purchase/PurchaseRequestsView.vue')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const item = { id: 1, status: 'approved', created_at: '2026-10-07', created_by_name: '申请编制人',
    reference: '', note: '', lines: [{ id: 2, material_id: 3, material_name: '电阻', quantity: '10', remaining_quantity: '4', unit: '个' }] }
  let bindings
  const RealView = { ...View, setup(p, ctx) { bindings = View.setup(p, ctx); return bindings } }
  const render = async () => { buttons.length = 0; return renderToString(createSSRApp({ render: () => h(RealView) }).use(pinia)) }
  for (const approval of [undefined, { status: 'draft' }, { status: 'submitted' }, { status: 'withdrawn' }]) {
    store.purchaseRequests = [{ ...item, approval }]
    const html = await render()
    assert.ok(!buttons.some(b => b.label === '转订单'), '原申请 approved 不代替本单统一批准')
    assert.ok(!buttons.some(b => ['批准', '提交审批', '驳回'].includes(b.label)), '列表不保留旧无版本入口')
    assert.match(html, approval?.status === 'submitted' ? /审批中/ : approval?.status === 'withdrawn' ? /已撤回/ : /未送审/)
    calls.length = 0
    await buttons.find(b => b.label === '单据审批').click()
    assert.deepEqual(calls, [['approval', { document_type: 'PurchaseRequest', document_id: 1, intent: 'execute' }]])
  }
  for (const status of ['approved', 'executed']) {
    store.purchaseRequests = [{ ...item, approval: { status } }]
    await render(); calls.length = 0
    await buttons.find(b => b.label === '转订单').click()
    assert.deepEqual(calls, [['select', 1]])
    // 已打开弹窗的草稿保留，但批准被撤回时不能提交；重新取得授权才允许转换。
    store.purchaseRequests[0].approval.status = 'withdrawn'
    calls.length = 0; await bindings.submitConversion(); assert.equal(calls.length, 0)
    store.purchaseRequests[0].approval.status = status
    setPermission(false); await bindings.submitConversion(); assert.equal(calls.length, 0)
    setPermission(true); await bindings.submitConversion(); assert.deepEqual(calls, [['convert']])
  }
  store.purchaseRequests[0].lines[0].remaining_quantity = '0'
  await render(); assert.ok(!buttons.some(b => b.label === '转订单'))
})
