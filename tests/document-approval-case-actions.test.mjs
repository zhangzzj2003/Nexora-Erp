import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { approvalTargetKey, createDocumentApprovalCaseActions } from '../src/renderer/src/store/modules/document-approval-case-actions.ts'

const target = { document_type: 'WarehouseInbound', document_id: 1, intent: 'execute' }
const draft = () => ({ ...target, document_no: 'QTRK-20261007-000001', business_status: 'draft', reversal_reason: '', summary: [], content_matches: true,
  version: 0, status: 'draft', generation: 0, current_step: 0, steps: [], policy_version: null,
  submitted_by: null, submitted_at: null, executed_by: null, executed_at: null,
  can_submit: true, can_review: false, can_withdraw: false, events: [] })
function environment(t, callApi, refresh = async () => {}) {
  const previous = globalThis.window
  globalThis.window = { nexora: { callApi } }
  const scope = effectScope(), state = createAppState()
  state.user.value = { id: 1, roles: ['admin'], permissions: ['other_inbound.view'] }
  state.server.value = { id: 'instance-a', fingerprint: 'a' }
  const actions = scope.run(() => createDocumentApprovalCaseActions(state, refresh))
  t.after(() => { scope.stop(); globalThis.window = previous })
  return { state, actions }
}

test('审批只允许服务端返回的可用动作，送审使用读取版本，不能直接执行', async t => {
  let refreshes = 0
  const requests = []
  const { state, actions } = environment(t, async (action, input) => {
    requests.push([action, input])
    if (action === 'documentApproval') return draft()
    return { ...draft(), version: 1, status: 'submitted', generation: 1, policy_version: 1,
      steps: [{ name: '批准', role: null }], submitted_by: 1, submitted_at: '2026-10-07 12:00:00',
      can_submit: false, can_withdraw: true,
      events: [{ id: 1, version: 1, generation: 1, action: 'submit', step: 0, step_name: null, actor_id: 1,
        actor_name: '建单员', reason: '', created_at: '2026-10-07 12:00:00' }] }
  }, async () => { refreshes++ })
  assert.equal(await actions.openDocumentApproval(target), true)
  assert.equal(await actions.actDocumentApproval('approve'), false)
  state.documentApprovalReasons.value[approvalTargetKey(target)] = '提交说明'
  assert.equal(await actions.actDocumentApproval('submit'), true)
  assert.equal(refreshes, 1)
  assert.deepEqual(requests.at(-1), ['actDocumentApproval', { ...target, action: 'submit', version: 0, reason: '提交说明' }])
  assert.equal(state.documentApprovalRecord.value.status, 'submitted')
  assert.equal(state.documentApprovalReasons.value[approvalTargetKey(target)], undefined)
  assert.equal(state.busy.value, false)
})

test('审批失败刷新服务端版本并保留意见，断线后没有旧批准权限', async t => {
  const { state, actions } = environment(t, async action => {
    if (action === 'actDocumentApproval') throw Error('审批内容已更新')
    return draft()
  })
  await actions.openDocumentApproval(target)
  const key = approvalTargetKey(target)
  state.documentApprovalReasons.value[key] = '保留失败意见'
  assert.equal(await actions.actDocumentApproval('submit'), false)
  assert.equal(state.documentApprovalReasons.value[key], '保留失败意见')
  assert.match(state.documentApprovalError.value, /已更新/)
  state.connectionLost.value = true
  assert.equal(state.documentApprovalRecord.value, null)
  assert.equal(state.documentApprovalReasons.value[key], '保留失败意见')
  assert.equal(await actions.actDocumentApproval('submit'), false)
})

test('切换单据、实例或账号后迟到的审批响应不能恢复旧弹窗', async t => {
  let finish
  const { state, actions } = environment(t, () => new Promise(resolve => { finish = resolve }))
  const loading = actions.openDocumentApproval(target)
  actions.closeDocumentApproval(); finish(draft())
  assert.equal(await loading, false)
  assert.equal(state.documentApprovalRecord.value, null)
  const loadingAgain = actions.openDocumentApproval(target)
  state.server.value = { id: 'instance-b', fingerprint: 'b' }; finish(draft())
  assert.equal(await loadingAgain, false)
  assert.equal(state.documentApprovalTarget.value, null)
  state.documentApprovalReasons.value[approvalTargetKey(target)] = '旧账号草稿'
  state.user.value.id = 2
  assert.deepEqual(state.documentApprovalReasons.value, {})
})

test('错误单据和不完整审批历史被拒绝，忙碌时不能关闭或重复送审', async t => {
  const { state, actions } = environment(t, async () => ({ ...draft(), document_id: 2 }))
  assert.equal(await actions.openDocumentApproval(target), false)
  assert.match(state.documentApprovalError.value, /不一致/)
  state.busy.value = true
  assert.equal(await actions.openDocumentApproval({ ...target, document_id: 3 }), false)
  actions.closeDocumentApproval()
  assert.equal(state.documentApprovalTarget.value.document_id, 1)
  assert.equal(await actions.actDocumentApproval('submit'), false)
})
