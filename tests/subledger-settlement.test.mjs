import assert from 'node:assert/strict'
import {test} from 'node:test'
import {sameSubledgerScope, settlementActions, canReverseSettlement} from '../src/renderer/src/views/workspace/finance/subledger-settlement-display.ts'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createSubledgerActions} from '../src/renderer/src/store/modules/subledger-actions.ts'
import {callBackend} from '../src/main/backend.ts'
import {validatePaymentRecordResponse} from '../src/shared/payment-record-api.ts'

test('历史核销只匹配同原方案同往来和完整辅助组合，辅助顺序不影响身份',()=>{
  const source={id:1,opening_id:1,kind:'receivable',party_id:3,account_id:4,auxiliary:[{kind:'customer',id:3},{kind:'project',id:5}]}
  const target={...source,id:2,auxiliary:[...source.auxiliary].reverse()}
  assert.equal(sameSubledgerScope(source,target),true)
  for(const change of [{id:1},{opening_id:2},{kind:'payable'},{party_id:4},{account_id:5},{auxiliary:[{kind:'customer',id:3}]}])
    assert.equal(sameSubledgerScope(source,{...target,...change}),false)
})

test('核销批准、撤回与反向草稿分别保护执行和冲销入口',()=>{
  const row={id:1,status:'draft',reverses_id:null}
  assert.deepEqual(settlementActions(row,['finance.record']),['cancel'])
  assert.deepEqual(settlementActions({...row,approval:{status:'submitted'}},['finance.record']),[])
  assert.deepEqual(settlementActions({...row,approval:{status:'approved'}},['finance.record']),['post'])
  assert.deepEqual(settlementActions({...row,reverses_id:2,approval:{status:'approved'}},['finance.record']),[])
  assert.deepEqual(settlementActions({...row,reverses_id:2,approval:{status:'approved'}},['finance.reverse']),['post'])
  const executed={...row,status:'executed'}
  assert.equal(canReverseSettlement(executed,[{reverses_id:1,status:'draft'}]),false)
  assert.equal(canReverseSettlement(executed,[{reverses_id:1,status:'cancelled'}]),true)
  assert.equal(canReverseSettlement({...executed,reverses_id:2},[]),false)
})

test('核销 IPC 限定字段及地址，拒绝路径片段、伪造执行与版本',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old})
  const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,body:config.body?JSON.parse(config.body):null});
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200,headers:{'Content-Type':'application/json'}})}
  await callBackend('login',{});requests.length=0
  const input={from_line_id:3,to_line_id:4,amount:'10',reference:'REFERENCE',reason:'核对历史原单'}
  await callBackend('createSubledgerSettlement',{...input,status:'executed',party_id:999,created_at:'1999-01-01'})
  assert.deepEqual(requests[0],{path:'/api/v1/finance/subledger-settlements',body:input})
  await callBackend('changeSubledgerSettlementStatus',{id:8,version:2,action:'post',reason:' 核对执行 ',executed_by:1})
  assert.deepEqual(requests[1],{path:'/api/v1/finance/subledger-settlements/8/post',body:{version:2,reason:'核对执行'}})
  for(const invalid of [true,0,-1,'2/../../roles',1.1])await assert.rejects(callBackend('reverseSubledgerSettlement',{id:invalid,reason:'更正'}))
  for(const change of [{action:'approve'},{version:true},{version:0},{reason:' '}])
    await assert.rejects(callBackend('changeSubledgerSettlementStatus',{id:8,version:2,action:'post',reason:'核对',...change}))
  const record={kind:'receivable',from_line_id:1,to_line_id:2,status:'draft',version:1,executed_at:null,executed_by:null,
    cancelled_at:null,cancelled_by:null,cancellation_reason:''}
  validatePaymentRecordResponse(record)
  assert.throws(()=>validatePaymentRecordResponse({...record,status:'approved'}))
  assert.throws(()=>validatePaymentRecordResponse({...record,executed_at:'2026-01-01'}))
})

test('核销排队执行不能跨实例，撤权清除历史金额与列表',async t=>{
  const old=globalThis.window;t.after(()=>{globalThis.window=old})
  const calls=[];globalThis.window={nexora:{callApi:async(...args)=>{calls.push(args);return []}}}
  let release;const pending=new Promise(resolve=>{release=resolve})
  const state=createAppState();state.user.value={id:1,permissions:['subledger_opening.view','finance.record']};state.server.value={id:'one',fingerprint:'ca-one'}
  const actions=createSubledgerActions(state,async fn=>{await pending;try{await fn()}catch{}})
  const row={id:1,status:'draft',version:1,reverses_id:null,approval:{status:'approved'}}
  assert.equal(await actions.changeSubledgerSettlementStatus({...row,approval:null},'post','未批准'),false)
  const execution=actions.changeSubledgerSettlementStatus(row,'post','核对执行')
  state.subledgerSettlements.value=[row];state.server.value={id:'two',fingerprint:'ca-two'};release()
  assert.equal(await execution,false);assert.deepEqual(calls,[]);assert.deepEqual(state.subledgerSettlements.value,[])
  state.subledgerSettlements.value=[row];state.user.value={id:1,permissions:[]}
  assert.deepEqual(state.subledgerSettlements.value,[])
})
