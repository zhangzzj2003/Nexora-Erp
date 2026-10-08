import assert from 'node:assert/strict'
import { test } from 'node:test'
import { documentApprovalProgress } from '../src/renderer/src/utils/document-approval-progress.ts'

// 验证真实审批状态投影；进度图不写回状态，也不把批准误认为业务执行。
function record(overrides = {}) {
  return { document_type: 'WarehouseInbound', intent: 'execute', version: 1, generation: 1,
    business_status: 'draft', status: 'submitted', current_step: 0, can_submit: false,
    steps: [{ name: '审核', role: 'warehouse' }, { name: '核准', role: null }, { name: '批准', role: null }],
    events: [], ...overrides }
}
test('单步及多步流程保留送审和业务执行，只有当前步骤高亮', () => {
  const single = documentApprovalProgress(record({ steps: [{ name: '批准', role: null }] }))
  assert.deepEqual(single.nodes.map(node => [node.name, node.state]), [['送审', 'completed'], ['批准', 'current'], ['业务执行', 'pending']])
  const source = record({ current_step: 1 })
  const before = structuredClone(source)
  const progress = documentApprovalProgress(source)
  assert.deepEqual(progress.nodes.map(node => node.state), ['completed', 'completed', 'current', 'pending', 'pending'])
  assert.equal(progress.summary, '当前待办：核准')
  assert.equal(progress.completed, 1)
  assert.equal(progress.nodes[1].role, 'warehouse')
  assert.deepEqual(source, before)
  // 最大五步加上送审/执行仍只有一个当前节点，不按完成率猜测未来步骤。
  const five = documentApprovalProgress(record({ current_step: 2,
    steps: ['审核', '核准', '财务核对', '负责人复核', '批准'].map(name => ({ name, role: null })) }))
  assert.equal(five.nodes.length, 7)
  assert.equal(five.nodes.filter(node => node.state === 'current').length, 1)
  assert.equal(five.nodes[3].name, '财务核对')
})
test('批准后执行仍是待办，真实执行后才显示完成', () => {
  const approved = documentApprovalProgress(record({ status: 'approved', current_step: 3 }))
  assert.equal(approved.label, '已批准，待执行')
  assert.equal(approved.nodes.at(-1).state, 'current')
  assert.equal(approved.nodes.at(-1).caption, '待执行')
  const executed = documentApprovalProgress(record({ status: 'executed', current_step: 3 }))
  assert.ok(executed.nodes.every(node => node.state === 'completed'))
  assert.equal(executed.nodes.at(-1).caption, '已执行')
})
test('驳回定位失败步骤，撤回保留完成事实但中止后续办理', () => {
  for (const status of ['rejected', 'withdrawn']) {
    const progress = documentApprovalProgress(record({ status, current_step: 1 }))
    assert.equal(progress.nodes[1].state, 'completed')
    assert.equal(progress.nodes[2].state, status)
    assert.equal(progress.nodes[3].caption, '已中止')
    assert.equal(progress.nodes.at(-1).caption, '已中止')
    assert.ok(!progress.nodes.some(node => node.state === 'current'))
  }
  const withdrawnAfterApproval = documentApprovalProgress(record({ status: 'withdrawn', current_step: 3 }))
  assert.equal(withdrawnAfterApproval.nodes.at(-1).state, 'withdrawn')
  assert.equal(withdrawnAfterApproval.nodes.at(-1).caption, '已中止')
})
test('本轮节点关联真实人员与时间，重新送审不借用上一轮记录', () => {
  const old = { id: 1, generation: 1, action: 'approve', step: 0, actor_name: '旧审核人' }
  const submit = { id: 2, generation: 2, action: 'submit', step: 0, actor_name: '新送审人', created_at: '2026-10-08T01:00:00Z' }
  const approve = { id: 3, generation: 2, action: 'approve', step: 0, actor_name: '本轮审核人', created_at: '2026-10-08T02:00:00Z' }
  const progress = documentApprovalProgress(record({ generation: 2, current_step: 1, events: [old, submit, approve] }))
  assert.equal(progress.nodes[0].event, submit)
  assert.equal(progress.nodes[1].event, approve)
  assert.equal(progress.nodes[2].event, undefined)
  const resubmitted = documentApprovalProgress(record({ generation: 2, events: [old, submit] }))
  assert.equal(resubmitted.nodes[1].event, undefined)
  assert.equal(resubmitted.nodes[1].state, 'current')
})
test('草稿明确未固定步骤，旧业务记录及旧转完申请不补造审批', () => {
  const draft = documentApprovalProgress(record({ status: 'draft', version: 0, generation: 0, steps: [] }))
  assert.equal(draft.nodes[0].caption, '待送审')
  assert.equal(draft.nodes[1].caption, '送审后确定步骤')
  for (const business_status of ['posted', 'released', 'completed', 'cancelled']) {
    const historical = documentApprovalProgress(record({ version: 0, business_status, steps: [] }))
    assert.deepEqual(historical.nodes, [])
    assert.equal(historical.label, '历史业务记录')
    assert.match(historical.summary, /不补造审批记录/)
  }
  const converted = documentApprovalProgress(record({ document_type: 'PurchaseRequest', version: 0, business_status: 'approved', steps: [] }))
  assert.deepEqual(converted.nodes, [])
  assert.match(converted.summary, /申请已无待转数量/)
  // 冲销意图另行申请，不能因原业务已经执行而隐藏新的审批流程。
  assert.ok(documentApprovalProgress(record({ intent: 'reverse', version: 0, business_status: 'posted', status: 'draft', steps: [] })).nodes.length)
})
