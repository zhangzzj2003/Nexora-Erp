import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createEquipmentActions} from '../src/renderer/src/store/modules/equipment-actions.ts'
import {maintenanceActions,equipmentChanges,maintenanceEffect,downtimeLabel} from '../src/renderer/src/views/workspace/production/equipment-display.ts'
import {validateEquipmentResult} from '../src/shared/equipment-validation.ts'
import {callBackend} from '../src/main/backend.ts'
import {canVisitRoute,routeByKey} from '../src/renderer/src/router/workspace-routes.ts'
const permissions=['equipment.view','equipment.manage','equipment.meter','equipment.create','equipment.execute','equipment.accept','equipment.review','equipment.submit','equipment.cancel','equipment.reverse']
const input={reference:'M-1',equipment_id:1,kind:'corrective',plan_id:null,hour_plan_id:null,work_order_id:null,assigned_to:1,request_note:'检查轴承',warehouse_id:null,parts:[],reason:'现场记录'}
const row={...input,id:1,version:3,status:'draft',plan_version:null,plan_due_date:null,plan_due_hours:null,plan_meter_reading_id:null,equipment_snapshot:{code:'EQ-1',name:'一号设备'},
  work_order_snapshot:{},work_order_linked:false,work_order_current_status:null,parts_outbound_id:null,parts_status:null,
  solution:'',labor_hours:null,service_amount:null,plan_roll:{},created_by:1,created_by_name:'admin',assigned_to_name:'admin',author_ids:[1],
  reviewed_by:null,reported_by:null,accepted_by:null,created_at:'2026-10-01 12:00:00',started_at:null,reported_at:null,accepted_at:null,
  allowed_actions:['submit','cancel'],can_edit:true,downtime:null,changes:[],purchase_requests:[]}

test('维护采购 IPC 限定来源和三位小数，详情校验收货与入库证据',async t=>{
  const previous=globalThis.fetch;t.after(()=>{globalThis.fetch=previous})
  const calls=[];globalThis.fetch=async(url,options)=>{
    calls.push([new URL(url).pathname,options.body?JSON.parse(options.body):null])
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:row),{status:200})
  }
  await callBackend('login',{});calls.length=0
  const input={id:1,version:3,reason:'维修备件',evidence:'检修记录',parts:[{material_id:2,quantity:'0.125',uiOnly:true}]}
  await callBackend('createMaintenancePurchaseRequest',input)
  assert.deepEqual(calls[0],['/api/v1/equipment/jobs/1/purchase-requests',{
    version:3,reason:'维修备件',evidence:'检修记录',parts:[{material_id:2,quantity:'0.125'}]}])
  await assert.rejects(callBackend('createMaintenancePurchaseRequest',{...input,parts:[{material_id:2,quantity:'0.1234'}]}),/最多三位小数/)
  await assert.rejects(callBackend('createMaintenancePurchaseRequest',{...input,id:'../users'}),/编号无效/)
  const linked={...row,purchase_requests:[{id:1,reference:'M-1-3',status:'approved',reason:'维修备件',evidence:'检修记录',created_by:1,
    created_at:'2026-10-01',lines:[{material_id:2,quantity:'0.125',orders:[{id:4,status:'confirmed',quantity:'0.125',goods_receipts:[{
      id:5,status:'confirmed',accepted_quantity:'0.125',inbound_receipt_id:6,inbound_status:'posted'}]}]}]}]}
  validateEquipmentResult('maintenanceJobDetail',linked)
  assert.throws(()=>validateEquipmentResult('maintenanceJobDetail',{...linked,purchase_requests:[{...linked.purchase_requests[0],
    lines:[{material_id:2,quantity:'0.125',orders:[{id:4,status:'confirmed',quantity:'0.125',goods_receipts:[{
      id:5,status:'confirmed',accepted_quantity:'0.125',inbound_receipt_id:6,inbound_status:1}]}]}]}]}),/响应格式/)
})
const overview={as_of:'2026-10-01 12:00:00',equipment:[],plans:[],hour_plans:[],jobs:[row],executors:[{id:1,username:'admin'}],materials:[],warehouses:[],work_orders:[]}
const meter={id:1,equipment_id:1,hours:'100.00',reference:'METER-1',reason:'现场表计',previous_reading_id:null,
  correction:false,recorded_by:1,recorded_by_name:'admin',recorded_at:'2026-10-01 12:00:00'}
