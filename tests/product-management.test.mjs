import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, ref } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createProductActions } from '../src/renderer/src/store/modules/product-actions.ts'
import { productBody, productModelBody, productQueryBody, productBomBody, validateProductResult } from '../src/shared/product-api.ts'
import { callBackend } from '../src/main/backend.ts'

const material = (id = 11) => ({id,sku:`EL-PC-${id}`,name:'测试产品',unit:'件',version:1,created_at:'2026-10-15 08:00:00',
  ...Object.fromEntries(['category_code','specification','package','brand','manufacturer_part_number','electrical_value','tolerance',
    'rated_voltage','rated_power','temperature_range','compliance','notes'].map(key=>[key,''])),
  extra_attributes:[],supplier_ids:[]})
const product = (id = 1) => ({id,material_id:11,kind:'finished',model_id:null,configuration_name:'标准版',version:1,
  created_by:1,created_at:'2026-10-15 08:00:00',model_code:'',model_name:'',material:material()})
const model = {id:1,code:'A100',name:'机型A',notes:'',version:1,created_by:1,created_at:'2026-10-15 08:00:00'}
const page = (id=1) => ({items:[product(id)],page:1,page_size:20,total:1})
const deferred = () => {let resolve, reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
function fixture(t, handler = async action => action==='productModels'?[model]:page()) {
  const previous=globalThis.window, state=createAppState(), calls=[]
  state.user.value={id:1,permissions:['inventory.view','catalog.manage','production.view','bom.create'],roles:[]}
  state.server.value={id:'test',fingerprint:'cert'}
  globalThis.window={nexora:{callApi:async(action,payload)=>{calls.push([action,payload]);return handler(action,payload)}}}
  const scope=effectScope(), actions=scope.run(()=>createProductActions(state))
  t.after(()=>{scope.stop();globalThis.window=previous})
  return {state,actions,calls}
}

test('产品 IPC 白名单、建档互斥、版本及数量分页边界', () => {
  const base={kind:'finished',model_id:null,configuration_name:' 标准版 '}
  assert.deepEqual(productBody({...base,material_id:11,ignored:'不得透传'},false),{...base,configuration_name:'标准版',material_id:11})
  for(const input of [{...base},{...base,material_id:1,material:{}},{...base,material_id:'../1'},
    {...base,material_id:1,kind:'unknown'},{...base,material_id:1,model_id:-1}]) assert.throws(()=>productBody(input,false))
  assert.throws(()=>productBody({...base,version:1,reason:' '},true))
  assert.throws(()=>productBody({...base,version:0,reason:'更正'},true))
  assert.deepEqual(productBody({...base,version:2,reason:' 更正 ',material:material()},true).version,2)
  assert.throws(()=>productModelBody({code:' ',name:'A',notes:''},false))
  assert.throws(()=>productModelBody({code:'A',name:'A',notes:'',version:1},true))
  assert.throws(()=>productQueryBody({query:'',kind:null,model_id:null,page:1,page_size:101}))
  assert.throws(()=>validateProductResult('queryProducts',{...page(),items:[product(),product()]}))
  assert.throws(()=>validateProductResult('productDetail',{...product(),material_id:99}))
  assert.doesNotThrow(()=>validateProductResult('productDetail',product()))
  const bom={product_material_id:11,base_quantity:'1',note:'',source_bom_id:7,lines:[{component_material_id:22,quantity:'2'}]}
  assert.deepEqual(productBomBody({...bom,ignored:'drop'}),bom)
  for(const bad of [{...bom,source_bom_id:'../7'}, {...bom,lines:[{component_material_id:11,quantity:'2'}]},
    {...bom,lines:[...bom.lines,...bom.lines]}, {...bom,base_quantity:'1.0001'}]) assert.throws(()=>productBomBody(bad))
  assert.throws(()=>validateProductResult('bomDetail',{id:7}))
})

test('真实主进程产品路径固定，输入和服务端响应都验证', async t => {
  const previous=process.env.NEXORA_API_URL
  process.env.NEXORA_API_URL='http://127.0.0.1:8123'
  t.after(()=>{if(previous===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=previous})
  const calls=[];let output=product()
  t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push([url.pathname+url.search,options]);return Response.json(url.pathname.endsWith('/login')?{token:'test-token',user:{id:1}}:output)})
  await callBackend('login',{})
  await callBackend('createProduct',{kind:'finished',model_id:null,configuration_name:'',material_id:11,unexpected:'drop'})
  assert.equal(calls.at(-1)[0],'/api/v1/products')
  assert.equal(JSON.parse(calls.at(-1)[1].body).unexpected,undefined)
  output=page();await callBackend('queryProducts',{query:'',kind:null,model_id:null,page:1,page_size:20})
  assert.equal(calls.at(-1)[0],'/api/v1/products/query')
  output=[];await callBackend('productBoms',{materialId:11})
  assert.equal(calls.at(-1)[0],'/api/v1/boms?product_material_id=11')
  await assert.rejects(callBackend('productDetail',{id:'../auth'}))
  output={id:1};await assert.rejects(callBackend('productDetail',{id:1}),/产品资料不完整/)
})

