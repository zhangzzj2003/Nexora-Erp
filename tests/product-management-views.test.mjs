import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createRenderer, createSSRApp, h, markRaw, nextTick, reactive, ssrContextKey } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createServer, normalizePath } from 'vite'
import vue from '@vitejs/plugin-vue'

const componentRenderer=()=>createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},
 setText(){},setElementText(){},patchProp(){},parentNode:()=>null,nextSibling:()=>null})
async function click(button) {
 const handlers=button.attrs.onClick
 for(const handler of Array.isArray(handlers)?handlers:[handlers])await handler()
}
// 页面查询、详情和 BOM 分两段异步回填；等待稳定状态后再检查是否发生了额外读取。
const settleProductView=async()=>{await new Promise(done=>setImmediate(done));await nextTick();await new Promise(done=>setImmediate(done));await nextTick()}

// 保留产品页、共享 BOM 编辑器与详情真实组件，仅替换需要 DOM 的绘制控件。
async function fixture(t) {
 const liveModules=['views/workspace/catalog/ProductsView.vue','components/workspace/WorkspaceDocumentDialog.vue','views/workspace/catalog/ProductBomStructure.vue','views/workspace/catalog/ProductModelsDialog.vue'].map(file=>{
  const filename=resolve('src/renderer/src',file)
  const content=compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,{id:file,inlineTemplate:true}).content
   .replace("import { NCollapse, NDropdown } from 'naive-ui'","import { NCollapse, NDropdown } from 'virtual:products-live-collapse'")
   .replace("import { NCollapse } from 'naive-ui'","import { NCollapse } from 'virtual:products-live-collapse'")
  return [normalizePath(filename)+'.client.ts',content]
 })
 const liveSources=new Map(liveModules)
 const server=await createServer({configFile:false,plugins:[{name:'product-views',enforce:'pre',resolveId(id,importer){
   if(liveSources.has(id))return id
   if(id==='virtual:products-live-collapse')return '\0products-live-collapse'
   if(id==='virtual:products-store')return '\0products-store'
   if(importer?.endsWith('.vue.client.ts')){
    if(id.endsWith('/WorkspaceDocumentDialog.vue'))return liveModules[1][0]
    if(id.endsWith('/ProductBomStructure.vue'))return liveModules[2][0]
    if(id.endsWith('/ProductModelsDialog.vue'))return liveModules[3][0]
    if(id.endsWith('/InventoryDetailDialogs.vue'))return '\0products-inventory-details'
    if(id.endsWith('/ProductTreeSidebar.vue'))return '\0products-live-tree'
    if(id.endsWith('/AppCollapseItem.vue'))return '\0products-live-collapse-item'
    if(id.endsWith('/AppStatusTag.vue'))return '\0products-live-status'
    if(['ProductTreeSidebar','ProductEditor','ProductBomReuseDialog','ProductModelsDialog','ProductModelDeleteDialog','ProductLifecycleDialog','BomEditor','BomDetailDialog'].some(name=>id.endsWith('/'+name+'.vue')))return '\0products-empty'
   }
   if(id.startsWith('~icons/'))return '\0products-icon'
   if(!importer?.includes('/src/renderer/'))return
   if(id.endsWith('/store/app-store'))return '\0products-store'
   if(id.endsWith('/InventoryDetailDialogs.vue'))return '\0products-inventory-details'
   if(id==='test-products-dropdown')return '\0products-dropdown'
   if(['ProductionAssociationDialog','DocumentApprovalDialog','WorkOrderMaterialFlowPanel'].some(name=>id.endsWith('/'+name+'.vue')))return '\0products-empty'
   for(const [name,key] of [['AppModal','modal'],['WorkspaceTable','table'],['WorkspacePagination','pagination'],['AppButton','button'],['AppInput','input'],['WorkspaceMaterialSelect','select'],['WorkspaceSelect','select'],['MaterialEditor','material']])
     if(id.endsWith('/'+name+'.vue'))return '\0products-'+key
 },transform(code,id){
   // 浮层定位需要浏览器 DOM；保留真实页面菜单选项和选择处理，只替换绘制层。
   if(id.endsWith('/ProductsView.vue'))return code.replace("import { NCollapse, NDropdown } from 'naive-ui'",
     "import { NCollapse } from 'naive-ui'\nimport NDropdown from 'test-products-dropdown'")
 },load(id){
   if(liveSources.has(id))return liveSources.get(id)
   // 历史读取测试持续绘制真实页面、资料弹窗和 BOM，只替换不影响业务的折叠及状态控件。
   if(id==='\0products-live-collapse')return `import {h} from 'vue';const Fold={setup:(p,{slots})=>()=>h('section',slots.default?.())};export const NCollapse=Fold,NDropdown=Fold`
   if(id==='\0products-live-collapse-item')return `import {h} from 'vue';export default {props:['title'],setup:(p,{slots})=>()=>h('section',[h('h4',p.title),slots.default?.()])}`
   if(id==='\0products-live-status')return `import {h} from 'vue';export default {props:['label'],setup:p=>()=>h('span',p.label)}`
   if(id==='\0products-live-tree')return `import {h} from 'vue';export default {props:['rows','models'],emits:['select','edit','newSeries'],setup:(p,{emit})=>()=>h('nav',[h('button',{onClick:()=>emit('newSeries')},'新建系列'),...p.models.map(model=>h('button',{onClick:()=>emit('edit',model.id)},'编辑产品系列 '+model.name)),...p.rows.map(row=>h('button',{onClick:()=>emit('select',row.id)},'选择产品 '+row.material.name))])}`
   // 图标仅替换绘制层，系列折叠、删除事件与可访问文案继续由真实组件提供。
   if(id==='\0products-icon')return `import {h} from 'vue';export default {render:()=>h('svg',{'aria-hidden':'true'})}`
   if(id==='\0products-empty')return 'export default {render:()=>null}'
   if(id==='\0products-dropdown')return `import {h} from 'vue';export default {props:['options','disabled'],setup:(p,{slots})=>()=>h('div',{'data-lifecycle-menu':p.options.map(row=>row.key).join(',')},slots.default?.())}`
   if(id==='\0products-store')return `import {defineStore,storeToRefs} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    import {createProductActions} from '/src/renderer/src/store/modules/product-actions.ts';import {createProductionActions} from '/src/renderer/src/store/modules/production-actions.ts';
    import {createInventoryLedgerDetailActions} from '/src/renderer/src/store/modules/inventory-ledger-detail-actions.ts';
    export const usePiniaAppStore=defineStore('product-view',()=>{const s=createAppState();return {...s,...createProductActions(s),...createInventoryLedgerDetailActions(s),
     ...createProductionActions(s,async(action,success)=>{s.error.value='';try{await action();s.notice.value=success}catch(e){s.error.value=e.message}},()=>{}),
     can:key=>s.user.value?.permissions.includes(key)??false,localTime:v=>v}});export const useAppStore=()=>{const store=usePiniaAppStore();return {...store,...storeToRefs(store)}}`
   // 共享详情的内部绘制已有独立用例；本页保留单一挂载点与真实库存读取 actions，避免把请求伪造为成功。
   if(id==='\0products-inventory-details')return `import {h} from 'vue';import {usePiniaAppStore} from 'virtual:products-store';export default {setup(){const store=usePiniaAppStore();return()=>h('aside',{'data-shared-inventory-details':true},store.ledgerMaterialTarget?h('section',{'data-inventory-material':store.ledgerMaterialTarget.material_id},[store.ledgerMaterialTarget.sku,store.ledgerMaterialDetail?.name]):null)}}`
   if(id==='\0products-modal')return `import {h} from 'vue';export default {props:['show','title'],setup:(p,{slots})=>()=>p.show?h('section',{'data-modal':p.title},[h('h2',p.title),slots.default?.()]):null}`
   if(id==='\0products-table')return `import {h} from 'vue';export const tables=[];export default {props:['data','columns','title','pagination'],setup:(p,{slots})=>()=>{tables.push(p);return h('section',{'data-table':p.title},[slots.heading?.(),slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...(p.data??[]).map(row=>h('article',(p.columns??[]).map(c=>h('div',{'data-column':c.key,'data-column-title':c.title},slots['cell-'+c.key]?.({row}))))),!(p.data??[]).length?slots.empty?.():null])}}`
   if(id==='\0products-pagination')return `import {h} from 'vue';export const paginations=[];export default {props:['page','pageSize','total','disabled'],setup:(p,{attrs})=>()=>{paginations.push({...p,...attrs});return h('nav',{'data-product-pagination':p.total})}}`
   if(id==='\0products-button')return `import {h} from 'vue';export const buttons=[];const text=v=>(v??[]).map(n=>typeof n.children==='string'?n.children:Array.isArray(n.children)?text(n.children):'').join('');export default {props:['disabled','type'],setup:(p,{slots,attrs})=>()=>{const content=slots.default?.();buttons.push({label:text(content).trim(),props:p,attrs});return h('button',{...attrs,disabled:p.disabled,type:p.type},content)}}`
   if(id==='\0products-input')return `import {h} from 'vue';export default {props:['modelValue'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue})}`
   if(id==='\0products-select')return `import {h} from 'vue';export const selects=[];export default {props:['modelValue','options','materials'],setup:(p,{attrs})=>()=>{selects.push({props:p,attrs});return h('select',attrs,(p.options??p.materials??[]).map(o=>h('option',{value:o.value??o.id},o.label??o.name)))}}`
   if(id==='\0products-material')return `import {h} from 'vue';export default {props:['form'],setup:(p,{slots})=>()=>h('form',[slots.beforeFields?.(),slots.profileFields?.(),h('input',{value:p.form.name})])}`
 }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore}=await server.ssrLoadModule('\0products-store')
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductsView.vue')
 const {default:Tree}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductTreeSidebar.vue')
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
   action==='productChanges'?[]:action==='productDetail'?product:action==='productBoms'?[source]:action==='bomDetail'?source:
   action==='materialDetail'?{...material,id:payload.id,sku:'EL-IC-22',name:'主芯片'}:
   action==='inventoryLedger'?{groups:[],rows:[],total:0,page:payload.page,page_size:payload.page_size}:undefined}}}
 t.after(()=>{globalThis.window=previous})
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/workspace/products',component:View},{path:'/workspace/work-orders',component:{render:()=>null}}]})
 await router.push('/workspace/products');await router.isReady()
 let setup;const overrides={}, beforeRender={}, components={}
 const render=async()=>{buttons.length=0;tables.length=0;paginations.length=0;selects.length=0
   const app=createSSRApp(View).use(pinia).use(router)
   app.mixin({async serverPrefetch(){if(this.$options.__name==='ProductsView'){await store.queryProducts();const id=store.productDetailId || store.productResult?.items[0]?.id;if(id)await store.openProduct(id);beforeRender.apply?.(store);
    // 模拟用户在详情读取完成后打开目标弹窗，不让初始化选中事件误清测试意图。
    for(const[key,value]of Object.entries(overrides))this.$.setupState[key]=value
    // 在同一页面实例记录选择来源的意图，避免测试越过产品与会话校验。
    await beforeRender.interact?.(this.$.setupState,store)}},created(){components[this.$options.__name]=this.$.setupState;if(this.$options.__name==='ProductsView')setup=this.$.setupState}})
   return renderToString(app)
 }
 await store.queryProducts()
 store.materials=[material,{...material,id:22,sku:'EL-IC-22',name:'主芯片',unit:'个'}]
 const renderLegacyBom=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(LegacyBom,{show:true})}).use(pinia).use(router))}
 const renderWorkOrders=async()=>{buttons.length=0;selects.length=0;const app=createSSRApp(WorkOrders).use(pinia).use(router);app.mixin({created(){components[this.$options.__name]=this.$.setupState}});return renderToString(app)}
 const treeEvents=[],treeProps=reactive({models:store.productModels,rows:[product],activeSeriesId:null,page:{items:[product],page:1,page_size:20,total:43},
  query:store.productQuery,selectedId:1,selected:product,loading:false,error:'',loadingMore:false,moreError:'',busy:false,disconnected:false,canManage:true})
 const renderTree=async(props={})=>{Object.assign(treeProps,props);buttons.length=0;paginations.length=0
  const app=createSSRApp({render:()=>h(Tree,{...treeProps,onLoadMore:()=>treeEvents.push('loadMore'),onRetry:()=>treeEvents.push('retry')})}).use(pinia)
  app.mixin({created(){components[this.$options.__name]=this.$.setupState}})
  return renderToString(app)
 }
 const mountView=async()=>{
  // 真实监听必须持续挂载，才能发现追加元数据误触发“选择新页首项”的回归。
  const renderer=componentRenderer()
  let liveSetup
  const app=renderer.createApp({render:()=>h({...View,render:()=>null})}).use(pinia).use(router)
  app.mixin({created(){components[this.$options.__name]=this.$.setupState;if(this.$options.__name==='ProductsView')liveSetup=this.$.setupState}})
  app.provide(ssrContextKey,{modules:new Set()});app.mount({});t.after(()=>app.unmount())
  await new Promise(done=>setImmediate(done));await nextTick()
  return liveSetup
 }
 const mountRenderedView=async()=>{
  const {default:LiveView}=await server.ssrLoadModule(liveModules[0][0])
  // 原生节点保留父子关系和实际文字，检查局部历史状态时不以 setup 变量冒充已渲染界面。
  const element=tag=>markRaw({tag,children:[],props:{},text:'',parent:null}),root=element('root')
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:()=>element('#comment'),
   insert(node,parent,anchor){
    if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1)
    const index=anchor?parent.children.indexOf(anchor):-1
    parent.children.splice(index<0?parent.children.length:index,0,node);node.parent=parent
   },remove(node){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=null},
   setText(node,text){node.text=text},setElementText(node,text){node.text=text;node.children=[]},
   patchProp(node,key,old,value){node.props[key]=value},parentNode:node=>node.parent,
   nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1]??null})
  const app=renderer.createApp({render:()=>h(LiveView)}).use(pinia).use(router)
  // 支持主动卸载，验证物料详情的在途请求会随页面销毁撤销，清理钩子只执行一次。
  let unmounted=false
  const unmount=()=>{if(!unmounted){unmounted=true;app.unmount()}}
  app.mount(root);t.after(unmount);await settleProductView()
  const text=node=>[node.text,...node.children.map(text)].join('')
  const descendants=node=>[node,...node.children.flatMap(descendants)]
  const nodes=()=>descendants(root)
  const button=(label,within=root)=>descendants(within).find(node=>node.tag==='button'&&(label instanceof RegExp?label.test(text(node)):text(node)===label))
  const press=node=>{assert.ok(node,'目标操作必须真实渲染');for(const handler of [node.props.onClick].flat())handler()}
  const modal=()=>nodes().find(node=>node.props['data-modal']==='产品资料')
  const bomVisible=()=>nodes().some(node=>node.props['data-table']==='组成明细 · V1')
  return {nodes,button,press,modal,bomVisible,nodeText:text,text:()=>text(root),unmount}
 }
 const renderBom=async(props)=>{
  // 单独绘制共享编辑器，可确认行内表单没有意外套回弹窗，也保留真实物料控件事件。
  buttons.length=0;tables.length=0;selects.length=0
  const app=createSSRApp({render:()=>h(LegacyBom,props)}).use(pinia).use(router)
  app.mixin({created(){if(this.$options.__name==='BomEditor')components.BomEditor=this.$.setupState}})
  return renderToString(app)
 }
 const mountBom=async(props,handlers={})=>{
  // 保存会更新受控 show 属性；持续挂载才能覆盖关闭完成后派发 saved 的真实时序。
  const controlled=reactive({...props}),savedRecords=[],updates=[],Editor={...LegacyBom,render:()=>null}
  const app=componentRenderer().createApp({render:()=>h(Editor,{...controlled,
   'onUpdate:show':show=>{updates.push(show);controlled.show=show;handlers.update?.(show)},
   onSaved:bom=>{savedRecords.push(bom);return handlers.saved?.(bom)}})}).use(pinia).use(router)
  app.mixin({created(){if(this.$options.__name==='BomEditor')components.BomEditor=this.$.setupState}})
  let unmounted=false
  const unmount=()=>{if(!unmounted){unmounted=true;app.unmount()}}
  app.provide(ssrContextKey,{modules:new Set()});app.mount({});t.after(unmount);await nextTick()
  return {controlled,savedRecords,updates,unmount}
 }
 return {store,source,product,render,renderLegacyBom,renderWorkOrders,renderTree,renderBom,mountView,mountRenderedView,mountBom,treeProps,treeEvents,buttons,tables,paginations,selects,router,calls,overrides,beforeRender,components,get setup(){return setup}}
}

