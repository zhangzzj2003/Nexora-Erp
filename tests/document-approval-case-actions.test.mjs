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
  assert.equal(refreshes, 2)
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

// 读审批记录同时读领域快照，账号或页面变化不能让迟到的刷新恢复旧批准。
test('刷新审批同步列表，刷新期间关闭弹窗不恢复旧记录', async t => {
  let state, finishRefresh, defer = false
  const value = { ...draft(), version: 2, status: 'approved', generation: 1, policy_version: 1,
    steps: [{ name: '批准', role: null }], current_step: 1,
    submitted_by: 2, submitted_at: '2026-10-07 12:00:00', can_submit: false,
    // 完整历史与版本一致，模拟另一客户端真实完成的一次批准。
    events: [
      { id: 1, version: 1, generation: 1, action: 'submit', step: 0, step_name: null,
        actor_id: 2, actor_name: '建单员', reason: '', created_at: '2026-10-07 12:00:00' },
      { id: 2, version: 2, generation: 1, action: 'approve', step: 1, step_name: '批准',
        actor_id: 3, actor_name: '审批员', reason: '核对数量', created_at: '2026-10-07 12:01:00' }
    ] }
  const environmentResult = environment(t, async () => value, async () => {
    if (defer) await new Promise(resolve => { finishRefresh = resolve })
    state.otherInbounds.value = [{ id: 1, approval: value }]
  })
  state = environmentResult.state
  state.otherInbounds.value = [{ id: 1, approval: { status: 'submitted', version: 1 } }]
  assert.equal(await environmentResult.actions.openDocumentApproval(target), true)
  assert.equal(state.otherInbounds.value[0].approval.status, 'approved')
  defer = true
  const reading = environmentResult.actions.loadDocumentApproval()
  await new Promise(resolve => setImmediate(resolve))
  environmentResult.actions.closeDocumentApproval()
  finishRefresh()
  assert.equal(await reading, false)
  assert.equal(state.documentApprovalRecord.value, null)
})

// 新领域刷新失败时不丢操作依据；切换实例后不得调用原领域刷新或恢复旧意见。
test('审批领域刷新失败保留意见，实例切换阻止迟到领域读取',async t=>{
  let fail=false,finish,delay=false,domainReads=0
  const {state}=environment(t,async action=>{
    if(action==='documentApproval')return draft()
    return {...draft(),version:1,status:'submitted',generation:1,policy_version:1,steps:[{name:'批准',role:null}],
      submitted_by:1,submitted_at:'2026-10-07 12:00:00',can_submit:false,can_withdraw:true,
      events:[{id:1,version:1,generation:1,action:'submit',step:0,step_name:null,actor_id:1,actor_name:'作者',reason:'核对依据',created_at:'2026-10-07 12:00:00'}]}
  })
  const scope=effectScope();t.after(()=>scope.stop())
  const actions=scope.run(()=>createDocumentApprovalCaseActions(state,async()=>{
    if(delay)await new Promise(resolve=>{finish=resolve})
  },async()=>{domainReads++;if(fail)throw Error('领域列表刷新失败')}))
  assert.equal(await actions.openDocumentApproval(target),true)
  const key=approvalTargetKey(target);state.documentApprovalReasons.value[key]='核对依据';fail=true
  assert.equal(await actions.actDocumentApproval('submit'),false)
  assert.equal(state.documentApprovalReasons.value[key],'核对依据')
  assert.match(state.documentApprovalError.value,/刷新失败/)
  fail=false;delay=true;const before=domainReads,reading=actions.loadDocumentApproval()
  await new Promise(resolve=>setImmediate(resolve))
  state.server.value={id:'new-instance',fingerprint:'new'};finish()
  assert.equal(await reading,false);assert.equal(domainReads,before)
  assert.deepEqual(state.documentApprovalReasons.value,{})
})

// 与审批意见使用相同的实例、人员和失败边界，不丢失原维护现场依据。
test('维护依据单独提交且失败保留，同实例断线保留，换实例清除',async t=>{
  const maintenance={...target,document_type:'MaintenanceJob'}
  const requests=[]
  const {state,actions}=environment(t,async(action,input)=>{
    requests.push([action,input]);if(action==='actDocumentApproval')throw Error('现场依据需复核')
    return {...draft(),...maintenance}
  })
  await actions.openDocumentApproval(maintenance)
  const key=approvalTargetKey(maintenance)
  state.documentApprovalReasons.value[key]='方案意见';state.documentApprovalEvidence.value[key]='现场记录'
  assert.equal(await actions.actDocumentApproval('submit'),false)
  assert.equal(requests.find(([action])=>action==='actDocumentApproval')[1].evidence,'现场记录')
  assert.equal(state.documentApprovalEvidence.value[key],'现场记录')
  state.connectionLost.value=true;assert.equal(state.documentApprovalEvidence.value[key],'现场记录')
  state.server.value={id:'second',fingerprint:'second'}
  assert.deepEqual(state.documentApprovalEvidence.value,{})
})
