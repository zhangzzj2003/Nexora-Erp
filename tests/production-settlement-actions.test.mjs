import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { createProductionActions } from '../src/renderer/src/store/modules/production-actions.ts'

// 真实会话、队列归属与固定冲销审批保证旧弹窗不能在切服后继续写入。
function environment(t, callApi, perform) {
  const original = globalThis.window
  t.after(() => {globalThis.window = original})
  globalThis.window = {nexora: {callApi}}
  const state = {
    productionSettlementForm: ref({work_order_id: 7, reference: 'COST-7', note: '成本复核'}),
    settlementReversalReasons: ref({1: '旧输入'}), connectionLost: ref(false),
    server: ref({id: 'first', fingerprint: 'a'}),
    user: ref({id: 1, roles: ['finance'], permissions: ['production_cost.settle', 'production_cost.reopen']})
  }
  const feedback = []
  const actions = createProductionActions(state, perform ?? (async (action, success) => {
    try {await action(); feedback.push(success)} catch { /* 失败保留原草稿。 */ }
  }), () => {})
  return {state, actions, feedback}
}
const approved = () => ({document_type: 'ProductionCostSettlement', document_id: 1, intent: 'reverse',
  document_no: 'PCS-20261007-000001', business_status: 'active', reversal_reason: '固定单价更正',
  status: 'approved', version: 2, generation: 1, current_step: 1, steps: [{name: '批准', role: null}],
  policy_version: 1, submitted_by: 1, submitted_at: '2026-10-07T00:00:00Z', executed_by: null, executed_at: null,
  content_matches: true, can_submit: false, can_review: false, can_withdraw: true, summary: [],
  events: ['submit', 'approve'].map((action, index) => ({id: index+1, version: index+1, generation: 1,
    action, step: index, step_name: '批准', actor_id: index+1, actor_name: '审批人', reason: '核对', created_at: '2026-10-07T00:00:00Z'}))})

test('预计草稿失败保留，批准冲销使用固定原因并保留失败输入', async t => {
  const calls = []; let fail = true
  const {state, actions, feedback} = environment(t, async (operation, payload) => {
    calls.push([operation, structuredClone(payload)])
    if (operation === 'documentApproval') return approved()
    if (fail) throw Error('来源已变化')
    return {id: 1}
  })
  await actions.settleProductionCost()
  assert.equal(state.productionSettlementForm.value.reference, 'COST-7')
  await actions.reverseProductionSettlement(1)
  assert.deepEqual(calls[2], ['reverseProductionSettlement', {settlementId: 1, reason: '固定单价更正'}])
  assert.equal(state.settlementReversalReasons.value[1], '旧输入')
  assert.deepEqual(feedback, [])
  fail = false
  await actions.settleProductionCost()
  assert.deepEqual(state.productionSettlementForm.value, {work_order_id: 0, reference: '', note: ''})
  await actions.reverseProductionSettlement(1)
  assert.equal(state.settlementReversalReasons.value[1], undefined)
  assert.equal(feedback.length, 2)
})

test('结算排队后换账号或权限撤销不能发送旧执行请求', async t => {
  let queued; let calls = 0
  const {state, actions} = environment(t, async () => {calls++}, async action => {queued = action})
  await actions.changeProductionSettlementStatus({id: 1, version: 1, status: 'draft', approval: {status: 'approved'}}, 'post', '核对')
  state.user.value.id = 2
  await assert.rejects(queued(), /会话或授权/)
  assert.equal(calls, 0)
})

test('冲销审批读取期间切服或正文不匹配时不能执行', async t => {
  let resolve; const calls = []
  const {state, actions} = environment(t, async operation => {
    calls.push(operation)
    if (operation === 'documentApproval') return new Promise(finish => {resolve = finish})
  })
  const pending = actions.reverseProductionSettlement(1)
  state.server.value.id = 'second'; resolve(approved()); await pending
  assert.deepEqual(calls, ['documentApproval'])
  calls.length = 0
  globalThis.window.nexora.callApi = async operation => {calls.push(operation); return {...approved(), content_matches: false}}
  await actions.reverseProductionSettlement(1)
  assert.deepEqual(calls, ['documentApproval'])
})

test('整批不合格完工确认不提示成品已入库', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const calls = []
  globalThis.window = { nexora: { async callApi(operation, payload) {
    calls.push([operation, payload])
    return {id: 9}
  } } }
  const feedback = []
  const actions = createProductionActions({}, async (action, success) => {
    await action()
    feedback.push(success)
  }, () => {})
  await actions.postProductionCompletion(9)
  assert.deepEqual(calls, [['postProductionCompletion', {completionId: 9}]])
  assert.deepEqual(feedback, ['完工单 #9 已确认。'])
})
