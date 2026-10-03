import assert from 'node:assert/strict'
import {test} from 'node:test'
import {callBackend} from '../src/main/backend.ts'

test('生产领料冲销只发送固定编号与原因，拒绝无效输入',async t=>{
  const calls=[]
  t.mock.method(globalThis,'fetch',async (url,options)=>{
    calls.push({path:url.pathname,body:options.body})
    if(url.pathname.endsWith('/login'))return Response.json({token:'test-token',user:{id:1}})
    return Response.json({id:7,status:'reversed',reversal_reason:'错误确认'})
  })
  await callBackend('login',{})
  const result=await callBackend('reverseMaterialIssue',{
    issueId:7,reason:'  错误确认  ',warehouse_id:999})
  assert.equal(result.status,'reversed')
  assert.equal(calls.at(-1).path,'/api/v1/material-issues/7/reverse')
  assert.deepEqual(JSON.parse(calls.at(-1).body),{reason:'错误确认'})
  const count=calls.length
  for(const payload of [
    {issueId:0,reason:'错误确认'},
    {issueId:'../users',reason:'错误确认'},
    {issueId:7,reason:'  '},
    {issueId:7,reason:'x'.repeat(201)},
    {issueId:7,reason:'带\n换行'},
  ])await assert.rejects(callBackend('reverseMaterialIssue',payload))
  assert.equal(calls.length,count)
})
