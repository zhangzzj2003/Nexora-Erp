import assert from 'node:assert/strict'
import { test } from 'node:test'
import { documentApprovalDefaultNode, documentApprovalGenerations, documentApprovalRound } from '../src/renderer/src/utils/document-approval-progress.ts'

// 模板更名和重新送审是主要历史风险；旧人员、意见、依据只能归到实际轮次与节点。
const event = (id, generation, action, step, step_name = null) => ({ id, version: id, generation, action, step,
  step_name, actor_id: id, actor_name: `人员${id}`, reason: `意见${id}`, evidence: `依据${id}`, created_at: '2026-10-08T07:00:00Z' })
const source = () => ({ document_type: 'WarehouseInbound', document_id: 1, intent: 'execute', version: 7,
  generation: 2, business_status: 'draft', status: 'submitted', current_step: 1, can_submit: false,
  steps: [{name: '新审核', role: null}, {name: '新批准', role: null}],
  events: [event(1, 1, 'submit', 0), event(2, 1, 'approve', 0, '旧审核'), event(3, 1, 'withdraw', 1),
    event(4, 2, 'submit', 0), event(5, 2, 'approve', 0, '新审核')] })

test('本轮记录与节点一一归档，历史轮次不借用新模板和新人员', () => {
  const record = source(), before = structuredClone(record)
  assert.deepEqual(documentApprovalGenerations(record), [2, 1])
  const current = documentApprovalRound(record, 2)
  assert.equal(documentApprovalDefaultNode(current), 'step-1')
  assert.deepEqual(current.nodes[1].events.map(row => row.id), [5])
  assert.deepEqual(current.nodes[2].events, [])
  const old = documentApprovalRound(record, 1)
  assert.equal(old.isCurrent, false)
  assert.equal(old.label, '已撤回')
  assert.deepEqual(old.nodes.map(node => node.name), ['送审', '旧审核', '撤回'])
  assert.equal(documentApprovalDefaultNode(old), 'withdraw')
  assert.deepEqual(old.nodes.flatMap(node => node.events).map(row => row.id), [1, 2, 3])
  assert.equal(old.nodes[1].events[0].evidence, '依据2')
  assert.ok(old.nodes.every(node => node.state !== 'current'))
  assert.deepEqual(record, before)
})
test('旧驳回保留当时步骤名，草稿和旧已执行记录不补造历史', () => {
  const record = source()
  record.events[2] = event(3, 1, 'reject', 1, '旧财务核准')
  const old = documentApprovalRound(record, 1)
  assert.equal(old.label, '已驳回')
  assert.equal(old.nodes.at(-1).name, '旧财务核准')
  assert.equal(documentApprovalDefaultNode(old), 'step-1')
  const draft = {...record, version: 0, generation: 0, current_step: 0, status: 'draft', steps: [], events: []}
  assert.deepEqual(documentApprovalGenerations(draft), [0])
  assert.equal(documentApprovalDefaultNode(documentApprovalRound(draft, 0)), 'submit')
  assert.deepEqual(documentApprovalRound({...draft, business_status: 'posted'}, 0).nodes, [])
})
test('批准后撤回与真实执行分别关联执行节点，所有事件和原意见完整保留', () => {
  for (const action of ['withdraw', 'execute']) {
    const record = source()
    record.status = action === 'withdraw' ? 'withdrawn' : 'executed'
    record.current_step = 2
    record.events.push(event(6, 2, 'approve', 1, '新批准'), event(7, 2, action, 2))
    const round = documentApprovalRound(record, 2)
    assert.equal(documentApprovalDefaultNode(round), 'execute')
    assert.equal(round.nodes.at(-1).events[0].action, action)
    assert.deepEqual(round.nodes.flatMap(node => node.events).map(row => row.id), [4, 5, 6, 7])
  }
})