// 标题由公共工作台生成；只替换导航和业务页，保留外壳的真实条件渲染。
async function shellFixture(t) {
 const server=await createServer({configFile:false,plugins:[{name:'product-shell',enforce:'pre',resolveId(id,importer){
  if(!importer?.includes('/src/renderer/'))return
  if(id.endsWith('/store/app-store'))return '\0product-shell-store'
  if(importer.endsWith('/WorkspaceShell.vue') && id.endsWith('.vue'))return '\0product-shell-empty'
 },load(id){
  if(id==='\0product-shell-empty')return 'export default {render:()=>null}'
  if(id==='\0product-shell-store')return `import {ref} from 'vue';export const state={screen:ref('app'),documentNumbering:ref(null),
    activeTab:ref('products'),workspacePageVersion:ref(0),expandedGroupKey:ref(null),busy:ref(false),user:ref(null),
    username:ref(''),password:ref(''),roles:ref([]),visibleGroups:ref([]),openedTabs:ref([]),activeRouteAllowed:ref(true),
    visibleTabs:ref([{key:'products',label:'产品与 BOM'},{key:'stock',label:'库存查询'}])};export const useAppStore=()=>state`
 }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
 t.after(()=>server.close())
 const previous=globalThis.window
 globalThis.window={nexora:{platform:'darwin'}}
 t.after(()=>{globalThis.window=previous})
 const {state}=await server.ssrLoadModule('\0product-shell-store')
 const {default:Shell}=await server.ssrLoadModule('/src/renderer/src/views/WorkspaceShell.vue')
 const render=async key=>{state.activeTab.value=key;return renderToString(createSSRApp(Shell).use(createPinia()).component('RouterView',{render:()=>null}))}
 return {render,state}
}

test('产品真实页面使用服务端目录和物料身份，移除分页且查看权限不显示维护入口',async t=>{
 const f=await fixture(t)
 const html=await f.render()
 assert.match(html,/EL-PC-11/);assert.match(html,/标准版/);assert.match(html,/新建系列/);assert.match(html,/新建子机型/)
 assert.equal(f.paginations.length,0)
 assert.doesNotMatch(html,/data-product-pagination/)
 assert.equal(f.store.productResult.total,43)
 assert.equal(f.store.productResult.items.length,1)
 assert.equal(f.store.productDirectoryRows.length,1)
 assert.match(html,/产品系列/);assert.match(html,/选择系列与子机型/)
 const left=html.slice(html.indexOf('<aside'),html.indexOf('</aside>'))
 assert.match(left,/新建系列/);assert.match(left,/新建子机型/);assert.match(left,/标准版/)
 // 目录仅收起产品编码的展示；系列编码和右侧产品身份仍可查看。
 assert.doesNotMatch(left,/EL-PC-11/);assert.match(left,/A100/)
 const right=html.slice(html.indexOf('class="product-main"'))
 assert.match(right,/EL-PC-11/)
 assert.doesNotMatch(right,/产品类型<select|class="product-options"/)
 f.store.user={...f.store.user,permissions:['inventory.view']}
 const readonly=await f.render()
 assert.doesNotMatch(readonly,/新建系列|新建子机型|纳入已有物料|系列管理/)
})

// 变更历史并非 BOM 展示的前置资料：用永不提前完成的请求证明真实主表可以先绘制。
test('产品变更记录仅在打开资料后读取，历史在途不阻塞基本资料与 BOM，关闭重开复用请求及缓存',async t=>{
 const f=await fixture(t),historyCalls=[]
 let resolve
 const pending=new Promise(done=>{resolve=done})
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productChanges'){historyCalls.push(payload.id);return pending}
  return previous(action,payload)
 }
 const live=await f.mountRenderedView()
 assert.deepEqual(historyCalls,[])
 assert.equal(live.bomVisible(),true);assert.match(live.text(),/主芯片/)
 assert.equal(f.store.productDetailLoading,false);assert.equal(f.store.productDetailError,'')
 live.press(live.button('产品资料'));await settleProductView()
 assert.deepEqual(historyCalls,[1]);assert.equal(f.store.productChangesLoading,true)
 assert.ok(live.modal());assert.match(live.nodeText(live.modal()),/产品编码/)
 // 左侧列表隐藏编号不改变产品资料弹窗，用户仍能查看完整产品编码。
 assert.match(live.nodeText(live.modal()),/EL-PC-11/)
 assert.match(live.nodeText(live.modal()),/产品名称/);assert.match(live.nodeText(live.modal()),/标准版/)
 assert.match(live.nodeText(live.modal()),/正在读取产品变更记录/)
 assert.equal(live.bomVisible(),true);assert.match(live.text(),/主芯片/)
 assert.equal(f.store.productDetailLoading,false);assert.equal(f.store.productDetailError,'')
 live.press(live.button('关闭',live.modal()));await settleProductView()
 assert.equal(live.modal(),undefined)
 live.press(live.button('产品资料'));await settleProductView()
 assert.deepEqual(historyCalls,[1],'同一份在途历史不能因重开资料重复读取')
 resolve([{id:1,before:null,after:f.product,reason:'首次建立产品档案',changed_by_name:'资料管理员',created_at:'2026-10-16 08:00:00'}])
 await settleProductView()
 assert.equal(f.store.productChangesLoading,false)
 assert.match(live.nodeText(live.modal()),/首次建立产品档案/)
 assert.doesNotMatch(live.nodeText(live.modal()),/正在读取产品变更记录/)
 live.press(live.button('关闭',live.modal()));await settleProductView()
 live.press(live.button('产品资料'));await settleProductView()
 assert.deepEqual(historyCalls,[1],'已成功读取的同产品历史直接复用缓存')
 assert.match(live.nodeText(live.modal()),/首次建立产品档案/)
 assert.equal(live.bomVisible(),true)
})

test('历史失败只在资料内显示并可重试，已可见 BOM 不进入错误或重新加载状态',async t=>{
 const f=await fixture(t)
 let historyReads=0
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productChanges'){
   if(++historyReads===1)throw Error('历史服务暂不可用')
   return [{id:2,before:null,after:f.product,reason:'重试后读取的产品历史',changed_by_name:'管理员',created_at:'2026-10-16 08:00:00'}]
  }
  return previous(action,payload)
 }
 const live=await f.mountRenderedView()
 assert.equal(historyReads,0);assert.equal(live.bomVisible(),true)
 live.press(live.button('产品资料'));await settleProductView()
 assert.equal(historyReads,1)
 assert.match(f.store.productChangesError,/历史服务暂不可用/)
 assert.match(live.nodeText(live.modal()),/历史服务暂不可用/)
 assert.equal(f.store.productChangesLoading,false)
 assert.equal(f.store.productDetailError,'');assert.equal(f.store.productDetailLoading,false)
 assert.equal(live.bomVisible(),true);assert.match(live.text(),/主芯片/)
 const retry=live.button('重试读取记录',live.modal())
 assert.ok(retry);assert.equal(retry.props.disabled,false)
 live.press(retry);await settleProductView()
 assert.equal(historyReads,2);assert.equal(f.store.productChangesError,'')
 assert.match(live.nodeText(live.modal()),/重试后读取的产品历史/)
 assert.doesNotMatch(live.nodeText(live.modal()),/历史服务暂不可用/)
 assert.equal(f.store.productDetailError,'');assert.equal(f.store.productDetailLoading,false)
 assert.equal(live.bomVisible(),true)
})

test('切换产品后旧历史回执不进入新产品资料，两个产品的 BOM 与基本资料保持独立',async t=>{
 const f=await fixture(t),historyCalls=[]
 const second={...f.product,id:2,material_id:33,material:{...f.product.material,id:33,sku:'EL-PC-33',name:'第二款产品'}}
 const secondBom={...f.source,id:9,product_material_id:33,product_sku:second.material.sku,product_name:second.material.name,
  lines:[{...f.source.lines[0],material_name:'第二款专用芯片'}]}
 let resolve
 const oldHistory=new Promise(done=>{resolve=done})
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='queryProducts')return {items:[f.product,second],page:1,page_size:20,total:2}
  if(action==='productDetail'&&payload.id===2)return second
  if(action==='productBoms'&&payload.materialId===33)return [secondBom]
  if(action==='productChanges'){
   historyCalls.push(payload.id)
   return payload.id===1?oldHistory:[{id:2,before:null,after:second,reason:'第二款独立历史',changed_by_name:'管理员',created_at:'2026-10-16 08:00:00'}]
  }
  return previous(action,payload)
 }
 const live=await f.mountRenderedView()
 live.press(live.button('产品资料'));await settleProductView()
 assert.deepEqual(historyCalls,[1]);assert.equal(f.store.productChangesLoading,true)
 live.press(live.button('选择产品 第二款产品'));await settleProductView()
 assert.equal(live.modal(),undefined)
 assert.equal(f.store.productDetailId,2);assert.equal(live.bomVisible(),true)
 assert.match(live.text(),/第二款专用芯片/)
 live.press(live.button('产品资料'));await settleProductView()
 assert.deepEqual(historyCalls,[1,2])
 assert.match(live.nodeText(live.modal()),/第二款产品/)
 assert.match(live.nodeText(live.modal()),/第二款独立历史/)
 resolve([{id:1,before:null,after:f.product,reason:'不能带入第二款的旧历史',changed_by_name:'管理员',created_at:'2026-10-16 08:00:00'}])
 await settleProductView()
 assert.equal(f.store.productDetailId,2);assert.equal(f.store.productDetailError,'')
 assert.equal(f.store.productChangesLoading,false);assert.equal(f.store.productChangesError,'')
 assert.deepEqual(f.store.productChangeRecords.map(row=>row.reason),['第二款独立历史'])
 assert.doesNotMatch(live.nodeText(live.modal()),/不能带入第二款的旧历史/)
 assert.match(live.text(),/第二款专用芯片/)
})

