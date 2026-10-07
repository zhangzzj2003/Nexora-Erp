import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createQualityActions } from '../src/renderer/src/store/modules/quality-actions.ts'
import { qualityActions,qualityChanges } from '../src/renderer/src/views/workspace/production/quality-display.ts'
import { callBackend } from '../src/main/backend.ts'
import { canVisitRoute,routeByKey } from '../src/renderer/src/router/workspace-routes.ts'

const permissions=['quality.view','quality.create','quality.submit','quality.review','quality.post','quality.cancel','quality.reverse']
const row={id:1,version:3,status:'submitted',current_source_valid:true,author_ids:[1],cost_allocation:null}
const input={completion_id:1,reference:'Q-1',kind:'rework',quantity:'2',loss_treatment:'carry',defect:'尺寸超差',action_note:'追加处理后复检',warehouse_id:1,materials:[{material_id:2,quantity:'1.005'}],reason:'核对质检'}
const overview={cases:[{id:1,remaining_quantity:'2',qc_note:'尺寸超差',settled:false}],dispositions:[],materials:[],warehouses:[]}
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}}
function fixture(t,callApi,perform=run=>run()){
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions}
  return {state,actions:createQualityActions(state,perform)}
}
test('处置入口独立授权，历史编制人不能审核，已结算不能更正',()=>{
  assert.equal(canVisitRoute(routeByKey('qualityDisposition'),['production.view']),false)
  assert.equal(canVisitRoute(routeByKey('qualityDisposition'),['quality.view']),true)
  assert.deepEqual(qualityActions(row,['quality.review'],1),[])
  assert.deepEqual(qualityActions(row,['quality.review'],2),[])
  assert.deepEqual(qualityActions({...row,current_source_valid:false},['quality.review'],2),[])
  assert.deepEqual(qualityActions({...row,status:'posted'},permissions,2),[])
  assert.deepEqual(qualityActions({...row,status:'posted',reversal_approval:{status:'approved'}},permissions,2),['reverse'])
  assert.deepEqual(qualityActions({...row,status:'approved',approval:{status:'approved'}},permissions,2),['post'])
  assert.deepEqual(qualityActions({...row,status:'approved',approval:{status:'submitted'}},permissions,2),[])
  assert.deepEqual(qualityActions({...row,status:'posted',cost_allocation:{settlement_id:1}},permissions,2),[])
})
test('操作证据显示追加材料之前之后及冻结检验，不输出原始 JSON',()=>{
  const before={materials_json:JSON.stringify([{sku:'R1',material_name:'材料',quantity:'1',unit:'件'}])}
  const after={...before,materials_json:JSON.stringify([{sku:'R1',material_name:'材料',quantity:'2',unit:'件'}])}
  const change=qualityChanges(before,after).find(item=>item.name==='追加材料快照')
  assert.match(change.before,/1 件/);assert.match(change.after,/2 件/)
  assert.ok(!change.after.includes('material_name'))
})
test('IPC 拒绝路径和版本注入，忽略状态金额与组件行标记',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,method:config.method,body:config.body?JSON.parse(config.body):null});return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200})}
  await callBackend('login',{});requests.length=0
  await callBackend('saveQualityDisposition',{...input,status:'posted',rework_order_id:55,amount:'0',materials:input.materials.map(line=>({...line,_X_ROW_KEY:'ui',unit_cost:'0'}))})
  assert.deepEqual(requests[0],{path:'/api/v1/production-quality/dispositions',method:'POST',body:input})
  await callBackend('saveQualityDisposition',{...input,id:1,version:3})
  assert.equal(requests[1].method,'PUT');assert.equal(requests[1].body.version,3)
  await callBackend('changeQualityDisposition',{id:1,version:3,action:'post',reason:'核对',status:'approved'})
  assert.deepEqual(requests[2].body,{version:3,reason:'核对'})
  for(const id of [true,0,1.2,'1/../../users'])await assert.rejects(callBackend('qualityDetail',{id}),/编号无效/)
  await assert.rejects(callBackend('changeQualityDisposition',{id:1,version:3,action:'post/../../users'}),/不允许/)
  await assert.rejects(callBackend('saveQualityDisposition',{...input,materials:null}),/明细无效/)
  await assert.rejects(callBackend('saveQualityDisposition',{...input,id:1,version:true}),/编号无效/)
  assert.equal(requests.length,3)
})
test('较旧详情和断线结果不能覆盖当前证据，同账号草稿与版本保留',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,(_action,data)=>data?.id===1?pending.promise:Promise.resolve({...row,id:2}))
  const first=actions.loadQualityDetail(1);await actions.loadQualityDetail(2);pending.resolve(row)
  assert.equal(await first,false);assert.equal(state.qualityDetail.value.id,2)
  state.qualityForm.value=structuredClone(input);state.qualityEdit.value={id:1,version:3}
  const late=deferred();globalThis.window.nexora.callApi=()=>late.promise
  const read=actions.loadQuality();state.connectionLost.value=true;late.resolve(overview)
  assert.equal(await read,false);assert.equal(state.qualityOverview.value,null);assert.equal(state.qualityDetail.value,null)
  assert.equal(state.qualityForm.value.reference,'Q-1');assert.equal(state.qualityEdit.value.version,3)
  state.user.value={id:2,permissions:['quality.view']}
  assert.equal(state.qualityForm.value.reference,'');assert.equal(state.qualityEdit.value,null)
})
test('保存冲突保留输入，成功只发送允许字段并重新读取证据',async t=>{
  const calls=[];let fail=true
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);if(action==='saveQualityDisposition' && fail)throw Error('版本冲突');return action==='qualityOverview'?overview:{...row,id:9}},async run=>{try{await run()}catch{}})
  state.qualityForm.value={...structuredClone(input),materials:input.materials.map(line=>({...line,_X_ROW_KEY:'ui'}))};state.qualityEdit.value={id:1,version:3}
  assert.equal(await actions.saveQualityDisposition(),false);assert.equal(state.qualityForm.value.reference,'Q-1');assert.equal(state.qualityEdit.value.version,3)
  assert.deepEqual(calls[0][1],{...input,id:1,version:3})
  fail=false;assert.equal(await actions.saveQualityDisposition(),true);assert.equal(state.qualityForm.value.reference,'');assert.equal(state.qualityDetail.value.id,9)
})
test('报废成本必须明确选择，不能默认零价或静默吸收',async t=>{
  let called=false;const {state,actions}=fixture(t,()=>{called=true})
  state.qualityForm.value={...structuredClone(input),kind:'scrap',loss_treatment:''}
  assert.equal(await actions.saveQualityDisposition(),false);assert.equal(called,false);assert.match(state.error.value,/明确选择/)
})
test('换号后的新草稿不被旧保存清空，未发出的旧保存不能使用新账号',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.qualityForm.value=structuredClone(input);const save=actions.saveQualityDisposition()
  state.user.value={id:2,permissions};state.qualityForm.value.reference='新账号草稿';pending.resolve(row)
  assert.equal(await save,false);assert.equal(state.qualityForm.value.reference,'新账号草稿')
  const gate=deferred();let called=false;const delayed=fixture(t,()=>{called=true;return Promise.resolve(row)},async run=>{await gate.promise;await run()})
  delayed.state.qualityForm.value=structuredClone(input);const old=delayed.actions.saveQualityDisposition();delayed.state.user.value={id:3,permissions};gate.resolve()
  assert.equal(await old,false);assert.equal(called,false)
})
test('只读账号不能写入，新建受已结算与剩余数量限制',async t=>{
  const calls=[];const {state,actions}=fixture(t,async action=>{calls.push(action);return overview})
  state.user.value={id:2,permissions:['quality.view']};assert.equal(await actions.loadQuality(),true)
  assert.equal(actions.startQualityDisposition(1),false);assert.equal(await actions.changeQualityDisposition(row,'approve','核对'),false)
  state.user.value={id:2,permissions};state.qualityOverview.value=overview
  assert.equal(actions.startQualityDisposition(1),true);assert.equal(state.qualityForm.value.quantity,'2')
  state.qualityOverview.value.cases[0].settled=true;assert.equal(actions.startQualityDisposition(1),false)
  assert.deepEqual(calls,['qualityOverview'])
})

