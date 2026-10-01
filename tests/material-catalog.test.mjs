import assert from 'node:assert/strict'
import { test } from 'node:test'
import { materialDraft, materialInput, matchesMaterial } from '../src/renderer/src/views/workspace/catalog/material-form.ts'
import { materialBody, validateMaterialResult } from '../src/shared/material-validation.ts'
import { createCatalogActions } from '../src/renderer/src/store/modules/catalog-actions.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { callBackend } from '../src/main/backend.ts'

const categories = [{code:'EL',name:'电子类',children:[{code:'EL-SR',name:'贴片电阻'}]}]
const row = {...materialInput(materialDraft(), false), id:1, sku:'EL-SR-000001', version:3,
  name:'电阻', category_code:'EL-SR', specification:'10kΩ ±1%', package:'0603', brand:'示例', manufacturer_part_number:'RC0603-10K'}

test('新增省略编码，编辑保留版本；草稿与共享快照分离，重新新增清空旧参数', () => {
  const edit = materialDraft(row)
  edit.name = '新名称'
  assert.equal(row.name, '电阻')
  assert.equal(edit.group_code, 'EL')
  assert.deepEqual(Object.keys(materialInput(edit, true)).filter(key => ['sku','version'].includes(key)), ['sku','version'])
  const fresh = materialDraft()
  assert.equal(fresh.package, '')
  assert.equal(fresh.category_code, '')
  const create = materialInput({...fresh, category_code:'EL-SC'}, false)
  assert.equal('sku' in create, false)
  assert.equal('version' in create, false)
  assert.equal('group_code' in create, false)
})

test('分类筛选、未分类和独立规格/封装/品牌/制造商料号搜索', () => {
  for (const query of ['10kΩ','0603','示例',' rc0603-10k ','贴片电阻']) {
    assert.equal(matchesMaterial(row, query, 'EL-SR', categories), true)
  }
  assert.equal(matchesMaterial(row, '', 'EL-SC', categories), false)
  assert.equal(matchesMaterial(row, '', 'unclassified', categories), false)
  assert.equal(matchesMaterial({...row,category_code:''}, '', 'unclassified', categories), true)
})

test('物料输入白名单及严格响应，避免把旧服务漏字段当成有效空值', () => {
  const body = materialBody({...materialInput(materialDraft(row), true), id:1, group_code:'EL', _X_ROW_KEY:'ui'}, true)
  assert.equal('id' in body, false)
  assert.equal('group_code' in body, false)
  assert.equal('_X_ROW_KEY' in body, false)
  for (const bad of [{...body,version:true},{...body,version:0},{...body,name:' '},{...body,notes:'字'.repeat(1001)}]) {
    assert.throws(() => materialBody(bad, true), /物料|填写/)
  }
  validateMaterialResult('materials', [row])
  validateMaterialResult('materialCategories', categories)
  assert.throws(() => validateMaterialResult('materials',[{id:1,sku:'R',name:'旧物料',unit:'件'}]), /升级服务端/)
  assert.throws(() => validateMaterialResult('materialCategories',[{...categories[0],children:[{code:'PL-OT',name:'错误归属'}]}]), /分类响应/)
  assert.throws(() => validateMaterialResult('materials',{items:[row]}), /响应格式/)
})

test('保存失败保留全部参数和版本；成功编辑发送普通对象，旧版本由服务端处理', async t => {
  const original = globalThis.window
  t.after(() => {globalThis.window = original})
  const state = createAppState()
  let fail = true
  const calls = []
  globalThis.window = {nexora:{async callApi(action, input) {
    calls.push([action,structuredClone(input)])
    if (fail) throw Error('版本冲突')
    return row
  }}}
  const actions = createCatalogActions(state, async run => {try {await run()} catch {/* 与统一反馈一致，失败保留编辑窗口。 */}})
  const draft = materialDraft(row)
  assert.equal(await actions.saveMaterial(materialInput(draft,true),1), false)
  assert.equal(draft.manufacturer_part_number, row.manufacturer_part_number)
  assert.equal(draft.version, 3)
  fail = false
  assert.equal(await actions.saveMaterial(materialInput(draft,true),1), true)
  assert.equal(calls.at(-1)[0], 'updateMaterial')
  assert.equal(calls.at(-1)[1].version, 3)
  assert.equal(await actions.saveMaterial({name:'旧请求',unit:'件'},1), false)
})

test('IPC 新增由分类分配编码，编辑限制版本，分类目录固定路径', async t => {
  const original = globalThis.fetch
  t.after(() => {globalThis.fetch = original})
  const calls=[]
  globalThis.fetch=async(url, init)=>{
    const path=new URL(url).pathname
    calls.push([path,init.body ? JSON.parse(init.body) : undefined])
    return new Response(JSON.stringify(path.endsWith('/login') ? {token:'test',user:{id:1}}
      : path.endsWith('/material-categories') ? categories : row),{status:200})
  }
  await callBackend('login',{})
  await callBackend('materialCategories',undefined)
  assert.equal(calls.at(-1)[0],'/api/v1/material-categories')
  const draft=materialDraft(row)
  await callBackend('createMaterial',{...materialInput(draft,false),group_code:'EL'})
  assert.equal('sku' in calls.at(-1)[1],false)
  assert.equal('group_code' in calls.at(-1)[1],false)
  await callBackend('updateMaterial',{...materialInput(draft,true),id:1})
  assert.equal(calls.at(-1)[0],'/api/v1/materials/1')
  assert.equal(calls.at(-1)[1].version,3)
  await callBackend('materialDetail',{id:1})
  assert.equal(calls.at(-1)[0],'/api/v1/materials/1')
  await assert.rejects(callBackend('updateMaterial',{id:1,name:'电阻',unit:'件',version:true}),/版本无效/)
})

test('重新打开编辑器读取当前资料，失败和退出后的迟到结果不覆盖快照', async t => {
  const previous=globalThis.window
  t.after(()=>{globalThis.window=previous})
  const state=createAppState()
  state.user.value={id:1,permissions:['inventory.view','catalog.manage']}
  state.materials.value=[row]
  let failure=false, pending=false, resolve
  globalThis.window={nexora:{async callApi(action,input){
    assert.equal(action,'materialDetail')
    assert.equal(input.id,1)
    if(failure) throw Error('资料读取失败')
    if(pending) return new Promise(done=>{resolve=done})
    return {...row,version:4,notes:'另一客户端的资料'}
  }}}
  const actions=createCatalogActions(state,async run=>run())
  assert.equal((await actions.loadMaterial(1)).version,4)
  assert.equal(state.materials.value[0].notes,'另一客户端的资料')
  failure=true
  assert.equal(await actions.loadMaterial(1),undefined)
  assert.match(state.error.value,/资料读取失败/)
  failure=false;pending=true
  const loading=actions.loadMaterial(1)
  state.user.value=null
  resolve({...row,version:5,notes:'退出后的旧响应'})
  assert.equal(await loading,undefined)
  assert.equal(state.materials.value[0].version,4)
})
