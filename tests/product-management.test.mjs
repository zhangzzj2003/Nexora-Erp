import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, ref, watch } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createProductActions } from '../src/renderer/src/store/modules/product-actions.ts'
import { productBody, productModelBody, productModelDeleteBody, productQueryBody, productBomBody, validateProductResult } from '../src/shared/product-api.ts'
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

// 删除请求只带并发版本与原因；目录拒绝墓碑，历史审计仍能读取旧快照。
test('产品软删除校验版本、原因和回执，兼容缺省删除字段的旧历史', () => {
  assert.deepEqual(productModelDeleteBody({id:1,version:2,reason:' 清理空系列 ',deleted_at:'不得透传'}),
    {version:2,reason:'清理空系列'})
  for (const value of [{version:0,reason:'清理'}, {version:1.5,reason:'清理'}, {version:1,reason:' '},
    {version:1,reason:8}, {version:1,reason:'长'.repeat(501)}]) assert.throws(()=>productModelDeleteBody(value))
  const tombstone={deleted_at:'2026-10-16 08:00:00',deleted_by:1,deletion_reason:'清理'}
  const deletedModel={...model,...tombstone,version:2,child_count:0}
  const deletedProduct={...product(),...tombstone,version:2,can_produce:false}
  assert.doesNotThrow(()=>validateProductResult('deleteProductModel',deletedModel))
  assert.doesNotThrow(()=>validateProductResult('deleteProduct',deletedProduct))
  assert.throws(()=>validateProductResult('productModels',[deletedModel]),/已删除/)
  assert.throws(()=>validateProductResult('queryProducts',{...page(),items:[deletedProduct]}),/已删除/)
  for (const invalid of [{...deletedModel,child_count:1},{...deletedModel,deleted_by:null},
    {...deletedModel,deleted_at:null},{...deletedModel,deletion_reason:''}])
    assert.throws(()=>validateProductResult('deleteProductModel',invalid))
  for (const invalid of [{...deletedProduct,can_produce:true},{...deletedProduct,deleted_by:null},
    {...deletedProduct,deleted_at:null},{...deletedProduct,deletion_reason:''}])
    assert.throws(()=>validateProductResult('deleteProduct',invalid))
  const change={id:1,before:null,reason:'最早建档',changed_by_name:'管理员',created_at:'2026-10-15'}
  assert.doesNotThrow(()=>validateProductResult('productModelChanges',[{...change,after:model}]))
  assert.doesNotThrow(()=>validateProductResult('productChanges',[{...change,before:product(),after:deletedProduct}]))
  assert.throws(()=>validateProductResult('productModels',[{...model,child_count:-1}]))
  assert.throws(()=>validateProductResult('productDetail',{...product(),deleted_at:42}))
})

test('真实主进程系列和子机型删除固定路径，并拒绝非法编号及伪造删除回执', async t => {
  const previous=process.env.NEXORA_API_URL
  process.env.NEXORA_API_URL='http://127.0.0.1:8123'
  t.after(()=>{if(previous===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=previous})
  const calls=[], tombstone={deleted_at:'2026-10-16 08:00:00',deleted_by:1,deletion_reason:'清理'}
  let output
  t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push([url.pathname,options]);return Response.json(
    url.pathname.endsWith('/login')?{token:'deletion-token',user:{id:1}}:output)})
  await callBackend('login',{})
  for (const [action,path,row] of [
    ['deleteProductModel','/api/v1/product-models/1',{...model,...tombstone,child_count:0,version:2}],
    ['deleteProduct','/api/v1/products/1',{...product(),...tombstone,can_produce:false,version:2}]
  ]) {
    output=row
    await callBackend(action,{id:1,version:1,reason:' 清理 ',ignored:'不能透传'})
    assert.equal(calls.at(-1)[0],path);assert.equal(calls.at(-1)[1].method,'DELETE')
    assert.deepEqual(JSON.parse(calls.at(-1)[1].body),{version:1,reason:'清理'})
    const count=calls.length
    await assert.rejects(callBackend(action,{id:'../auth',version:1,reason:'清理'}))
    await assert.rejects(callBackend(action,{id:1,version:0,reason:'清理'}))
    await assert.rejects(callBackend(action,{id:1,version:1,reason:' '}))
    assert.equal(calls.length,count)
    output={...row,deleted_at:null}
    await assert.rejects(callBackend(action,{id:1,version:1,reason:'清理'}),/删除结果不完整/)
  }
})

