import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createInventoryWarningActions} from '../src/renderer/src/store/modules/inventory-warning-actions.ts'
import {createInventoryWarningAlerts} from '../src/renderer/src/store/modules/inventory-warning-alerts.ts'
import {warningThresholdValid} from '../src/shared/inventory-warning-api.ts'
import {validateInventoryWarningResult} from '../src/shared/inventory-warning-validation.ts'
import {callBackend} from '../src/main/backend.ts'
import {canVisitRoute,routeByKey} from '../src/renderer/src/router/workspace-routes.ts'

const permissions=['inventory.view','inventory_warning.manage']
const input={warehouse_id:1,material_id:1,version:0,threshold:'1.000',enabled:true,reason:'备货依据'}
const row={...input,id:1,version:1,created_by:1,created_at:'2026-10-01 12:00:00',warehouse_code:'MAIN',warehouse_name:'主仓库',
  sku:'PART',material_name:'物料',unit:'件',quantity:'0.125',shortage:'0.875',status:'low'}
const detail={row,changes:[{id:1,reason:'备货依据',changed_by:1,changed_by_name:'admin',created_at:row.created_at,before:null,after:row}]}
const overview={as_of:row.created_at,warehouse_id:null,rows:[row],warehouses:[{id:1,code:'MAIN',name:'主仓库'}],
  materials:[{id:1,sku:'PART',name:'物料',unit:'件'}],summary:{normal:0,low:1,out_of_stock:0,disabled:0,configured:1,unconfigured:0}}
const warningEvent={id:2,rule_id:1,warehouse_id:1,material_id:1,previous_status:'normal',status:'low',
  quantity:'0.125',threshold:'1.000',shortage:'0.875',rule_version:1,warehouse_code:'MAIN',warehouse_name:'主仓库',
  sku:'PART',material_name:'物料',unit:'件',observed_at:row.created_at,created_at:row.created_at}
const eventPage={as_of:row.created_at,warehouse_id:null,events:[warningEvent],next_before_id:null}
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}}
function fixture(t,callApi,perform=run=>run()){
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions}
  return {state,actions:createInventoryWarningActions(state,perform)}
}

