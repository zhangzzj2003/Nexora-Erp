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
   if(id==='test-products-dropdown')return '\0products-dropdown'
   if(['ProductionAssociationDialog','DocumentApprovalDialog','WorkOrderMaterialFlowPanel'].some(name=>id.endsWith('/'+name+'.vue')))return '\0products-empty'
   for(const [name,key] of [['AppModal','modal'],['WorkspaceTable','table'],['WorkspacePagination','pagination'],['AppButton','button'],['AppInput','input'],['WorkspaceMaterialSelect','select'],['WorkspaceSelect','select'],['MaterialEditor','material']])
     if(id.endsWith('/'+name+'.vue'))return '\0products-'+key
 },transform(code,id){
   // 浮层定位需要浏览器 DOM；保留真实页面菜单选项和选择处理，只替换绘制层。
   if(id.endsWith('/ProductsView.vue'))return code.replace("import { NCollapse, NDropdown } from 'naive-ui'",
     "import { NCollapse } from 'naive-ui'\nimport NDropdown from 'test-products-dropdown'")
 },load(id){
   if(id==='\0products-empty')return 'export default {render:()=>null}'
   if(id==='\0products-dropdown')return `import {h} from 'vue';export default {props:['options','disabled'],setup:(p,{slots})=>()=>h('div',{'data-lifecycle-menu':p.options.map(row=>row.key).join(',')},slots.default?.())}`
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
   if(id==='\0products-select')return `import {h} from 'vue';export const selects=[];export default {props:['modelValue','options','materials'],setup:(p,{attrs})=>()=>{selects.push({props:p,attrs});return h('select',attrs,(p.options??p.materials??[]).map(o=>h('option',{value:o.value??o.id},o.label??o.name)))}}`
   if(id==='\0products-material')return `import {h} from 'vue';export default {props:['form'],setup:(p,{slots})=>()=>h('form',[slots.beforeFields?.(),slots.profileFields?.(),h('input',{value:p.form.name})])}`
 }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore}=await server.ssrLoadModule('\0products-store')
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductsView.vue')
 const {default:LegacyBom}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/BomEditor.vue')
 const {default:WorkOrders}=await server.ssrLoadModule('/src/renderer/src/views/workspace/production/ProductionWorkOrdersView.vue')
 const {paginations}=await server.ssrLoadModule('\0products-pagination')
 const {selects}=await server.ssrLoadModule('\0products-select')
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
 let setup;const overrides={}, beforeRender={}, components={}
 const render=async()=>{buttons.length=0;tables.length=0;paginations.length=0;selects.length=0
   const app=createSSRApp(View).use(pinia).use(router)
   app.mixin({async serverPrefetch(){if(this.$options.__name==='ProductsView'){await store.queryProducts();const id=store.productDetailId || store.productResult?.items[0]?.id;if(id)await store.openProduct(id);beforeRender.apply?.(store)}},created(){components[this.$options.__name]=this.$.setupState;if(this.$options.__name==='ProductsView'){setup=this.$.setupState;for(const[key,value]of Object.entries(overrides))setup[key]=value}}})
   return renderToString(app)
 }
 await store.queryProducts()
 store.materials=[material,{...material,id:22,sku:'EL-IC-22',name:'主芯片',unit:'个'}]
 const renderLegacyBom=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(LegacyBom,{show:true})}).use(pinia).use(router))}
 const renderWorkOrders=async()=>{buttons.length=0;selects.length=0;const app=createSSRApp(WorkOrders).use(pinia).use(router);app.mixin({created(){components[this.$options.__name]=this.$.setupState}});return renderToString(app)}
 return {store,source,product,render,renderLegacyBom,renderWorkOrders,buttons,tables,paginations,selects,router,calls,overrides,beforeRender,components,get setup(){return setup}}
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
 assert.match(html,/BOM 版本/);assert.doesNotMatch(html,/复制派生/)
 const openVersions=f.buttons.find(b=>b.label==='版本管理 · 1').attrs.onClick
 for(const handler of Array.isArray(openVersions)?openVersions:[openVersions])handler()
 assert.equal(f.setup.versionsOpen,true)
 f.overrides.versionsOpen=true
 html=await f.render();assert.match(html,/复制派生/)
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
 assert.equal(f.selects.find(row=>row.attrs['aria-label']==='选择 BOM 版本').props.modelValue,9)
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

