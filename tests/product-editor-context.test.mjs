import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { materialDraft, materialInput } from '../src/renderer/src/utils/material-form.ts'

const field = {id:1,category_code:'EL-PC',name:'产品额定输出',kind:'number',unit:'W',options:[],allow_custom:false,required:true,enabled:true,sort_order:0,used:false,deleted:false}
const spec = {field_id:1,category_code:'EL-PC',name:field.name,kind:'number',unit:'W',status:'filled',value:'12.5',source:'设计图纸 A',historical:false}
const categories = [
  {code:'EL',name:'电子类',children:[{code:'EL-PC',name:'控制板',template_version:3,fields:[field]},{code:'EL-OT',name:'其他电子产品',template_version:1,fields:[]}]},
  {code:'PL',name:'塑料类',children:[{code:'PL-HS',name:'外壳',template_version:1,fields:[]}]}
]
const material = () => ({id:11,sku:'EL-PC-000011',name:'NET-8890',unit:'台',version:7,category_code:'EL-PC',
  specification:'NET-8890 标准版',package:'历史封装',brand:'历史制造商',manufacturer_part_number:'OLD-PART',
  electrical_value:'历史电参数',tolerance:'±1%',rated_voltage:'12V',rated_power:'5W',temperature_range:'-20℃～60℃',
  compliance:'RoHS',notes:'产品备注',supplier_ids:[3,8],spec_values:[{...spec}],spec_template_version:3,
  spec_summary:'产品额定输出：12.5W',extra_attributes:[{name:'历史工艺',value:'绝缘',unit:''}]})
const product = () => ({id:1,material_id:11,kind:'finished',model_id:null,configuration_name:'标准版',version:4,
  can_sell:true,can_purchase:false,can_produce:true,created_by:1,created_at:'2026-10-16',model_code:'',model_name:'',material:material()})

