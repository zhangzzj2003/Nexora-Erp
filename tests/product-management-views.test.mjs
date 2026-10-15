import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 保留产品页、共享 BOM 编辑器与详情真实组件，仅替换需要 DOM 的绘制控件。
async function fixture(t) {
 const server=await createServer({configFile:false,plugins:[{name:'product-views',enforce:'pre',resolveId(id,importer){
   if(!importer?.includes('/src/renderer/'))return
   if(id.endsWith('/store/app-store'))return '\0products-store'
   for(const [name,key] of [['AppModal','modal'],['WorkspaceTable','table'],['WorkspacePagination','pagination'],['AppButton','button'],['AppInput','input'],['WorkspaceMaterialSelect','select'],['WorkspaceSelect','select'],['MaterialEditor','material']])
     if(id.endsWith('/'+name+'.vue'))return '\0products-'+key
 },load(id){
   if(id==='\0products-store')return `import {defineStore,storeToRefs} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    import {createProductActions} from '/src/renderer/src/store/modules/product-actions.ts';import {createProductionActions} from '/src/renderer/src/store/modules/production-actions.ts';
    export const usePiniaAppStore=defineStore('product-view',()=>{const s=createAppState();return {...s,...createProductActions(s),
     ...createProductionActions(s,async(action,success)=>{s.error.value='';try{await action();s.notice.value=success}catch(e){s.error.value=e.message}},()=>{}),
     can:key=>s.user.value?.permissions.includes(key)??false,localTime:v=>v}});export const useAppStore=()=>{const store=usePiniaAppStore();return {...store,...storeToRefs(store)}}`
   if(id==='\0products-modal')return `import {h} from 'vue';export default {props:['show','title'],setup:(p,{slots})=>()=>p.show?h('section',{'data-modal':p.title},[h('h2',p.title),slots.default?.()]):null}`
   if(id==='\0products-table')return `import {h} from 'vue';export const tables=[];export default {props:['data','columns','title','pagination'],setup:(p,{slots})=>()=>{tables.push(p);return h('section',{'data-table':p.title},[slots.heading?.(),slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...(p.data??[]).map(row=>h('article',(p.columns??[]).map(c=>slots['cell-'+c.key]?.({row})))),!(p.data??[]).length?slots.empty?.():null])}}`
   if(id==='\0products-pagination')return `import {h} from 'vue';export const paginations=[];export default {props:['page','pageSize','total','disabled'],setup:(p,{attrs})=>()=>{paginations.push({...p,...attrs});return h('nav',{'data-product-pagination':p.total})}}`
   if(id==='\0products-button')return `import {h} from 'vue';export const buttons=[];const text=v=>(v??[]).map(n=>typeof n.children==='string'?n.children:Array.isArray(n.children)?text(n.children):'').join('');export default {props:['disabled','type'],setup:(p,{slots,attrs})=>()=>{const content=slots.default?.();buttons.push({label:text(content).trim(),props:p,attrs});return h('button',{...attrs,disabled:p.disabled,type:p.type},content)}}`
   if(id==='\0products-input')return `import {h} from 'vue';export default {props:['modelValue'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue})}`
   if(id==='\0products-select')return `import {h} from 'vue';export default {props:['modelValue','options','materials'],setup:(p,{attrs})=>()=>h('select',attrs,(p.options??p.materials??[]).map(o=>h('option',{value:o.value??o.id},o.label??o.name)))}`
   if(id==='\0products-material')return `import {h} from 'vue';export default {props:['form'],setup:(p,{slots})=>()=>h('form',[slots.beforeFields?.(),slots.profileFields?.(),h('input',{value:p.form.name})])}`
 }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore}=await server.ssrLoadModule('\0products-store')
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductsView.vue')
 const {default:LegacyBom}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/BomEditor.vue')
 const {paginations}=await server.ssrLoadModule('\0products-pagination')
 const {buttons}=await server.ssrLoadModule('\0products-button'), {tables}=await server.ssrLoadModule('\0products-table')
 const pinia=createPinia(), store=usePiniaAppStore(pinia)
 store.user={id:1,permissions:['inventory.view','catalog.manage','production.view','bom.create','bom.activate','work_order.create']}
 store.server={id:'test',fingerprint:'cert'}
 const material={id:11,sku:'EL-PC-11',name:'标准版',unit:'块',version:1,
  ...Object.fromEntries(['category_code','specification','package','brand','manufacturer_part_number','electrical_value','tolerance','rated_voltage','rated_power','temperature_range','compliance','notes'].map(key=>[key,'']))}
 const product={id:1,material_id:11,kind:'finished',model_id:1,model_name:'机型A',model_code:'A100',configuration_name:'标准版',version:1,created_by:1,created_at:'2026-10-15',material}
 const source={id:7,product_material_id:11,product_name:'标准版',product_sku:'EL-PC-11',version:1,base_quantity:'1',product_unit:'块',status:'active',
   lines:[{id:1,component_material_id:22,sku:'EL-IC-22',material_name:'主芯片',unit:'个',quantity:'2'}]}
 const calls=[],previous=globalThis.window
 globalThis.window={nexora:{callApi:async(action,payload)=>{calls.push([action,payload]);return action==='queryProducts'?{items:[product],page:1,page_size:20,total:43}:
   action==='productModels'?[{id:1,code:'A100',name:'机型A',notes:'',version:1,created_by:1,created_at:'2026-10-15'}]:
   action==='productChanges'?[]:action==='productDetail'?product:action==='productBoms'?[source]:action==='bomDetail'?source:undefined}}}
 t.after(()=>{globalThis.window=previous})
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/workspace/products',component:View},{path:'/workspace/work-orders',component:{render:()=>null}}]})
 await router.push('/workspace/products');await router.isReady()
 let setup;const overrides={}
 const render=async()=>{buttons.length=0;tables.length=0;paginations.length=0
   const app=createSSRApp(View).use(pinia).use(router)
   app.mixin({async serverPrefetch(){if(this.$options.__name==='ProductsView'){await store.queryProducts();const id=store.productDetailId || store.productResult?.items[0]?.id;if(id)await store.openProduct(id)}},created(){if(this.$options.__name==='ProductsView'){setup=this.$.setupState;for(const[key,value]of Object.entries(overrides))setup[key]=value}}})
   return renderToString(app)
 }
 await store.queryProducts()
 store.materials=[material,{...material,id:22,sku:'EL-IC-22',name:'主芯片',unit:'个'}]
 const renderLegacyBom=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(LegacyBom,{show:true})}).use(pinia).use(router))}
 return {store,source,product,render,renderLegacyBom,buttons,tables,paginations,router,calls,overrides,get setup(){return setup}}
}