test('库存查看控制入口，阈值只接受界限内的精确文本',()=>{
  assert.equal(canVisitRoute(routeByKey('inventoryWarnings'),['inventory.view']),true)
  assert.equal(canVisitRoute(routeByKey('inventoryWarnings'),['inventory_warning.manage']),false)
  for(const value of ['0','0.001','0.125','1000000.000'])assert.equal(warningThresholdValid(value),true)
  for(const value of ['','-1','01','1e3','NaN','1.0001','1000000.001'])assert.equal(warningThresholdValid(value),false)
})
test('IPC 固定路径、仓库范围和写字段白名单，拒绝浮点、假编号和缺失原因',async t=>{
  const previous=globalThis.fetch;t.after(()=>{globalThis.fetch=previous})
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push([new URL(url).pathname+new URL(url).search,options.body?JSON.parse(options.body):null]);
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:
      new URL(url).pathname.includes('/rules/')?detail:new URL(url).pathname.endsWith('/events')?eventPage:overview),{status:200})}
  await callBackend('login',{});calls.length=0
  await callBackend('inventoryWarnings',{warehouseId:2})
  await callBackend('inventoryWarningEvents',{warehouseId:2,beforeId:3})
  await callBackend('saveInventoryWarning',{...input,status:'normal',quantity:'999',_X_ROW_KEY:'table'})
  assert.deepEqual(calls,[['/api/v1/inventory/warnings?warehouse_id=2',null],
    ['/api/v1/inventory/warnings/events?warehouse_id=2&before_id=3',null],
    ['/api/v1/inventory/warnings/rules/1/1',{version:0,threshold:'1.000',enabled:true,reason:'备货依据'}]])
  for(const bad of [{warehouse_id:'../users'},{material_id:true},{version:true},{threshold:0.125},{threshold:'1.0001'},{enabled:1},{reason:' '}]){
    await assert.rejects(callBackend('saveInventoryWarning',{...input,...bad}))
  }
  for(const bad of [null,[],true,{warehouseId:0},{warehouseId:'1'}])await assert.rejects(callBackend('inventoryWarnings',bad))
  for(const bad of [null,[],true,{warehouseId:0},{beforeId:'3'}])await assert.rejects(callBackend('inventoryWarningEvents',bad))
  assert.equal(calls.length,3)
})
test('响应拒绝伪零、未知状态、停用假差额及缺失审计',()=>{
  validateInventoryWarningResult('inventoryWarnings',overview);validateInventoryWarningResult('inventoryWarningDetail',detail)
  validateInventoryWarningResult('inventoryWarningDetail',{...detail,row:{...row,enabled:false,status:'disabled',shortage:null}})
  for(const bad of [{...row,quantity:null},{...row,quantity:0},{...row,status:'safe'},
    {...row,enabled:false,status:'disabled',shortage:'0'},{...row,shortage:null},{...row,version:0}]){
    assert.throws(()=>validateInventoryWarningResult('inventoryWarningDetail',{...detail,row:bad}),/响应格式/)
  }
  assert.throws(()=>validateInventoryWarningResult('inventoryWarningDetail',{row,changes:null}),/响应格式/)
  assert.throws(()=>validateInventoryWarningResult('inventoryWarnings',{...overview,summary:{...overview.summary,unconfigured:-1}}),/响应格式/)
  validateInventoryWarningResult('inventoryWarningEvents',eventPage)
  for(const bad of [{...warningEvent,status:'normal'},{...warningEvent,quantity:0},{...warningEvent,rule_version:0}])
    assert.throws(()=>validateInventoryWarningResult('inventoryWarningEvents',{...eventPage,events:[bad]}),/响应格式/)
})
test('服务端事件翻页保留历史，换号和迟到响应不泄露旧实例事件',async t=>{
  const pending=deferred(),calls=[]
  const {state,actions}=fixture(t,async(_action,data)=>{
    calls.push(data)
    if(data?.beforeId)return pending.promise
    return {...eventPage,next_before_id:warningEvent.id}
  })
  assert.equal(await actions.loadWarningEvents(),true)
  const more=actions.loadWarningEvents(true)
  state.user.value={id:2,permissions}
  pending.resolve({...eventPage,events:[{...warningEvent,id:1}],next_before_id:null})
  assert.equal(await more,false);assert.equal(state.warningEvents.value,null)
  globalThis.window.nexora.callApi=async()=>eventPage
  assert.equal(await actions.loadWarningEvents(),true)
  assert.equal(state.warningEvents.value.events.length,1)
  state.warningWarehouseId.value=2
  assert.equal(await actions.loadWarningEvents(),false)
  assert.match(state.warningEventsError.value,/来源范围不匹配/)
  state.connectionLost.value=true
  assert.equal(state.warningEvents.value,null)
  assert.equal(calls.length,2)
})
test('仓库改变、晚到详情和来源不匹配不覆盖当前结果',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  const old=actions.loadInventoryWarnings();state.warningWarehouseId.value=2;pending.resolve(overview)
  assert.equal(await old,false);assert.equal(state.warningOverview.value,null)
  globalThis.window.nexora.callApi=()=>Promise.resolve(overview)
  assert.equal(await actions.loadInventoryWarnings(),false);assert.match(state.warningError.value,/范围不匹配/)
  const first=deferred();globalThis.window.nexora.callApi=(_action,data)=>data.material_id===1?first.promise:Promise.resolve({...detail,row:{...row,material_id:2}})
  const late=actions.loadWarningDetail(row);await actions.loadWarningDetail({...row,material_id:2});first.resolve(detail)
  assert.equal(await late,false);assert.equal(state.warningDetail.value.row.material_id,2)
  assert.equal(await actions.loadWarningDetail({...row,material_id:3}),false);assert.equal(state.warningDetail.value,null)
})
test('断线清除旧量并保留正文和版本；换号或撤权清除',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.warningForm.value={...input,version:4};state.warningEditing.value=true;state.warningDetail.value=detail
  const reading=actions.loadInventoryWarnings();state.connectionLost.value=true;pending.resolve(overview)
  assert.equal(await reading,false);assert.equal(state.warningOverview.value,null);assert.equal(state.warningDetail.value,null)
  assert.equal(state.warningForm.value.version,4);assert.equal(state.warningForm.value.reason,'备货依据')
  state.user.value={id:1,permissions:['inventory.view']}
  assert.equal(state.warningForm.value.reason,'');assert.equal(state.warningEditing.value,false)
})
test('修订必须读取匹配的当前版本，只读账号不能建改',async t=>{
  const {state,actions}=fixture(t,()=>Promise.resolve({...detail,row:{...row,version:5}}))
  assert.equal(await actions.editWarningRule(row),true);assert.equal(state.warningForm.value.version,5)
  state.user.value={id:1,permissions:['inventory.view']}
  assert.equal(actions.startWarningRule(),false);assert.equal(await actions.editWarningRule(row),false)
  assert.equal(await actions.saveWarningRule(),false)
})
test('冲突保留原正文及旧版本，成功后读取当前量和审计',async t=>{
  let fail=true;const calls=[]
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);if(action==='saveInventoryWarning' && fail)throw Error('409 版本冲突');return action==='inventoryWarnings'?overview:detail},async run=>{try{await run()}catch{}})
  state.warningForm.value={...input,version:1};state.warningEditing.value=true
  assert.equal(await actions.saveWarningRule(),false);assert.equal(state.warningForm.value.version,1);assert.equal(state.warningForm.value.reason,'备货依据')
  fail=false;assert.equal(await actions.saveWarningRule(),true)
  assert.equal(state.warningEditing.value,false);assert.equal(state.warningForm.value.threshold,'');assert.equal(state.warningDetail.value.row.id,1)
  assert.deepEqual(calls.map(call=>call[0]),['saveInventoryWarning','saveInventoryWarning','inventoryWarnings','inventoryWarningDetail'])
})
test('迟到或排队写入不能写入新账号，写后刷新断线保留输入',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.warningForm.value={...input};const writing=actions.saveWarningRule()
  state.user.value={id:2,permissions};state.warningForm.value.reason='新账号正文';pending.resolve(detail)
  assert.equal(await writing,false);assert.equal(state.warningForm.value.reason,'新账号正文')
  const gate=deferred();let called=false;const queued=fixture(t,()=>{called=true;return Promise.resolve(detail)},async run=>{await gate.promise;await run()})
  queued.state.warningForm.value={...input};const waiting=queued.actions.saveWarningRule();queued.state.user.value={id:3,permissions}
  gate.resolve();assert.equal(await waiting,false);assert.equal(called,false)
  const read=deferred();const dropped=fixture(t,async action=>action==='inventoryWarnings'?read.promise:detail)
  dropped.state.warningForm.value={...input};const saving=dropped.actions.saveWarningRule()
  await new Promise(done=>setImmediate(done));dropped.state.connectionLost.value=true;read.resolve(overview)
  assert.equal(await saving,false);assert.equal(dropped.state.warningForm.value.reason,'备货依据')
})

