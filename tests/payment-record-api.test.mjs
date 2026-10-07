import assert from 'node:assert/strict'
import {test} from 'node:test'
import {validatePaymentRecordResponse} from '../src/shared/payment-record-api.ts'
import {callBackend} from '../src/main/backend.ts'

// 财务执行响应须有合法业务版本和状态，旧固定归档仍能只读显示。
test('资金响应拒绝未知状态、无效版本和草稿伪造执行时间',()=>{
  const row={id:1,kind:'receivable',order_id:1,action:'settlement',status:'draft',version:1,
    executed_at:null,executed_by:null,cancelled_at:null,cancelled_by:null,cancellation_reason:''}
  validatePaymentRecordResponse({payments:[row,{...row,order_id:undefined,opening_line_id:1}]})
  for(const change of [{status:'approved'},{version:true},{version:0},{executed_at:'2026-01-01'},{executed_by:-1}]) {
    assert.throws(()=>validatePaymentRecordResponse({...row,...change}))
  }
  validatePaymentRecordResponse({evidence:{payments:[{kind:'receivable',order_id:1,action:'settlement',amount:'10.00'}]}})
})

test('资金执行 IPC 固定地址及字段，拒绝路径片段和无效原因',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old})
  const calls=[]
  globalThis.fetch=async(url,config)=>{calls.push([new URL(url).pathname,JSON.parse(config.body)]);return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200,headers:{'Content-Type':'application/json'}})}
  await callBackend('login',{});calls.length=0
  await callBackend('changePaymentRecordStatus',{id:7,version:3,action:'post',reason:' 原资金核对 ',approved_by:1})
  assert.deepEqual(calls,[['/api/v1/finance/payment-records/7/post',{version:3,reason:'原资金核对'}]])
  for(const change of [{id:'../users'},{version:true},{version:0},{action:'reverse'},{reason:' '},{reason:'字'.repeat(201)}]) {
    await assert.rejects(callBackend('changePaymentRecordStatus',{id:7,version:3,action:'post',reason:'核对',...change}))
  }
  assert.equal(calls.length,1)
})

// 分户资金与订单资金共享响应校验，但只能发送到自己的固定执行地址。
test('分户资金 IPC 固定执行地址并校验真实版本及依据',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old})
  const calls=[]
  globalThis.fetch=async(url,config)=>{calls.push([new URL(url).pathname,JSON.parse(config.body)]);return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200,headers:{'Content-Type':'application/json'}})}
  await callBackend('login',{});calls.length=0
  await callBackend('changeSubledgerPaymentStatus',{id:7,version:3,action:'post',reason:' 原分户资金核对 ',approved_by:1})
  assert.deepEqual(calls,[['/api/v1/finance/subledger-openings/payments/7/post',{version:3,reason:'原分户资金核对'}]])
  for(const change of [{id:'../users'},{version:true},{version:0},{action:'reverse'},{reason:' '},{reason:'字'.repeat(201)}]) {
    await assert.rejects(callBackend('changeSubledgerPaymentStatus',{id:7,version:3,action:'post',reason:'核对',...change}))
  }
  assert.equal(calls.length,1)
})