test('侧栏固定搜索在新建之前，滚动目录与维护按钮分开且没有分页控件',async t=>{
 const f=await fixture(t)
 const html=await f.renderTree()
 const search=html.indexOf('class="tree-search"'), create=html.indexOf('class="tree-create"')
 const scroll=html.indexOf('class="tree-scroll"'), footer=html.indexOf('<footer')
 assert.ok(search>=0 && create>search && scroll>create && footer>scroll)
 assert.ok(html.indexOf('搜索子机型')<html.indexOf('新建系列'))
 assert.doesNotMatch(html,/系列管理/)
 assert.ok(html.indexOf('纳入已有物料')>html.indexOf('</nav>'))
 assert.doesNotMatch(html,/data-product-pagination|20\s*\/\s*页/)
 assert.equal(f.paginations.length,0)
})

// 一次触底只派发一笔追加；页面状态变化与手动重试使用同一道入口。
test('目录触底阈值与同 tick 闩锁生效，加载、失败、忙碌和断线不重复追加',async t=>{
 const f=await fixture(t)
 await f.renderTree()
 let tree=f.components.ProductTreeSidebar
 const scroll=remaining=>tree.onScroll({currentTarget:{scrollHeight:1000,clientHeight:400,scrollTop:600-remaining}})
 scroll(65);assert.equal(f.treeEvents.length,0)
 scroll(64);scroll(0);tree.requestMore()
 assert.equal(f.treeEvents.length,1)
 await nextTick()
 // 目录折叠会让浏览器把位置向上修正；即使仍接近底部，也不能据此追加。
 scroll(30);scroll(30)
 assert.equal(f.treeEvents.length,1)
 for(const field of ['loading','loadingMore','busy','disconnected']) {
  await f.renderTree({[field]:true});tree=f.components.ProductTreeSidebar
  scroll(0);tree.requestMore(true)
  assert.equal(f.treeEvents.length,1);f.treeProps[field]=false
 }
 await f.renderTree({moreError:'追加失败'});tree=f.components.ProductTreeSidebar
 scroll(0);tree.requestMore();assert.equal(f.treeEvents.length,1)
 tree.requestMore(true);assert.equal(f.treeEvents.length,2)
 await nextTick()
 await f.renderTree({moreError:'',page:{...f.treeProps.page,page:3}});tree=f.components.ProductTreeSidebar
 scroll(0);tree.requestMore(true);assert.equal(f.treeEvents.length,2)
 await f.renderTree({page:null});tree=f.components.ProductTreeSidebar
 tree.requestMore(true);assert.equal(f.treeEvents.length,2)
})

test('目录未填满滚动容器时可补下一批，重复尺寸检查仍只派发一次',async t=>{
 const f=await fixture(t)
 await f.renderTree()
 const tree=f.components.ProductTreeSidebar
 tree.checkMore();assert.equal(f.treeEvents.length,0)
 tree.scrollEl={scrollHeight:900,clientHeight:500,scrollTop:0}
 tree.checkMore();assert.equal(f.treeEvents.length,0)
 tree.scrollEl={scrollHeight:500,clientHeight:500,scrollTop:0}
 tree.checkMore();tree.checkMore()
 assert.equal(f.treeEvents.length,1)
})

test('追加期间保留已加载及当前选中节点，失败在树底重试，查看账号也可继续读取',async t=>{
 const f=await fixture(t)
 const second={...f.product,id:2,material_id:33,material:{...f.product.material,id:33,sku:'EL-PC-33',name:'第二款产品'}}
 let html=await f.renderTree({rows:[f.product,second],page:{items:[second],page:2,page_size:20,total:43},loadingMore:true})
 assert.match(html,/标准版/);assert.match(html,/第二款产品/)
 assert.doesNotMatch(html,/EL-PC-11|EL-PC-33/)
 assert.match(html,/正在加载更多/);assert.doesNotMatch(html,/正在读取子机型/)
 assert.equal(f.components.ProductTreeSidebar.children.find(row=>row.id===1).material.sku,'EL-PC-11')
 assert.equal(f.buttons.find(row=>row.attrs.class?.includes('tree-model') && row.attrs['aria-pressed']===true)?.label.includes('标准版'),true)
 html=await f.renderTree({loadingMore:false,moreError:'下一批读取失败',canManage:false})
 assert.match(html,/标准版/);assert.match(html,/第二款产品/);assert.match(html,/下一批读取失败/)
 assert.doesNotMatch(html,/EL-PC-11|EL-PC-33/)
 assert.doesNotMatch(html,/新建系列|新建子机型|纳入已有物料|系列管理/)
 const retry=f.buttons.find(row=>row.label==='重试加载')
 assert.ok(retry);assert.equal(retry.props.disabled,false)
 assert.equal(f.buttons.find(row=>row.label==='刷新目录').props.disabled,false)
 retry.attrs.onClick();assert.equal(f.treeEvents.length,1)
 await nextTick()
 await f.renderTree({disconnected:true})
 assert.equal(f.buttons.find(row=>row.label==='重试加载').props.disabled,true)
 assert.equal(f.buttons.find(row=>row.label==='刷新目录').props.disabled,true)
 f.components.ProductTreeSidebar.requestMore(true);assert.equal(f.treeEvents.length,1)
})

// 服务端分页期间目录变化可能造成重叠；去重后的真实条数不能伪装成完整总数。
test('末页去重后条数不足时提示目录更新，刷新走首次查询入口',async t=>{
 const f=await fixture(t)
 const rows=Array.from({length:21},(_,index)=>({...f.product,id:index+1,material_id:index+11,
  material:{...f.product.material,id:index+11,sku:`EL-PC-${index+11}`,name:`产品${index+1}`}}))
 const page={items:rows.slice(-2),page:2,page_size:20,total:22}
 let html=await f.renderTree({rows,page})
 assert.match(html,/已加载 21 个子机型，目录有更新/)
 assert.doesNotMatch(html,/已显示全部/)
 assert.equal(f.components.ProductTreeSidebar.children.length,21)
 f.buttons.find(row=>row.label==='刷新目录').attrs.onClick()
 assert.deepEqual(f.treeEvents,['retry'])
 f.components.ProductTreeSidebar.requestMore(true)
 assert.deepEqual(f.treeEvents,['retry'])
 // 条数一致时正常结束，不再重复报数，也不留空的加载状态容器。
 const last={...rows[20],id:22,material_id:32,material:{...rows[20].material,id:32,sku:'EL-PC-32'}}
 html=await f.renderTree({rows:[...rows,last],page:{...page,items:[rows[20],last]}})
 assert.doesNotMatch(html,/已显示全部|class="tree-load-state"/)
 assert.doesNotMatch(html,/目录有更新/)
 assert.equal(f.buttons.some(row=>row.label==='刷新目录'),false)
})

// 真正派发到页面的追加事件不能触发“翻页清空选择”，右侧始终保留当前产品。
test('侧栏触底接通真实追加操作，保留产品选择与右侧 BOM',async t=>{
 const f=await fixture(t)
 await f.render();await f.mountView()
 const selected=f.store.productDetailRecord, bom=f.store.productBomRecords[0]
 const second={...f.product,id:2,material_id:33,material:{...f.product.material,id:33,sku:'EL-PC-33',name:'第二款产品'}}
 let resolve
 const reply=new Promise(done=>{resolve=done})
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='queryProducts' && payload.page===2){f.calls.push([action,payload]);return reply}
  return previous(action,payload)
 }
 f.components.ProductTreeSidebar.requestMore()
 assert.equal(f.store.productsLoadingMore,true)
 assert.equal(f.store.productDirectoryRows[0].id,1)
 assert.equal(f.store.productDetailRecord,selected);assert.equal(f.store.productBomRecords[0],bom)
 resolve({items:[second],page:2,page_size:20,total:43})
 await new Promise(done=>setImmediate(done));await nextTick()
 assert.deepEqual(f.store.productDirectoryRows.map(row=>row.id),[1,2])
 assert.deepEqual(f.store.productResult.items.map(row=>row.id),[2])
 assert.equal(f.store.productDetailId,1);assert.equal(f.store.productDetailRecord,selected)
 assert.equal(f.store.productBomRecords[0],bom);assert.equal(f.store.productsLoadingMore,false)
 assert.equal(f.calls.filter(([action,payload])=>action==='queryProducts' && payload.page===2).length,1)
})