// 保留产品编辑器、共用物料表单、动态规格和真实保存动作，只替换浮层及输入控件的绘制层。
async function fixture(t) {
  const server = await createServer({configFile:false,plugins:[{name:'product-form-context',enforce:'pre',resolveId(id,importer) {
    if(!importer?.includes('/src/renderer/')) return
    if(id.endsWith('/store/app-store')) return '\0context-store'
    for(const [name,key] of [['AppModal','modal'],['WorkspaceDocumentDialog','document'],['AppInput','input'],['WorkspaceSelect','select']])
      if(id.endsWith('/'+name+'.vue')) return '\0context-'+key
  },load(id) {
    if(id==='\0context-store') return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';import {createProductActions} from '/src/renderer/src/store/modules/product-actions.ts';
      export const usePiniaAppStore=defineStore('product-form-context',()=>{const state=createAppState();return {...state,...createProductActions(state),can:key=>state.user.value?.permissions.includes(key)??false}})`
    if(id==='\0context-modal') return `import {h} from 'vue';export default {props:['show','title'],setup:(p,{slots})=>()=>p.show?h('section',{'data-modal':p.title},slots.default?.()):null}`
    if(id==='\0context-document') return `import {h} from 'vue';export default {props:['show'],setup:(p,{slots})=>()=>p.show?h('section',slots.basicInfo?.()):null}`
    if(id==='\0context-input') return `import {h} from 'vue';export const inputs=[];export default {props:['modelValue'],setup:(p,{attrs})=>()=>{inputs.push({props:p,attrs});return h('input',{...attrs,value:p.modelValue})}}`
    if(id==='\0context-select') return `import {h} from 'vue';export const selects=[];export default {props:['modelValue','options'],setup:(p,{attrs})=>()=>{selects.push({props:p,attrs});return h('select',{...attrs,value:p.modelValue},(p.options??[]).map(row=>h('option',{value:row.value},row.label)))}}`
  }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:ProductEditor} = await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductEditor.vue')
  const {default:MaterialEditor} = await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/MaterialEditor.vue')
  const {usePiniaAppStore} = await server.ssrLoadModule('\0context-store')
  const {inputs} = await server.ssrLoadModule('\0context-input')
  const {selects} = await server.ssrLoadModule('\0context-select')
  const pinia=createPinia(), store=usePiniaAppStore(pinia), setups={}, calls=[]
  store.user={id:1,permissions:['inventory.view','catalog.manage']}
  store.server={id:'context-test',fingerprint:'test-cert'}
  store.materialCategories=structuredClone(categories)
  store.materialUnits=[{id:1,name:'台',enabled:true,notes:'',version:1,created_at:'',material_count:0}]
  const previous=globalThis.window
  globalThis.window={nexora:{callApi:async(action,payload)=>{
    calls.push([action,payload===undefined?undefined:structuredClone(payload)])
    if(action==='productModels') return []
    if(action==='queryProducts') return {items:[product()],page:1,page_size:20,total:1}
    if(action==='productDetail') return product()
    if(action==='createProduct'||action==='updateProduct') return {...product(),kind:payload.kind}
    throw Error('不应调用的接口：'+action)
  }}}
  t.after(()=>{globalThis.window=previous;pinia._s.forEach(value=>value.$dispose())})
  function open(mode='new',kind='finished',item) {
    store.productForm={id:mode==='edit'?1:0,version:mode==='edit'?4:0,mode,material_id:mode==='edit'?11:0,kind,model_id:null,configuration_name:'标准版',
      can_sell:true,can_purchase:false,can_produce:true,reason:''}
    store.productMaterialForm=materialDraft(item)
    store.productMaterialForm.category_code=item?.category_code??'EL-OT'
    store.productMaterialForm.name=item?.name??'NET-8890'
    store.productMaterialForm.unit='台'
    store.productEditorOpen=true
  }
  async function render(ordinary=false) {
    inputs.length=0;selects.length=0
    const app=createSSRApp({render:()=>ordinary?h(MaterialEditor,{form:store.productMaterialForm,categories:store.materialCategories,units:store.materialUnits,editing:false,busy:false,disconnected:false}):h(ProductEditor,{entityLabel:'子机型'})}).use(pinia)
    app.mixin({created(){setups[this.$options.__name]=this.$.setupState}})
    setupSsrStyles(app)
    return renderToString(app)
  }
  async function submit() {
    // 通过共用表单的真实 save 事件进入 ProductEditor 和 Pinia，不直接拼造保存请求。
    setups.MaterialEditor.submit()
    await nextTick();await new Promise(done=>setImmediate(done))
    assert.equal(store.error,'')
  }
  return {store,setups,inputs,selects,calls,open,render,submit}
}

const hiddenLabels = /供应商绑定|供货供应商|封装 \/ 外形|品牌 \/ 制造商|制造商料号|电子参数（选填）|标称值 \/ 关键参数|精度 \/ 容差|额定电压|额定功率|工作温度|环保 \/ 合规要求|非标准扩展属性|添加扩展属性/
function update(control,value) {
  assert.ok(control,'目标输入控件必须真实渲染')
  control.attrs['onUpdate:modelValue'](value)
}

test('新建成品和半成品只展示产品资料，无模板时不出现元件采购字段及空规格框',async t=>{
  const f=await fixture(t)
  for(const kind of ['finished','semi_finished']) {
    f.open('new',kind)
    const html=await f.render()
    assert.match(html,/新建子机型|子机型基本信息/)
    for(const label of ['产品类型','所属产品系列','配置名称','业务用途','物料大类','物料子类','子机型编码','子机型名称','单位','规格型号','备注']) assert.ok(html.includes(label),label)
    assert.doesNotMatch(html,hiddenLabels)
    assert.doesNotMatch(html,/分类规格字段|当前子类没有启用的规格字段|多家供应商/)
    assert.match(html,/placeholder="如：NET-8890、尺寸或功能配置"/)
  }
})

test('切换成品半成品及分类不清理隐藏资料，编辑保存保留供应商、元件参数和版本原因',async t=>{
  const f=await fixture(t), original={...material(),supplier_ids:Array.from({length:25},(_,index)=>index+1)}
  f.open('edit','finished',original)
  let html=await f.render()
  assert.doesNotMatch(html,hiddenLabels)
  assert.match(html,/修改原因/)
  const savedHidden=Object.fromEntries(['supplier_selection','package','brand','manufacturer_part_number','electrical_value','tolerance','rated_voltage','rated_power','temperature_range','compliance','historical_specs','extra_attributes'].map(key=>[key,structuredClone(JSON.parse(JSON.stringify(f.store.productMaterialForm[key])))]))
  update(f.selects.find(row=>row.props.options?.[0]?.value==='finished'),'semi_finished')
  update(f.selects.find(row=>row.attrs['aria-label']==='物料大类'),'PL')
  f.setups.MaterialEditor.changeGroup()
  assert.equal(f.store.productMaterialForm.category_code,'')
  f.store.productMaterialForm.category_code='PL-HS'
  html=await f.render()
  assert.doesNotMatch(html,hiddenLabels)
  assert.match(html,/保留的历史规格/)
  update(f.selects.find(row=>row.attrs['aria-label']==='物料大类'),'EL')
  f.setups.MaterialEditor.changeGroup();f.store.productMaterialForm.category_code='EL-PC'
  await f.render()
  for(const [key,value] of Object.entries(savedHidden)) assert.deepEqual(JSON.parse(JSON.stringify(f.store.productMaterialForm[key])),value,key)
  update(f.inputs.find(row=>row.attrs.placeholder==='说明本次补充或调整的原因'),'仅修改产品配置')
  await f.submit()
  const [,body]=f.calls.find(([action])=>action==='updateProduct')
  assert.equal(body.kind,'semi_finished');assert.equal(body.version,4);assert.equal(body.reason,'仅修改产品配置')
  assert.equal(body.material.version,7);assert.equal(body.material.sku,original.sku);assert.equal(body.material.reason,body.reason)
  // 隐藏资料不进入产品写入白名单；服务端保留原值，也不会因旧供应商数量超出当前上限阻止改产品。
  for(const key of ['suppliers','package','brand','manufacturer_part_number','electrical_value','tolerance','rated_voltage','rated_power','temperature_range','compliance']) assert.equal(key in body.material,false,key)
  // 未改动的规格与扩展属性沿用既有“省略即保留”协议，不能发送空数组清除历史资料。
  assert.equal('spec_values' in body.material,false);assert.equal('extra_attributes' in body.material,false)
  assert.equal(f.store.productEditorOpen,false)
  assert.deepEqual(original,{...material(),supplier_ids:Array.from({length:25},(_,index)=>index+1)})
})

test('产品仍能填写所选类别的必填规格，经真实保存链路提交模板版本与规格值',async t=>{
  const f=await fixture(t)
  f.open()
  f.store.productMaterialForm.category_code='EL-PC'
  let html=await f.render()
  assert.match(html,/分类规格字段/);assert.match(html,/产品额定输出 \*/)
  assert.doesNotMatch(html,hiddenLabels)
  update(f.selects.find(row=>row.attrs['aria-label']==='产品额定输出填写状态'),'filled')
  html=await f.render()
  assert.match(html,/数值（W）/)
  const input=f.inputs.find(row=>row.attrs.inputmode==='decimal')
  assert.ok('required' in input.attrs)
  update(input,'18.75')
  update(f.inputs.find(row=>row.attrs.placeholder==='如：规格书版本、图纸号、供应商确认'),'产品规格书 V2')
  await f.submit()
  const [,body]=f.calls.find(([action])=>action==='createProduct')
  assert.equal(body.material.spec_template_version,3)
  assert.deepEqual(body.material.spec_values,[{field_id:1,status:'filled',value:'18.75',source:'产品规格书 V2'}])
  assert.equal(body.material.category_code,'EL-PC')
  assert.equal(body.material.unit_id,1)
  assert.equal(f.store.productEditorOpen,false)
})

test('产品没有当前模板字段但有历史规格时保留可查看入口，普通物料编辑仍展示完整资料',async t=>{
  const f=await fixture(t)
  f.open('edit','semi_finished',{...material(),category_code:'EL-OT'})
  const productHtml=await f.render()
  assert.match(productHtml,/分类规格字段|保留的历史规格/)
  assert.doesNotMatch(productHtml,hiddenLabels)
  f.store.productMaterialForm.category_code='EL-PC'
  const ordinary=await f.render(true)
  for(const label of ['供应商绑定','封装 / 外形','品牌 / 制造商','制造商料号','电子参数（选填）','环保 / 合规要求','非标准扩展属性','添加扩展属性']) assert.ok(ordinary.includes(label),label)
  f.store.productMaterialForm.category_code='EL-OT'
  const noTemplate=await f.render(true)
  assert.match(noTemplate,/当前子类没有启用的规格字段/)
  const ordinaryDraft=materialDraft(material()), body=materialInput(ordinaryDraft,true)
  assert.deepEqual(body.suppliers,[{supplier_id:3},{supplier_id:8}])
  assert.equal(body.package,'历史封装');assert.equal(body.rated_voltage,'12V');assert.equal(body.compliance,'RoHS')
  ordinaryDraft.supplier_selection=Array.from({length:25},(_,index)=>`id:${index+1}`)
  assert.throws(()=>materialInput(ordinaryDraft,true),/20|数量/)
})