test('分页拒绝迟到响应，同账号刷新保留结果，断线和换证书使读取失效', async t => {
  let read=0;const delayed=deferred()
  const f=fixture(t,async action=>action==='productModels'?[model]:++read===1?delayed.promise:page(2))
  const first=f.actions.queryProducts();await f.actions.queryProducts();delayed.resolve(page())
  await first;assert.equal(f.state.productResult.value.items[0].id,2)
  f.state.user.value={...f.state.user.value,permissions:[...f.state.user.value.permissions].reverse()}
  assert.equal(f.state.productResult.value.items[0].id,2)
  const next=deferred();globalThis.window.nexora.callApi=async action=>action==='productModels'?[model]:next.promise
  const pending=f.actions.queryProducts()
  f.state.connectionLost.value=true;f.state.connectionLost.value=false
  next.resolve(page());await pending;assert.equal(f.state.productResult.value,null)
  await f.actions.queryProducts()
  // 机型历史和错误弹窗同样不能跨服务实例保留。
  f.state.productModelChanges.value=[{id:1,reason:'旧实例的机型历史'}]
  f.state.productsError.value='旧查询失败';f.state.productDetailError.value='旧产品失败';f.state.bomDetailError.value='旧 BOM 失败'
  f.state.server.value={...f.state.server.value,fingerprint:'other-cert'}
  assert.equal(f.state.productResult.value,null)
  assert.deepEqual(f.state.productModelChanges.value,[])
  assert.equal(f.state.productsError.value,'');assert.equal(f.state.productDetailError.value,'');assert.equal(f.state.bomDetailError.value,'')
})

test('产品详情对无生产权限账号不读取 BOM，旧详情不能覆盖新目标', async t => {
  const old=deferred()
  const f=fixture(t,async(action,payload)=>action==='productDetail'?(payload.id===1?old.promise:product(2)):
    action==='productChanges'?[]:action==='productBoms'?[]:[model])
  f.state.user.value.permissions=['inventory.view']
  const first=f.actions.openProduct(1);await f.actions.openProduct(2);old.resolve(product());await first
  assert.equal(f.state.productDetailRecord.value.id,2)
  assert.equal(f.calls.some(([action])=>action==='productBoms'),false)
  f.actions.closeProduct();assert.equal(f.state.productDetailId.value,0)
})

test('快捷建产品失败保留草稿，成功只带回 BOM 产出物料；写入跨会话响应不回填', async t => {
  let fail=true
  const f=fixture(t,async action=>action==='productModels'?[model]:action==='createProduct'?(fail?Promise.reject(Error('重复建档')):product()):page())
  f.state.productForm.value={...f.state.productForm.value,mode:'existing',material_id:11,configuration_name:'长续航'}
  f.state.bomForm.value.lines=[{component_material_id:22,quantity:'4'}]
  const component=f.state.bomForm.value.lines[0]
  f.state.productReturnToBom.value=true;f.state.productEditorOpen.value=true
  await f.actions.saveProduct()
  assert.equal(f.state.productEditorOpen.value,true);assert.equal(f.state.productForm.value.configuration_name,'长续航')
  fail=false;await f.actions.saveProduct()
  assert.equal(f.state.bomForm.value.product_material_id,11)
  assert.equal(f.state.bomForm.value.lines[0],component)
  assert.equal(f.state.productEditorOpen.value,false)
  const late=deferred()
  globalThis.window.nexora.callApi=()=>late.promise
  f.state.productForm.value={...f.state.productForm.value,mode:'existing',material_id:11}
  const pending=f.actions.saveProduct()
  f.state.server.value={id:'other',fingerprint:'new'}
  late.resolve(product());await pending
  assert.equal(f.state.bomForm.value.product_material_id,0)
  assert.equal(f.state.productForm.value.material_id,0)
})

test('派生草稿复制独立明细，拒绝取消来源、断线、忙碌和撤权', t => {
  const f=fixture(t)
  const source={id:7,status:'active',base_quantity:'2',lines:[{component_material_id:22,quantity:'4'}]}
  assert.equal(f.actions.prepareProductBom(11,source),true)
  f.state.bomForm.value.lines[0].quantity='8'
  assert.equal(f.actions.prepareProductBom(11,source),true)
  assert.equal(f.state.bomForm.value.lines[0].quantity,'8')
  assert.equal(source.lines[0].quantity,'4');assert.equal(f.state.bomForm.value.source_bom_id,7)
  assert.equal(f.actions.prepareProductBom(11,{...source,status:'cancelled'}),false)
  f.state.connectionLost.value=true;assert.equal(f.actions.prepareProductBom(11,source),false)
  f.state.connectionLost.value=false;f.state.busy.value=true;assert.equal(f.actions.prepareProductBom(11,source),false)
  f.state.busy.value=false;f.state.user.value.permissions=['inventory.view'];assert.equal(f.actions.prepareProductBom(11,source),false)
})
