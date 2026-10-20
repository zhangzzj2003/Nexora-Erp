import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createProductionPlanActions } from '../src/renderer/src/store/modules/production-plan-actions.ts'
import { productionPlanBody, productionPlanCommand, validateProductionPlanResult } from '../src/shared/production-plan-api.ts'
import { canReleasePlan, canCancelPlan, planStatus, planStatusTone, planProgressTone } from '../src/renderer/src/views/workspace/production/production-plan-display.ts'
import { routeByKey, canVisitRoute } from '../src/renderer/src/router/workspace-routes.ts'
import { callBackend } from '../src/main/backend.ts'
import { planFixture, planInputFixture, planOptionsFixture } from './production-plan-fixture.mjs'
const permissions=['production_plan.view','production_plan.create','production_plan.release','production_plan.cancel','work_order.create']
const pending=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
function fixture(t,callApi,perform=run=>run()){
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,roles:['planner'],permissions}
  return {state,actions:createProductionPlanActions(state,perform)}
}

test('生产计划路由与审批、建单双权限控制下达',()=>{
  const route=routeByKey('productionPlans'),plan=planFixture()
  assert.equal(route.path,'/workspace/production-plans');assert.ok(canVisitRoute(route,permissions))
  assert.equal(canVisitRoute(route,['production.view']),false)
  assert.equal(canReleasePlan(plan,plan.lines[0],permissions),true)
  assert.equal(canReleasePlan(plan,plan.lines[0],['production_plan.release']),false)
  assert.equal(canReleasePlan({...plan,approval:{status:'withdrawn'}},plan.lines[0],permissions),false)
  assert.equal(canReleasePlan(plan,{...plan.lines[0],plan_id:2},permissions),false)
  assert.equal(canCancelPlan(plan,permissions),false)
  // 终止剩余计划不取消已有工单；执行后允许关闭余额，随后禁止再次下达。
  assert.equal(canCancelPlan({...plan,approval:{...plan.approval,status:'executed'},releases:[{work_order_status:'draft'}]},permissions),true)
  assert.equal(canReleasePlan({...plan,status:'cancelled'},plan.lines[0],permissions),false)
  assert.equal(planStatus({...plan,status:'cancelled'}),'已取消')
})

test('计划边界拒绝坏日期、布尔编号、超量及非业务字段',()=>{
  const input=planInputFixture();assert.deepEqual(productionPlanBody({...input,status:'approved',lines:input.lines.map(row=>({...row,reported_quantity:'100',_X_ROW_KEY:'x'}))}),input)
  for(const line of [{bom_id:true},{quantity:'1e2'},{quantity:'1000001'},{quantity:'0'},{start_date:'2026-02-30'},{end_date:'2026-10-01'},{priority:'hacked'}])
    assert.throws(()=>productionPlanBody({...input,lines:[{...input.lines[0],...line}]}))
  assert.throws(()=>productionPlanCommand({version:1,reason:' ',line_id:1},true))
  assert.throws(()=>productionPlanCommand({version:1,reason:'依据',line_id:1,approval_version:true,quantity:'1',request_id:'1234567890123456'},true))
})

test('网络响应必须完整并归属于请求计划',()=>{
  const plan=planFixture()
  assert.doesNotThrow(()=>validateProductionPlanResult('productionPlanDetail',plan,1))
  assert.doesNotThrow(()=>validateProductionPlanResult('productionPlanOptions',planOptionsFixture()))
  for(const edit of [{id:2},{approval:{status:'approved'}},{lines:[]},{lines:[{...plan.lines[0],plan_id:2}]},{lines:[{...plan.lines[0],unreleased_quantity:'-1'}]}])
    assert.throws(()=>validateProductionPlanResult('productionPlanDetail',{...plan,...edit},1))
})

test('IPC 固定请求字段与路径并校验响应身份',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const calls=[]
  globalThis.fetch=async(url,config)=>{const path=new URL(url).pathname;calls.push({path,body:config.body?JSON.parse(config.body):null})
    return new Response(JSON.stringify(path.endsWith('/login')?{token:'test',user:{id:1}}:planFixture()),{status:200})}
  await callBackend('login',{});calls.length=0
  const input=planInputFixture();await callBackend('createProductionPlan',{...input,status:'approved'})
  assert.deepEqual(calls[0],{path:'/api/v1/production/plans',body:input})
  await assert.rejects(callBackend('productionPlanDetail',{id:'../users'}),/编号/)
  await assert.rejects(callBackend('productionPlanDetail',{id:2}),/其他生产计划/)
})

