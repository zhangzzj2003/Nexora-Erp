import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createAfterSalesActions} from '../src/renderer/src/store/modules/after-sales-actions.ts'
import {afterSalesActions,afterSalesChanges,afterSalesResponsibility,repairFeeState,afterSalesReversalHint} from '../src/renderer/src/views/workspace/sales/after-sales-display.ts'
import {financialSource} from '../src/renderer/src/utils/formatters.ts'
import {callBackend} from '../src/main/backend.ts'
import {canVisitRoute,routeByKey} from '../src/renderer/src/router/workspace-routes.ts'
const permissions=['after_sales.view','after_sales.create','after_sales.submit','after_sales.review','after_sales.process',
  'after_sales.receive','after_sales.inspect','after_sales.close','after_sales.cancel','after_sales.reverse','after_sales.labor','sales_return.create','sales_order.create']
const row={id:1,version:3,status:'submitted',kind:'repair',current_source_valid:true,author_ids:[1]}
const input={shipment_line_id:1,reference:'A-1',kind:'repair',quantity:'2',complaint:'产品故障',solution:'维修后交还',charge_mode:'charge',
  fee_amount:'10.50',customer_acceptance:'客户确认服务费 A-1',warranty_days:30,warranty_basis:'销售合同第 3 条',
  warehouse_id:1,replacement_material_id:null,replacement_quantity:null,
  replacement_unit_price:null,parts:[{material_id:2,quantity:'1.005'}],reason:'客户委托'}