test('关键词和类型筛选撤销旧范围选择，不能借详情保留逻辑选中旧产品',async t=>{
 const f=await fixture(t)
 const other={...f.product,id:2,material_id:33,model_id:2,model_code:'B200',model_name:'专业系列',kind:'semi_finished',
  material:{...f.product.material,id:33,sku:'EL-PC-33',name:'专业控制板'}}
 const secondBom={...f.source,id:9,product_material_id:33,product_name:'专业控制板'}
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='queryProducts'){
   const items=[f.product,other].filter(row=>(!payload.query || row.material.name.includes(payload.query))
    && (!payload.model_id || row.model_id===payload.model_id) && (!payload.kind || row.kind===payload.kind))
   return {items,page:1,page_size:20,total:items.length}
  }
  if(action==='productDetail')return payload.id===2?other:f.product
  if(action==='productBoms')return payload.materialId===33?[secondBom]:[f.source]
  return previous(action,payload)
 }
 await f.mountView()
 const settle=async()=>{await new Promise(done=>setImmediate(done));await nextTick()}
 assert.equal(f.store.productDetailId,1)
 f.store.productQuery.query='专业';await settle()
 assert.equal(f.store.productDetailId,2);assert.equal(f.store.productBomRecords[0].id,9)
 f.store.productQuery.query='';await settle();await f.store.openProduct(1)
 f.store.productQuery.kind='semi_finished';await settle()
 assert.equal(f.store.productDetailId,2);assert.equal(f.store.productDetailRecord.kind,'semi_finished')
 assert.equal(f.store.productDirectoryRows.some(row=>row.id===1),false)
})

test('产品页仅缩紧自己的公共标题，保留说明，库存页沿用原有标题',async t=>{
 const f=await shellFixture(t)
 const product=await f.render('products')
 assert.match(product,/class="[^"]*product-catalog-screen/)
 assert.match(product,/class="[^"]*topbar--compact/)
 assert.match(product,/<h1[^>]*>\s*产品与 BOM\s*<\/h1>/)
 assert.match(product,/统一管理成品与半成品/)
 assert.match(product,/NEXORA WORKSPACE/)
 const stock=await f.render('stock')
 assert.doesNotMatch(stock,/product-catalog-screen|topbar--compact/)
 assert.match(stock,/NEXORA WORKSPACE/);assert.match(stock,/<h1[^>]*>\s*库存查询\s*<\/h1>/)
 assert.match(stock,/按物料查看当前库存/)
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

test('产品工作区直接编辑当前产品，编辑权限和 BOM 创建权限相互独立',async t=>{
 const f=await fixture(t)
 let html=await f.render()
 assert.match(html,/编辑产品/);assert.match(html,/修订 BOM/)
 await f.buttons.find(row=>row.label==='编辑产品').attrs.onClick()
 assert.equal(f.store.productEditorOpen,true)
 assert.equal(f.store.productForm.mode,'edit');assert.equal(f.store.productForm.id,1)
 assert.equal(f.store.productForm.material_id,11);assert.equal(f.store.productForm.version,1)
 f.store.productEditorOpen=false
 f.store.user={...f.store.user,permissions:['inventory.view','production.view','bom.create']}
 html=await f.render()
 assert.doesNotMatch(html,/编辑产品/);assert.match(html,/修订 BOM/)
 await f.setup.editProduct();assert.equal(f.store.productEditorOpen,false)
 f.setup.reviseBom();assert.equal(f.store.bomForm.source_bom_id,7)
 f.store.user={...f.store.user,permissions:['inventory.view','catalog.manage']}
 html=await f.render()
 assert.match(html,/编辑产品/);assert.doesNotMatch(html,/修订 BOM/)
 const draft=JSON.stringify(f.store.bomForm)
 f.setup.reviseBom();assert.equal(JSON.stringify(f.store.bomForm),draft)
 f.store.user={...f.store.user,permissions:['inventory.view','production.view']}
 html=await f.render();assert.doesNotMatch(html,/编辑产品|修订 BOM/)
})

// 修订是从所选历史配方创建独立草稿，保存失败与收起都不能覆盖用户的修改。
test('修订所选历史 BOM 保留来源与旧数组，失败关闭重开仍保留数量及组件草稿',async t=>{
 const f=await fixture(t)
 f.source.version=3
 const history={...f.source,id:8,version:2,status:'retired',base_quantity:'2',
  lines:[{...f.source.lines[0],quantity:'5'}]}
 const original=JSON.stringify([f.source,history])
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productBoms')return [f.source,history]
  if(action==='createBom'){f.calls.push([action,payload]);throw Error('组件配方已变更，请修正后重试')}
  return previous(action,payload)
 }
 await f.render()
 f.selects.find(row=>row.attrs['aria-label']==='选择 BOM 版本').attrs['onUpdate:modelValue'](8)
 await click(f.buttons.find(row=>row.label==='修订 BOM'))
 assert.equal(f.setup.revisingBomVersion,2)
 assert.equal(f.store.bomForm.source_bom_id,8);assert.equal(f.store.bomForm.base_quantity,'2')
 assert.equal(f.store.bomForm.lines[0].quantity,'5')
 f.store.materials.push({...f.product.material,id:44,sku:'EL-IC-44',name:'替换芯片'})
 const draftLine=f.store.bomForm.lines[0]
 draftLine.component_material_id=44;draftLine.quantity='9';f.store.bomForm.note='修订中的用料'
 assert.equal(JSON.stringify([f.source,history]),original)
 f.overrides.selectedBomId=8;f.overrides.bomOpen=true;f.overrides.bomTargetId=11;f.overrides.revisingBomVersion=2
 let html=await f.render()
 assert.match(html,/data-modal="修订 BOM · V2"/)
 assert.match(html,/派生来源 BOM #8/);assert.match(html,/原版本及已有工单保持不变/)
 assert.equal(f.buttons.some(row=>row.label==='保存为新版本草稿'),true)
 await f.components.BomEditor.submitCreate()
 assert.match(f.store.error,/组件配方已变更/);assert.equal(f.setup.bomOpen,true)
 const payload=f.calls.find(([action])=>action==='createBom')[1]
 assert.equal(payload.source_bom_id,8);assert.equal(payload.product_material_id,11)
 assert.equal(payload.lines[0].component_material_id,44);assert.equal(payload.lines[0].quantity,'9')
 f.buttons.find(row=>row.label==='收起').attrs.onClick()
 assert.equal(f.setup.bomOpen,false)
 f.setup.reviseBom()
 assert.equal(f.setup.bomOpen,true);assert.equal(f.store.bomForm.lines[0],draftLine)
 assert.equal(f.store.bomForm.lines[0].quantity,'9');assert.equal(f.store.bomForm.note,'修订中的用料')
 assert.equal(JSON.stringify([f.source,history]),original)
 // 普通新建继续使用原有编辑器标题，不把修订标记带入另一份草稿。
 f.setup.startBom();f.overrides.revisingBomVersion=f.setup.revisingBomVersion
 html=await f.render();assert.match(html,/data-modal="新建 BOM 版本"/)
 assert.doesNotMatch(html,/data-modal="修订 BOM/)
})

test('修订和编辑入口拒绝忙碌、断线、加载错误、已取消版本及错误产出',async t=>{
 const f=await fixture(t)
 await f.render()
 f.store.bomForm.note='不得被覆盖的草稿'
 const draft=JSON.stringify(f.store.bomForm)
 for(const blocked of ['busy','productDetailLoading','productDetailError']){
  f.beforeRender.apply=store=>{store[blocked]=blocked==='productDetailError'?'读取失败':true}
  await f.render()
  assert.equal(f.buttons.find(row=>row.label==='编辑产品').props.disabled,true)
  const revise=f.buttons.find(row=>row.label==='修订 BOM')
  if(revise)assert.equal(revise.props.disabled,true)
  await f.setup.editProduct();f.setup.reviseBom()
  assert.equal(f.store.productEditorOpen,false);assert.equal(JSON.stringify(f.store.bomForm),draft)
  f.store[blocked]=blocked==='productDetailError'?'':false
 }
 f.beforeRender.apply=store=>{store.productBomRecords=[{...f.source,status:'cancelled'}]}
 await f.render()
 assert.equal(f.buttons.find(row=>row.label==='修订 BOM').props.disabled,true)
 f.setup.reviseBom();assert.equal(JSON.stringify(f.store.bomForm),draft)
 f.beforeRender.apply=store=>{store.productBomRecords=[{...f.source,product_material_id:99}]}
 await f.render();f.setup.reviseBom();assert.equal(JSON.stringify(f.store.bomForm),draft)
 f.beforeRender.apply=undefined
 await f.render();f.store.connectionLost=true
 await f.setup.editProduct();f.setup.reviseBom()
 assert.equal(f.store.productEditorOpen,false);assert.equal(JSON.stringify(f.store.bomForm),draft)
})

// 刷新期间可能出现别人的更高版本，当前选择必须跟随本次保存的真实回执。
test('修订保存后选中自己的新草稿回执，不猜并发产生的最新版本',async t=>{
 const f=await fixture(t)
 f.source.version=3
 const history={...f.source,id:8,version:2,status:'retired',base_quantity:'2',lines:f.source.lines.map(row=>({...row,quantity:'5'}))}
 const saved={...f.source,id:90,version:4,status:'draft',base_quantity:'2',source_bom_id:8,
  lines:f.source.lines.map(row=>({...row,id:90,quantity:'9'}))}
 const competing={...saved,id:120,version:5}
 let created=false
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productBoms')return created?[competing,saved,f.source,history]:[f.source,history]
  if(action==='createBom'){f.calls.push([action,payload]);created=true;return saved}
  return previous(action,payload)
 }
 await f.render();f.setup.selectVersion(8);f.setup.reviseBom()
 f.store.bomForm.lines[0].quantity='9'
 f.overrides.selectedBomId=8;f.overrides.bomOpen=true;f.overrides.bomTargetId=11;f.overrides.revisingBomVersion=2
 await f.render()
 const editor=await f.mountBom({show:f.setup.bomOpen,targetMaterialId:f.setup.bomTargetId,sourceVersion:f.setup.revisingBomVersion},
  {update:show=>{f.setup.bomOpen=show},saved:bom=>f.setup.afterBomSaved(bom)})
 await f.components.BomEditor.submitCreate()
 await new Promise(done=>setImmediate(done));await nextTick()
 assert.equal(f.setup.bomOpen,false)
 assert.equal(editor.controlled.show,false);assert.equal(editor.savedRecords[0].id,90)
 assert.equal(f.setup.selectedBom.id,90);assert.equal(f.setup.selectedBom.version,4)
 assert.equal(f.setup.selectedBom.status,'draft')
 assert.equal(f.store.productBomRecords.some(row=>row.id===120),true)
 assert.equal(history.lines[0].quantity,'5');assert.equal(f.source.lines[0].quantity,'2')
 assert.equal(f.calls.filter(([action])=>action==='createBom').length,1)
})

test('合法 BOM 回执不依赖成功提示，saved 回调换账号时不关闭另一会话弹窗',async t=>{
 const f=await fixture(t)
 await f.render();f.setup.reviseBom()
 const receipt={...f.source,id:90,version:2,status:'draft',source_bom_id:7}
 f.store.createBom=async()=>receipt
 f.store.notice='';f.store.error='BOM 已保存，但资料刷新失败'
 let switchAccount=false
 const editor=await f.mountBom({show:true,targetMaterialId:11,sourceVersion:1},{saved:()=>{
  if(switchAccount)f.store.user={...f.store.user,id:2}
 }})
 await f.components.BomEditor.submitCreate();await nextTick()
 assert.equal(editor.savedRecords[0].id,90);assert.equal(editor.controlled.show,false)
 assert.equal(f.store.notice,'');assert.match(f.store.error,/刷新失败/)
 editor.controlled.show=true;await nextTick();switchAccount=true
 await f.components.BomEditor.submitCreate();await nextTick()
 assert.equal(editor.savedRecords.length,2);assert.equal(editor.controlled.show,true)
})

