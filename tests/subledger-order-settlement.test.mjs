import assert from 'node:assert/strict'
import {test} from 'node:test'
import {matchingGroup, matchingLimit, cents, amountText} from '../src/renderer/src/views/workspace/finance/subledger-order-display.ts'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createSubledgerOrderActions} from '../src/renderer/src/store/modules/subledger-order-actions.ts'
import {callBackend} from '../src/main/backend.ts'
import {validatePaymentRecordResponse} from '../src/shared/payment-record-api.ts'
import {documentApprovalActionBody} from '../src/shared/document-approval-api.ts'

const line={id:1,kind:'receivable',party_id:3,account_id:4,outstanding_amount:'-30.00',auxiliary:[{kind:'customer',id:3},{kind:'project',id:5}]}
const group={account_id:4,outstanding_amount:'20.01',auxiliary:[...line.auxiliary].reverse(),evidence:[{type:'journal',journal_id:1}]}
const order={kind:'receivable',order_id:2,party_id:3,outstanding_amount:'50.00',groups:[group],blockers:[]}

test('历史与订单按完整科目辅助匹配，三项额度及精确分位分别约束两种方向',()=>{
  assert.equal(matchingGroup(line,order),group)
  assert.equal(matchingLimit(line,order,'historical_credit'),2001n)
  assert.equal(matchingLimit({...line,outstanding_amount:'25.00'},{...order,outstanding_amount:'-10.00',groups:[{...group,outstanding_amount:'-8.05'}]},'order_credit'),805n)
  for(const change of [{kind:'payable'},{party_id:4},{blockers:['无凭证']},{groups:[{...group,account_id:9}]},
    {groups:[{...group,auxiliary:[{kind:'customer',id:3}]}]},{groups:[{...group,evidence:[]}]},{outstanding_amount:'-10.00'}])
    assert.equal(matchingLimit(line,{...order,...change},'historical_credit'),0n)
  assert.equal(amountText(cents('9999999999999.99')),'9999999999999.99')
  assert.equal(amountText(cents('-0.05')),'-0.05');assert.equal(cents('NaN'),0n);assert.equal(cents('0.001'),0n)
})

test('核销 IPC 限定地址与可写字段，拒绝伪造方向、路径、动作和执行状态',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,body:config.body?JSON.parse(config.body):null});
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200,headers:{'Content-Type':'application/json'}})}
  await callBackend('login',{});requests.length=0
  const input={opening_line_id:3,order_id:4,direction:'historical_credit',amount:'10',reference:'R',reason:'原科目核对'}
  await callBackend('createSubledgerOrderSettlement',{...input,status:'executed',account_id:999,auxiliary:[],created_by:5})
  assert.deepEqual(requests[0],{path:'/api/v1/finance/subledger-order-settlements',body:input})
  await callBackend('changeSubledgerOrderSettlementStatus',{id:8,version:2,action:'post',reason:' 核对执行 ',executed_by:1})
  assert.deepEqual(requests[1],{path:'/api/v1/finance/subledger-order-settlements/8/post',body:{version:2,reason:'核对执行'}})
  for(const invalid of [true,0,-1,'2/../../roles',1.1])await assert.rejects(callBackend('reverseSubledgerOrderSettlement',{id:invalid,reason:'更正'}))
  await assert.rejects(callBackend('createSubledgerOrderSettlement',{...input,direction:'approve'}))
  for(const change of [{action:'approve'},{version:true},{version:0},{reason:' '}])
    await assert.rejects(callBackend('changeSubledgerOrderSettlementStatus',{id:8,version:2,action:'post',reason:'核对',...change}))
  const row={...input,kind:'receivable',status:'draft',version:1,executed_at:null,executed_by:null,cancelled_at:null,cancelled_by:null,cancellation_reason:''}
  validatePaymentRecordResponse(row);assert.throws(()=>validatePaymentRecordResponse({...row,status:'approved'}))
  assert.throws(()=>validatePaymentRecordResponse({...row,executed_at:'2026-01-01'}))
})

test('专属读取权限、撤权和跨实例排队写入清除核销状态并阻止发送',async t=>{
  const old=globalThis.window;t.after(()=>{globalThis.window=old});const calls=[]
  globalThis.window={nexora:{callApi:async(...args)=>{calls.push(args);return []}}}
  const state=createAppState();state.user.value={id:1,permissions:['finance.record']};state.server.value={id:'one',fingerprint:'ca-one'}
  let release;const gate=new Promise(resolve=>{release=resolve})
  const actions=createSubledgerOrderActions(state,async fn=>{await gate;try{await fn()}catch{}},async()=>{})
  assert.equal(await actions.loadSubledgerOrders(),false)
  assert.equal(await actions.createSubledgerOrderSettlement({}),false);assert.deepEqual(calls,[])
  state.user.value={id:1,permissions:['subledger_order_settlement.view','finance.record']}
  const row={id:1,status:'draft',version:1,reverses_id:null,approval:{status:'approved'}}
  assert.equal(await actions.changeSubledgerOrderSettlementStatus({...row,approval:null},'post','未批准'),false)
  const pending=actions.changeSubledgerOrderSettlementStatus(row,'post','核对执行')
  state.subledgerOrderSettlements.value=[row];state.subledgerOrderOptions.value={lines:[line],orders:[order]}
  state.server.value={id:'two',fingerprint:'ca-two'};release()
  assert.equal(await pending,false);assert.deepEqual(calls,[]);assert.deepEqual(state.subledgerOrderSettlements.value,[]);assert.equal(state.subledgerOrderOptions.value,null)
})

test('晚到读取结果不能覆盖新会话或连接失效，审批参数强制依据',async t=>{
  const old=globalThis.window;t.after(()=>{globalThis.window=old})
  let release;const gate=new Promise(resolve=>{release=resolve})
  globalThis.window={nexora:{callApi:async op=>{await gate;return op==='subledgerOrderOptions'?{lines:[line],orders:[order]}:[{id:1}]}}}
  const state=createAppState();state.user.value={id:1,permissions:['subledger_order_settlement.view']}
  const actions=createSubledgerOrderActions(state,async fn=>fn(),async()=>{})
  const pending=actions.loadSubledgerOrders();state.connectionLost.value=true;release()
  assert.equal(await pending,false);assert.equal(state.subledgerOrderLoading.value,false);assert.equal(state.subledgerOrderOptions.value,null)
  assert.throws(()=>documentApprovalActionBody({document_type:'SubledgerOrderSettlement',document_id:1,intent:'execute',action:'submit',version:0,reason:''}))
})