test('产品真实页面使用服务端分页和物料身份，查看权限不能显示维护入口',async t=>{
 const f=await fixture(t)
 const html=await f.render()
 assert.match(html,/EL-PC-11/);assert.match(html,/标准版/);assert.match(html,/新建系列/);assert.match(html,/新建子机型/)
 assert.equal(f.paginations[0].total,43)
 assert.equal(f.store.productResult.items.length,1)
 assert.match(html,/产品系列/);assert.match(html,/选择系列与子机型/)
 const left=html.slice(html.indexOf('<aside'),html.indexOf('</aside>'))
 assert.match(left,/新建系列/);assert.match(left,/新建子机型/);assert.match(left,/标准版/)
 const right=html.slice(html.indexOf('class="product-main"'))
 assert.doesNotMatch(right,/产品类型<select|class="product-options"/)
 f.store.user={...f.store.user,permissions:['inventory.view']}
 const readonly=await f.render()
 assert.doesNotMatch(readonly,/新建系列|新建子机型|纳入已有物料|系列管理/)
})

test('产品详情复用 BOM 编辑器派生，快捷建档保留组件，来源查看及启用版本创建工单',async t=>{
 const f=await fixture(t)
 await f.store.openProduct(1)
 let html=await f.render()
 assert.match(html,/BOM 版本/);assert.match(html,/复制派生/)
 f.buttons.find(b=>b.label==='复制派生').attrs.onClick()
 assert.equal(f.store.bomForm.source_bom_id,7)
 assert.equal(f.store.bomForm.lines[0].quantity,'2')
 f.overrides.bomOpen=true;f.overrides.bomTargetId=11
 html=await f.render();assert.match(html,/派生来源 BOM #7/)
 assert.doesNotMatch(html,/快捷新建产品/)
 assert.match(html,/<select[^>]*disabled/)
 // 独立 BOM 入口继续允许快捷新建，原有草稿不被工作区目标限制破坏。
 html=await f.renderLegacyBom()
 await f.buttons.find(b=>b.label==='快捷新建产品').attrs.onClick()
 const component=f.store.bomForm.lines[0]
 html=await f.renderLegacyBom();assert.match(html,/所属产品系列/)
 assert.equal(f.store.bomForm.lines[0],component)
 f.store.productEditorOpen=false
 f.overrides.bomOpen=false
 await f.store.openBomDetail(7)
 html=await f.render();assert.match(html,/BOM 版本详情/)
 await f.buttons.find(b=>b.label==='创建生产工单').attrs.onClick()
 assert.equal(f.router.currentRoute.value.path,'/workspace/work-orders')
 assert.equal(f.router.currentRoute.value.query.create_from_bom,'7')
})

// 验证系列切换实际发送服务端范围，并让右侧展示新产品的 BOM；不能只变侧栏高亮。
test('左侧系列限定服务端产品范围，右侧直接切换 BOM，重置保留当前系列',async t=>{
 const f=await fixture(t)
 const second={...f.product,id:2,material_id:33,model_id:2,model_name:'B200 系列',model_code:'B200',configuration_name:'专业版',material:{...f.product.material,id:33,sku:'EL-PC-33',name:'专业控制板'}}
 const otherBom={...f.source,id:9,product_material_id:33,product_name:'专业控制板',status:'cancelled'}
 globalThis.window.nexora.callApi=async(action,payload)=>{
   f.calls.push([action,payload])
   if(action==='queryProducts')return {items:payload.model_id===2?[second]:[f.product],page:1,page_size:20,total:1}
   if(action==='productModels')return [{id:1,code:'A100',name:'机型A',notes:'',version:1,created_by:1,created_at:'2026-10-15'},{id:2,code:'B200',name:'B200 系列',notes:'',version:1,created_by:1,created_at:'2026-10-15'}]
   if(action==='productDetail')return payload.id===2?second:f.product
   if(action==='productChanges')return []
   if(action==='productBoms')return payload.materialId===33?[otherBom]:[f.source]
 }
 await f.render()
 f.store.productQuery.query='旧条件';f.store.productQuery.page=3
 f.setup.selectSeries(2)
 assert.equal(f.store.productQuery.model_id,2);assert.equal(f.store.productQuery.page,1)
 assert.equal(f.store.productQuery.query,'');assert.equal(f.store.productDetailId,0)
 const html=await f.render()
 assert.match(html,/B200 系列/);assert.match(html,/专业控制板/)
 assert.equal(f.tables.find(row=>row.title==='BOM 版本').data[0].id,9)
 assert.equal(f.calls.some(([action,payload])=>action==='queryProducts'&&payload.model_id===2),true)
 assert.doesNotMatch(html,/复制派生/)
 f.setup.reset();assert.equal(f.store.productQuery.model_id,2)
 assert.equal(f.calls.at(-2)[0],'queryProducts');assert.equal(f.calls.at(-2)[1].page,1)
 f.setup.pageChange(2,20);assert.equal(f.store.productDetailId,0)
 f.store.connectionLost=true;f.setup.selectSeries(1);assert.equal(f.store.productQuery.model_id,2)
})

// 新建入口在目录内；子机型继承选中系列，重开保留输入，失效系列不能带入表单。
test('左侧新建系列与子机型使用独立入口，并继承当前系列',async t=>{
 const f=await fixture(t)
 await f.render()
 f.store.productModelForm={id:5,version:1,code:'OLD',name:'旧系列',notes:'',reason:''}
 f.setup.newSeries()
 assert.equal(f.setup.modelsOpen,true);assert.equal(f.setup.createSeriesOnly,true)
 assert.equal(f.store.productModelForm.id,0);assert.equal(f.store.productModelForm.code,'')
 f.store.productModelForm.code='NEW';f.setup.newSeries();assert.equal(f.store.productModelForm.code,'NEW')
 f.store.productQuery.model_id=1
 await f.setup.newModel()
 assert.equal(f.store.productForm.model_id,1);assert.equal(f.store.productEditorOpen,true)
 f.store.productMaterialForm.name='保留的机型名称'
 await f.setup.newModel();assert.equal(f.store.productMaterialForm.name,'保留的机型名称')
 f.store.productEditorOpen=false;f.store.productQuery.model_id=99
 await f.setup.newModel();assert.equal(f.store.productEditorOpen,false)
 assert.match(f.store.error,/产品系列已不存在/)
})

// 复用目录必须跨机型查询，并固定目标身份；编辑复制行不应更改来源。
test('右侧可从其他机型复用 BOM 到当前机型，排除取消版本',async t=>{
 const f=await fixture(t)
 const other={...f.source,id:88,product_material_id:33,product_name:'来源专业版',lines:f.source.lines.map(row=>({...row,quantity:'9'}))}
 f.store.boms=[other,{...f.source,id:99,status:'cancelled'}]
 f.overrides.reuseOpen=true
 const html=await f.render()
 assert.match(html,/选择要复用的 BOM/);assert.match(html,/来源专业版/)
 assert.equal(f.tables.find(row=>row.title==='可复用版本').data.length,1)
 f.buttons.find(row=>row.label==='复用到当前机型').attrs.onClick()
 assert.equal(f.store.bomForm.product_material_id,11)
 assert.equal(f.store.bomForm.source_bom_id,88)
 assert.equal(f.store.bomForm.lines[0].quantity,'9')
 f.store.bomForm.lines[0].quantity='4';assert.equal(other.lines[0].quantity,'9')
})