const hourPlan={id:1,equipment_id:1,reference:'PH-1',title:'每十小时检查',interval_hours:'10.00',next_due_hours:'110.00',
  enabled:true,reason:'',version:1,created_by:1,created_at:'2026-10-01 12:00:00',current_hours:'100.00',
  current_reading_id:1,due:false,open_job_ids:[],changes:[]}
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}}
function fixture(t,callApi,perform=run=>run()){
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions}
  return {state,actions:createEquipmentActions(state,perform)}
}
test('独立维护入口及耗材开始权限，不由生产权限替代',()=>{
  assert.equal(canVisitRoute(routeByKey('equipmentMaintenance'),['production.view']),false)
  assert.equal(canVisitRoute(routeByKey('equipmentMaintenance'),['equipment.view']),true)
  assert.deepEqual(maintenanceActions({...row,parts:[{material_id:1,quantity:'1'}],allowed_actions:['start','cancel']},permissions),['cancel'])
  assert.deepEqual(maintenanceActions({...row,parts:[{material_id:1,quantity:'1'}],approval:{status:'approved'},allowed_actions:['start']},[...permissions,'other_outbound.create']),['start'])
  assert.deepEqual(maintenanceActions(row,[]),[])
  assert.deepEqual(maintenanceActions(row,['equipment.view']),[])
})
test('IPC 固定路径、写字段白名单、严格编号与明确费用，界面标记不能写入正文',async t=>{
  const previous=globalThis.fetch;t.after(()=>{globalThis.fetch=previous})
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push([new URL(url).pathname,options.body?JSON.parse(options.body):null]);return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:row),{status:200})}
  await callBackend('login',{});calls.length=0
  await callBackend('saveMaintenanceJob',{...input,id:1,version:3,status:'accepted',parts:[{material_id:2,quantity:'0.125',_X_ROW_KEY:'ui'}]})
  assert.deepEqual(calls[0],['/api/v1/equipment/jobs/1',{...input,parts:[{material_id:2,quantity:'0.125'}],version:3}])
  await callBackend('changeMaintenanceJob',{id:1,version:3,action:'report',reason:'复核',evidence:'记录',solution:'试运行通过',labor_hours:'0',service_amount:'0',status:'accepted'})
  assert.deepEqual(calls[1][1],{version:3,reason:'复核',evidence:'记录',solution:'试运行通过',labor_hours:'0',service_amount:'0'})
  await assert.rejects(callBackend('changeMaintenanceJob',{id:1,version:3,action:'../users'}),/操作无效/)
  await assert.rejects(callBackend('changeMaintenanceJob',{id:1,version:3,action:'report',labor_hours:0,service_amount:'0'}),/明确填写/)
  await assert.rejects(callBackend('changeMaintenanceJob',{id:1,version:3,action:'accept',service_amount:'0'}),/只有报工/)
  await assert.rejects(callBackend('saveMaintenanceJob',{...input,equipment_id:true}),/编号无效/)
  await assert.rejects(callBackend('saveMaintenanceJob',{...input,parts:[null]}),/精确字符串/)
  await assert.rejects(callBackend('saveMaintenanceJob',{...input,parts:[{material_id:1,quantity:0.125}]}),/精确字符串/)
  await assert.rejects(callBackend('saveMaintenancePlan',{equipment_id:1,interval_days:30,enabled:1}),/启停选择无效/)
  await assert.rejects(callBackend('saveEquipment',{id:1,version:0,status:'active'}),/编号无效/)
  assert.equal(calls.length,2)
})
test('拒绝金额伪零、错误阶段动作、缺失证据数组和错误响应编号',()=>{
  validateEquipmentResult('equipmentOverview',overview);validateEquipmentResult('maintenanceJobDetail',row)
  for(const bad of [{...row,labor_hours:0},{...row,service_amount:'NaN'},{...row,status:'done'},{...row,allowed_actions:['delete']},{...row,changes:null},{...row,id:true}]){
    assert.throws(()=>validateEquipmentResult('maintenanceJobDetail',bad),/响应格式/)
  }
  assert.throws(()=>validateEquipmentResult('equipmentOverview',{...overview,executors:[{id:1}]}),/响应格式/)
})
test('运行小时 IPC 固定路径、精确输入和响应边界',async t=>{
  const previous=globalThis.fetch;t.after(()=>{globalThis.fetch=previous})
  const calls=[]
  globalThis.fetch=async(url,options)=>{
    const path=new URL(url).pathname;calls.push([path,options.body?JSON.parse(options.body):null])
    const result=path.endsWith('/meter-readings')?meter:path.includes('/hour-plans')?hourPlan:{token:'test',user:{id:1}}
    return new Response(JSON.stringify(result),{status:200})
  }
  await callBackend('login',{});calls.length=0
  validateEquipmentResult('recordEquipmentMeter',meter)
  validateEquipmentResult('maintenanceHourPlanDetail',hourPlan)
  assert.throws(()=>validateEquipmentResult('maintenanceHourPlanDetail',{...hourPlan,current_hours:100}),/响应格式/)
  await callBackend('recordEquipmentMeter',{equipment_id:1,hours:'100.25',reference:'METER-2',reason:'现场表计',
    previous_reading_id:1,correction:false,untrusted:'x'})
  assert.deepEqual(calls[0],['/api/v1/equipment/meter-readings',{equipment_id:1,hours:'100.25',
    reference:'METER-2',reason:'现场表计',previous_reading_id:1,correction:false}])
  await callBackend('saveMaintenanceHourPlan',{equipment_id:1,reference:'PH-1',title:'检查',interval_hours:'10.00',
    next_due_hours:'110.00',enabled:true,reason:'建立',id:1,version:2,untrusted:'x'})
  assert.deepEqual(calls[1],['/api/v1/equipment/hour-plans/1',{equipment_id:1,reference:'PH-1',title:'检查',
    interval_hours:'10.00',next_due_hours:'110.00',enabled:true,reason:'建立',version:2}])
  await assert.rejects(callBackend('recordEquipmentMeter',{equipment_id:1,hours:100,correction:false}),/精确十进制/)
  await assert.rejects(callBackend('recordEquipmentMeter',{equipment_id:1,hours:'-1',correction:false}),/精确十进制/)
  await assert.rejects(callBackend('recordEquipmentMeter',{equipment_id:1,hours:'1.001',correction:false}),/精确十进制/)
  await assert.rejects(callBackend('saveMaintenanceHourPlan',{equipment_id:1,enabled:true,interval_hours:'0',next_due_hours:'1'}),/精确十进制/)
  await assert.rejects(callBackend('saveMaintenanceJob',{...input,kind:'preventive',plan_id:1,hour_plan_id:1}),/关联无效/)
  assert.equal(calls.length,2)
})