test('保存途中关闭并重开同一修订窗，迟到回执不能关闭或定位新意图',async t=>{
 const f=await fixture(t)
 await f.render();f.setup.reviseBom()
 let resolve
 f.store.createBom=()=>new Promise(done=>{resolve=done})
 const editor=await f.mountBom({show:true,targetMaterialId:11,sourceVersion:1},{})
 const pending=f.components.BomEditor.submitCreate()
 editor.controlled.show=false;await nextTick()
 editor.controlled.show=true;await nextTick()
 resolve({...f.source,id:90,version:2,status:'draft',source_bom_id:7})
 await pending
 assert.equal(editor.savedRecords.length,0);assert.equal(editor.controlled.show,true)
})

test('保存途中卸载 BOM 编辑器，迟到回执不能向旧页面派发 saved',async t=>{
 const f=await fixture(t)
 await f.render();f.setup.reviseBom()
 let resolve
 f.store.createBom=()=>new Promise(done=>{resolve=done})
 const editor=await f.mountBom({show:true,targetMaterialId:11,sourceVersion:1},{})
 const pending=f.components.BomEditor.submitCreate()
 editor.unmount()
 resolve({...f.source,id:90,version:2,status:'draft',source_bom_id:7})
 await pending
 assert.equal(editor.savedRecords.length,0)
 assert.equal(editor.controlled.show,true)
})

// 同会话快速 A→B→A 仍是新的产品选择，旧刷新完成不能抢走用户后来选定的版本。
test('保存后刷新期间切换产品再返回，旧修订回执不能抢选版本',async t=>{
 const f=await fixture(t)
 const receipt={...f.source,id:90,version:2,status:'draft',source_bom_id:7}
 const other={...f.product,id:2,material_id:33,material:{...f.product.material,id:33,sku:'EL-PC-33',name:'其他产品'}}
 let resolve,delay=false
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productDetail'){
   if(payload.id===1 && delay){delay=false;return new Promise(done=>{resolve=done})}
   return payload.id===2?other:f.product
  }
  if(action==='productBoms')return payload.materialId===11?[receipt,f.source]:[{...f.source,id:18,product_material_id:33}]
  return previous(action,payload)
 }
 const live=await f.mountView()
 delay=true
 const pending=live.afterBomSaved(receipt)
 await f.store.openProduct(2);await f.store.openProduct(1)
 assert.equal(live.selectedBom.id,7)
 resolve(f.product);await pending;await nextTick()
 assert.equal(f.store.productDetailId,1);assert.equal(live.selectedBom.id,7)
})

// 系列点击仅记录本地新建归属，不能把全目录改成系列筛选或抢走右侧手动选中的历史版本。
test('点击系列保留全目录与未归组 PCB，右侧产品和历史 BOM 版本不切换',async t=>{
 const f=await fixture(t)
 const second={...f.product,id:2,material_id:33,model_id:2,model_name:'B200 系列',model_code:'B200',configuration_name:'专业版',material:{...f.product.material,id:33,sku:'EL-PC-33',name:'专业控制板'}}
 const pcb={...f.product,id:3,material_id:44,model_id:null,model_name:'',model_code:'',kind:'semi_finished',material:{...f.product.material,id:44,sku:'PCB-44',name:'未归组 PCB 板'}}
 const historical={...f.source,id:8,version:2,status:'retired'}
 globalThis.window.nexora.callApi=async(action,payload)=>{
   f.calls.push([action,payload])
   if(action==='queryProducts'){
    const items=[f.product,second,pcb].filter(row=>payload.model_id===null || row.model_id===payload.model_id)
    return {items,page:1,page_size:20,total:items.length}
   }
   if(action==='productModels')return [{id:1,code:'A100',name:'机型A',notes:'',version:1,created_by:1,created_at:'2026-10-15'},{id:2,code:'B200',name:'B200 系列',notes:'',version:1,created_by:1,created_at:'2026-10-15'}]
   if(action==='productDetail')return [f.product,second,pcb].find(row=>row.id===payload.id)
   if(action==='productChanges')return []
   if(action==='productBoms')return payload.materialId===11?[f.source,historical]:[]
 }
 const live=await f.mountView();await settleProductView()
 live.selectVersion(8)
 const selected=f.store.productDetailRecord,boms=f.store.productBomRecords,rows=f.store.productDirectoryRows
 const version=live.selectedBom,query=JSON.stringify(f.store.productQuery),count=f.calls.length
 for(const id of [2,1,null]){
  live.selectSeries(id);await settleProductView()
  assert.equal(live.currentSeriesId,id)
  assert.equal(JSON.stringify(f.store.productQuery),query)
  assert.equal(f.store.productQuery.model_id,null)
  assert.equal(f.store.productDirectoryRows,rows)
  assert.ok(f.store.productDirectoryRows.some(row=>row.id===pcb.id && row.model_id===null))
  assert.equal(f.store.productDetailId,1);assert.equal(f.store.productDetailRecord,selected)
  assert.equal(f.store.productBomRecords,boms);assert.equal(live.selectedBom,version)
  assert.equal(live.selectedBom.id,8)
  assert.equal(f.calls.length,count,'系列操作不能重新查询目录、详情或 BOM')
 }
 live.selectSeries(2)
 const html=await f.renderTree({models:f.store.productModels,rows,page:f.store.productResult,activeSeriesId:live.currentSeriesId,selectedId:1,selected})
 assert.match(html,/B200 系列/);assert.match(html,/未归组产品 \/ 半成品/);assert.match(html,/未归组 PCB 板/)
 assert.doesNotMatch(html,/EL-PC-11|EL-PC-33|PCB-44/)
})

test('入页清除遗留系列过滤但保留关键词类型，首次请求读取全目录',async t=>{
 const f=await fixture(t)
 f.store.productQuery={...f.store.productQuery,model_id:99,query:'标准',kind:'finished',page:3}
 f.calls.length=0
 await f.mountView();await settleProductView()
 const reads=f.calls.filter(([action])=>action==='queryProducts').map(([,payload])=>payload)
 assert.ok(reads.length>0)
 assert.ok(reads.every(query=>query.model_id===null && query.page===1 && query.query==='标准' && query.kind==='finished'))
 assert.equal(f.store.productQuery.model_id,null)
 assert.equal(f.store.productDetailId,1)
})

// 保存回执可能不在第一页；完整目录和固定编号定位必须同时成立，不能用系列筛选让目标碰巧出现。
test('保存子机型后全目录刷新不收窄，第一页之外的回执仍定位且未归组 PCB 保留',async t=>{
 const f=await fixture(t)
 const saved={...f.product,id:2,material_id:33,model_id:2,model_name:'B200 系列',model_code:'B200',material:{...f.product.material,id:33,sku:'EL-PC-33',name:'新保存的子机型'}}
 const pcb={...f.product,id:3,material_id:44,model_id:null,model_name:'',model_code:'',kind:'semi_finished',material:{...f.product.material,id:44,sku:'PCB-44',name:'未归组 PCB'}}
 globalThis.window.nexora.callApi=async(action,payload)=>{
  f.calls.push([action,payload])
  if(action==='queryProducts')return {items:[f.product,pcb],page:1,page_size:20,total:23}
  if(action==='productModels')return [{id:1,code:'A100',name:'机型A',notes:'',version:1,created_by:1,created_at:'2026-10-15'},{id:2,code:'B200',name:'B200 系列',notes:'',version:1,created_by:1,created_at:'2026-10-15'}]
  if(action==='createProduct')return saved
  if(action==='productDetail')return payload.id===saved.id?saved:f.product
  if(action==='productChanges')return []
  if(action==='productBoms')return payload.materialId===11?[f.source]:[]
 }
 const live=await f.mountView();await settleProductView()
 f.store.productForm={...f.store.productForm,mode:'existing',material_id:saved.material_id,model_id:saved.model_id}
 f.calls.length=0
 const receipt=await f.store.saveProduct()
 assert.ok(receipt);assert.equal(receipt.id,saved.id)
 live.productSaved(receipt);await settleProductView()
 const reads=f.calls.filter(([action])=>action==='queryProducts').map(([,payload])=>payload)
 assert.ok(reads.length>0);assert.ok(reads.every(query=>query.model_id===null && query.page===1))
 assert.equal(f.store.productQuery.model_id,null)
 assert.deepEqual(f.store.productDirectoryRows.map(row=>row.id),[1,3])
 assert.equal(f.store.productDetailId,saved.id);assert.equal(f.store.productDetailRecord.id,saved.id)
 assert.equal(live.currentSeriesId,saved.model_id)
 const html=await f.renderTree({models:f.store.productModels,rows:f.store.productDirectoryRows,page:f.store.productResult,activeSeriesId:live.currentSeriesId,selectedId:saved.id,selected:f.store.productDetailRecord})
 assert.match(html,/未归组 PCB/);assert.match(html,/新保存的子机型/)
 assert.doesNotMatch(html,/EL-PC-11|EL-PC-33|PCB-44/)
 assert.equal(f.components.ProductTreeSidebar.children.filter(row=>row.id===saved.id).length,1)
})

test('保存系列只更新本地新建归属，选择子机型时归属跟随实际记录',async t=>{
 const f=await fixture(t),live=await f.mountView()
 await settleProductView()
 const selected=f.store.productDetailRecord,boms=f.store.productBomRecords,query=JSON.stringify(f.store.productQuery),count=f.calls.length
 const model=f.store.productModels[0],reveal=live.seriesRevealKey
 live.seriesSaved(model);await settleProductView()
 assert.equal(live.currentSeriesId,model.id)
 assert.ok(live.seriesRevealKey>reveal)
 assert.equal(JSON.stringify(f.store.productQuery),query)
 assert.equal(f.store.productDetailRecord,selected);assert.equal(f.store.productBomRecords,boms)
 assert.equal(f.calls.length,count)
 live.selectSeries(null)
 assert.equal(live.currentSeriesId,null)
 const sameModelReveal=live.seriesRevealKey
 live.sameModel()
 assert.equal(live.currentSeriesId,selected.model_id)
 assert.ok(live.seriesRevealKey>sameModelReveal)
 assert.equal(f.calls.length,count,'查看同系列只定位展开目录，不重新收窄查询')
 live.selectSeries(null)
 await live.selectProduct(selected.id)
 assert.equal(live.currentSeriesId,selected.model_id)
})

// 请求发出时选的是产品，返回前用户已明确选择未归组；最后操作必须决定新建归属。
test('产品详情在途时选择未归组，迟到详情不覆盖归属，再次明确选产品才恢复其系列',async t=>{
 const f=await fixture(t)
 const second={...f.product,id:2,material_id:33,model_id:2,model_name:'第二系列',model_code:'B200',material:{...f.product.material,id:33,sku:'MODEL-33',name:'第二系列产品'}}
 const secondModel={id:2,code:'B200',name:'第二系列',notes:'',version:1,created_by:1,created_at:'2026-10-15'}
 let resolve,secondReads=0
 const pendingDetail=new Promise(done=>{resolve=done})
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='queryProducts')return {items:[f.product,second],page:1,page_size:20,total:2}
  if(action==='productModels')return [...f.store.productModels.filter(model=>model.id!==2),secondModel]
  if(action==='productDetail'&&payload.id===2)return ++secondReads===1?pendingDetail:second
  if(action==='productBoms'&&payload.materialId===33)return []
  return previous(action,payload)
 }
 const live=await f.mountView();await settleProductView()
 const reading=live.selectProduct(2)
 assert.equal(f.store.productDetailLoading,true)
 assert.equal(live.currentSeriesId,2,'明确点击目录中的产品时先使用已知归属')
 live.selectSeries(null)
 assert.equal(live.currentSeriesId,null)
 resolve(second);await reading;await settleProductView()
 assert.equal(f.store.productDetailId,2);assert.equal(f.store.productDetailRecord.id,2)
 assert.equal(live.currentSeriesId,null,'迟到详情不能推翻明确未归组意图')
 await live.newModel()
 assert.equal(f.store.productEditorOpen,true);assert.equal(f.store.productForm.model_id,null)
 f.store.productEditorOpen=false
 await live.selectProduct(2);await settleProductView()
 assert.equal(live.currentSeriesId,2)
 await live.newModel()
 assert.equal(f.store.productForm.model_id,2,'用户再次选产品后允许重新跟随其系列')
 assert.equal(f.store.productQuery.model_id,null)
})