test('应用内提醒只在首次异常和状态恶化时出现，恢复后再次异常会重新提示',async t=>{
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  let current={...overview,rows:[row]}
  globalThis.window={nexora:{callApi:async()=>current}}
  const state=createAppState();state.screen.value='app';state.user.value={id:1,permissions:['inventory.view']}
  const alerts=createInventoryWarningAlerts(state)
  await alerts.poll();const first=state.warningAlert.value
  assert.match(first.content,/低库存 1 项/)
  await alerts.poll();assert.equal(state.warningAlert.value,first)
  current={...overview,rows:[{...row,status:'out_of_stock',quantity:'0',shortage:'1.000'}]}
  await alerts.poll();assert.match(state.warningAlert.value.content,/缺货 1 项/)
  const worsened=state.warningAlert.value
  await alerts.poll();assert.equal(state.warningAlert.value,worsened)
  current={...overview,rows:[{...row,status:'normal',quantity:'2.000',shortage:'0.000'}]}
  await alerts.poll();assert.equal(state.warningAlert.value,worsened)
  current={...overview,rows:[row]}
  await alerts.poll();assert.match(state.warningAlert.value.content,/低库存 1 项/)
  assert.notEqual(state.warningAlert.value.id,first.id)
  alerts.stop()
})

test('提醒在无权、断线及迟到的旧账号响应时失效，失败不重置比较基线',async t=>{
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  let calls=0;let result=overview
  globalThis.window={nexora:{callApi:async()=>{calls++;if(result instanceof Error)throw result;return result}}}
  const state=createAppState();state.screen.value='app';state.user.value={id:1,permissions:[]}
  const alerts=createInventoryWarningAlerts(state)
  await alerts.poll();assert.equal(calls,0)
  state.user.value={id:1,permissions:['inventory.view']}
  await alerts.poll();const initial=state.warningAlert.value
  result=Error('短暂读取失败');await alerts.poll()
  result=overview;await alerts.poll();assert.equal(state.warningAlert.value,initial)
  const pending=deferred();globalThis.window.nexora.callApi=()=>pending.promise
  const old=alerts.poll();state.user.value={id:2,permissions:['inventory.view']}
  pending.resolve(overview);await old
  assert.equal(state.warningAlert.value,null)
  globalThis.window.nexora.callApi=async()=>overview
  await alerts.poll();assert.match(state.warningAlert.value.content,/低库存/)
  state.connectionLost.value=true;assert.equal(state.warningAlert.value,null)
  await alerts.poll();assert.equal(calls,3)
  alerts.stop()
})

test('窗口启动后登录立即提醒，释放时停止定时读取',async t=>{
  const originalWindow=globalThis.window,originalSetInterval=globalThis.setInterval,originalClearInterval=globalThis.clearInterval
  t.after(()=>{globalThis.window=originalWindow;globalThis.setInterval=originalSetInterval;globalThis.clearInterval=originalClearInterval})
  let calls=0,interval,cleared=false
  globalThis.setInterval=callback=>{interval=callback;return 17}
  globalThis.clearInterval=id=>{assert.equal(id,17);cleared=true}
  globalThis.window={nexora:{callApi:async()=>{calls++;return overview}}}
  const state=createAppState(),alerts=createInventoryWarningAlerts(state)
  alerts.start();assert.equal(calls,0)
  state.user.value={id:1,permissions:['inventory.view']};state.screen.value='app'
  await new Promise(done=>setImmediate(done))
  assert.equal(calls,1);assert.match(state.warningAlert.value.content,/低库存/)
  interval();await new Promise(done=>setImmediate(done))
  assert.equal(calls,2)
  alerts.stop();assert.equal(cleared,true);assert.equal(state.warningAlert.value,null)
})
