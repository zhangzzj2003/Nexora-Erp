import assert from 'node:assert/strict'
import { test } from 'node:test'
import { supplierBody, supplierDraft, supplierStatusLabel } from '../src/shared/supplier-api.ts'
import { materialBody } from '../src/shared/material-validation.ts'
import { materialDraft, materialInput } from '../src/renderer/src/views/workspace/catalog/material-form.ts'
import { newSupplierOption, supplierSelectionInput } from '../src/renderer/src/utils/supplier-selection.ts'
import { createCatalogActions } from '../src/renderer/src/store/modules/catalog-actions.ts'
import { callBackend } from '../src/main/backend.ts'

test('输入新供应商只生成草稿，重名复用编号，数字名称保持名称语义', () => {
  const vendors = [{ id: 7, name: 'Acme', version: 1, profile_status: 'pending' }]
  assert.equal(newSupplierOption(' acme ', vendors).value, 'id:7')
  const fresh = newSupplierOption(' 123 ', vendors)
  assert.equal(fresh.value, 'new:123')
  assert.match(fresh.label, /待完善供应商/)
  assert.equal(newSupplierOption(' ', vendors).disabled, true)
  assert.equal(newSupplierOption('字'.repeat(121), vendors).disabled, true)
  assert.equal(newSupplierOption('aCme', [...vendors,{id:8,name:'ACME'}]).disabled, true)
  assert.deepEqual(supplierSelectionInput(['id:7','new:123','id:7']), [{supplier_id:7},{name:'123'}])
  for (const value of ['7', 'id:true', 'id:0', 'id:9007199254740993','new: ']) {
    assert.throws(() => supplierSelectionInput([value]), /供应商选择/)
  }
})

test('物料绑定草稿从当前详情初始化，取消或新开表单不会污染原快照', () => {
  const row = {...materialInput(materialDraft(), false), id:1, sku:'HW-FA-000001', version:2, supplier_ids:[7]}
  const edit = materialDraft(row)
  edit.supplier_selection.push('new:临时名称')
  assert.deepEqual(row.supplier_ids, [7])
  assert.deepEqual(materialInput(edit, true).suppliers, [{supplier_id:7},{name:'临时名称'}])
  assert.deepEqual(materialDraft().supplier_selection, [])
  assert.deepEqual(materialInput({...edit,supplier_selection:[]},true).suppliers, [])
})

test('绑定边界拒绝伪造状态、错误编号与数量，未传字段保留旧调用语义', () => {
  const base={name:'螺丝',unit:'个'}
  assert.equal('suppliers' in materialBody(base,false), false)
  assert.deepEqual(materialBody({...base,suppliers:[]},false).suppliers, [])
  for(const suppliers of [[{}],[{supplier_id:true}],[{name:' '}],[{supplier_id:2,name:'甲'}],
    [{name:'甲',profile_status:'complete'}],Array(21).fill({name:'甲'})]) {
    assert.throws(()=>materialBody({...base,suppliers},false), /供应商/)
  }
})

test('供应商资料白名单及空资料重置，状态不可由客户端标记', () => {
  const draft=supplierDraft({id:7,name:'甲厂',version:2,phone:'13800000000',profile_status:'complete'})
  assert.equal(draft.phone,'13800000000')
  assert.equal(supplierDraft().phone,'')
  const body=supplierBody({...draft,reason:' 补资料 ',contact_name:' 张工 ',profile_status:'complete',id:7},true)
  assert.equal(body.contact_name,'张工')
  assert.equal('profile_status' in body,false)
  assert.equal('id' in body,false)
  assert.equal(supplierStatusLabel({profile_status:'pending'}),'待完善供应商')
  assert.equal(supplierStatusLabel({profile_status:'complete'}),'已完善')
  for(const bad of [{name:' '},{name:'甲',phone:123},{name:'甲',address:'字'.repeat(301)}]) {
    assert.throws(()=>supplierBody(bad,false), /供应商/)
  }
  assert.throws(()=>supplierBody({name:'甲',version:true,reason:'补资料'},true), /版本/)
})

test('Pinia 保存完整普通资料，失败保留资料并返回失败', async t => {
  const original=globalThis.window
  t.after(()=>{globalThis.window=original})
  const calls=[]
  let fail=false
  globalThis.window={nexora:{async callApi(action,payload){
    if(fail) throw Error('版本冲突')
    calls.push([action,structuredClone(payload)])
  }}}
  const actions=createCatalogActions({materialForm:{value:{}},supplierForm:{value:{}}},async run=>{
    try {await run()} catch {/* 模拟统一反馈保留草稿。 */}
  })
  const draft={...supplierDraft({id:7,name:'甲',version:2}),reason:'完善',contact_name:'张工',phone:'13800000000',address:'深圳'}
  assert.equal(await actions.saveSupplier(draft,7),true)
  assert.equal(calls[0][1].address,'深圳')
  assert.equal(calls[0][1].version,2)
  fail=true
  assert.equal(await actions.saveSupplier(draft,7),false)
  assert.equal(draft.contact_name,'张工')
})

test('IPC 编辑详情要求供应商编号快照，拒绝静默忽略标记的旧服务', async t => {
  const original=globalThis.fetch
  t.after(()=>{globalThis.fetch=original})
  const row={...materialInput(materialDraft(),false),id:1,sku:'HW-FA-000001',version:1}
  let supported=false
  const calls=[]
  globalThis.fetch=async(url,init)=>{
    calls.push([new URL(url).pathname+new URL(url).search,init.body])
    return Response.json(new URL(url).pathname.endsWith('/login') ? {token:'test',user:{id:1}}
      : supported ? {...row,supplier_ids:[7]} : row)
  }
  await callBackend('login',{})
  await assert.rejects(callBackend('materialDetail',{id:1,include_suppliers:true}),/升级 ERP 服务/)
  supported=true
  assert.deepEqual((await callBackend('materialDetail',{id:1,include_suppliers:true})).supplier_ids,[7])
  assert.equal(calls.at(-1)[0],'/api/v1/materials/1?include_suppliers=true')
  await assert.rejects(callBackend('materialDetail',{id:1,include_suppliers:'true'}),/查询参数无效/)
  await callBackend('createSupplier',{name:' 甲厂 ',contact_name:' 张工 ',address:' 深圳 ',profile_status:'complete'})
  assert.deepEqual(JSON.parse(calls.at(-1)[1]),{name:'甲厂',contact_name:'张工',address:'深圳'})
})
