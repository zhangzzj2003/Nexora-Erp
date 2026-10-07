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

test('业务列表与执行响应校验审批字段，旧响应缺省不能冒充已批准', () => {
  // 校验两种入口和独立冲销状态，拒绝仅提供 approved 文本的残缺响应。
  caseApi.validateDocumentApprovalResponse({ id: 1 })
  caseApi.validateDocumentApprovalResponse([{ id: 1, approval: draft() }, { id: 2 }])
  caseApi.validateDocumentApprovalResponse({ id: 1, approval: draft(), reversal_approval: draft() })
  for (const value of [null, undefined, 'approved', { status: 'approved' }, { ...draft(), version: true }]) {
    assert.throws(() => caseApi.validateDocumentApprovalResponse([{ id: 1, approval: value }]))
    assert.throws(() => caseApi.validateDocumentApprovalResponse({ id: 1, reversal_approval: value }))
    assert.throws(() => caseApi.validateDocumentApprovalResponse({ id: 1, outbound_approval: value }))
  }
})

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

// 报价最多百行加十份附件；审批摘要额度按单据类型扩展，其他单据仍保持原上限。
test('合法报价完整摘要保留全部物料与附件且拒绝越界',()=>{
  const state={document_type:'CrmQuote',document_id:1,intent:'execute',document_no:null,business_status:'draft',reversal_reason:'',
    version:0,status:'draft',generation:0,current_step:0,steps:[],policy_version:null,submitted_by:null,submitted_at:null,
    executed_by:null,executed_at:null,content_matches:true,can_submit:true,can_review:false,can_withdraw:false,events:[],
    summary:Array.from({length:117},(_,i)=>({label:'固定依据'+i,value:'物料或附件摘要'}))}
  caseApi.validateDocumentApprovalRecord(state)
  // 凭证最多百行、十份附件及原流程记录，适配只扩大凭证摘要，不放宽其他领域。
  caseApi.validateDocumentApprovalRecord({...state,document_type:'Journal'})
  assert.throws(()=>caseApi.validateDocumentApprovalRecord({...state,document_type:'WarehouseInbound'}))
  assert.throws(()=>caseApi.validateDocumentApprovalRecord({...state,summary:Array(129).fill({label:'越界',value:''})}))
})

// 维护现场依据独立跨 IPC 传递；其他单据不能使用维护字段绕过其原边界。
test('维护审批保留二百字意见及六百字现场依据，拒绝空证据和跨类型字段',()=>{
  const input={document_type:'MaintenanceJob',document_id:1,intent:'execute',action:'submit',version:0,
    reason:' 检查维护方案 ',evidence:' 现场记录 W-001 '}
  assert.deepEqual(caseApi.documentApprovalActionBody(input),{version:0,intent:'execute',reason:'检查维护方案',evidence:'现场记录 W-001'})
  for(const bad of [{reason:''},{reason:'x'.repeat(201)},{evidence:''},{evidence:'x'.repeat(601)},
    {evidence:1},{document_type:'WorkOrder'}])assert.throws(()=>caseApi.documentApprovalActionBody({...input,...bad}))
  caseApi.documentApprovalActionBody({...input,action:'withdraw',reason:'',evidence:''})
  caseApi.validateDocumentApprovalRecord({...draft(),document_type:'MaintenanceJob',reversal_evidence:'固定现场依据'})
  assert.throws(()=>caseApi.validateDocumentApprovalRecord({...draft(),reversal_evidence:'非法跨类型依据'}))
})

// 凭证仍使用原二百字依据；没有维护现场依据字段，防止客户端放宽原财务输入。
test('凭证审批白名单保留必填依据和原长度约束',()=>{
  const input={document_type:'Journal',document_id:1,intent:'execute',action:'submit',version:0,reason:' 凭据核对 '}
  assert.deepEqual(caseApi.documentApprovalActionBody(input),{version:0,intent:'execute',reason:'凭据核对'})
  for(const bad of [{reason:' '},{reason:'字'.repeat(201)},{evidence:'维护字段'}])assert.throws(()=>caseApi.documentApprovalActionBody({...input,...bad}))
})

// 财务期初沿原二百字依据边界，客户端不能伪造批准字段或省略操作依据。
test('期初审批依据必填且最多二百字，撤回保持独立版本',()=>{
  const input={document_type:'OpeningBalance',document_id:1,intent:'execute',action:'submit',version:0,reason:'核对期初'}
  assert.equal(caseApi.documentApprovalActionBody(input).reason,'核对期初')
  for(const reason of [' ','字'.repeat(201)])assert.throws(()=>caseApi.documentApprovalActionBody({...input,reason}))
  assert.equal(caseApi.documentApprovalActionBody({...input,action:'withdraw',version:2,reason:''}).version,2)
})