const overview={sources:[{shipment_line_id:1,remaining_quantity:'2'}],cases:[],materials:[],warehouses:[]}
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}}
test('维修金额文案区分免费、未交付、收费结案及追加更正',()=>{
  assert.match(repairFeeState({charge_mode:'free',closed_at:'2026-10-01',reversed_at:null}),/免费维修不形成收费来源/)
  assert.doesNotMatch(repairFeeState({charge_mode:'free',closed_at:'2026-10-01',reversed_at:null}),/收费来源已固定/)
  assert.match(repairFeeState({charge_mode:'charge',closed_at:null,reversed_at:null}),/不形成维修应收/)
  assert.match(repairFeeState({charge_mode:'charge',closed_at:'2026-10-01',reversed_at:null}),/收费来源已固定/)
  assert.match(repairFeeState({charge_mode:'charge',closed_at:'2026-10-01',reversed_at:'2026-10-02'}),/反向收费来源/)
  assert.match(afterSalesReversalHint({kind:'repair',charge_mode:'free'}),/不产生收费或反向收费来源/)
  assert.match(afterSalesReversalHint({kind:'repair',charge_mode:'charge'}),/追加原服务费反向来源/)
  assert.match(afterSalesReversalHint({kind:'exchange',charge_mode:'none'}),/须先更正关联业务/)
})
function fixture(t,callApi,perform=run=>run()){
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions}
  return {state,actions:createAfterSalesActions(state,perform)}
}
test('售后入口、独立审核及关联单据权限均独立核对',()=>{
  assert.equal(canVisitRoute(routeByKey('afterSales'),['sales.view']),false)
  assert.equal(canVisitRoute(routeByKey('afterSales'),['after_sales.view']),true)
  assert.deepEqual(afterSalesActions(row,['after_sales.review'],1),[])
  assert.deepEqual(afterSalesActions(row,['after_sales.review'],2),['approve','reject'])
  assert.deepEqual(afterSalesActions({...row,status:'approved',kind:'exchange'},['after_sales.process'],2),[])
  assert.deepEqual(afterSalesActions({...row,status:'approved',kind:'exchange'},permissions,2),['process','cancel'])
  assert.equal(financialSource({source_type:'after_sales_repair',source_id:3}),'售后维修服务费 #3')
})
test('IPC 只发送编制字段及固定动作，拒绝编号、检验结果和路径注入',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  const requests=[];globalThis.fetch=async(url,options)=>{requests.push([url,options.body?JSON.parse(options.body):null]);return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:row),{status:200})}
  await callBackend('login',{});requests.length=0
  await callBackend('saveAfterSalesCase',{...input,status:'closed',fee_paid:true,parts:[{...input.parts[0],_X_ROW_KEY:'ui'}]})
  assert.deepEqual(requests[0][1],input)
  await callBackend('changeAfterSalesCase',{id:1,version:3,action:'inspect',reason:'复核',evidence:'检验单',inspection_result:'fail',status:'closed'})
  assert.deepEqual(requests[1][1],{version:3,reason:'复核',evidence:'检验单',inspection_result:'fail'})
  await assert.rejects(callBackend('changeAfterSalesCase',{id:1,version:3,action:'../users'}),/操作无效/)
  await assert.rejects(callBackend('saveAfterSalesCase',{...input,shipment_line_id:true}),/编号无效/)
  await assert.rejects(callBackend('saveAfterSalesCase',{...input,id:1,version:0}),/编号无效/)
  await assert.rejects(callBackend('saveAfterSalesCase',{...input,warranty_days:1.5}),/保修天数无效/)
  await assert.rejects(callBackend('saveAfterSalesCase',{...input,warranty_days:'30'}),/保修天数无效/)
  await assert.rejects(callBackend('saveAfterSalesCase',{...input,warranty_basis:42}),/保修依据无效/)
  await assert.rejects(callBackend('changeAfterSalesCase',{id:1,version:3,action:'inspect',inspection_result:'auto'}),/检验结果无效/)
  assert.equal(requests.length,2)
})
test('维修工时 IPC 使用固定路径与字段，拒绝金额精度和记录编号注入',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  const requests=[];globalThis.fetch=async(url,options)=>{
    requests.push([new URL(url).pathname,JSON.parse(options.body)])
    return new Response(JSON.stringify(row),{status:200})
  }
  await callBackend('recordAfterSalesLabor',{id:1,version:3,hours:'1.25',reason:'维修',evidence:'工单',status:'closed'})
  await callBackend('reverseAfterSalesLabor',{id:1,version:4,entry_id:2,reason:'重复计时',evidence:'复核',hours:'999'})
  assert.deepEqual(requests,[
    ['/api/v1/after-sales/cases/1/labor',{version:3,hours:'1.25',reason:'维修',evidence:'工单'}],
    ['/api/v1/after-sales/cases/1/labor/2/reverse',{version:4,reason:'重复计时',evidence:'复核'}]
  ])
  await assert.rejects(callBackend('recordAfterSalesLabor',{id:1,version:3,hours:'1.234',reason:'维修',evidence:'工单'}),/工时无效/)
  await assert.rejects(callBackend('recordAfterSalesLabor',{id:1,version:3,hours:1.25,reason:'维修',evidence:'工单'}),/工时无效/)
  await assert.rejects(callBackend('reverseAfterSalesLabor',{id:1,version:3,entry_id:'../users',reason:'更正',evidence:'复核'}),/编号无效/)
  assert.equal(requests.length,2)
})
test('维修工时操作校验独立权限并在成功后刷新证据',async t=>{
  const calls=[]
  const {state,actions}=fixture(t,async(operation,input)=>{
    calls.push([operation,input]);return operation==='afterSalesOverview'?overview:row
  })
  state.user.value={id:1,permissions:['after_sales.view']}
  assert.equal(await actions.recordAfterSalesLabor(row,'1.25','维修','工单'),false)
  assert.equal(calls.length,0)
  state.user.value={id:1,permissions}
  assert.equal(await actions.recordAfterSalesLabor(row,'1.25','维修','工单'),true)
  assert.deepEqual(calls[0],['recordAfterSalesLabor',{id:1,version:3,hours:'1.25',reason:'维修',evidence:'工单'}])
  assert.deepEqual(calls.slice(1).map(([operation])=>operation),['afterSalesOverview','afterSalesDetail'])
  calls.length=0
  assert.equal(await actions.reverseAfterSalesLabor(row,5,'重复计时','复核'),true)
  assert.deepEqual(calls[0],['reverseAfterSalesLabor',{id:1,version:3,entry_id:5,reason:'重复计时',evidence:'复核'}])
})

