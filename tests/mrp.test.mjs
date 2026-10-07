import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createMrpActions } from '../src/renderer/src/store/modules/mrp-actions.ts'
import { mrpActions, mrpCanConvert, mrpDraftError, mrpSourceStatus } from '../src/renderer/src/views/workspace/production/mrp-display.ts'
import { movementTypeLabel } from '../src/renderer/src/utils/formatters.ts'
import { routeByKey, canVisitRoute } from '../src/renderer/src/router/workspace-routes.ts'
import { callBackend } from '../src/main/backend.ts'

const permissions = ['mrp.view','mrp.create','mrp.configure','mrp.convert','mrp.submit']
const input = {reference:'MRP-1',reason:'订单承诺',start_date:'2030-01-01',demand_dates:[],supply_dates:[],
  manual_demands:[{material_id:1,quantity:'2.125',due_date:'2030-01-10',reference:'预估订单'}]}
const options = {today:'2030-01-01',fingerprint:'current',demands:[],supplies:[],materials:[],policies:[],warehouses:[]}
const deferred = () => {let resolve;const promise = new Promise(done=>{resolve=done});return {promise,resolve}}
function fixture(t, callApi, perform = action => action()) {
  const previous = globalThis.window; t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions}
  return {state,actions:createMrpActions(state,perform)}
}
test('MRP 日期及数量校验阻止空日期、非法日期和超出范围',()=>{
  assert.equal(mrpDraftError(input,options.today),'')
  for(const edit of [{start_date:'2029-12-31'},{reference:' '},{manual_demands:[{...input.manual_demands[0],due_date:'2030-02-30'}]},
    {supply_dates:[{key:'po:1',due_date:''}]},{manual_demands:[{...input.manual_demands[0],quantity:'1e2'}]},
    {manual_demands:[{...input.manual_demands[0],quantity:'0'}]}]) assert.ok(mrpDraftError({...input,...edit},options.today))
})

test('原单状态和库存来源使用业务中文，未知来源要求核对',()=>{
  assert.equal(mrpSourceStatus('draft'),'草稿')
  assert.equal(mrpSourceStatus('partially_shipped'),'部分出库')
  assert.equal(mrpSourceStatus('released'),'已下达')
  assert.equal(mrpSourceStatus('new_state'),'状态待核对')
  assert.equal(movementTypeLabel('receipt'),'采购入库')
  assert.equal(movementTypeLabel('production_completion_reversal'),'生产完工冲销')
  assert.equal(movementTypeLabel('new_source'),'未识别的库存来源')
})
test('独立路由与曾提交人审核保护，有效原单阻止取消',()=>{
  assert.ok(canVisitRoute(routeByKey('materialPlanning'),['mrp.view']))
  assert.equal(canVisitRoute(routeByKey('materialPlanning'),['production.view','finance.view']),false)
  const item={status:'submitted',author_ids:[1,2],conversions:[]}
  assert.deepEqual(mrpActions(item,['mrp.review'],2),[])
  assert.deepEqual(mrpActions(item,['mrp.review'],3),[])
  assert.deepEqual(mrpActions({...item,approval:{status:'submitted'}},['mrp.cancel'],3),[])
  assert.deepEqual(mrpActions({...item,status:'approved',conversions:[{target_status:'draft'}]},['mrp.cancel'],3),[])
})
test('IPC 只接受固定计划字段及动作，不能伪造建议数量和快照',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,body:config.body ? JSON.parse(config.body) : null});
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200})}
  await callBackend('login',{});requests.length=0
  await callBackend('createMrpPlan',{...input,snapshot:{suggestions:[]},status:'approved',manual_demands:input.manual_demands.map(row=>({...row,_X_ROW_KEY:'ui'}))})
  assert.deepEqual(requests[0],{path:'/api/v1/production/mrp/plans',body:input})
  await callBackend('convertMrpSuggestion',{id:2,version:3,suggestion_key:'1:2030-01-10',warehouse_id:1,reference:'',reason:'转单',quantity:'0',bom_id:100})
  assert.deepEqual(requests[1].body,{version:3,suggestion_key:'1:2030-01-10',warehouse_id:1,reference:'',reason:'转单'})
  for(const id of [true,0,1.1,'1/../../roles']) await assert.rejects(callBackend('mrpDetail',{id}),/编号无效/)
  await assert.rejects(callBackend('changeMrpStatus',{id:1,version:1,action:'post',reason:'越权'}),/不允许/)
  await assert.rejects(callBackend('createMrpPlan',{...input,supply_dates:null}),/明细无效/)
  await assert.rejects(callBackend('saveMrpPolicy',{id:1,version:0,supply_mode:'auto',lead_time_days:true}),/参数无效/)
  assert.equal(requests.length,2)
})
test('来源重新读取保留既有日期，新增来源必须手工指定日期',async t=>{
  const next={...options,demands:[{key:'old'},{key:'new'}],supplies:[{key:'planned',due_date:'2030-01-05'},{key:'po:2'}]}
  const {state,actions}=fixture(t,async action=>action==='mrpPlans'?[]:next)
  state.mrpForm.value={...input,demand_dates:[{key:'old',due_date:'2030-01-10'},{key:'deleted',due_date:'2030-01-02'}],supply_dates:[]}
  assert.equal(await actions.loadMrp(),true)
  assert.deepEqual(state.mrpForm.value.demand_dates,[{key:'old',due_date:'2030-01-10'},{key:'new',due_date:''}])
  assert.deepEqual(state.mrpForm.value.supply_dates,[{key:'po:2',due_date:''}])
})
test('断线保留输入并丢弃迟到来源，换号清除敏感计划',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.mrpForm.value=structuredClone(input)
  const read=actions.loadMrp();state.connectionLost.value=true;pending.resolve(options)
  assert.equal(await read,false);assert.equal(state.mrpOptions.value,null);assert.equal(state.mrpForm.value.reference,'MRP-1')
  state.user.value={id:2,permissions};assert.equal(state.mrpForm.value.reference,'');assert.equal(state.mrpDetail.value,null)
})
test('较旧详情请求不能覆盖后打开的计划，关闭后迟到结果作废',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,(action,{id})=>id===1?pending.promise:Promise.resolve(action==='mrpDetail'?{id:2}:action==='mrpCheck'?{matched:true}:[]))
  const first=actions.loadMrpDetail({id:1});assert.equal(await actions.loadMrpDetail({id:2}),true)
  pending.resolve({id:1});assert.equal(await first,false);assert.equal(state.mrpDetail.value.id,2)
  globalThis.window.nexora.callApi=()=>pending.promise
  const late=actions.loadMrpDetail({id:3});actions.clearMrpDetail();assert.equal(await late,false);assert.equal(state.mrpDetail.value,null)
})
test('保存冲突保留全部输入和行标签，成功仅发送业务字段',async t=>{
  const calls=[];let fail=true
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);if(action==='createMrpPlan'){if(fail)throw Error('来源变化');return {id:9}}
    return action==='mrpOptions'?options:action==='mrpPlans'?[]:action==='mrpChanges'?[]:{id:9}},async run=>{try{await run()}catch{}})
  state.mrpForm.value={...structuredClone(input),manual_demands:input.manual_demands.map(row=>({...row,_X_ROW_KEY:'ui'}))}
  assert.equal(await actions.createMrpPlan(),false);assert.equal(state.mrpForm.value.reference,'MRP-1')
  assert.deepEqual(calls[0][1],input);fail=false;assert.equal(await actions.createMrpPlan(),true);assert.equal(state.mrpDetail.value.id,9)
})
test('旧账号或断线期间完成的保存不能清除新草稿',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.mrpForm.value=structuredClone(input);const write=actions.createMrpPlan()
  state.connectionLost.value=true;pending.resolve({id:1});assert.equal(await write,false);assert.equal(state.mrpForm.value.reference,'MRP-1')
})
test('查看者可读取结果和参数，但没有写入与转单能力',async t=>{
  const called=[];const {state,actions}=fixture(t,async action=>{called.push(action);return action==='mrpPlans'?[]:options})
  state.user.value={id:3,permissions:['mrp.view']}
  assert.equal(await actions.loadMrp(),true)
  assert.equal(await actions.createMrpPlan(),false);assert.equal(await actions.saveMrpPolicy(1,{}),false)
  assert.equal(await actions.convertMrpSuggestion({id:1,version:1},'1:2030-01-01',null,'',''),false)
  assert.deepEqual(called,['mrpPlans','mrpOptions'])
})

