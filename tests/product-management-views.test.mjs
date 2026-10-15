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
   for(const [name,key] of [['AppModal','modal'],['WorkspaceTable','table'],['AppButton','button'],['AppInput','input'],['WorkspaceMaterialSelect','select'],['WorkspaceSelect','select'],['MaterialEditor','material']])
     if(id.endsWith('/'+name+'.vue'))return '\0products-'+key
 },load(id){
   if(id==='\0products-store')return `import {defineStore,storeToRefs} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    import {createProductActions} from '/src/renderer/src/store/modules/product-actions.ts';import {createProductionActions} from '/src/renderer/src/store/modules/production-actions.ts';
    export const usePiniaAppStore=defineStore('product-view',()=>{const s=createAppState();return {...s,...createProductActions(s),
     ...createProductionActions(s,async(action,success)=>{s.error.value='';try{await action();s.notice.value=success}catch(e){s.error.value=e.message}},()=>{}),
     can:key=>s.user.value?.permissions.includes(key)??false,localTime:v=>v}});export const useAppStore=()=>{const store=usePiniaAppStore();return {...store,...storeToRefs(store)}}`
   if(id==='\0products-modal')return `import {h} from 'vue';export default {props:['show','title'],setup:(p,{slots})=>()=>p.show?h('section',{'data-modal':p.title},[h('h2',p.title),slots.default?.()]):null}`
   if(id==='\0products-table')return `import {h} from 'vue';export const tables=[];export default {props:['data','columns','title','pagination'],setup:(p,{slots})=>()=>{tables.push(p);return h('section',{'data-table':p.title},[slots.heading?.(),slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...(p.data??[]).map(row=>h('article',(p.columns??[]).map(c=>slots['cell-'+c.key]?.({row})))),!(p.data??[]).length?slots.empty?.():null])}}`
   if(id==='\0products-button')return `import {h} from 'vue';export const buttons=[];const text=v=>(v??[]).map(n=>typeof n.children==='string'?n.children:Array.isArray(n.children)?text(n.children):'').join('');export default {props:['disabled','type'],setup:(p,{slots,attrs})=>()=>{const content=slots.default?.();buttons.push({label:text(content).trim(),props:p,attrs});return h('button',{...attrs,disabled:p.disabled,type:p.type},content)}}`
   if(id==='\0products-input')return `import {h} from 'vue';export default {props:['modelValue'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue})}`
   if(id==='\0products-select')return `import {h} from 'vue';export default {props:['modelValue','options','materials'],setup:(p,{attrs})=>()=>h('select',attrs,(p.options??p.materials??[]).map(o=>h('option',{value:o.value??o.id},o.label??o.name)))}`
   if(id==='\0products-material')return `import {h} from 'vue';export default {props:['form'],setup:(p,{slots})=>()=>h('form',[slots.beforeFields?.(),h('input',{value:p.form.name})])}`
 }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore}=await server.ssrLoadModule('\0products-store')
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductsView.vue')
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
 const render=async()=>{buttons.length=0;tables.length=0
   const app=createSSRApp(View).use(pinia).use(router)
   app.mixin({created(){if(this.$options.__name==='ProductsView'){setup=this.$.setupState;for(const[key,value]of Object.entries(overrides))setup[key]=value}}})
   return renderToString(app)
 }
 await store.queryProducts()
 store.materials=[material,{...material,id:22,sku:'EL-IC-22',name:'主芯片',unit:'个'}]
 return {store,source,product,render,buttons,tables,router,calls,overrides,get setup(){return setup}}
}

test('产品真实页面使用服务端分页和物料身份，查看权限不能显示维护入口',async t=>{
 const f=await fixture(t)
 const html=await f.render()
 assert.match(html,/EL-PC-11/);assert.match(html,/标准版/);assert.match(html,/新增产品/)
 assert.equal(f.tables.find(p=>p.title==='产品管理').pagination.total,43)
 assert.equal(f.tables.find(p=>p.title==='产品管理').data.length,1)
 f.store.user={...f.store.user,permissions:['inventory.view']}
 const readonly=await f.render()
 assert.doesNotMatch(readonly,/新增产品|纳入已有物料|机型管理/)
})

test('产品详情复用 BOM 编辑器派生，快捷建档保留组件，来源查看及启用版本创建工单',async t=>{
 const f=await fixture(t)
 await f.store.openProduct(1)
 let html=await f.render()
 assert.match(html,/关联 BOM/);assert.match(html,/复制派生/)
 f.buttons.find(b=>b.label==='复制派生').attrs.onClick()
 assert.equal(f.store.bomForm.source_bom_id,7)
 assert.equal(f.store.bomForm.lines[0].quantity,'2')
 f.overrides.bomOpen=true
 html=await f.render();assert.match(html,/派生来源 BOM #7/)
 await f.buttons.find(b=>b.label==='快捷新建产品').attrs.onClick()
 const component=f.store.bomForm.lines[0]
 html=await f.render();assert.match(html,/产品归组/)
 assert.equal(f.store.bomForm.lines[0],component)
 f.store.productEditorOpen=false
 f.overrides.bomOpen=false
 await f.store.openBomDetail(7)
 html=await f.render();assert.match(html,/BOM 版本详情/)
 await f.buttons.find(b=>b.label==='创建生产工单').attrs.onClick()
 assert.equal(f.router.currentRoute.value.path,'/workspace/work-orders')
 assert.equal(f.router.currentRoute.value.query.create_from_bom,'7')
})