// 审批更新只恢复仍打开的详情，关闭与换实例后不恢复迟到响应。
test('处置审批刷新保留草稿并隔离已关闭详情与服务实例',async t=>{
  let pending
  const {state,actions}=fixture(t,async operation=>operation==='qualityOverview' && pending?pending.promise:operation==='qualityOverview'?overview:row)
  state.qualityForm.value.reference='尚未保存';state.qualityDetail.value=row
  await actions.refreshQualityApproval(1)
  assert.equal(state.qualityDetail.value.id,1);assert.equal(state.qualityForm.value.reference,'尚未保存')
  pending=deferred();const refreshing=actions.refreshQualityApproval(1)
  actions.clearQualityDetail();pending.resolve(overview);await refreshing
  assert.equal(state.qualityDetail.value,null)
  pending=deferred();const old=actions.loadQuality()
  state.server.value={id:'other',fingerprint:'other'};pending.resolve(overview)
  assert.equal(await old,false);assert.equal(state.qualityOverview.value,null)
})
function correctionApproval(){
  const time='2026-10-07 00:00:00'
  return {document_type:'QualityDisposition',document_id:1,intent:'reverse',document_no:'BHGCZ-20261007-000001',
    business_status:'posted',reversal_reason:'原已批准的处置更正原因',summary:[],content_matches:true,
    version:2,status:'approved',generation:1,current_step:1,steps:[{name:'批准',role:null}],policy_version:1,
    submitted_by:1,submitted_at:time,executed_by:null,executed_at:null,
    can_submit:false,can_review:false,can_withdraw:true,
    events:[{id:1,version:1,generation:1,action:'submit',step:0,step_name:null,actor_id:1,actor_name:'申请人',reason:'更正原因',created_at:time},
      {id:2,version:2,generation:1,action:'approve',step:0,step_name:'批准',actor_id:2,actor_name:'审核人',reason:'核对',created_at:time}]}
}
// 原因取自服务端固定批准；异步读取期间切换实例不得发送任何更正。
test('处置更正只使用固定批准原因，旧实例响应不能触发新实例写入',async t=>{
  const calls=[];let pending
  const {state,actions}=fixture(t,async(operation,data)=>{
    calls.push([operation,data])
    if(operation==='documentApproval')return pending?pending.promise:correctionApproval()
    return operation==='qualityOverview'?overview:row
  })
  assert.equal(await actions.changeQualityDisposition({...row,status:'posted'},'reverse','界面意见不能替代原原因'),true)
  assert.equal(calls.find(([operation])=>operation==='changeQualityDisposition')[1].reason,'原已批准的处置更正原因')
  calls.length=0;pending=deferred()
  const old=actions.changeQualityDisposition({...row,status:'posted'},'reverse','旧实例操作')
  state.server.value={id:'another',fingerprint:'different'}
  pending.resolve(correctionApproval());assert.equal(await old,false)
  assert.deepEqual(calls.map(([operation])=>operation),['documentApproval'])
})
