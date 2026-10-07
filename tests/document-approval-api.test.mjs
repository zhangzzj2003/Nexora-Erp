import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  documentApprovalTypes, documentApprovalType, documentApprovalPolicyBody,
  validateDocumentApprovalPolicy, validateDocumentApprovalPolicies
} from '../src/shared/document-approval-api.ts'

// 固定类型阻止路径注入，前后端目录保持同一个真实范围。
test('审批类型覆盖全部 29 类，并拒绝未知类型和路径注入', () => {
  assert.equal(new Set(documentApprovalTypes).size, 29)
  const backend = readFileSync(new URL('../backend/app/core/document_types.py', import.meta.url), 'utf8')
  for (const name of documentApprovalTypes) {
    assert.ok(backend.includes(`('${name}',`))
    assert.equal(documentApprovalType({ document_type: name }), name)
  }
  for (const name of ['users', '../users', 'WarehouseInbound/approve', '', null, ['WarehouseInbound']]) {
    assert.throws(() => documentApprovalType({ document_type: name }))
  }
})

test('模板提交保留版本并校验步骤，拒绝客户端附带审批结果', () => {
  const valid = { document_type: 'WarehouseInbound', version: 2, steps: [
    { name: ' 审核 ', role: 'warehouse' }, { name: '批准', role: null }
  ] }
  assert.deepEqual(documentApprovalPolicyBody(valid), { version: 2, steps: [
    { name: '审核', role: 'warehouse' }, { name: '批准', role: null }
  ] })
  for (const bad of [
    { version: true }, { version: '2' }, { version: 0 }, { status: 'approved' },
    { steps: [] }, { steps: Array(6).fill({ name: '批准', role: null }) },
    { steps: [{ name: ' ', role: null }] }, { steps: [{ name: '批准', role: '../admin' }] },
    { steps: [{ name: '批准', role: ['admin'] }] }, { steps: [{ name: '批准', role: null, actor_id: 1 }] }
  ]) assert.throws(() => documentApprovalPolicyBody({ ...valid, ...bad }))
})

test('审批模板响应拒绝无效配置，并允许按权限裁剪后的列表', () => {
  const policy = { document_type: 'WarehouseInbound', title: '其他入库', version: 1,
    steps: [{ name: '批准', role: null }], configured_by: null, configured_at: null }
  validateDocumentApprovalPolicy(policy)
  validateDocumentApprovalPolicies([policy])
  validateDocumentApprovalPolicies([])
  for (const bad of [{ version: -1 }, { title: '' }, { configured_by: 0 },
    { configured_by: 1 }, { configured_at: 'invalid' }, { steps: [] }, { document_type: 'Unknown' }]) {
    assert.throws(() => validateDocumentApprovalPolicy({ ...policy, ...bad }))
  }
  assert.throws(() => validateDocumentApprovalPolicies([policy, policy]))
  assert.throws(() => validateDocumentApprovalPolicies({ rows: [policy] }))
})

const caseApi = await import('../src/shared/document-approval-api.ts')
const draft = () => ({ document_type: 'WarehouseInbound', document_id: 1, intent: 'execute',
  document_no: 'QTRK-20261007-000001', business_status: 'draft', reversal_reason: '', summary: [], content_matches: true,
  version: 0, status: 'draft', generation: 0, current_step: 0, steps: [], policy_version: null,
  submitted_by: null, submitted_at: null, executed_by: null, executed_at: null,
  can_submit: true, can_review: false, can_withdraw: false, events: [] })

test('单据审批动作禁止路径、意图、结果或快照注入，并保留读取到的版本', () => {
  const input = { document_type: 'WarehouseInbound', document_id: 1, intent: 'execute',
    action: 'submit', version: 0, reason: ' 说明 ' }
  assert.deepEqual(caseApi.documentApprovalActionBody(input), { version: 0, intent: 'execute', reason: '说明' })
  for (const bad of [{ document_id: true }, { document_id: '1' }, { document_id: 0 },
    { intent: '../reverse' }, { action: 'execute' }, { version: true }, { version: -1 },
    { status: 'approved' }, { snapshot: {} }, { action: 'reject', reason: ' ' }]) {
    assert.throws(() => caseApi.documentApprovalActionBody({ ...input, ...bad }))
  }
})

test('单据审批响应校验实际进度和完整历史，不能凭伪造状态开放操作', () => {
  caseApi.validateDocumentApprovalRecord(draft())
  const sent = { ...draft(), can_submit: false, version: 1, status: 'submitted', generation: 1, policy_version: 1,
    steps: [{ name: '批准', role: null }], submitted_by: 1, submitted_at: '2026-10-07 12:00:00',
    events: [{ id: 1, version: 1, generation: 1, action: 'submit', step: 0, step_name: null, actor_id: 1,
      actor_name: '建单员', reason: '', created_at: '2026-10-07 12:00:00' }] }
  caseApi.validateDocumentApprovalRecord(sent)
  for (const bad of [{ current_step: 1 }, { submitted_by: null }, { executed_by: 1 },
    { events: [] }, { events: [{ ...sent.events[0], version: 2 }] }, { can_review: 'yes' },
    { business_status: null }, { intent: 'unknown' }]) {
    assert.throws(() => caseApi.validateDocumentApprovalRecord({ ...sent, ...bad }))
  }
  const approved = { ...sent, status: 'approved', current_step: 1, version: 2,
    events: [...sent.events, { ...sent.events[0], id: 2, version: 2, action: 'approve', actor_id: 2, actor_name: '审核员' }] }
  caseApi.validateDocumentApprovalRecord(approved)
  assert.throws(() => caseApi.validateDocumentApprovalRecord({ ...approved, status: 'executed' }))
})