// 使用真实页面的事件与组成行验证版本切换，避免只断言新增文案。
test('紧凑版本栏默认选启用版本，历史选择切换组成并拒绝失效或禁用事件',async t=>{
 const f=await fixture(t)
 const previous=globalThis.window.nexora.callApi
 const history={...f.source,id:8,version:2,status:'retired',lines:[{...f.source.lines[0],material_name:'旧版芯片',quantity:'5'}]}
 globalThis.window.nexora.callApi=async(action,payload)=>action==='productBoms'?[history,f.source]:previous(action,payload)
 let html=await f.render()
 assert.doesNotMatch(html,/data-modal="BOM 版本管理"/)
 assert.equal(f.tables.some(row=>row.title==='全部版本'),false)
 assert.match(html,/data-table="组成明细 · V1"/)
 const selector=f.selects.find(row=>row.attrs['aria-label']==='选择 BOM 版本')
 assert.equal(selector.props.modelValue,7)
 selector.attrs['onUpdate:modelValue'](8)
 assert.equal(f.setup.selectedBom.id,8)
 selector.attrs['onUpdate:modelValue'](999)
 assert.equal(f.setup.selectedBom.id,8)
 f.store.busy=true;selector.attrs['onUpdate:modelValue'](7)
 assert.equal(f.setup.selectedBom.id,8)
 f.store.busy=false;f.overrides.selectedBomId=8
 html=await f.render()
 assert.match(html,/旧版芯片/);assert.match(html,/data-table="组成明细 · V2"/)
 f.overrides.versionsOpen=true
 await f.render()
 f.buttons.find(row=>row.label==='查看组成').attrs.onClick()
 assert.equal(f.setup.selectedBom.id,7);assert.equal(f.setup.versionsOpen,false)
})

// 管理操作迁移位置后仍沿用权限、单一启用版本和断线保护。
test('版本管理保留启停和取消权限，当前启用版本阻止重复启用，断线禁用写入',async t=>{
 const f=await fixture(t)
 const previous=globalThis.window.nexora.callApi
 const draft={...f.source,id:8,version:2,status:'draft'}
 globalThis.window.nexora.callApi=async(action,payload)=>action==='productBoms'?[f.source,draft]:previous(action,payload)
 f.store.user.permissions.push('bom.retire','bom.cancel')
 f.overrides.versionsOpen=true
 await f.render()
 assert.equal(f.buttons.find(row=>row.label==='启用').props.disabled,true)
 assert.equal(f.buttons.find(row=>row.label==='停用').attrs.tone,'warning')
 assert.equal(f.buttons.find(row=>row.label==='取消草稿').attrs.tone,'error')
 await f.buttons.find(row=>row.label==='停用').attrs.onClick()
 assert.equal(f.calls.some(([action,payload])=>action==='retireBom'&&payload.bomId===7),true)
 f.store.connectionLost=true
 await f.render()
 for(const label of ['复制派生','停用','启用','取消草稿'])
   assert.equal(f.buttons.filter(row=>row.label===label).every(row=>row.props.disabled),true)
 f.store.connectionLost=false;f.store.user={...f.store.user,permissions:['inventory.view','production.view']}
 const html=await f.render()
 assert.doesNotMatch(html,/复制派生|取消草稿|>停用<|>启用<|新建版本|复用 BOM/)
 assert.match(html,/当前组成/)
})

