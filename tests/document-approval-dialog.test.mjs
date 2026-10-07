import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 真实审批组件验证每个状态的动作和意见要求，外壳只替换绘制，业务条件仍来自真实组件。
test('审批弹窗展示独立步骤和人员记录，驳回必填，离线禁用且不把批准当执行', async t => {
  const fixture = `import {defineStore} from 'pinia';import {ref} from 'vue';
    export const calls=[];export const usePiniaAppStore=defineStore('approval-dialog-test',()=>({
      documentApprovalTarget:ref({document_type:'WarehouseInbound',document_id:1,intent:'execute'}),
      documentApprovalRecord:ref(null),documentApprovalLoading:ref(false),documentApprovalError:ref(''),
      documentApprovalReasons:ref({}),busy:ref(false),connectionLost:ref(false),roles:ref([{code:'admin',label:'管理员'}]),
      localTime:value=>value,closeDocumentApproval(){calls.push('close')},loadDocumentApproval(){calls.push('refresh')},
      actDocumentApproval(action){calls.push(action)}
    }));`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'approval-dialog-fixture', enforce: 'pre',
    transform(code, id) {
      if (id.endsWith('/DocumentApprovalDialog.vue')) return code.replace("'naive-ui'", "'virtual:approval-dialog-modal'")
    }, resolveId(id, importer) {
      if (id === 'virtual:approval-dialog-modal') return '\0approval-dialog-modal'
      if (importer?.includes('DocumentApprovalDialog') && id.endsWith('/store/app-store')) return '\0approval-dialog-store'
      if (id === 'naive-ui' && importer?.includes('DocumentApprovalDialog')) return '\0approval-dialog-modal'
      for (const name of ['AppButton.vue', 'AppInput.vue']) if (id.endsWith('/' + name)) return '\0approval-dialog-' + name
    }, load(id) {
      if (id === '\0approval-dialog-store') return fixture
      if (id === '\0approval-dialog-modal') return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show','title'],setup(p,{slots}){return()=>p.show?h('section',{'data-title':p.title},slots.default?.()):null}})`
      if (id === '\0approval-dialog-AppButton.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if (id === '\0approval-dialog-AppInput.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore } = await server.ssrLoadModule('\0approval-dialog-store')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const { default: Dialog } = await server.ssrLoadModule('/src/renderer/src/components/workspace/DocumentApprovalDialog.vue')
  const render = () => renderToString(createSSRApp({ render: () => h(Dialog) }).use(pinia))
  store.documentApprovalRecord = { document_no: 'QTRK-20261007-000001', intent: 'execute', business_status: 'draft',
    summary: [{label:'入库明细',value:'电阻 × 100 个'}], content_matches: true,
    version: 1, status: 'submitted', current_step: 0, steps: [{ name: '审核', role: 'admin' }, { name: '批准', role: null }],
    can_submit: false, can_review: false, can_withdraw: true, reversal_reason: '', events: [] }
  let html = await render()
  assert.match(html, /指定角色：管理员/)
  assert.match(html, /审批中/)
  assert.match(html, /电阻 × 100 个/)
  assert.match(html, /撤回审批/)
  assert.doesNotMatch(html, />驳回<|>审核<|审批意见/)
  store.documentApprovalRecord.can_review = true
  html = await render()
  assert.match(html, /<button[^>]*disabled[^>]*>驳回/)
  assert.match(html, /<button[^>]*>审核/)
  store.documentApprovalReasons['WarehouseInbound:1:execute'] = '数量需核对'
  html = await render()
  assert.doesNotMatch(html, /<button[^>]*disabled[^>]*>驳回/)
  store.documentApprovalRecord = { ...store.documentApprovalRecord, status: 'approved', current_step: 2, can_review: false,
    events: [{ id: 1, generation: 1, action: 'approve', step_name: '审核', actor_name: '独立审核人', created_at: '2026-10-07', reason: '核对明细' }] }
  html = await render()
  assert.match(html, /已批准，待执行/)
  assert.match(html, /审核 · 独立审核人/)
  assert.match(html, /核对明细/)
  assert.doesNotMatch(html, />批准<|>执行<|>确认入库</)
  // 已确认订单允许追加合同依据，查看原执行快照时不能提示无法完成的撤回操作。
  store.documentApprovalRecord = { ...store.documentApprovalRecord, status: 'executed', content_matches: false, can_withdraw: false }
  html = await render()
  assert.match(html, /下方保留原审批内容/)
  assert.doesNotMatch(html, /请撤回后重新送审|>撤回审批</)
  store.documentApprovalRecord = { ...store.documentApprovalRecord, status: 'approved', content_matches: true, can_withdraw: true }
  store.connectionLost = true
  assert.match(await render(), /<button[^>]*disabled[^>]*>撤回审批/)
  store.documentApprovalTarget.intent = 'reverse'
  store.documentApprovalRecord = { ...store.documentApprovalRecord, intent: 'reverse', status: 'draft', can_submit: true, can_withdraw: false }
  html = await render()
  assert.match(html, /冲销原因（必填）/)
  assert.match(html, /<button[^>]*disabled[^>]*>提交审批/)
  // 已处理的旧生产工单保留原流程；未质检完工明确提示业务前置。
  store.documentApprovalTarget = { document_type: 'WorkOrder', document_id: 1, intent: 'execute' }
  store.documentApprovalRecord = { ...store.documentApprovalRecord, document_type: 'WorkOrder',
    intent: 'execute', version: 0, can_submit: false, can_review: false, can_withdraw: false }
  for (const business_status of ['released', 'in_progress', 'completed']) {
    store.documentApprovalRecord.business_status = business_status
    html = await render()
    assert.match(html, /已处理单据保留原业务记录/)
    assert.doesNotMatch(html, /未送审|>提交审批</)
  }
  // 旧申请已无剩余需求只供查询，不为已转订单补造新批准。
  store.documentApprovalRecord.document_type = 'PurchaseRequest'
  store.documentApprovalRecord.business_status = 'approved'
  html = await render()
  assert.match(html, /申请已无待转数量，保留原转单记录/)
  assert.doesNotMatch(html, /未送审|>提交审批</)
  store.documentApprovalRecord.document_type = 'ProductionCompletion'
  store.documentApprovalRecord.business_status = 'draft'
  html = await render()
  assert.match(html, /请先记录质检结果/)
  assert.doesNotMatch(html, />提交审批</)
  // 报价送审、批准都保留原必填依据，旧已转单记录不生成虚假审批。
  store.connectionLost = false
  store.documentApprovalTarget = {document_type:'CrmQuote',document_id:1,intent:'execute'}
  store.documentApprovalRecord = {...store.documentApprovalRecord, document_type:'CrmQuote', business_status:'draft', can_submit:true}
  html = await render()
  assert.match(html, /报价操作依据（必填）/)
  assert.match(html, /<button[^>]*disabled[^>]*>提交审批/)
  store.documentApprovalReasons['CrmQuote:1:execute'] = '核对报价附件与条款'
  assert.doesNotMatch(await render(), /<button[^>]*disabled[^>]*>提交审批/)
  store.documentApprovalRecord.can_submit=false;store.documentApprovalRecord.can_review=true
  store.documentApprovalRecord.current_step=0
  delete store.documentApprovalReasons['CrmQuote:1:execute']
  assert.match(await render(), /<button[^>]*disabled[^>]*>审核/)
  store.documentApprovalRecord.can_review=false;store.documentApprovalRecord.business_status='converted'
  assert.match(await render(), /已处理单据保留原业务记录/)

})