test('断线保留草稿但丢弃旧来源，换号清空计划',async t=>{
  const job=pending();const {state,actions}=fixture(t,()=>job.promise)
  state.productionPlanForm.value=planInputFixture()
  const read=actions.loadProductionPlans();state.connectionLost.value=true;job.resolve([])
  assert.equal(await read,false);assert.equal(state.productionPlanOptions.value,null)
  assert.equal(state.productionPlanForm.value.reference,'十月生产计划')
  state.user.value={id:2,permissions};assert.equal(state.productionPlanForm.value.reference,'')
})

test('详情切换和关闭后，旧响应不能重新打开原计划',async t=>{
  const job=pending();const {state,actions}=fixture(t,(_,{id})=>id===1?job.promise:Promise.resolve({...planFixture(),id:2}))
  const first=actions.loadProductionPlanDetail(1);await actions.loadProductionPlanDetail(2)
  job.resolve(planFixture());assert.equal(await first,false);assert.equal(state.productionPlanDetail.value.id,2)
  const next=actions.loadProductionPlanDetail(1);actions.clearProductionPlanDetail();assert.equal(await next,false)
})

test('保存失败保留草稿，写入期间撤权不得清空新输入',async t=>{
  let fail=true;const job=pending();const {state,actions}=fixture(t,()=>{if(fail)throw Error('来源变化');return job.promise},async run=>{try{await run()}catch{}})
  state.productionPlanForm.value=planInputFixture();assert.equal(await actions.saveProductionPlan(),false)
  assert.equal(state.productionPlanForm.value.reference,'十月生产计划')
  fail=false;const write=actions.saveProductionPlan();state.user.value={id:2,permissions};state.productionPlanForm.value.reference='新账号草稿'
  job.resolve(planFixture());assert.equal(await write,false);assert.equal(state.productionPlanForm.value.reference,'新账号草稿')
})

test('编辑关闭后保持原版本，清空未保存输入才能重新编制新计划',t=>{
  const {state,actions}=fixture(t,async()=>planFixture())
  assert.equal(actions.editProductionPlan({...planFixture(),can_edit:true}),true)
  assert.deepEqual(state.productionPlanEdit.value,{id:1,version:1})
  assert.equal(state.productionPlanForm.value.reason,'')
  actions.clearProductionPlanDetail()
  assert.equal(state.productionPlanForm.value.reference,'十月智能控制器备货')
  actions.resetProductionPlanForm()
  assert.equal(state.productionPlanEdit.value,null)
  assert.deepEqual(state.productionPlanForm.value.lines,[])
})

test('审批刷新保留未保存输入，排队下达需重新核对工单权限',async t=>{
  const calls=[],queue=[];const {state,actions}=fixture(t,async(op,data)=>{calls.push([op,data]);return op==='productionPlans'?[planFixture()]:op==='productionPlanOptions'?planOptionsFixture():planFixture()},async run=>queue.push(run))
  state.productionPlanDetail.value=planFixture();state.productionPlanForm.value=planInputFixture()
  await actions.refreshProductionPlanApproval(1);assert.equal(state.productionPlanForm.value.reference,'十月生产计划')
  calls.length=0
  await actions.releaseProductionPlan({id:1,version:1,approval_version:2,line_id:1,quantity:'4',request_id:'1234567890123456',reason:'拆单'})
  state.user.value={id:1,permissions:['production_plan.view','production_plan.release']}
  await queue[0]();assert.equal(calls.length,0)
})

// 审批色调沿用其他入库，完成色由报工进度决定；取消覆盖历史审批结果。
test('计划状态标签覆盖全部审批及生产阶段，取消优先且审批执行不误报完成', () => {
  const plan = planFixture()
  for (const [status, tone] of Object.entries({ draft: 'pending', submitted: 'info', approved: 'ready', rejected: 'danger', withdrawn: 'neutral', executed: 'ready' })) {
    const row = { ...plan, approval: { ...plan.approval, status } }
    assert.equal(planStatusTone(row), tone)
    assert.equal(planStatusTone({ ...row, status: 'cancelled' }), 'neutral')
    assert.equal(planStatus({ ...row, status: 'cancelled' }), '已取消')
  }
  assert.equal(planStatusTone({ ...plan, approval: { ...plan.approval, status: 'unknown' } }), 'neutral')
  assert.deepEqual(planProgressTone, { unreleased: 'pending', released: 'ready', in_progress: 'info', completed: 'success' })
})