test('旧服务忽略新字段前阻止写入，能力核对期间切换会话也不能提交', async t => {
  const calls=[]
  let capable=false, switchSession=false
  const previous=process.env.NEXORA_API_URL
  process.env.NEXORA_API_URL='http://127.0.0.1:8123'
  t.after(()=>{if(previous===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=previous})
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    calls.push([url.pathname,options.method])
    if(url.pathname.endsWith('/login'))return Response.json({token:'feature-token',user:{id:1}})
    if(url.pathname.endsWith('/product-bom-features')) {
      if(switchSession)await callBackend('logout',undefined)
      return capable?Response.json({independent_uses:true,component_bom_versions:true}):Response.json({detail:'Not Found'},{status:404})
    }
    return Response.json(product())
  })
  await callBackend('login',{})
  const input={kind:'semi_finished',model_id:null,configuration_name:'',material_id:11,can_sell:false}
  await assert.rejects(callBackend('createProduct',input),/先升级 ERP 服务/)
  assert.equal(calls.some(([path,method])=>path==='/api/v1/products'&&method==='POST'),false)
  await assert.rejects(callBackend('createBom',{product_material_id:11,base_quantity:'1',note:'',
    lines:[{component_material_id:22,quantity:'1',component_bom_id:7}]}),/先升级 ERP 服务/)
  assert.equal(calls.some(([path,method])=>path==='/api/v1/boms'&&method==='POST'),false)
  capable=true
  await callBackend('createProduct',input)
  assert.equal(calls.filter(([path,method])=>path==='/api/v1/products'&&method==='POST').length,1)
  switchSession=true
  await assert.rejects(callBackend('createProduct',input),/账号已切换/)
  assert.equal(calls.filter(([path,method])=>path==='/api/v1/products'&&method==='POST').length,1)
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
  fail=false;const saved=await f.actions.saveProduct();assert.equal(saved.id,1)
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

// 新建成功返回真实身份供目录定位；失败保留草稿，不伪造成功节点。
test('新建系列返回服务端身份，失败保留输入', async t => {
  let fail=true
  const f=fixture(t,async action=>action==='createProductModel'?(fail?Promise.reject(Error('编码重复')):model):action==='productModels'?[model]:page())
  f.state.productModelForm.value={id:0,version:0,code:'A100',name:'控制系列',notes:'保留说明',reason:''}
  assert.equal(await f.actions.saveProductModel(),undefined)
  assert.equal(f.state.productModelForm.value.notes,'保留说明')
  fail=false
  const saved=await f.actions.saveProductModel()
  assert.equal(saved.id,1);assert.equal(f.state.productModelForm.value.code,'')
})

// 删除的是系列目录资料，不能顺带丢失用户正在填写的产品或 BOM 草稿。
test('删除空系列清理失效选择并刷新，关联冲突和错误回执保留现场', async t => {
  const empty={...model,child_count:0}, tombstone={...model,child_count:0,version:2,
    deleted_at:'2026-10-16 08:00:00',deleted_by:1,deletion_reason:'系列已弃用'}
  let failure='仍有子机型', wrong=false
  const f=fixture(t,async action=>{
    if(action==='deleteProductModel') {if(failure)throw Error(failure);return {...tombstone,id:wrong?2:1}}
    return action==='productModels'?[]:{items:[],page:1,page_size:20,total:0}
  })
  f.state.productModels.value=[empty];f.state.productQuery.value.model_id=1
  f.state.productDetailId.value=1
  f.state.productForm.value={...f.state.productForm.value,model_id:1,configuration_name:'保留输入'}
  f.state.bomForm.value.note='保留组件草稿'
  assert.equal(await f.actions.deleteProductModel(empty,'系列已弃用'),false)
  assert.equal(f.state.productQuery.value.model_id,1);assert.equal(f.state.productModels.value.length,1)
  assert.match(f.state.error.value,/仍有子机型/)
  failure='';wrong=true
  assert.equal(await f.actions.deleteProductModel(empty,'系列已弃用'),false)
  assert.equal(f.state.productModels.value.length,1);assert.match(f.state.error.value,/另一产品系列/)
  wrong=false
  assert.equal(await f.actions.deleteProductModel(empty,'系列已弃用'),true)
  assert.deepEqual(f.calls.find(([action])=>action==='deleteProductModel')[1],{id:1,version:1,reason:'系列已弃用'})
  assert.equal(f.state.productDetailId.value,0);assert.equal(f.state.productQuery.value.model_id,null)
  assert.equal(f.state.productForm.value.model_id,null);assert.equal(f.state.productForm.value.configuration_name,'保留输入')
  assert.equal(f.state.bomForm.value.note,'保留组件草稿');assert.deepEqual(f.state.productModels.value,[])
  assert.equal(f.calls.at(-2)[0],'queryProducts');assert.equal(f.calls.at(-2)[1].page,1)
})

// 全局停用只关闭新生产，不修改销售采购用途，也不改任何 BOM 历史版本的状态。
test('子机型停用与启用保留其他资料，同步 BOM 生产资格后刷新当前详情', async t => {
  let current={...product(),model_id:1,can_sell:false,can_purchase:true,can_produce:true}
  const bom={id:7,version:1,product_material_id:11,product_name:'测试产品',product_sku:'EL-PC-11',product_unit:'件',
    base_quantity:'1',status:'active',lines:[],product_can_produce:true}
  const unrelated={...bom,id:8,product_material_id:22}
  const f=fixture(t,async(action,payload)=>{
    if(action==='updateProduct')return current={...current,can_produce:payload.can_produce,version:current.version+1}
    if(action==='productDetail')return current
    if(action==='productChanges')return []
    if(action==='productBoms')return [{...bom,product_can_produce:current.can_produce}]
    return action==='productModels'?[model]:{...page(),items:[current]}
  })
  f.state.productDetailId.value=1;f.state.productDetailRecord.value=current
  f.state.productResult.value={...page(),items:[current]}
  f.state.boms.value=[bom,unrelated];f.state.productBomRecords.value=[bom];f.state.bomDetailRecord.value=bom
  f.state.productForm.value={...f.state.productForm.value,configuration_name:'未保存草稿'}
  assert.equal(await f.actions.applyProductLifecycle(current,'disable','停止新生产'),true)
  const payload=f.calls.find(([action])=>action==='updateProduct')[1]
  assert.deepEqual(payload,{id:1,version:1,kind:'finished',model_id:1,configuration_name:'标准版',
    can_sell:false,can_purchase:true,can_produce:false,reason:'停止新生产'})
  assert.equal(f.state.productResult.value.items[0].can_produce,false)
  assert.equal(f.state.productDetailRecord.value.can_produce,false)
  assert.equal(f.state.boms.value.find(row=>row.id===7).product_can_produce,false)
  assert.equal(f.state.boms.value.find(row=>row.id===8).product_can_produce,true)
  assert.equal(f.state.productBomRecords.value[0].product_can_produce,false)
  assert.equal(f.state.bomDetailRecord.value.product_can_produce,false)
  assert.equal(f.state.boms.value[0].status,'active');assert.equal(f.state.productForm.value.configuration_name,'未保存草稿')
  assert.equal(await f.actions.applyProductLifecycle(current,'enable','恢复新生产'),true)
  assert.equal(f.state.productDetailRecord.value.can_produce,true)
  assert.equal(f.state.boms.value[0].product_can_produce,true)
  assert.equal(f.state.boms.value[0].status,'active')
})

test('子机型软删除清空选中目标，失败仍保留确认草稿与 BOM 视图', async t => {
  const current={...product(),can_sell:true,can_purchase:false,can_produce:true}
  let failure=true
  const f=fixture(t,async action=>{
    if(action==='deleteProduct') {if(failure)throw Error('仍有未完工工单');return {...current,version:2,can_produce:false,
      deleted_at:'2026-10-16 08:00:00',deleted_by:1,deletion_reason:'不再维护此机型'}}
    return action==='productModels'?[model]:{items:[],page:1,page_size:20,total:0}
  })
  f.state.productDetailId.value=1;f.state.productDetailRecord.value=current
  f.state.productResult.value={...page(),items:[current]}
  f.state.productForm.value={...f.state.productForm.value,configuration_name:'保留配置草稿'}
  assert.equal(await f.actions.applyProductLifecycle(current,'delete','不再维护此机型'),false)
  assert.equal(f.state.productDetailId.value,1);assert.equal(f.state.productDetailRecord.value.id,1)
  assert.equal(f.state.productForm.value.configuration_name,'保留配置草稿');assert.match(f.state.error.value,/未完工工单/)
  failure=false
  assert.equal(await f.actions.applyProductLifecycle(current,'delete','不再维护此机型'),true)
  assert.deepEqual(f.calls.find(([action])=>action==='deleteProduct')[1],{id:1,version:1,reason:'不再维护此机型'})
  assert.equal(f.state.productDetailId.value,0);assert.equal(f.state.productDetailRecord.value,null)
  assert.equal(f.state.productResult.value.total,0);assert.deepEqual(f.state.productBomRecords.value,[])
  assert.equal(f.state.productForm.value.configuration_name,'保留配置草稿')
})

test('生命周期写入受忙碌断线权限保护，跨会话迟到回执不能重新填回旧资料', async t => {
  for(const kind of ['series','product']) for(const switchKind of ['certificate','account','permission'])
    await t.test(`${kind}-${switchKind}`,async t=>{
    const delayed=deferred()
    const f=fixture(t,async()=>delayed.promise)
    const mutate=()=>kind==='series'?f.actions.deleteProductModel(model,'清理'):
      f.actions.applyProductLifecycle({...product(),can_produce:true},'disable','暂停生产')
    f.state.busy.value=true;assert.equal(await mutate(),false)
    f.state.busy.value=false;f.state.connectionLost.value=true;assert.equal(await mutate(),false)
    f.state.connectionLost.value=false;f.state.user.value.permissions=['inventory.view'];assert.equal(await mutate(),false)
    assert.equal(f.calls.length,0)
    f.state.user.value.permissions=['inventory.view','catalog.manage']
    const pending=mutate()
    if(switchKind==='certificate')f.state.server.value={...f.state.server.value,fingerprint:'new-cert'}
    if(switchKind==='account')f.state.user.value={...f.state.user.value,id:2}
    if(switchKind==='permission')f.state.user.value.permissions=['inventory.view']
    delayed.resolve(kind==='series'?{...model,child_count:0,version:2,deleted_at:'2026-10-16',deleted_by:1,deletion_reason:'清理'}:
      {...product(),version:2,can_produce:false})
    assert.equal(await pending,false)
    assert.equal(f.state.productDetailRecord.value,null);assert.equal(f.state.productResult.value,null)
    assert.equal(f.calls.some(([action])=>action==='queryProducts'),false)
    assert.equal(f.state.busy.value,false)
  })
})

// busy 解锁会触发同步观察者；即使接口已返回，也不能在这道边界后回填另一账号。
test('生命周期写入解锁瞬间切换账号，旧回执不能清新账号选择或发起读取', async t => {
  for(const kind of ['series','product']) await t.test(kind,async t=>{
    const fresh={...product(),can_produce:true,material:{...material(),name:'新账号的同号产品'}}
    const f=fixture(t,async action=>{
      if(action==='deleteProductModel')return {...model,child_count:0,version:2,deleted_at:'2026-10-16',deleted_by:1,deletion_reason:'清理'}
      if(action==='updateProduct')return {...product(),version:2,can_produce:false}
      if(action==='productDetail')return fresh
      if(action==='productChanges' || action==='productBoms')return []
      return action==='productModels'?[model]:{...page(),items:[fresh]}
    })
    let switched=false
    const stop=watch(f.state.busy,active=>{
      if(active || switched)return
      switched=true;f.state.user.value={...f.state.user.value,id:2}
      // 不同账号可能有相同数字 ID，仍须以会话身份区分这份新草稿与选择。
      f.state.productModels.value=[model]
      f.state.productForm.value={...f.state.productForm.value,model_id:1,configuration_name:'新账号未保存配置'}
      f.state.productDetailId.value=1;f.state.productDetailRecord.value=fresh
    },{flush:'sync'})
    t.after(stop)
    const saved=kind==='series'?await f.actions.deleteProductModel(model,'清理'):
      await f.actions.applyProductLifecycle({...product(),can_produce:true},'disable','暂停生产')
    assert.equal(saved,false)
    assert.equal(f.calls.some(([action])=>['queryProducts','productModels','productDetail'].includes(action)),false)
    assert.equal(f.state.productModels.value[0].id,1)
    assert.equal(f.state.productForm.value.model_id,1)
    assert.equal(f.state.productForm.value.configuration_name,'新账号未保存配置')
    assert.equal(f.state.productDetailRecord.value.material.name,'新账号的同号产品')
    assert.equal(f.state.productDetailRecord.value.can_produce,true)
  })
})

// 联合保存已经成功但刷新还在途中时换实例，不能把旧身份作为“新子机型”发给页面。
test('子机型保存后的刷新跨实例时不返回旧导航身份', async t => {
  const reading=deferred(), reply=deferred()
  const f=fixture(t,async action=>{
    if(action==='createProduct')return product()
    if(action==='productModels')return [model]
    reading.resolve();return reply.promise
  })
  f.state.productForm.value={...f.state.productForm.value,mode:'existing',material_id:11}
  const pending=f.actions.saveProduct()
  await reading.promise
  f.state.server.value={id:'other',fingerprint:'new'}
  reply.resolve(page())
  assert.equal(await pending,undefined)
  assert.equal(f.state.productForm.value.material_id,0)
})
