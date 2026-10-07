import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createDocumentApprovalActions } from '../src/renderer/src/store/modules/document-approval-actions.ts'

const policy = { document_type: 'WarehouseInbound', title: '其他入库', version: 1,
  steps: [{ name: '批准', role: null }], configured_by: null, configured_at: null }
const copied = () => structuredClone(policy)
function environment(t, callApi) {
  const previous = globalThis.window
  globalThis.window = { nexora: { callApi } }
  const scope = effectScope()
  const state = createAppState()
  state.user.value = { id: 1, roles: ['admin'], permissions: ['other_inbound.view'] }
  state.server.value = { id: 'instance-a', fingerprint: 'a' }
  const actions = scope.run(() => createDocumentApprovalActions(state))
  t.after(() => { scope.stop(); globalThis.window = previous })
  return { state, actions }
}

test('审批模板草稿跨页面保留，成功保存只更新对应类型和版本', async t => {
  const requests = []
  const { state, actions } = environment(t, async (action, payload) => {
    requests.push([action, payload])
    if (action === 'documentApprovalPolicies') return [copied()]
    return { ...copied(), ...payload, version: 2, configured_by: 1, configured_at: '2026-10-07 10:00:00' }
  })
  assert.equal(await actions.loadApprovalPolicies(), true)
  assert.equal(actions.editApprovalPolicy('WarehouseInbound'), true)
  state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name = '独立审核'
  await actions.loadApprovalPolicies()
  actions.editApprovalPolicy('WarehouseInbound')
  assert.equal(state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name, '独立审核')
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), true)
  assert.equal(state.approvalPolicyDrafts.value.WarehouseInbound.version, 2)
  assert.deepEqual(requests.at(-1)[1], { document_type: 'WarehouseInbound', version: 1,
    steps: [{ name: '独立审核', role: null }] })
  assert.equal(state.busy.value, false)
})

test('保存冲突保留输入和原版本，显式重载后才替换草稿', async t => {
  let latest = copied()
  const { state, actions } = environment(t, async action => {
    if (action === 'documentApprovalPolicies') return [latest]
    latest = { ...copied(), version: 2, steps: [{ name: '其他管理员规则', role: 'admin' }] }
    throw Error('审批内容已更新')
  })
  await actions.loadApprovalPolicies(); actions.editApprovalPolicy('WarehouseInbound')
  state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name = '保留草稿'
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), false)
  assert.equal(state.approvalPolicyDrafts.value.WarehouseInbound.version, 1)
  assert.equal(state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name, '保留草稿')
  assert.equal(state.approvalPolicies.value[0].version, 2)
  assert.match(state.approvalPolicyError.value, /审批内容已更新/)
  assert.equal(actions.editApprovalPolicy('WarehouseInbound', true), true)
  assert.equal(state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name, '其他管理员规则')
})

test('旧实例响应与撤销权限后的保存响应不能污染当前会话', async t => {
  let finish
  const { state, actions } = environment(t, () => new Promise(resolve => { finish = resolve }))
  const loading = actions.loadApprovalPolicies()
  state.server.value = { id: 'instance-b', fingerprint: 'b' }
  finish([copied()])
  assert.equal(await loading, false)
  assert.deepEqual(state.approvalPolicies.value, [])
  state.approvalPolicies.value = [copied()]; actions.editApprovalPolicy('WarehouseInbound')
  const saving = actions.saveApprovalPolicy('WarehouseInbound')
  state.user.value.roles = ['viewer']
  finish({ ...copied(), version: 2 })
  assert.equal(await saving, false)
  assert.deepEqual(state.approvalPolicyDrafts.value, {})
  assert.deepEqual(state.approvalPolicies.value, [])
})

test('断线保留同实例草稿，忙碌、普通用户和非法步骤均阻止提交', async t => {
  let writes = 0
  const { state, actions } = environment(t, async action => {
    if (action !== 'documentApprovalPolicies') writes++
    return [copied()]
  })
  await actions.loadApprovalPolicies(); actions.editApprovalPolicy('WarehouseInbound')
  state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name = '保留输入'
  state.connectionLost.value = true
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), false)
  assert.equal(state.approvalPolicyDrafts.value.WarehouseInbound.steps[0].name, '保留输入')
  state.connectionLost.value = false
  state.busy.value = true
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), false)
  state.busy.value = false
  state.approvalPolicyDrafts.value.WarehouseInbound.steps = []
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), false)
  assert.match(state.approvalPolicyError.value, /一至五步/)
  state.user.value.roles = ['viewer']
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), false)
  assert.equal(writes, 0)
})

test('迟到的列表响应不能覆盖已保存的新规则', async t => {
  let finishRead
  const { state, actions } = environment(t, async (action, payload) => {
    if (action === 'documentApprovalPolicies') return new Promise(resolve => { finishRead = resolve })
    return { ...copied(), ...payload, version: 2 }
  })
  state.approvalPolicies.value = [copied()]; actions.editApprovalPolicy('WarehouseInbound')
  const read = actions.loadApprovalPolicies()
  assert.equal(await actions.saveApprovalPolicy('WarehouseInbound'), true)
  finishRead([copied()])
  assert.equal(await read, false)
  assert.equal(state.approvalPolicies.value[0].version, 2)
})