test('初次目录在途时明确选择系列，自动选中详情不覆盖新建上下文',async t=>{
 const f=await fixture(t)
 const second={...f.product,id:2,material_id:33,model_id:2,model_name:'第二系列',model_code:'B200',material:{...f.product.material,id:33,sku:'MODEL-33',name:'首先加载的第二系列产品'}}
 const firstModel=f.store.productModels[0],secondModel={...firstModel,id:2,code:'B200',name:'第二系列'}
 let resolve
 const pendingDirectory=new Promise(done=>{resolve=done})
 const previous=globalThis.window.nexora.callApi
 f.store.productResult=null;f.store.productDirectoryRows=[];f.store.productDetailRecord=null;f.store.productDetailId=0
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='queryProducts')return pendingDirectory
  if(action==='productModels')return [firstModel,secondModel]
  if(action==='productDetail'&&payload.id===2)return second
  if(action==='productBoms'&&payload.materialId===33)return []
  return previous(action,payload)
 }
 const live=await f.mountView()
 assert.equal(f.store.productsLoading,true);assert.equal(f.store.productDetailId,0)
 live.selectSeries(1)
 assert.equal(live.currentSeriesId,1)
 resolve({items:[second],page:1,page_size:20,total:1});await settleProductView()
 assert.equal(f.store.productDetailId,2);assert.equal(f.store.productDetailRecord.model_id,2)
 assert.equal(live.currentSeriesId,1,'首次自动展示详情不应抢走已选的新建系列')
 await live.newModel()
 assert.equal(f.store.productForm.model_id,1)
 assert.equal(f.store.productQuery.model_id,null)
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
 f.setup.selectSeries(1)
 await f.setup.newModel()
 assert.equal(f.store.productForm.model_id,1);assert.equal(f.store.productEditorOpen,true)
 f.store.productMaterialForm.name='保留的机型名称'
 await f.setup.newModel();assert.equal(f.store.productMaterialForm.name,'保留的机型名称')
 // null 是用户明确选择未归组，不能使用 ?? 回退为右侧旧产品的所属系列。
 f.store.productEditorOpen=false;f.setup.selectSeries(null)
 assert.equal(f.store.productDetailRecord.model_id,1)
 await f.setup.newModel();assert.equal(f.store.productForm.model_id,null)
 assert.equal(f.store.productQuery.model_id,null)
 f.store.productEditorOpen=false;f.setup.currentSeriesId=99
 await f.setup.newModel();assert.equal(f.store.productEditorOpen,false)
 assert.match(f.store.error,/产品系列已不存在/)
})

// 复用目录必须跨机型查询，并固定目标身份；编辑复制行不应更改来源。
test('右侧可从其他机型复用 BOM 到当前机型，排除取消版本',async t=>{
 const f=await fixture(t)
 const other={...f.source,id:88,product_material_id:33,product_name:'来源专业版',lines:f.source.lines.map(row=>({...row,quantity:'9'}))}
 f.store.boms=[other,{...f.source,id:99,status:'cancelled'}]
 f.beforeRender.interact=setup=>setup.openBomCreation(false)
 const html=await f.render()
 assert.match(html,/选择要复用的 BOM/);assert.match(html,/来源专业版/)
 assert.equal(f.tables.find(row=>row.title==='可复用版本').data.length,1)
 f.buttons.find(row=>row.label==='复用到当前机型').attrs.onClick()
 assert.equal(f.store.bomForm.product_material_id,11)
 assert.equal(f.store.bomForm.source_bom_id,88)
 assert.equal(f.store.bomForm.lines[0].quantity,'9')
 assert.equal(f.setup.reuseOpen,false);assert.equal(f.setup.bomOpen,true)
 f.store.bomForm.lines[0].quantity='4';assert.equal(other.lines[0].quantity,'9')
})

// 首次建配方直接发生在工作区；重复读取不能把用户已选组件和数量清回空白。
test('无 BOM 产品自动准备固定产出草稿，右侧直接显示共享物料编辑器并保留未保存内容',async t=>{
 const f=await fixture(t)
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>action==='productBoms'?[]:previous(action,payload)
 const prepare=f.store.prepareProductBom,prepared=[]
 f.store.prepareProductBom=(...args)=>{prepared.push(args);return prepare(...args)}
 let html=await f.render()
 assert.equal(f.store.productDetailId,1);assert.equal(f.setup.selectedBom,undefined)
 assert.equal(prepared.some(([id])=>id===11),true)
 assert.equal(f.store.bomForm.product_material_id,11)
 assert.equal(f.store.bomForm.source_bom_id??null,null)
 assert.equal(f.store.bomForm.base_quantity,'1')
 const line=f.store.bomForm.lines[0]
 assert.doesNotMatch(html,/data-modal="新建 BOM 版本"/)
 assert.match(html,/aria-label="建立首个 BOM"/)
 assert.match(html,/第 1 行物料/);assert.match(html,/基准用量/)
 assert.equal(f.buttons.some(row=>row.label==='复用已有 BOM'),true)
 assert.equal(f.buttons.some(row=>row.props.type==='submit' && row.label==='保存 BOM 草稿'),true)
 const component=f.selects.find(row=>row.attrs['aria-label']==='第 1 行物料')
 component.attrs['onUpdate:modelValue'](22)
 line.quantity='3';f.store.bomForm.note='首版配方'
 html=await f.render()
 assert.equal(f.store.bomForm.lines[0],line)
 assert.equal(line.component_material_id,22);assert.equal(line.quantity,'3')
 assert.equal(f.store.bomForm.note,'首版配方')
 assert.match(html,/第 1 行物料/)
})

// 关闭详情、刷新或返回页面均会重新挂载编辑器，同目标不能丢掉已经复用并修改的整份配方。
test('首建复用草稿重挂载和重读仍保留来源、基准、备注与下层配方，切换目标才初始化',async t=>{
 const f=await fixture(t)
 const other={...f.source,id:88,product_material_id:33,base_quantity:'2',
  lines:f.source.lines.map(row=>({...row,quantity:'9',component_bom_id:71}))}
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>action==='productBoms'?[]:previous(action,payload)
 f.store.materials.push({...f.product.material,id:33,sku:'EL-PC-33',name:'另一款产品'})
 f.store.prepareProductBom(11,other)
 const draft=f.store.bomForm,line=draft.lines[0]
 draft.base_quantity='3';draft.note='复用后调整的首版';line.quantity='5'
 const snapshot=JSON.stringify(draft)
 const first=await f.mountBom({show:true,inline:true,targetMaterialId:11})
 assert.equal(f.store.bomForm,draft);assert.equal(f.store.bomForm.lines[0],line)
 assert.equal(JSON.stringify(f.store.bomForm),snapshot)
 first.unmount()
 const second=await f.mountBom({show:true,inline:true,targetMaterialId:11})
 assert.equal(f.store.bomForm,draft);assert.equal(f.store.bomForm.lines[0],line)
 assert.equal(JSON.stringify(f.store.bomForm),snapshot)
 const html=await f.render()
 assert.match(html,/aria-label="建立首个 BOM"/);assert.match(html,/派生来源 BOM #88/)
 assert.equal(f.store.bomForm,draft);assert.equal(f.store.bomForm.lines[0],line)
 assert.equal(JSON.stringify(f.store.bomForm),snapshot)
 assert.equal(line.component_bom_id,71)
 second.controlled.targetMaterialId=33;await nextTick()
 assert.notEqual(f.store.bomForm,draft);assert.notEqual(f.store.bomForm.lines[0],line)
 assert.equal(f.store.bomForm.product_material_id,33);assert.equal(f.store.bomForm.source_bom_id??null,null)
 assert.equal(f.store.bomForm.base_quantity,'1');assert.equal(f.store.bomForm.note,'')
 assert.equal(f.store.bomForm.lines[0].component_material_id,0)
 assert.equal(JSON.stringify(draft),snapshot)
})

// 产品弹窗由工作区统一承载；行内编辑器不能像独立 BOM 弹窗一样再挂一份默认产品编辑器。
test('行内首建时新建或编辑子机型仅显示一份产品弹窗，不叠加默认产品编辑器',async t=>{
 const f=await fixture(t)
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>action==='productBoms'?[]:previous(action,payload)
 for(const [action,title]of [['newModel','新建子机型'],['editProduct','编辑子机型']]){
  f.store.productEditorOpen=false
  f.beforeRender.interact=setup=>setup[action]()
  const html=await f.render()
  assert.equal(f.store.productEditorOpen,true)
  assert.equal((html.match(new RegExp(`data-modal="${title}"`,'g'))??[]).length,1)
  assert.equal((html.match(/data-modal="(?:新建|编辑)(?:子机型|产品)"/g)??[]).length,1)
  assert.doesNotMatch(html,/data-modal="(?:新建|编辑)产品"/)
 }
})

// 保存调用真实 Pinia 写入与产品重读，确保清空已确认草稿后仍能定位 V1 回执。
test('行内首建 BOM 失败保留用料，重试成功选中 V1 且不派发关闭事件',async t=>{
 const f=await fixture(t)
 const previous=globalThis.window.nexora.callApi
 const saved={...f.source,id:90,version:1,status:'draft',source_bom_id:null,
  lines:f.source.lines.map(row=>({...row,id:90,quantity:'3'}))}
 const competing={...saved,id:120,version:2}
 let fail=true,created=false
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productBoms')return created?[competing,saved]:[]
  if(action==='createBom'){
   f.calls.push([action,payload])
   if(fail)throw Error('首版配方保存失败，请重试')
   created=true;return saved
  }
  return previous(action,payload)
 }
 await f.render()
 const live=await f.mountView()
 const line=f.store.bomForm.lines[0]
 line.component_material_id=22;line.quantity='3';f.store.bomForm.note='首版配方'
 const html=await f.renderBom({show:true,inline:true,targetMaterialId:11})
 assert.doesNotMatch(html,/data-modal=/)
 assert.match(html,/第 1 行物料/)
 const editor=await f.mountBom({show:true,inline:true,targetMaterialId:11},{saved:bom=>live.afterBomSaved(bom)})
 await f.components.BomEditor.submitCreate()
 assert.match(f.store.error,/首版配方保存失败/)
 assert.equal(f.store.bomForm.lines[0],line);assert.equal(line.quantity,'3')
 assert.equal(f.store.bomForm.note,'首版配方')
 assert.equal(editor.savedRecords.length,0);assert.deepEqual(editor.updates,[])
 assert.equal(editor.controlled.show,true)
 fail=false
 await f.components.BomEditor.submitCreate()
 await new Promise(done=>setImmediate(done));await nextTick()
 assert.equal(editor.savedRecords[0].id,90);assert.deepEqual(editor.updates,[])
 assert.equal(editor.controlled.show,true)
 assert.equal(live.selectedBom.id,90);assert.equal(live.selectedBom.version,1)
 assert.equal(live.selectedBom.status,'draft')
 assert.equal(f.store.productBomRecords.some(row=>row.id===120),true)
 const writes=f.calls.filter(([action])=>action==='createBom')
 assert.equal(writes.length,2)
 for(const [,payload]of writes){
  assert.equal(payload.product_material_id,11);assert.equal(payload.source_bom_id,undefined)
  assert.equal(payload.base_quantity,'1');assert.equal(payload.lines[0].component_material_id,22)
  assert.equal(payload.lines[0].quantity,'3')
 }
})

