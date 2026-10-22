import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { documentApprovalPolicyBody, validateDocumentApprovalPolicy, validateDocumentApprovalState, validateDocumentApprovalRecord } from '../src/shared/document-approval-api.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createDocumentApprovalActions } from '../src/renderer/src/store/modules/document-approval-actions.ts'

const steps = [{ name: '批准', role: null, action: 'approve' }]
const branch = (low = '25.00', high = null, name = '大额流程') => ({ name, min_amount: low, max_amount: high, steps })
const input = () => ({ document_type: 'PurchaseOrder', version: 1, steps, branches: [branch()] })

test('金额分支使用精确金额文本，邻接区间只有一个命中范围', () => {
  const row = input()
  row.branches = [branch('0.00', '25.00', '小额流程'), branch()]
  assert.deepEqual(documentApprovalPolicyBody(row).branches, row.branches)
  // 超过 JavaScript 安全整数后的分界仍按分精确比较，不使用浮点数抹掉尾分。
  row.branches = [branch('900719925474099.91', '900719925474099.92', '一分区间'),
    branch('900719925474099.92', null, '以上金额')]
  assert.equal(documentApprovalPolicyBody(row).branches.length, 2)
  assert.equal(documentApprovalPolicyBody({ ...input(), branches: [] }).branches.length, 0)
})

test('无效、重复、重叠与非金额单据的分支在 IPC 边界拒绝', () => {
  for (const branches of [null, {}, Array(6).fill(branch()), [branch('-1')], [branch('1e3')],
    [branch('25', '25')], [branch('NaN')], [branch('0.001')], [branch(25)],
    [branch('0', '25'), branch('24', null, '重叠')], [branch('0', '25'), branch('25')],
    [{ ...branch(), actor_id: 1 }], [{ ...branch(), steps: [] }], [branch('1000000000000000001')]]) {
    assert.throws(() => documentApprovalPolicyBody({ ...input(), branches }))
  }
  assert.throws(() => documentApprovalPolicyBody({ ...input(), document_type: 'WarehouseInbound' }))
})

test('服务端分支和命中证据须完整，未送审不能伪造分支', () => {
  const policy = { ...input(), title: '采购订单', amount_basis: '订单逐行金额合计', configured_by: null, configured_at: null }
  validateDocumentApprovalPolicy(policy)
  assert.throws(() => validateDocumentApprovalPolicy({ ...policy, branches: [branch('25', '20')] }))
  const state = { version: 1, status: 'submitted', generation: 1, current_step: 0, steps,
    policy_version: 2, submitted_by: 1, submitted_at: '2026-10-22 10:00:00', executed_by: null, executed_at: null,
    routing: { mode: 'amount', basis: '订单逐行金额合计', amount: '25.00', branch: { name: '大额流程', min_amount: '25.00', max_amount: null } } }
  validateDocumentApprovalState(state)
  for (const patch of [{ amount: '24.99' }, { amount: null }, { mode: 'unknown' }, { basis: '' },
    { branch: { ...state.routing.branch, max_amount: '25.00' } }]) {
    assert.throws(() => validateDocumentApprovalState({ ...state, routing: { ...state.routing, ...patch } }))
  }
  assert.throws(() => validateDocumentApprovalState({ ...state, status: 'draft' }))
  validateDocumentApprovalState({ ...state, routing: { ...state.routing, mode: 'reverse_default', amount: null, branch: null } })
  const record = { ...state, document_type:'PurchaseOrder', document_id:1, intent:'execute', document_no:'PO-1',
    business_status:'draft', reversal_reason:'', can_submit:false, can_review:true, can_withdraw:true,
    content_matches:true, summary:[], events:[{id:1,version:1,generation:1,action:'submit',step:0,step_name:null,
      actor_id:1,actor_name:'管理员',reason:'',created_at:state.submitted_at,routing:state.routing}] }
  validateDocumentApprovalRecord(record)
  assert.throws(() => validateDocumentApprovalRecord({ ...record, document_type:'WarehouseInbound' }))
  assert.throws(() => validateDocumentApprovalRecord({ ...record, intent:'reverse' }))
  assert.throws(() => validateDocumentApprovalRecord({ ...record, routing:undefined,
    events:[{...record.events[0], routing:{mode:'reverse_default',basis:'本单金额',amount:null,branch:null}}] }))
})

test('Pinia 金额分支草稿独立复制，冲突保留输入，重置后再按新版本保存', async t => {
  const previous = globalThis.window, scope = effectScope()
  let remote = { ...input(), title: '采购订单', amount_basis: '订单逐行金额合计', configured_by: null, configured_at: null }
  let conflict = true, write
  globalThis.window = { nexora: { callApi: async (operation, payload) => {
    if (operation === 'documentApprovalPolicies') return [remote]
    write = structuredClone(payload)
    if (conflict) { remote = { ...remote, version: 2 }; throw Error('审批内容已更新') }
    return remote = { ...remote, ...payload, version: payload.version + 1 }
  } } }
  t.after(() => { scope.stop(); globalThis.window = previous })
  const state = createAppState()
  state.user.value = { id: 1, roles: ['admin'], permissions: ['purchase.view'] }
  state.server.value = { id: 'routing-instance', fingerprint: 'routing-fingerprint' }
  const actions = scope.run(() => createDocumentApprovalActions(state))
  await actions.loadApprovalPolicies()
  actions.editApprovalPolicy('PurchaseOrder')
  const draft = state.approvalPolicyDrafts.value.PurchaseOrder
  draft.branches[0].steps[0].name = '财务复核'
  draft.branches[0].min_amount = '30.00'
  assert.equal(remote.branches[0].min_amount, '25.00')
  assert.equal(remote.branches[0].steps[0].name, '批准')
  assert.equal(await actions.saveApprovalPolicy('PurchaseOrder'), false)
  assert.equal(state.approvalPolicyDrafts.value.PurchaseOrder.branches[0].min_amount, '30.00')
  assert.equal(state.approvalPolicies.value[0].version, 2)
  actions.editApprovalPolicy('PurchaseOrder', true)
  conflict = false
  assert.equal(await actions.saveApprovalPolicy('PurchaseOrder'), true)
  assert.equal(write.version, 2)
  assert.equal(write.branches[0].min_amount, '25.00')
  assert.equal(state.approvalPolicyDrafts.value.PurchaseOrder.version, 3)
  state.approvalPolicyDrafts.value.PurchaseOrder.branches[0].steps[0].name = '独立草稿'
  assert.equal(state.approvalPolicies.value[0].branches[0].steps[0].name, '批准')
})