test('目录名称与配置去重，产品资料保留编辑入口，组成说明可按需展开',async t=>{
 const f=await fixture(t)
 let html=await f.render()
 const left=html.slice(html.indexOf('<aside'),html.indexOf('</aside>'))
 assert.equal((left.match(/标准版/g)??[]).length,1)
 assert.match(left,/tree-kind/);assert.equal(f.buttons.some(row=>row.label==='领料与版本说明'),true)
 assert.match(html,/基准产出/);assert.match(html,/1 项直接组件/)
 assert.doesNotMatch(html,/未设置配置/)
 f.overrides.detailsOpen=true
 html=await f.render()
 assert.match(html,/data-modal="产品资料"/);assert.match(html,/编辑子机型/)
 // 独立配置仍展示，产品名称不再被配置名称替代。
 f.product.configuration_name='长续航';html=await f.render()
 const updatedLeft=html.slice(html.indexOf('<aside'),html.indexOf('</aside>'))
 assert.equal((updatedLeft.match(/标准版/g)??[]).length,1);assert.match(updatedLeft,/长续航/)
})

// 原版本表格承担的读取状态不能在压缩布局后消失，也不能露出上一次组成。
test('BOM 读取失败、加载与空状态都隐藏旧组成，失败可重试',async t=>{
 const f=await fixture(t)
 f.beforeRender.apply=store=>{store.productDetailError='版本读取失败'}
 let html=await f.render()
 assert.match(html,/role="alert"/);assert.match(html,/版本读取失败/)
 assert.equal(f.tables.some(row=>row.title.startsWith('组成明细')),false)
 const reads=f.calls.filter(([action])=>action==='productBoms').length
 await f.buttons.find(row=>row.label==='重试').attrs.onClick()
 assert.equal(f.calls.filter(([action])=>action==='productBoms').length,reads+1)
 f.beforeRender.apply=store=>{store.productDetailLoading=true}
 html=await f.render();assert.match(html,/正在读取 BOM/)
 assert.equal(f.tables.some(row=>row.title.startsWith('组成明细')),false)
 f.beforeRender.apply=store=>{store.productBomRecords=[]}
 html=await f.render();assert.match(html,/尚未建立 BOM/)
 assert.equal(f.tables.some(row=>row.title.startsWith('组成明细')),false)
})

// 服务端子机型总数与当前分页互不混淆，停用机型仍占用系列归属。
test('系列删除按完整子机型数量阻断，失败保留原因，查看账号不显示删除入口',async t=>{
 const f=await fixture(t)
 const model={id:1,code:'A100',name:'机型A',notes:'',version:3,child_count:4,created_by:1,created_at:'2026-10-15'}
 f.product.can_produce=false
 f.overrides.modelToDelete=model
 let html=await f.render()
 assert.match(html,/删除产品系列/);assert.match(html,/先删除子机型，再删除系列/)
 assert.equal(f.buttons.find(row=>row.label==='确认删除系列').props.disabled,true)
 const blocked=f.components.ProductModelDeleteDialog
 blocked.reason='清理停用系列';await blocked.remove()
 assert.equal(f.calls.some(([action])=>action==='deleteProductModel'),false)
 // 空系列可发起删除；服务端并发新增或关联校验失败时保留本次确认原因。
 f.overrides.modelToDelete={...model,child_count:0}
 await f.render()
 const empty=f.components.ProductModelDeleteDialog
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='deleteProductModel'){f.calls.push([action,payload]);throw Error('系列已有新的子机型')}
  return previous(action,payload)
 }
 empty.reason='整理空系列';await empty.remove()
 assert.equal(empty.reason,'整理空系列');assert.match(f.store.error,/新的子机型/)
 assert.deepEqual(f.calls.find(([action])=>action==='deleteProductModel')[1],{id:1,version:3,reason:'整理空系列'})
 f.store.user={...f.store.user,permissions:['inventory.view','production.view']}
 html=await f.render();assert.doesNotMatch(html,/删除产品系列|确认删除系列/)
})

// 子机型停用优先于其 BOM 的 active 状态，旧详情按钮不能继续发出建单意图。
test('停用子机型的 BOM 详情禁止建单，启用版本历史仍可查看',async t=>{
 const f=await fixture(t)
 f.store.bomDetailRecord={...f.source,product_can_produce:false}
 const html=await f.render()
 assert.match(html,/BOM 版本详情/);assert.match(html,/主芯片/)
 const button=f.buttons.find(row=>row.label==='创建生产工单')
 assert.equal(button.props.disabled,true)
 await button.attrs.onClick()
 assert.equal(f.router.currentRoute.value.path,'/workspace/products')
 assert.equal(f.store.bomDetailRecord.id,7)
})