test('行内保存途中切换目标，迟到回执不得定位另一产品',async t=>{
 const f=await fixture(t)
 await f.render();f.store.prepareProductBom(11,f.source)
 let resolve
 f.store.createBom=()=>new Promise(done=>{resolve=done})
 const editor=await f.mountBom({show:true,inline:true,targetMaterialId:11})
 f.store.bomForm.lines[0].component_material_id=22
 const pending=f.components.BomEditor.submitCreate()
 editor.controlled.targetMaterialId=33;await nextTick()
 resolve({...f.source,id:90,version:2,status:'draft',source_bom_id:7})
 await pending
 assert.deepEqual(editor.savedRecords,[]);assert.deepEqual(editor.updates,[])
 assert.equal(editor.controlled.show,true)
})

// 新建后续版本先明确来源，空白创建与复制都会成为独立草稿，不能改写旧组成。
test('已有版本新建先选择空白或复用，空白分支清理来源后才打开编辑器',async t=>{
 const f=await fixture(t)
 f.store.prepareProductBom(11,f.source)
 f.store.bomForm.note='旧草稿说明'
 const existing=JSON.stringify(f.source)
 const draft=JSON.stringify(f.store.bomForm)
 await f.render()
 await click(f.buttons.find(row=>row.label==='新建版本'))
 assert.equal(f.setup.reuseOpen,true);assert.equal(f.setup.bomOpen,false)
 assert.equal(JSON.stringify(f.store.bomForm),draft)
 f.beforeRender.interact=setup=>setup.openBomCreation()
 await f.render()
 assert.equal(f.selects.some(row=>row.attrs['aria-label']==='第 1 行物料'),false)
 assert.equal(f.buttons.some(row=>row.label==='空白创建'),true)
 await click(f.buttons.find(row=>row.label==='空白创建'))
 assert.equal(f.setup.reuseOpen,false);assert.equal(f.setup.bomOpen,true)
 assert.equal(f.store.bomForm.product_material_id,11)
 assert.equal(f.store.bomForm.source_bom_id??null,null)
 assert.equal(f.store.bomForm.lines[0].component_material_id,0)
 assert.equal(f.store.bomForm.base_quantity,'1');assert.equal(f.store.bomForm.note,'')
 assert.equal(JSON.stringify(f.source),existing)
})

test('后续版本选择原 BOM 复用时复制完整用料，来源本身不随新草稿更改',async t=>{
 const f=await fixture(t)
 const original=JSON.stringify(f.source)
 f.store.boms=[f.source]
 f.beforeRender.interact=setup=>setup.openBomCreation()
 await f.render()
 await click(f.buttons.find(row=>row.label==='复用到当前机型'))
 assert.equal(f.setup.reuseOpen,false);assert.equal(f.setup.bomOpen,true)
 assert.equal(f.setup.bomTargetId,11)
 assert.equal(f.store.bomForm.product_material_id,11);assert.equal(f.store.bomForm.source_bom_id,7)
 assert.equal(f.store.bomForm.base_quantity,'1');assert.equal(f.store.bomForm.lines[0].quantity,'2')
 f.store.bomForm.lines[0].quantity='6'
 assert.equal(JSON.stringify(f.source),original)
})

test('首建复用来源后继续在右侧编辑，不打开新建版本弹窗',async t=>{
 const f=await fixture(t)
 const other={...f.source,id:88,product_material_id:33,product_name:'来源专业版',base_quantity:'2',
  lines:f.source.lines.map(row=>({...row,quantity:'9'}))}
 f.store.boms=[other]
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>action==='productBoms'?[]:previous(action,payload)
 f.beforeRender.interact=setup=>setup.openBomCreation(false)
 const html=await f.render()
 assert.match(html,/第 1 行物料/)
 await click(f.buttons.find(row=>row.label==='复用到当前机型'))
 assert.equal(f.setup.reuseOpen,false);assert.equal(f.setup.bomOpen,false)
 assert.equal(f.store.bomForm.product_material_id,11);assert.equal(f.store.bomForm.source_bom_id,88)
 assert.equal(f.store.bomForm.base_quantity,'2');assert.equal(f.store.bomForm.lines[0].quantity,'9')
 f.store.bomForm.lines[0].quantity='4'
 assert.equal(other.lines[0].quantity,'9')
})

// 来源按钮可能在切换产品后才结束事件派发，旧目标意图不得套用到新的子机型。
test('选择来源期间切换产品，迟到复用事件不替换新产品草稿',async t=>{
 const f=await fixture(t)
 const other={...f.product,id:2,material_id:33,material:{...f.product.material,id:33,sku:'EL-PC-33',name:'其他产品'}}
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productDetail' && payload.id===2)return other
  if(action==='productBoms' && payload.materialId===33)return [{...f.source,id:18,product_material_id:33}]
  return previous(action,payload)
 }
 const live=await f.mountView()
 f.store.boms=[f.source]
 live.openBomCreation()
 assert.equal(live.reuseOpen,true)
 await live.selectProduct(2);await nextTick()
 f.store.prepareProductBom(33)
 f.store.bomForm.note='另一个子机型的草稿'
 const draft=JSON.stringify(f.store.bomForm)
 live.chooseBomSource(f.source)
 assert.equal(f.store.productDetailId,2)
 assert.equal(live.reuseOpen,false);assert.equal(live.bomOpen,false)
 assert.equal(JSON.stringify(f.store.bomForm),draft)
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
 html=await f.render();assert.match(html,/aria-label="建立首个 BOM"/)
 assert.equal(f.tables.some(row=>row.title.startsWith('组成明细')),false)
 f.store.user={...f.store.user,permissions:['inventory.view','production.view']}
 html=await f.render();assert.match(html,/尚未建立 BOM/)
 assert.doesNotMatch(html,/aria-label="建立首个 BOM"/)
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

// 保留真实 ProductsView、组成组件和库存读取链路，只替换物料详情内部的绘制，验证入口身份及查询范围。
test('组成编号独立于名称列，点击真实编号才读取共享物料详情且清空旧库存筛选',async t=>{
 const f=await fixture(t)
 f.store.ledgerQuery={warehouse_id:9,material_id:88,from_date:'2026-09-01',to_date:'2026-09-30',source_type:'other_inbound',page:4,page_size:10}
 const originalQuery=JSON.stringify(f.store.ledgerQuery),entries=[]
 const open=f.store.openLedgerMaterial
 f.store.openLedgerMaterial=(...args)=>{entries.push(args);return open(...args)}
 const live=await f.mountRenderedView()
 assert.equal(live.nodes().filter(node=>node.props['data-shared-inventory-details']).length,1)
 assert.equal(f.calls.some(([action])=>['materialDetail','inventoryLedger','queryStock'].includes(action)),false,'目录和 BOM 首屏不能预读物料详情')
 const component=live.nodes().find(node=>node.props['data-column']==='component')
 const sku=live.nodes().find(node=>node.props['data-column']==='sku')
 assert.ok(component);assert.ok(sku);assert.notEqual(component,sku)
 assert.match(live.nodeText(component),/主芯片/);assert.doesNotMatch(live.nodeText(component),/EL-IC-22/)
 assert.equal(sku.props['data-column-title'],'物料编号')
 const entry=live.button('EL-IC-22',sku)
 assert.equal(entry.props['aria-label'],'查看物料 EL-IC-22 的详情')
 live.press(entry);await settleProductView()
 assert.deepEqual(entries,[[{material_id:22,sku:'EL-IC-22',material_name:'主芯片'},
  {warehouse_id:null,from_date:null,to_date:null,source_type:null}]])
 assert.deepEqual(f.calls.filter(([action])=>['materialDetail','inventoryLedger'].includes(action)),[
  ['materialDetail',{id:22}],
  ['inventoryLedger',{warehouse_id:null,from_date:null,to_date:null,source_type:null,material_id:22,page:1,page_size:20}]
 ])
 assert.deepEqual(f.store.ledgerMaterialTarget,{material_id:22,sku:'EL-IC-22',material_name:'主芯片'})
 assert.equal(f.store.ledgerMaterialDetail.id,22)
 assert.equal(f.store.ledgerMaterialError,'');assert.equal(f.store.ledgerMaterialRowsError,'')
 assert.equal(f.store.stockMaterialMode,false)
 assert.equal(JSON.stringify(f.store.ledgerQuery),originalQuery,'BOM 入口不能修改库存台账原查询范围及页码')
 assert.equal(live.nodes().filter(node=>node.props['data-inventory-material']===22).length,1)
 assert.equal(f.calls.some(([action])=>action==='productChanges'),false,'打开物料不等于打开产品审计资料')
})

// 先保留未完成的真实库存请求，再切版本、切产品和销毁页面，保证旧响应不能重开物料窗口。
test('组成物料详情随版本产品及卸载关闭，旧编号事件和在途回执不能重开',async t=>{
 const f=await fixture(t),pending=[]
 const history={...f.source,id:8,version:2,status:'retired',lines:[{...f.source.lines[0],component_material_id:44,sku:'HISTORY-44',material_name:'历史组件'}]}
 const second={...f.product,id:2,material_id:33,material:{...f.product.material,id:33,sku:'P-33',name:'第二款产品'}}
 const secondBom={...f.source,id:9,product_material_id:33,product_sku:'P-33',product_name:'第二款产品'}
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='queryProducts')return {items:[f.product,second],page:1,page_size:20,total:2}
  if(action==='productDetail'&&payload.id===2)return second
  if(action==='productBoms')return payload.materialId===11?[f.source,history]:[secondBom]
  if(['materialDetail','inventoryLedger'].includes(action))return new Promise(resolve=>{pending.push({action,payload,resolve})})
  return previous(action,payload)
 }
 const complete=async()=>{
  for(const job of pending.splice(0))job.resolve(job.action==='materialDetail'?{id:job.payload.id,name:'请求返回的组件'}:
   {groups:[],rows:[],total:0,page:job.payload.page,page_size:job.payload.page_size})
  await settleProductView()
 }
 const live=await f.mountRenderedView(),first=live.button('EL-IC-22')
 const lateFirst=[first.props.onClick].flat()
 live.press(first);await settleProductView()
 assert.equal(f.store.ledgerMaterialTarget.material_id,22);assert.equal(pending.length,2)
 const select=live.nodes().find(node=>node.tag==='select'&&node.props['aria-label']==='选择 BOM 版本')
 for(const handler of [select.props['onUpdate:modelValue']].flat())handler(8)
 await settleProductView()
 assert.equal(f.store.ledgerMaterialTarget,null);assert.equal(f.store.ledgerMaterialQuery,null)
 assert.equal(f.store.ledgerMaterialLoading,false);assert.equal(f.store.ledgerMaterialRowsLoading,false)
 for(const handler of lateFirst)handler()
 assert.equal(pending.length,2,'旧版本编号的迟到点击不能创建新请求')
 await complete()
 assert.equal(f.store.ledgerMaterialTarget,null);assert.equal(f.store.ledgerMaterialDetail,null)
 live.press(live.button('HISTORY-44'));await settleProductView();await complete()
 assert.equal(f.store.ledgerMaterialTarget.material_id,44);assert.equal(f.store.ledgerMaterialDetail.id,44)
 live.press(live.button('选择产品 第二款产品'));await settleProductView()
 assert.equal(f.store.productDetailId,2);assert.equal(f.store.ledgerMaterialTarget,null)
 assert.equal(f.store.ledgerMaterialDetail,null);assert.equal(f.store.ledgerMaterialQuery,null)
 live.press(live.button('EL-IC-22'));await settleProductView()
 assert.equal(f.store.ledgerMaterialTarget.material_id,22);assert.equal(pending.length,2)
 live.unmount()
 assert.equal(f.store.ledgerMaterialTarget,null);assert.equal(f.store.ledgerMaterialQuery,null)
 await complete()
 assert.equal(f.store.ledgerMaterialTarget,null);assert.equal(f.store.ledgerMaterialDetail,null)
 assert.equal(f.store.ledgerMaterialLoading,false);assert.equal(f.store.ledgerMaterialRowsLoading,false)
})