test('表计登记遵守更正权限、旧会话失效并刷新当前读数',async t=>{
  const calls=[]
  const asset={id:1,code:'EQ-1',name:'一号设备',location:'车间',serial_number:'',status:'active',version:1,
    running_job_ids:[],meter_reading:meter,meter_readings:[meter],changes:[],created_at:'2026-10-01 12:00:00'}
  const {state,actions}=fixture(t,async(action,data)=>{
    calls.push([action,data])
    return action==='equipmentOverview'?overview:action==='equipmentDetail'?asset:meter
  })
  const input={equipment_id:1,hours:'101.00',reference:'METER-2',reason:'现场复核',previous_reading_id:1,correction:false}
  assert.equal(await actions.recordEquipmentMeter(input),true)
  assert.deepEqual(calls.map(([action])=>action),['recordEquipmentMeter','equipmentOverview','equipmentDetail'])
  assert.equal(state.equipmentDetail.value.row.meter_reading.hours,'100.00')
  state.user.value={id:1,permissions:['equipment.view','equipment.meter']}
  assert.equal(await actions.recordEquipmentMeter({...input,correction:true}),false)
  assert.equal(calls.length,3)

  const pending=deferred()
  globalThis.window.nexora.callApi=(action,data)=>{calls.push([action,data]);return pending.promise}
  const old=actions.recordEquipmentMeter(input)
  state.user.value={id:2,permissions}
  pending.resolve(meter)
  assert.equal(await old,false)
  assert.equal(state.equipmentOverview.value,null)
  assert.equal(state.equipmentDetail.value,null)
})
test('旧详情和断线迟到读取失效，同账号输入与版本保留，换号撤权清除',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,(_action,data)=>data?.id===1?pending.promise:Promise.resolve({...row,id:2}))
  const first=actions.loadEquipmentDetail('job',1);await actions.loadEquipmentDetail('job',2);pending.resolve(row)
  assert.equal(await first,false);assert.equal(state.equipmentDetail.value.row.id,2)
  state.equipmentForms.value.job=structuredClone(input);state.equipmentEdit.value={kind:'job',id:1,version:3}
  const late=deferred();globalThis.window.nexora.callApi=()=>late.promise
  const reading=actions.loadEquipment();state.connectionLost.value=true;late.resolve(overview)
  assert.equal(await reading,false);assert.equal(state.equipmentOverview.value,null);assert.equal(state.equipmentDetail.value,null)
  assert.equal(state.equipmentForms.value.job.reference,'M-1');assert.equal(state.equipmentEdit.value.version,3)
  state.user.value={id:1,permissions:['equipment.view']}
  assert.equal(state.equipmentForms.value.job.reference,'');assert.equal(state.equipmentEdit.value,null)
})
test('保存冲突保留正文及旧版本，保存后才清空；隐藏计划和仓库字段归一',async t=>{
  let fail=true;const calls=[]
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);if(action==='saveMaintenanceJob' && fail)throw Error('版本冲突');return action==='equipmentOverview'?overview:row},async run=>{try{await run()}catch{}})
  state.equipmentForms.value.job={...structuredClone(input),plan_id:9,warehouse_id:1};state.equipmentEdit.value={kind:'job',id:1,version:3}
  assert.equal(await actions.saveEquipmentRecord('job'),false)
  assert.equal(state.equipmentForms.value.job.reference,'M-1');assert.equal(state.equipmentEdit.value.version,3)
  assert.deepEqual(calls[0][1],{...input,id:1,version:3})
  fail=false;assert.equal(await actions.saveEquipmentRecord('job'),true);assert.equal(state.equipmentForms.value.job.reference,'')
})
test('迟到及排队写入不能进入新账号，写后刷新时断线不能清空未保存正文',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.equipmentForms.value.job=structuredClone(input);const old=actions.saveEquipmentRecord('job')
  state.user.value={id:2,permissions};state.equipmentForms.value.job.reference='新账号正文';pending.resolve(row)
  assert.equal(await old,false);assert.equal(state.equipmentForms.value.job.reference,'新账号正文')
  const gate=deferred();let called=false;const queued=fixture(t,()=>{called=true;return Promise.resolve(row)},async run=>{await gate.promise;await run()})
  queued.state.equipmentForms.value.job=structuredClone(input);const write=queued.actions.saveEquipmentRecord('job')
  queued.state.user.value={id:3,permissions};gate.resolve();assert.equal(await write,false);assert.equal(called,false)
  const reading=deferred();const dropped=fixture(t,async action=>action==='equipmentOverview'?reading.promise:row)
  dropped.state.equipmentForms.value.job=structuredClone(input);const saved=dropped.actions.saveEquipmentRecord('job')
  await new Promise(done=>setImmediate(done));dropped.state.connectionLost.value=true;reading.resolve(overview)
  assert.equal(await saved,false);assert.equal(dropped.state.equipmentForms.value.job.reference,'M-1')
})
test('修订必须等待匹配详情，隐藏生产来源不允许重新编辑',async t=>{
  const {state,actions}=fixture(t,()=>Promise.resolve({...row,can_edit:false,work_order_linked:true}))
  assert.equal(await actions.editEquipmentRecord('job',1),false);assert.equal(state.equipmentEdit.value,null)
  state.connectionLost.value=true;assert.equal(actions.startEquipmentRecord('asset'),false)
})
test('更正与取消显示真实库存和停机影响，审计中文差异不打印 JSON',()=>{
  assert.match(maintenanceEffect('reverse'),/保留真实停机与耗材领用/)
  assert.match(maintenanceEffect('cancel'),/不会自动归库/)
  assert.match(maintenanceEffect('report'),/费用也须明确填零/)
  assert.equal(downtimeLabel({seconds:3661,ongoing:true}),'1 小时 1 分（截至本次读取）')
  const changes=equipmentChanges({before:{status:'draft',parts_json:'[]',service_amount:null},after:{status:'accepted',parts_json:'[{"material_id":2,"quantity":"0.125"}]',service_amount:'0.00'}})
  assert.match(JSON.stringify(changes),/草稿/);assert.match(JSON.stringify(changes),/物料 #2 × 0.125/)
  assert.equal(changes.find(row=>row.name==='声明外委费用（元）').before,'未登记')
})

// 共用审批刷新只恢复当前单据详情，不能覆盖其他资料或未保存正文。
test('维护审批刷新保留表单与当前详情，切换实例拒绝排队写入',async t=>{
  const calls=[]
  const {state,actions}=fixture(t,async(action,input)=>{calls.push([action,input]);return action==='equipmentOverview'?overview:row})
  state.equipmentDetail.value={kind:'job',row};state.equipmentForms.value.job.reference='未保存正文'
  await actions.refreshEquipmentApproval(1)
  assert.equal(state.equipmentDetail.value.row.id,1);assert.equal(state.equipmentForms.value.job.reference,'未保存正文')
  const gate=deferred();let writes=0
  const queued=fixture(t,async()=>{writes++;return row},async run=>{await gate.promise;await run()})
  const pending=queued.actions.saveEquipmentRecord('job')
  queued.state.server.value={id:'new-instance',fingerprint:'new-instance'}
  queued.state.equipmentForms.value.job.reference='新实例草稿';gate.resolve()
  assert.equal(await pending,false);assert.equal(writes,0);assert.equal(queued.state.equipmentForms.value.job.reference,'新实例草稿')
})


// 来源旧 approved 字样不等于新的本单独立批准。
test('维护动作拒绝旧审核按钮与缺失审批，开始和更正各自核对批准',()=>{
  assert.deepEqual(maintenanceActions({...row,allowed_actions:['submit','approve','reject']},permissions),[])
  assert.deepEqual(maintenanceActions({...row,allowed_actions:['start']},permissions),[])
  assert.deepEqual(maintenanceActions({...row,allowed_actions:['reverse'],approval:{status:'approved'}},permissions),[])
  assert.deepEqual(maintenanceActions({...row,allowed_actions:['reverse'],reversal_approval:{status:'approved'}},permissions),['reverse'])
})

// 审核意见和前端传入依据都不能替换送审时固定的验收更正依据。
test('验收更正读取服务端固定两项依据，撤回或切换实例后拒绝执行',async t=>{
  const caseRow={document_type:'MaintenanceJob',document_id:1,intent:'reverse',document_no:null,business_status:'accepted',
    reversal_reason:'固定更正原因',reversal_evidence:'固定现场依据',summary:[],content_matches:true,
    version:2,status:'approved',generation:1,current_step:1,steps:[{name:'批准',role:null}],policy_version:1,
    submitted_by:1,submitted_at:'2026-10-07 12:00:00',executed_by:null,executed_at:null,
    can_submit:false,can_review:false,can_withdraw:true,events:[
      {id:1,version:1,generation:1,action:'submit',step:0,step_name:null,actor_id:1,actor_name:'建单人',reason:'固定更正原因',evidence:'固定现场依据',created_at:'2026-10-07 12:00:00'},
      {id:2,version:2,generation:1,action:'approve',step:0,step_name:'批准',actor_id:2,actor_name:'审核人',reason:'不同审核意见',evidence:'不同审核依据',created_at:'2026-10-07 12:00:00'}]}
  let result=caseRow;const calls=[]
  const {state,actions}=fixture(t,async(action,input)=>{
    calls.push([action,input]);return action==='documentApproval'?result:action==='equipmentOverview'?overview:row
  })
  const command={id:1,version:3,action:'reverse',reason:'客户端原因',evidence:'客户端依据'}
  assert.equal(await actions.changeMaintenanceJob(command),true)
  assert.deepEqual(calls.find(([action])=>action==='changeMaintenanceJob')[1],{...command,reason:'固定更正原因',evidence:'固定现场依据'})
  result={...caseRow,content_matches:false};calls.length=0
  assert.equal(await actions.changeMaintenanceJob(command),false);assert.equal(calls.length,1)
  const wait=deferred();globalThis.window.nexora.callApi=()=>wait.promise
  const pending=actions.changeMaintenanceJob(command)
  state.server.value={id:'another',fingerprint:'another'};wait.resolve(caseRow)
  assert.equal(await pending,false)
})
