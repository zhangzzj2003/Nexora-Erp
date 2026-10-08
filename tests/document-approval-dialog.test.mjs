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
      documentApprovalReasons:ref({}),documentApprovalEvidence:ref({}),busy:ref(false),connectionLost:ref(false),roles:ref([{code:'admin',label:'管理员'}]),
      localTime:value=>value,closeDocumentApproval(){calls.push('close')},loadDocumentApproval(){calls.push('refresh')},
      actDocumentApproval(action){calls.push(action)}
    }));`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'approval-dialog-fixture', enforce: 'pre',
    transform(code, id) {
      if (id.endsWith('/WorkspaceDocumentDialog.vue')) return code.replace("'naive-ui'", "'virtual:approval-dialog-modal'")
    }, resolveId(id, importer) {
      if (id === 'virtual:approval-dialog-modal') return '\0approval-dialog-modal'
      if (importer?.includes('DocumentApprovalDialog') && id.endsWith('/store/app-store')) return '\0approval-dialog-store'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0approval-dialog-table'
      if (id === 'naive-ui' && importer?.includes('WorkspaceDocumentDialog')) return '\0approval-dialog-modal'
      for (const name of ['AppButton.vue', 'AppInput.vue']) if (id.endsWith('/' + name)) return '\0approval-dialog-' + name
    }, load(id) {
      if (id === '\0approval-dialog-store') return fixture
      if (id === '\0approval-dialog-modal') return `import {defineComponent,h} from 'vue';export const captured={};export const NModal=defineComponent({props:['show','title','maskClosable','closeOnEsc','closable'],setup(p,{slots,attrs}){Object.assign(captured,{props:p,attrs,slots});return()=>p.show?h('section',{...attrs,'data-title':p.title},slots.default?.()):null}})`
      // 表格仅替换绘制，列数据与行插槽仍经过真实公共单据组件。
      if (id === '\0approval-dialog-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns','emptyText'],setup(p,{slots}){return()=>h('section',{'data-table':true},[slots.heading?.(),...p.data.map(row=>h('article',p.columns.map(c=>slots['cell-'+c.key]?.({row})))),p.data.length?null:h('p',p.emptyText)])}})`
      if (id === '\0approval-dialog-AppButton.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if (id === '\0approval-dialog-AppInput.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore } = await server.ssrLoadModule('\0approval-dialog-store')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const { default: Dialog } = await server.ssrLoadModule('/src/renderer/src/components/workspace/DocumentApprovalDialog.vue')
  const render = () => renderToString(createSSRApp({ render: () => h(Dialog) }).use(pinia))
  store.documentApprovalRecord = { document_type: 'WarehouseInbound', document_no: 'QTRK-20261007-000001', intent: 'execute', business_status: 'draft',
    summary: [{label:'仓库',value:'主仓库'},{label:'用途',value:'赠品'},{label:'入库说明',value:'完整说明'.repeat(40)},
      {label:'参考号',value:'REF-1'},{label:'入库明细',value:'电阻 × 100 个'}], content_matches: true,
    version: 1, generation: 1, status: 'submitted', current_step: 0, steps: [{ name: '审核', role: 'admin' }, { name: '批准', role: null }],
    can_submit: false, can_review: false, can_withdraw: true, reversal_reason: '', events: [] }
  let html = await render()
  assert.match(html, /由有审核权限的人员处理/); assert.doesNotMatch(html, /不能自审|指定角色/); assert.match(html, /同一人员可完成多个已授权步骤/)
  assert.match(html, /审批中/)
  assert.match(html, /电阻 × 100 个/)
  assert.match(html, /撤回审批/)
  assert.doesNotMatch(html, /<button[^>]*>驳回<|<button[^>]*>审核<|审批意见（/)
  assert.match(html, /workspace-document-dialog/)
  assert.match(html, /document-basic--readonly/)
  assert.match(html, /min\(1280px/)
  assert.ok(html.indexOf('主仓库') < html.indexOf('物料明细'))
  // 顶部流程与节点记录先于正文；底部保留意见，避免两处重复记录。
  assert.ok(html.indexOf('审批进度') < html.indexOf('主仓库'))
  assert.ok(html.indexOf('审批记录') < html.indexOf('主仓库'))
  assert.doesNotMatch(html, /class="approval-history"/)
  assert.match(html, /aria-current="step"/)
  assert.match(html, /当前待办：审核/)
  // 图形节点保持有序语义与键盘可滚动入口，状态不再退化为纯数字列表。
  assert.match(html, /aria-label="审批流程（可左右滚动）"/)
  assert.equal((html.match(/class="approval-stage-icon"/g) ?? []).length, 4)
  assert.ok(html.indexOf('审批记录') < html.indexOf('document-footer'))
  assert.doesNotMatch(html, /保存草稿|添加物料|type="submit"/)
  // 忙碌状态禁止关闭；断线仍可收起，而审批按钮保持禁用。
  const { captured } = await server.ssrLoadModule('\0approval-dialog-modal')
  const { calls } = await server.ssrLoadModule('\0approval-dialog-store')
  store.busy = true
  await render()
  assert.equal(captured.props.closable, false)
  captured.attrs['onUpdate:show'](false)
  assert.deepEqual(calls, [])
  store.busy = false
  store.connectionLost = true
  await render()
  captured.attrs['onUpdate:show'](false)
  assert.deepEqual(calls, ['close'])
  store.connectionLost = false
  // 刷新失败保留原送审摘要，加载和错误提示在固定页脚之前显示。
  store.documentApprovalLoading = true
  store.documentApprovalError = '读取失败，请重试'
  html = await render()
  assert.match(html, /role="status"[^>]*>正在读取审批记录/)
  assert.match(html, /role="alert"[^>]*>读取失败/)
  assert.match(html, /电阻 × 100 个/)
  assert.match(html, /<button[^>]*disabled[^>]*>刷新记录/)
  store.documentApprovalLoading = false
  store.documentApprovalError = ''
  store.documentApprovalRecord.can_review = true
  html = await render()
  assert.match(html, /<button[^>]*disabled[^>]*>驳回/)
  assert.match(html, /<button[^>]*>审核/)
  // 自定义名称不替代动作名称，核准按钮仍按服务端 action 呈现。
  store.documentApprovalRecord.steps[0] = {name:'负责人确认',role:null,action:'verify'}
  assert.match(await render(), /<button[^>]*>核准/)
  store.documentApprovalRecord.steps[0] = {name:'审核',role:null,action:'review'}
  store.documentApprovalReasons['WarehouseInbound:1:execute'] = '数量需核对'
  html = await render()
  assert.doesNotMatch(html, /<button[^>]*disabled[^>]*>驳回/)
  store.documentApprovalRecord = { ...store.documentApprovalRecord, status: 'approved', current_step: 2, can_review: false,
    events: [{ id: 1, generation: 1, action: 'approve', step: 0, step_name: '审核', actor_name: '独立审核人', created_at: '2026-10-07', reason: '核对明细' }] }
  html = await render()
  assert.match(html, /已批准，待执行/)
  assert.match(html, /查看最近记录 · 审核/)
  assert.match(html, /等待业务执行，尚无处理记录/)
  assert.doesNotMatch(html, /核对明细/)
  assert.doesNotMatch(html, /<button[^>]*>批准<|<button[^>]*>执行<|<button[^>]*>确认入库</)
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

  // 售后意见沿用原二百字约束，已收件的旧单据不补造新批准。
  store.documentApprovalTarget={document_type:'AfterSalesCase',document_id:1,intent:'execute'}
  store.documentApprovalRecord={...store.documentApprovalRecord,document_type:'AfterSalesCase',
    business_status:'draft',version:0,can_submit:true,can_review:false}
  html=await render()
  assert.match(html,/售后操作依据（必填）/)
  assert.match(html,/maxlength="200"/)
  assert.match(html,/<button[^>]*disabled[^>]*>提交审批/)
  store.documentApprovalRecord={...store.documentApprovalRecord,business_status:'received',can_submit:false}
  html=await render()
  assert.match(html,/已处理单据保留原业务记录/)

  // 处置仍要求原二百字原因，统一入口不能放宽审核依据。
  store.documentApprovalTarget={document_type:'QualityDisposition',document_id:1,intent:'execute'}
  store.documentApprovalRecord={...store.documentApprovalRecord,document_type:'QualityDisposition',business_status:'draft',can_submit:true}
  html=await render();assert.match(html,/处置操作依据（必填）/);assert.match(html,/maxlength="200"/)
  assert.match(html,/<button[^>]*disabled[^>]*>提交审批/)

  // 计划沿用五百字必填依据，不能以空意见完成送审或审核。
  store.documentApprovalTarget={document_type:'MrpPlan',document_id:1,intent:'execute'}
  store.documentApprovalRecord={...store.documentApprovalRecord,document_type:'MrpPlan',business_status:'draft',can_submit:true}
  html=await render();assert.match(html,/计划操作依据（必填）/);assert.match(html,/maxlength="500"/)
  assert.match(html,/<button[^>]*disabled[^>]*>提交审批/)

  // 维护两项原始依据分别必填，不能只有操作意见就送审。
  store.documentApprovalTarget={document_type:'MaintenanceJob',document_id:1,intent:'execute'}
  store.documentApprovalRecord={...store.documentApprovalRecord,document_type:'MaintenanceJob',business_status:'draft',can_submit:true}
  store.documentApprovalReasons['MaintenanceJob:1:execute']='核对维护方案'
  html=await render();assert.match(html,/现场依据（必填）/);assert.match(html,/maxlength="600"/)
  assert.match(html,/<button[^>]*disabled[^>]*>提交审批/)
  store.documentApprovalEvidence['MaintenanceJob:1:execute']='现场独立依据'
  assert.doesNotMatch(await render(),/<button[^>]*disabled[^>]*>提交审批/)
  store.documentApprovalRecord.generation=1
  store.documentApprovalRecord.events=[{id:1,step:0,action:'submit',actor_name:'编制人',generation:1,created_at:'2026-10-07',reason:'方案意见',evidence:'现场独立依据'}]
  assert.match(await render(),/现场依据：现场独立依据/)

  // 凭证保留原二百字必填依据，统一弹窗不能显示原五百字默认限制。
  store.documentApprovalTarget={document_type:'Journal',document_id:1,intent:'execute'}
  store.documentApprovalRecord={...store.documentApprovalRecord,document_type:'Journal',status:'draft',can_submit:true,can_review:false}
  store.documentApprovalReasons={}
  html=await render();assert.match(html,/凭证操作依据（必填）/);assert.match(html,/maxlength="200"/)
  assert.match(html,/<button[^>]*disabled[^>]*>提交审批/)
  // 非物料审批不展示空物料表，未知摘要完整保留在基础信息中。
  assert.doesNotMatch(html.replace(/<!--[\s\S]*?-->/g, ''), /data-table|物料明细|此单据暂无物料明细/)
  assert.match(html, /电阻 × 100 个/)

  // 历史原单核销在送审时即要求二百字内依据，空输入不能触发请求。
  store.documentApprovalTarget={document_type:'SubledgerSettlement',document_id:1,intent:'execute'}
  store.documentApprovalRecord={...store.documentApprovalRecord,document_type:'SubledgerSettlement',status:'draft',can_submit:true,can_review:false}
  store.documentApprovalReasons={}
  html=await render();assert.match(html,/核销操作依据（必填）/);assert.match(html,/maxlength="200"/)
  assert.match(html,/<button[^>]*disabled[^>]*>提交审批/)
  store.documentApprovalReasons['SubledgerSettlement:1:execute']='原单核对依据'
  assert.doesNotMatch(await render(),/<button[^>]*disabled[^>]*>提交审批/)
})