// 禁用不仅体现在按钮属性，已经派发或保留下来的编号事件也必须被当前状态拒绝。
test('组成编号在忙碌与断线时禁用且拒绝迟到点击',async t=>{
 const f=await fixture(t),entries=[]
 const open=f.store.openLedgerMaterial
 f.store.openLedgerMaterial=(...args)=>{entries.push(args);return open(...args)}
 const live=await f.mountRenderedView(),entry=live.button('EL-IC-22'),lateClick=[entry.props.onClick].flat()
 f.store.busy=true;await settleProductView()
 assert.equal(live.button('EL-IC-22').props.disabled,true)
 for(const handler of lateClick)handler()
 assert.deepEqual(entries,[])
 assert.equal(f.calls.some(([action])=>action==='materialDetail'),false)
 f.store.busy=false;await settleProductView()
 assert.equal(live.button('EL-IC-22').props.disabled,false)
 f.store.connectionLost=true;await settleProductView()
 const disconnectedEntry=live.button('EL-IC-22')
 if(disconnectedEntry)assert.equal(disconnectedEntry.props.disabled,true)
 for(const handler of lateClick)handler()
 assert.deepEqual(entries,[]);assert.equal(f.store.ledgerMaterialTarget,null)
 assert.equal(f.calls.some(([action])=>['materialDetail','inventoryLedger'].includes(action)),false)
})

test('组成物料入口在权限失效后拒绝旧事件，不能借已缓存 BOM 请求库存详情',async t=>{
 const f=await fixture(t),entries=[]
 const open=f.store.openLedgerMaterial
 f.store.openLedgerMaterial=(...args)=>{entries.push(args);return open(...args)}
 const live=await f.mountRenderedView(),entry=live.button('EL-IC-22'),lateClick=[entry.props.onClick].flat()
 // 读取权限变化会同步清理产品上下文；旧 DOM 保存的事件仍不应越过页面的权限边界。
 f.store.user={...f.store.user,permissions:f.store.user.permissions.filter(key=>key!=='inventory.view')}
 for(const handler of lateClick)handler()
 await settleProductView()
 assert.deepEqual(entries,[])
 assert.equal(f.store.ledgerMaterialTarget,null)
 assert.equal(f.calls.some(([action])=>['materialDetail','inventoryLedger'].includes(action)),false)
})

// 真正点击树项编辑，绘制共享表单并从表单事件保存，避免只检查父级变量就漏掉重复目录或失效提交。
test('系列树项打开聚焦编辑表单，保留原因审计且保存关闭，右侧 BOM 不被替换',async t=>{
 const f=await fixture(t),model=f.store.productModels[0],seriesCalls=[]
 let saved=null
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(['productModelDetail','productModelChanges','updateProductModel'].includes(action))seriesCalls.push([action,payload])
  if(action==='productModelDetail')return model
  if(action==='productModelChanges')return [{id:1,before:null,after:model,reason:'原系列建立记录',changed_by_name:'管理员',created_at:'2026-10-16'}]
  if(action==='updateProductModel')return saved={...model,name:payload.name,notes:payload.notes,version:model.version+1}
  if(action==='productModels'&&saved)return [saved]
  return previous(action,payload)
 }
 const live=await f.mountRenderedView(),originalQuery=JSON.stringify(f.store.productQuery)
 assert.deepEqual(seriesCalls,[])
 live.press(live.button('编辑产品系列 机型A'));await settleProductView()
 const modal=()=>live.nodes().find(node=>node.props['data-modal']==='编辑产品系列')
 assert.ok(modal());assert.equal(live.nodes().filter(node=>node.props['data-modal']==='编辑产品系列').length,1)
 assert.match(live.nodeText(modal()),/修改原因/);assert.match(live.nodeText(modal()),/原系列建立记录/)
 assert.doesNotMatch(live.nodeText(modal()),/产品系列目录|新增另一产品系列/)
 assert.equal(f.tables.some(table=>table.title==='产品系列目录'),false)
 assert.equal(live.bomVisible(),true);assert.equal(f.store.productDetailId,1);assert.equal(f.store.productBomRecords[0].id,7)
 assert.equal(JSON.stringify(f.store.productQuery),originalQuery)
 assert.deepEqual(seriesCalls.map(([action])=>action),['productModelDetail','productModelChanges'])
 const submit=()=>live.nodes().find(node=>node.tag==='form').props.onSubmit({preventDefault(){},stopPropagation(){}})
 submit();await settleProductView()
 assert.equal(seriesCalls.some(([action])=>action==='updateProductModel'),false,'编辑必须填写修改原因')
 const field=label=>live.nodes().find(node=>node.tag==='label'&&live.nodeText(node).startsWith(label)).children.find(node=>node.tag==='input')
 field('产品系列名称').props['onUpdate:modelValue']('机型A新名称')
 field('修改原因').props['onUpdate:modelValue']('统一系列命名')
 await settleProductView();submit();await settleProductView()
 assert.equal(seriesCalls.filter(([action])=>action==='updateProductModel').length,1)
 assert.equal(seriesCalls.find(([action])=>action==='updateProductModel')[1].reason,'统一系列命名')
 assert.equal(modal(),undefined)
 assert.equal(f.store.productModels[0].name,'机型A新名称')
 assert.equal(live.bomVisible(),true);assert.equal(f.store.productDetailId,1)
 live.press(live.button('新建系列'));await settleProductView()
 const create=live.nodes().find(node=>node.props['data-modal']==='新建产品系列')
 assert.ok(create);assert.doesNotMatch(live.nodeText(create),/产品系列目录|修改原因/)
})

test('系列编辑失败不展示旧草稿，同系列收起重开保留输入，维护权限与当前目录约束入口',async t=>{
 const f=await fixture(t),model=f.store.productModels[0],second={...model,id:2,code:'B200',name:'第二系列'}
 let fail=false,reads=0
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productModels')return [model,second]
  if(action==='productModelDetail'){reads++;if(fail)throw Error('系列详情暂不可用');return payload.id===1?model:second}
  if(action==='productModelChanges')return []
  return previous(action,payload)
 }
 const live=await f.mountView()
 await live.editSeries(1)
 assert.equal(live.modelsOpen,true);assert.equal(f.store.productModelForm.id,1)
 f.store.productModelForm.notes='未保存的说明';f.store.productModelForm.reason='未保存的修改原因'
 live.modelsOpen=false;await live.editSeries(1)
 assert.equal(reads,1);assert.equal(f.store.productModelForm.notes,'未保存的说明')
 assert.equal(f.store.productModelForm.reason,'未保存的修改原因')
 fail=true;await live.editSeries(2)
 assert.equal(live.modelsOpen,false);assert.equal(f.store.productModelForm.id,1)
 assert.equal(f.store.productModelForm.notes,'未保存的说明');assert.match(f.store.error,/系列详情暂不可用/)
 const before=reads
 await live.editSeries(999);f.store.busy=true;await live.editSeries(1);f.store.busy=false
 f.store.connectionLost=true;await live.editSeries(1);f.store.connectionLost=false
 f.store.user={...f.store.user,permissions:['inventory.view','production.view']};await live.editSeries(1)
 assert.equal(reads,before);assert.equal(live.modelsOpen,false)
})

test('系列读取在途改为新建或换编辑目标时旧结果失效，切用户与卸载也不重新开窗',async t=>{
 const f=await fixture(t),model=f.store.productModels[0],second={...model,id:2,code:'B200',name:'第二系列'},jobs=[]
 const previous=globalThis.window.nexora.callApi
 globalThis.window.nexora.callApi=async(action,payload)=>{
  if(action==='productModels')return [model,second]
  if(['productModelDetail','productModelChanges'].includes(action))return new Promise(resolve=>jobs.push({action,payload,resolve}))
  return previous(action,payload)
 }
 const live=await f.mountView()
 const first=live.editSeries(1)
 assert.equal(live.modelsOpen,false)
 live.newSeries();f.store.productModelForm.name='新的系列草稿'
 jobs.splice(0).forEach(job=>job.resolve(job.action==='productModelDetail'?model:[]))
 await first
 assert.equal(live.modelsOpen,true);assert.equal(live.createSeriesOnly,true)
 assert.equal(f.store.productModelForm.id,0);assert.equal(f.store.productModelForm.name,'新的系列草稿')
 const old=live.editSeries(1),latest=live.editSeries(2)
 jobs[2].resolve(second);jobs[3].resolve([]);await latest
 jobs[0].resolve(model);jobs[1].resolve([]);await old;jobs.length=0
 assert.equal(live.modelsOpen,true);assert.equal(f.store.productModelForm.id,2)
 const stale=live.editSeries(1)
 f.store.user={...f.store.user,id:2}
 jobs.splice(0).forEach(job=>job.resolve(job.action==='productModelDetail'?model:[]))
 await stale;await settleProductView()
 assert.equal(live.modelsOpen,false);assert.equal(f.store.productModelForm.id,0)
 // 新页面在读取中卸载，原 action 和页面的打开意图一起撤销。
 const rendered=await f.mountRenderedView()
 rendered.press(rendered.button('编辑产品系列 机型A'));await settleProductView()
 rendered.unmount()
 jobs.splice(0).forEach(job=>job.resolve(job.action==='productModelDetail'?model:[]))
 await settleProductView()
 assert.equal(f.store.productModelForm.id,0)
})

// 系列读取未完成时用户仍可使用其他入口；明确的新弹窗意图必须撤销旧系列回执，不能叠加窗口。
test('其他弹窗意图取消在途系列读取，删除资料BOM生命周期及产品编辑不会被旧系列窗覆盖',async t=>{
 for(const target of ['delete','details','create-bom','revise-bom','bom-details','versions','lifecycle','material','edit-product'])await t.test(target,async t=>{
  const f=await fixture(t),model=f.store.productModels[0]
  let resolve
  const pending=new Promise(done=>{resolve=done}),previous=globalThis.window.nexora.callApi
  globalThis.window.nexora.callApi=async(action,payload)=>action==='productModelDetail'?pending:
   action==='productModelChanges'?[]:previous(action,payload)
  const live=await f.mountView(),editing=live.editSeries(model.id)
  assert.equal(live.modelsOpen,false)
  if(target==='delete')live.requestSeriesDelete(model)
  else if(target==='details')live.openProductDetails()
  else if(target==='create-bom')live.openBomCreation()
  else if(target==='revise-bom')live.reviseBom()
  else if(target==='bom-details')live.openBomDetails(f.source.id)
  else if(target==='versions')live.openVersionList()
  else if(target==='lifecycle')live.selectLifecycle('disable')
  else if(target==='material')live.openCompositionMaterial({key:'7/1',materialId:22,sku:'EL-IC-22',name:'主芯片'})
  else await live.editProduct()
  resolve(model);await editing;await settleProductView()
  assert.equal(live.modelsOpen,false,'旧系列回执不能在新弹窗意图之后重新开窗')
  assert.equal(f.store.productModelForm.id,0,'旧系列资料不能回填编辑草稿')
  if(target==='delete')assert.equal(live.modelToDelete.id,model.id)
  else if(target==='details')assert.equal(live.detailsOpen,true)
  else if(target==='create-bom')assert.equal(live.reuseOpen,true)
  else if(target==='revise-bom')assert.equal(live.bomOpen,true)
  else if(target==='bom-details')assert.equal(f.store.bomDetailRecord.id,f.source.id)
  else if(target==='versions')assert.equal(live.versionsOpen,true)
  else if(target==='lifecycle')assert.equal(live.lifecycleTarget.id,f.product.id)
  else if(target==='material')assert.equal(f.store.ledgerMaterialTarget.material_id,22)
  else assert.equal(f.store.productEditorOpen,true)
 })
})
