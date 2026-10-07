import assert from 'node:assert/strict'
import {test} from 'node:test'
import {productionAssociationInput, validateProductionAssociations} from '../src/shared/production-association-api.ts'
import {callBackend} from '../src/main/backend.ts'
import {associationFixture} from './production-association-fixture.mjs'

// 查询范围、精确数量和权限隐藏在响应边界检查，错误来源不能进入可信展示。
test('关联协议区分采购参考、实物证据并拒绝目标错位及隐藏权限泄露', () => {
  const row = associationFixture(); validateProductionAssociations(row)
  for (const change of [{scope:'product'},{reference_limit:500},{inventory_visible:false,references_included:true},{target:{kind:'work_order',id:9}}]) {
    assert.throws(() => validateProductionAssociations({...row,...change}))
  }
  row.target = {kind:'completion',id:99}; assert.throws(() => validateProductionAssociations(row))
  row.target = {kind:'work_order',id:1}
  row.components[0].issues[0].quantity = 200; assert.throws(() => validateProductionAssociations(row))
  for (const change of [{id:'../users'},{kind:'supplier'},{include_references:'true'},{price:true}]) {
    assert.throws(() => productionAssociationInput({kind:'work_order',id:1,include_references:false,...change}))
  }
})

test('关联 IPC 仅使用固定 GET 地址并校验返回目标范围', async t => {
  const old = globalThis.fetch; t.after(() => {globalThis.fetch = old}); const calls=[]
  globalThis.fetch = async (url,config) => {
    calls.push([new URL(url).pathname+new URL(url).search,config.method])
    const row = associationFixture()
    if (new URL(url).pathname.includes('production-completions')) row.target = {kind:'completion',id:3}
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login') ? {token:'test',user:{id:1}} : row),
      {status:200,headers:{'Content-Type':'application/json'}})
  }
  await callBackend('login',{}); calls.length=0
  await callBackend('productionAssociations',{kind:'work_order',id:1,include_references:false})
  await callBackend('productionAssociations',{kind:'completion',id:3,include_references:true})
  assert.deepEqual(calls,[['/api/v1/work-orders/1/associations?include_references=false','GET'],['/api/v1/production-completions/3/associations?include_references=true','GET']])
  await assert.rejects(callBackend('productionAssociations',{kind:'work_order',id:'../users',include_references:false}))
  assert.equal(calls.length,2)
})