test('责任核定 IPC 只发送枚举与依据，独立审核权限控制写入',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  const requests=[];globalThis.fetch=async(url,options)=>{
    requests.push([new URL(url).pathname,JSON.parse(options.body)])
    return new Response(JSON.stringify(row),{status:200})
  }
  assert.equal(afterSalesResponsibility.third_party,'第三方责任')
  await callBackend('assessAfterSalesResponsibility',{id:1,version:3,outcome:'company',basis:'检验记录 R-1',reason:'核定',fee_amount:'0'})
  assert.deepEqual(requests,[['/api/v1/after-sales/cases/1/responsibility',
    {version:3,outcome:'company',basis:'检验记录 R-1',reason:'核定'}]])
  await assert.rejects(callBackend('assessAfterSalesResponsibility',{id:1,version:3,outcome:'auto',basis:'检验',reason:'核定'}),/责任核定结果无效/)
  await assert.rejects(callBackend('assessAfterSalesResponsibility',{id:1,version:3,outcome:'company',basis:' ',reason:'核定'}),/责任依据/)
  assert.equal(requests.length,1)
  const calls=[];const {state,actions}=fixture(t,async(operation,data)=>{
    calls.push([operation,data]);return operation==='afterSalesOverview'?overview:row
  })
  state.user.value={id:2,permissions:['after_sales.view']}
  assert.equal(await actions.assessAfterSalesResponsibility(row,'company','检验记录 R-1','核定'),false)
  assert.equal(calls.length,0)
  state.user.value={id:2,permissions}
  assert.equal(await actions.assessAfterSalesResponsibility(row,'company','检验记录 R-1','核定'),true)
  assert.deepEqual(calls[0],['assessAfterSalesResponsibility',
    {id:1,version:3,outcome:'company',basis:'检验记录 R-1',reason:'核定'}])
  assert.deepEqual(calls.slice(1).map(([operation])=>operation),['afterSalesOverview','afterSalesDetail'])
})
test('较旧证据与断线迟到结果不覆盖当前，同账号草稿和版本保留',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,(_action,data)=>data?.id===1?pending.promise:Promise.resolve({...row,id:2}))
  const first=actions.loadAfterSalesDetail(1);await actions.loadAfterSalesDetail(2);pending.resolve(row)
  assert.equal(await first,false);assert.equal(state.afterSalesDetail.value.id,2)
  state.afterSalesForm.value=structuredClone(input);state.afterSalesEdit.value={id:1,version:3}
  const late=deferred();globalThis.window.nexora.callApi=()=>late.promise
  const load=actions.loadAfterSales();state.connectionLost.value=true;late.resolve(overview)
  assert.equal(await load,false);assert.equal(state.afterSalesOverview.value,null);assert.equal(state.afterSalesDetail.value,null)
  assert.equal(state.afterSalesForm.value.reference,'A-1');assert.equal(state.afterSalesEdit.value.version,3)
  state.user.value={id:2,permissions:['after_sales.view']}
  assert.equal(state.afterSalesForm.value.reference,'');assert.equal(state.afterSalesEdit.value,null)
})
test('维修必须明确免费或收费，保存冲突保留输入及旧版本',async t=>{
  const calls=[];let fail=true
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);if(action==='saveAfterSalesCase'&&fail)throw Error('版本冲突');return action==='afterSalesOverview'?overview:row},async run=>{try{await run()}catch{}})
  state.afterSalesForm.value={...structuredClone(input),charge_mode:''}
  assert.equal(await actions.saveAfterSalesCase(),false);assert.equal(calls.length,0);assert.match(state.error.value,/明确选择/)
  state.afterSalesForm.value=structuredClone(input);state.afterSalesEdit.value={id:1,version:3}
  assert.equal(await actions.saveAfterSalesCase(),false);assert.equal(state.afterSalesForm.value.fee_amount,'10.50');assert.equal(state.afterSalesEdit.value.version,3)
  assert.deepEqual(calls[0][1],{...input,id:1,version:3})
  fail=false;assert.equal(await actions.saveAfterSalesCase(),true);assert.equal(state.afterSalesForm.value.reference,'')
})
test('迟到保存不能清除新账号草稿，排队中的旧写入也不能使用新账号',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.afterSalesForm.value=structuredClone(input);const save=actions.saveAfterSalesCase()
  state.user.value={id:2,permissions};state.afterSalesForm.value.reference='新账号草稿';pending.resolve(row)
  assert.equal(await save,false);assert.equal(state.afterSalesForm.value.reference,'新账号草稿')
  const gate=deferred();let called=false;const delayed=fixture(t,()=>{called=true;return Promise.resolve(row)},async run=>{await gate.promise;await run()})
  delayed.state.afterSalesForm.value=structuredClone(input);const old=delayed.actions.saveAfterSalesCase()
  delayed.state.user.value={id:3,permissions};gate.resolve()
  assert.equal(await old,false);assert.equal(called,false)
})
test('退货、换货写入剔除隐藏维修字段，材料剔除界面行标识',async t=>{
  const calls=[];const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);return action==='afterSalesOverview'?overview:row})
  state.afterSalesForm.value={...structuredClone(input),kind:'exchange',replacement_material_id:3,replacement_quantity:'2',replacement_unit_price:'0'}
  assert.equal(await actions.saveAfterSalesCase(),true)
  assert.equal(calls[0][1].charge_mode,'none');assert.equal(calls[0][1].fee_amount,'0');assert.deepEqual(calls[0][1].parts,[])
  assert.equal(calls[0][1].replacement_unit_price,'0')
})
test('审计显示中文方案、收费与耗材差异，不打印原始 JSON',()=>{
  const changes=afterSalesChanges({before:{parts_json:'[]',charge_mode:'free',fee_amount:'0.00'},
    after:{parts_json:JSON.stringify([{sku:'P',material_name:'维修件',quantity:'2',unit:'件'}]),charge_mode:'charge',fee_amount:'10.50'}})
  assert.match(changes.join('\n'),/免费维修 → 收费维修/)
  assert.match(changes.join('\n'),/维修件 2 件/)
  assert.doesNotMatch(changes.join('\n'),/parts_json|\{/)
})

test('保修条款随草稿修订保留并显示中文审计差异',async t=>{
  const calls=[];const evidence={...row,...input,parts:[],warranty_applied_on:'2026-10-05',warranty_expires_on:'2026-10-31',
    warranty_status:'within_period'}
  const {state,actions}=fixture(t,async(action,data)=>{calls.push([action,data]);return action==='afterSalesOverview'?overview:evidence})
  assert.equal(await actions.editAfterSalesCase(1),false)
  evidence.status='draft'
  assert.equal(await actions.editAfterSalesCase(1),true)
  assert.equal(state.afterSalesForm.value.warranty_days,30)
  assert.equal(state.afterSalesForm.value.warranty_basis,'销售合同第 3 条')
  assert.equal(await actions.saveAfterSalesCase(),true)
  assert.equal(calls.find(([operation])=>operation==='saveAfterSalesCase')[1].warranty_days,30)
  const lines=afterSalesChanges({before:{warranty_days:30,warranty_basis:'旧合同'},
    after:{warranty_days:60,warranty_basis:'补充协议'}})
  assert.match(lines.join('；'),/保修天数：30 → 60/)
  assert.match(lines.join('；'),/保修依据：旧合同 → 补充协议/)
})

test('从原出库建立售后草稿时带入订单保修条款',async t=>{
  const {state,actions}=fixture(t,async()=>row)
  state.afterSalesOverview.value={...overview,sources:[{
    shipment_line_id:3,remaining_quantity:'2',warranty_days:365,warranty_basis:'销售合同 W-365'
  }]}
  assert.equal(actions.startAfterSalesCase(3),true)
  assert.equal(state.afterSalesForm.value.warranty_days,365)
  assert.equal(state.afterSalesForm.value.warranty_basis,'销售合同 W-365')
  assert.equal(state.afterSalesForm.value.quantity,'2')
  state.afterSalesOverview.value={...overview,sources:[{
    shipment_line_id:4,remaining_quantity:'1',warranty_days:null,warranty_basis:''
  }]}
  assert.equal(actions.startAfterSalesCase(4),true)
  assert.equal(state.afterSalesForm.value.warranty_days,null)
  assert.equal(state.afterSalesForm.value.warranty_basis,'')
})
