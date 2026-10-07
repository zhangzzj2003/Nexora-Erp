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