// 确认窗把停用与删除的后果分开，所有写入都要求原因，失败不丢输入。
test('子机型操作按当前生产状态切换，确认窗保留失败原因并受权限断线约束',async t=>{
 const f=await fixture(t)
 await f.render()
 assert.deepEqual(f.setup.lifecycleOptions.map(row=>row.key),['disable','delete'])
 f.setup.selectLifecycle('disable')
 assert.equal(f.setup.lifecycleTarget.id,1);assert.equal(f.setup.lifecycleAction,'disable')
 f.overrides.lifecycleTarget=f.product;f.overrides.lifecycleAction='disable'
 let html=await f.render()
 assert.match(html,/停用后禁止此子机型的新生产/);assert.match(html,/已有工单继续履行/)
 assert.equal(f.buttons.find(row=>row.label==='确认停用子机型').props.disabled,true)
 assert.equal(f.buttons.find(row=>row.label==='确认停用子机型').attrs.tone,'warning')
 const dialog=f.components.ProductLifecycleDialog
 await dialog.submit();assert.equal(f.calls.some(([action])=>action==='updateProduct'),false)
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='updateProduct'){f.calls.push([action,payload]);throw Error('资料版本已变更，请刷新')}
  return previous(action,payload)
 }
 dialog.reason=' 暂停此型号生产 ';await dialog.submit()
 assert.equal(dialog.reason,' 暂停此型号生产 ');assert.match(f.store.error,/版本已变更/)
 assert.equal(f.calls.find(([action])=>action==='updateProduct')[1].reason,'暂停此型号生产')
 const writes=f.calls.filter(([action])=>action==='updateProduct').length
 f.store.connectionLost=true;await dialog.submit()
 assert.equal(f.calls.filter(([action])=>action==='updateProduct').length,writes)
 f.store.connectionLost=false;f.product.can_produce=false
 f.overrides.lifecycleAction='enable'
 html=await f.render()
 assert.deepEqual(f.setup.lifecycleOptions.map(row=>row.key),['enable','delete'])
 assert.match(html,/子机型已停用/);assert.match(html,/原 BOM 版本状态保持不变/)
 assert.equal(f.buttons.find(row=>row.label==='确认启用子机型').attrs.tone,'success')
 f.overrides.lifecycleAction='delete'
 html=await f.render()
 assert.match(html,/保留原物料、库存、BOM 及历史工单/)
 assert.equal(f.buttons.find(row=>row.label==='确认删除子机型').attrs.tone,'error')
 f.store.user={...f.store.user,permissions:['inventory.view','production.view']}
 html=await f.render();assert.doesNotMatch(html,/子机型操作|确认删除子机型/)
 f.setup.lifecycleTarget=null
 f.setup.selectLifecycle('delete');assert.equal(f.setup.lifecycleTarget,null)
})

test('工单产品选项排除停用子机型，旧建单链接及已填草稿均不能继续生产',async t=>{
 const f=await fixture(t)
 const blocked={...f.source,product_can_produce:false}
 const available={...f.source,id:8,product_material_id:22,product_name:'可生产主控板',product_can_produce:true}
 f.store.boms=[blocked,available]
 await f.router.push({path:'/workspace/work-orders',query:{create_from_bom:'7'}})
 f.store.workOrderForm={...f.store.workOrderForm,bom_id:7,target_quantity:'1',warehouse_id:1}
 f.store.warehouses=[{id:1,name:'主仓库'}]
 await f.renderWorkOrders()
 const view=f.components.ProductionWorkOrdersView
 assert.equal(view.createOpen,false)
 assert.deepEqual(view.activeBoms.map(row=>row.id),[8])
 assert.deepEqual(view.productChoices.map(row=>row.id),[22])
 assert.match(view.productIssue,/子机型已停用或删除/)
 await view.submitCreate()
 assert.match(f.store.error,/子机型已停用或删除/)
 assert.equal(f.calls.some(([action])=>action==='createWorkOrder'),false)
})
