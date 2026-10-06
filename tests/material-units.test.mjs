import assert from 'node:assert/strict'
import { test } from 'node:test'
import { materialUnitBody, validateMaterialUnitResult } from '../src/shared/material-unit-api.ts'
import { materialBody } from '../src/shared/material-validation.ts'
import { materialDraft, materialInput } from '../src/renderer/src/views/workspace/catalog/material-form.ts'
import { defaultMaterialUnit, materialUnitOptions } from '../src/renderer/src/views/workspace/catalog/unit-options.ts'
import { createCatalogActions } from '../src/renderer/src/store/modules/catalog-actions.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { routeByKey, routeGroupByKey, canVisitRoute } from '../src/renderer/src/router/workspace-routes.ts'
import { callBackend } from '../src/main/backend.ts'

const unit = {id:1,name:'件',enabled:true,notes:'',version:2,created_at:'2026-10-07',material_count:3}
const disabled = {...unit,id:2,name:'条',enabled:false}

test('单位目录的启用过滤、原单位保留及空目录都使用真实目录数据', () => {
  assert.deepEqual(materialUnitOptions([unit,disabled],'条',false),[{value:'件',label:'件'}])
  const editOptions=materialUnitOptions([unit,disabled],'条',true)
  assert.equal(editOptions[1].value,'条')
  assert.match(editOptions[1].label,/已停用/)
  assert.deepEqual(materialUnitOptions([unit,disabled],'件',true),[{value:'件',label:'件'}])
  assert.equal(defaultMaterialUnit([disabled,unit]),'件')
  assert.equal(defaultMaterialUnit([disabled]),'')
  assert.equal(defaultMaterialUnit([{...unit,name:'米'}]),'米')
  // 窗口里没有临时创建选项，新增单位只能先到独立管理表。
  assert.deepEqual(materialUnitOptions([],'未知单位',true),[])
})

test('物料提交绑定目录编号，并保留停用原值；未知或新选停用单位被拒绝', () => {
  const draft=materialDraft()
  draft.name='测试物料'
  const input=materialInput(draft,false,[unit,disabled])
  assert.equal(input.unit_id,1)
  assert.equal(materialBody(input,false).unit_id,1)
  assert.equal('original_unit' in input,false)
  assert.throws(()=>materialInput({...draft,unit:'条'},false,[unit,disabled]),/停用/)
  assert.throws(()=>materialInput({...draft,unit:'未知'},false,[unit]),/目录/)
  const edit=materialDraft({unit:'条',category_code:'HW-FA',id:8,version:3})
  assert.equal(materialInput(edit,true,[unit,disabled]).unit_id,2)
  for (const id of [true,0,-1,'1',1.5]) assert.throws(()=>materialBody({...input,unit_id:id},false),/编号/)
})

test('单位边界校验拒绝非法状态、过期版本和损坏响应，白名单不传 UI 字段', () => {
  assert.deepEqual(materialUnitBody({...unit,name:' 件 ',reason:' 核对 ',id:9},true),
    {name:'件',enabled:true,notes:'',version:2,reason:'核对'})
  for(const bad of [{...unit,name:' '},{...unit,name:'字'.repeat(21)}, {...unit,enabled:1},
    {...unit,version:true},{...unit,notes:'字'.repeat(501)},{...unit,reason:' '}]) {
    assert.throws(()=>materialUnitBody(bad,true))
  }
  validateMaterialUnitResult('materialUnits',[unit,disabled])
  for(const value of [{items:[unit]},[unit,unit],[{...unit,enabled:1}], [{...unit,material_count:-1}], [{id:1}]]) {
    assert.throws(()=>validateMaterialUnitResult('materialUnits',value))
  }
})

test('单位管理属于基础资料并沿用资料查看权限', () => {
  const route=routeByKey('materialUnits')
  assert.equal(route.path,'/workspace/material-units')
  assert.equal(route.label,'单位管理')
  assert.equal(routeGroupByKey('materialUnits').key,'catalog')
  assert.equal(canVisitRoute(route,['inventory.view']),true)
  assert.equal(canVisitRoute(route,['catalog.manage']),false)
})

test('单位写操作成功才关闭草稿，冲突或断开桥接时保留修改', async t => {
  const original=globalThis.window
  t.after(()=>{globalThis.window=original})
  const calls=[]
  let fail=false
  globalThis.window={nexora:{callApi:async(action,data)=>{
    if(fail)throw Error('版本冲突')
    calls.push([action,structuredClone(data)])
  }}}
  const state=createAppState()
  const actions=createCatalogActions(state,async action=>{try{await action()}catch{/* 模拟统一消息入口保留失败草稿。 */}})
  assert.equal(await actions.saveMaterialUnit({name:'米',notes:'线材长度',enabled:true}),true)
  assert.equal(await actions.saveMaterialUnit({...unit,reason:'停用',enabled:false},1),true)
  assert.equal(calls[1][0],'updateMaterialUnit')
  assert.equal(calls[1][1].id,1)
  assert.equal('material_count' in calls[1][1],false)
  fail=true
  assert.equal(await actions.saveMaterialUnit({...unit,reason:'冲突'},1),false)
  globalThis.window={}
  assert.equal(await actions.saveMaterialUnit({...unit,reason:'断开'},1),false)
})

test('共享单位目录随业务刷新，查看权限撤销后清除旧目录', async t => {
  const original=globalThis.window
  t.after(()=>{globalThis.window=original})
  const state=createAppState()
  let user={id:1,roles:[],permissions:['inventory.view']}
  state.user.value=user
  const calls=[]
  globalThis.window={nexora:{callApi:async action=>{
    calls.push(action)
    if(action==='me')return user
    return action==='materialUnits'?[unit]:[]
  }}}
  const loader=createDataLoader(state,code=>state.user.value.permissions.includes(code),()=>{})
  await loader.refreshData()
  assert.deepEqual(state.materialUnits.value,[unit])
  assert.ok(calls.includes('materialUnits'))
  user={...user,permissions:[]}
  calls.length=0
  await loader.refreshData()
  assert.deepEqual(state.materialUnits.value,[])
  assert.ok(!calls.includes('materialUnits'))
})

test('单位 IPC 使用固定地址，校验请求和响应，拒绝路径注入', async t => {
  const previous=process.env.NEXORA_API_URL
  t.after(()=>{if(previous===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=previous})
  process.env.NEXORA_API_URL='http://127.0.0.1:8123'
  const calls=[]
  let broken=false
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    calls.push([url.pathname,options.method,options.body])
    if(url.pathname.endsWith('/auth/login'))return Response.json({token:'test',user:{id:1}})
    return Response.json(broken ? [{}] : options.method==='GET' && url.pathname==='/api/v1/material-units' ? [unit] : unit)
  })
  await callBackend('login',{})
  await callBackend('materialUnits',undefined)
  await callBackend('materialUnitDetail',{id:1})
  await callBackend('createMaterialUnit',{...unit,extra:'discard'})
  assert.equal(calls.at(-1)[0],'/api/v1/material-units')
  assert.deepEqual(JSON.parse(calls.at(-1)[2]),{name:'件',enabled:true,notes:''})
  await callBackend('updateMaterialUnit',{...unit,reason:'核对'})
  assert.equal(calls.at(-1)[0],'/api/v1/material-units/1')
  await assert.rejects(callBackend('materialUnitDetail',{id:'../users'}),/编号/)
  broken=true
  await assert.rejects(callBackend('materialUnits',undefined),/单位/)
})