// 分批转换只允许固定批准正文；旧原生批准、来源变化或重复建议必须阻止。
test('计划转单核对独立批准、剩余建议及原单建单权限',()=>{
  const item={status:'approved',conversions:[],approval:{status:'approved'}}
  const row={key:'fixed',supply_mode:'buy'}, check={matched:true}, perms=['mrp.convert','purchase_request.create']
  assert.equal(mrpCanConvert(item,check,row,perms),true)
  assert.equal(mrpCanConvert({...item,approval:{status:'executed'}},check,row,perms),true)
  for(const state of [undefined,{status:'submitted'},{status:'withdrawn'}])assert.equal(mrpCanConvert({...item,approval:state},check,row,perms),false)
  assert.equal(mrpCanConvert(item,{matched:false},row,perms),false)
  assert.equal(mrpCanConvert({...item,conversions:[{suggestion_key:'fixed'}]},check,row,perms),false)
  assert.equal(mrpCanConvert(item,check,row,['mrp.convert']),false)
})
test('审批刷新保留编排草稿并恢复当前详情，换实例丢弃排队写入',async t=>{
  const {state,actions}=fixture(t,async action=>action==='mrpPlans'?[]:action==='mrpOptions'?options:action==='mrpChanges'?[]:action==='mrpCheck'?{matched:true}:{id:9,version:2})
  state.mrpForm.value=structuredClone(input);state.mrpDetail.value={id:9,version:1}
  await actions.refreshMrpApproval(9)
  assert.equal(state.mrpDetail.value.version,2);assert.equal(state.mrpForm.value.reference,'MRP-1')
  const queued=deferred();let count=0
  const next=fixture(t,async()=>{count++;return {id:1}},async run=>{await queued.promise;await run()})
  next.state.mrpForm.value=structuredClone(input)
  const saving=next.actions.createMrpPlan();next.state.server.value={id:'other',fingerprint:'new'}
  next.state.mrpForm.value=structuredClone({...input,reference:'新实例草稿'});queued.resolve()
  assert.equal(await saving,false);assert.equal(count,0);assert.equal(next.state.mrpForm.value.reference,'新实例草稿')
})
