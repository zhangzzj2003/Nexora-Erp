import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { associationFixture } from './production-association-fixture.mjs'

const material={id:1,sku:'CURRENT-PCB',name:'当前档案名称',unit:'块',specification:'FR-4 1.6mm',package:'双层板',
  spec_values:[{field_id:1,category_code:'EL-PC',name:'板厚',kind:'number',unit:'mm',historical:false,status:'filled',value:'0',source:'图纸 A'},
    {field_id:2,category_code:'EL-PC',name:'含铅',kind:'boolean',unit:'',historical:false,status:'filled',value:false,source:'规格书'}],
  extra_attributes:[{name:'表面工艺',value:'沉金',unit:''}]}
const line={id:71,material_id:1,sku:'OLD-PCB',material_name:'历史物料名称',quantity:'2.125',unit:'块',physical_lots:[],material}
const inbound={id:7,document_no:'QTRK-20261017-000007',status:'posted',reason:'other',note:'原始入库说明',reference:'REF-7',
  warehouse_id:1,warehouse_name:'主仓库',created_at:'2026-10-17T08:00:00Z',created_by_name:'原建单人',posted_at:'2026-10-17T09:00:00Z',
  posted_by_name:'确认人',cancelled_at:null,reversal_id:null,lines:[line]}
const summaryItem={label:'OLD-PCB · 历史送审名称',value:'2.125 块',material_id:1,material}
function approval(document_type='WarehouseInbound',summary=[{label:'仓库',value:'送审主仓库'},summaryItem]) {
  return {document_type,document_id:7,intent:'execute',document_no:'TEST-20261017-000007',version:2,status:'executed',generation:1,
    current_step:0,steps:[],policy_version:1,submitted_by:1,submitted_at:null,executed_by:2,executed_at:null,
    business_status:'posted',reversal_reason:'',content_matches:true,can_submit:false,can_review:false,can_withdraw:false,events:[],summary}
}

// 真实入口和公共参数组件共同编译；只替换传送、表格绘制与外部业务动作，避免测试借参数读取扩张权限。
async function fixture(t) {
  const server=await createServer({configFile:false,plugins:[{name:'material-parameter-views',enforce:'pre',
    transform(code,id){
      // SSR 重建实例时指定已打开的详情，渲染的仍是页面自己的只读单元格与来源绑定。
      if(id.endsWith('/OtherInboundsView.vue'))return code.replace('const detailInboundId = ref(0)','const detailInboundId = ref(store.initialDetailId)')
    },resolveId(id){
      if(id==='virtual:parameter-view-store')return '\0parameter-view-store'
      if(id.endsWith('/store/app-store'))return '\0parameter-view-store'
      if(id.endsWith('/store/modules/material-flow-store'))return '\0parameter-view-flow'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0parameter-view-table'
      if(id.endsWith('/AppModal.vue'))return '\0parameter-view-modal'
      if(id.endsWith('/AppButton.vue'))return '\0parameter-view-button'
      if(id.endsWith('/AppInput.vue'))return '\0parameter-view-input'
      if(id.endsWith('/DocumentApprovalProgress.vue'))return '\0parameter-view-progress'
      if(['/WorkspaceSearchFilters.vue','/WorkspaceSummaryFilters.vue','/WorkspaceMaterialSelect.vue','/WorkspaceSelect.vue',
        '/WorkspaceLotDialog.vue','/WorkspaceInboundLotTable.vue','/OtherInboundReopenTrace.vue',
        '/InventoryMaterialFacts.vue','/InventoryMaterialLedger.vue','/CrmQuoteAttachments.vue','/CrmRecordAttachments.vue'].some(name=>id.endsWith(name)))return '\0parameter-view-empty'
    },load(id){
      if(id==='\0parameter-view-store')return `import {defineStore} from 'pinia';import {ref} from 'vue';
        import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('parameter-view-store',()=>{const state=createAppState(),permissions=ref([]);
          return {...state,permissions,initialDetailId:ref(0),can:key=>permissions.value.includes(key),localTime:value=>value,
            createOtherInbound(){calls.push('create')},postOtherInbound(){calls.push('post')},cancelOtherInbound(){calls.push('cancel')},
            reverseOtherInbound(){calls.push('reverse')},prepareOtherInboundReopen(){calls.push('reopen')},
            openDocumentApproval(){calls.push('approval')},loadDocumentApproval(){calls.push('loadApproval')},
            closeDocumentApproval(){calls.push('closeApproval')},actDocumentApproval(){calls.push('writeApproval')},
            closeLedgerMaterial(){calls.push('closeMaterial')},closeLedgerDocument(){calls.push('closeDocument')},
            loadLedgerDocument(){calls.push('loadDocument')},closeBomDetail(){calls.push('closeBom')},
            closeProduct(){calls.push('closeProduct')},openBomDetail(){calls.push('loadBom')},
            closeProductionAssociations(){calls.push('closeAssociation')},loadProductionAssociations(){calls.push('loadAssociation')}}})`
      if(id==='\0parameter-view-flow')return `import {defineStore} from 'pinia';import {ref,computed} from 'vue';
        import {usePiniaAppStore,calls} from 'virtual:parameter-view-store';
        export const materialFlowLabels={dispatch:'生产发料',receipt:'生产领料',exchange:'生产换料',return:'生产退料'};
        export const materialFlowRoutes={dispatch:'productionDispatches',receipt:'productionReceipts',exchange:'productionExchanges',return:'productionReturns'};
        export const materialFlowStatusLabel=(kind,status)=>status;
        export const useMaterialFlowStore=defineStore('parameter-view-flow',()=>{const app=usePiniaAppStore(),orders=ref({});return {
          orders,loading:ref({}),readErrors:ref({}),available:computed(()=>app.can('material_flow.view')&&!app.connectionLost),
          async loadOrder(id){calls.push(['loadOrder',id]);return orders.value[id]},cancelRead(key){calls.push(['cancelRead',key])}}})`
      if(id==='\0parameter-view-table')return `import {h} from 'vue';export default {props:['data','columns','title'],setup:(p,{slots})=>()=>h('section',[
        slots.heading?.(),slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),
        h('table',{'data-test-title':p.title??''},[h('thead',h('tr',(p.columns??[]).map(c=>h('th',c.title)))),
          h('tbody',(p.data??[]).map((row,index)=>h('tr',{'data-test-row':index},(p.columns??[]).map(c=>h('td',{'data-test-cell':c.key},slots['cell-'+c.key]?.({row})??String(row[c.key]??''))))))]),slots.footer?.()])}`
      if(id==='\0parameter-view-modal')return `import {h} from 'vue';export default {props:['show','ready','title','loadError'],setup:(p,{slots})=>()=>p.show&&p.ready!==false&&!p.loadError?h('section',{'data-test-dialog':p.title},[slots.default?.(),slots.footer?.()]):null}`
      if(id==='\0parameter-view-button')return `import {h} from 'vue';export default {props:['disabled','type'],setup:(p,{slots,attrs})=>()=>h('button',{...attrs,disabled:p.disabled,type:p.type??'button'},slots.default?.())}`
      if(id==='\0parameter-view-input')return `import {h} from 'vue';export default {props:['modelValue','disabled'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}`
      if(id==='\0parameter-view-progress')return `import {h} from 'vue';export default {render:()=>h('div',{'data-test-progress':''},'审批进度')}`
      if(id==='\0parameter-view-empty')return 'export default {render:()=>null}'
    }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0parameter-view-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  t.after(()=>store.$dispose())
  store.user={id:1,roles:[],permissions:['other_inbound.view']};store.permissions=['other_inbound.view']
  const paths={inbound:'/src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue',
    approval:'/src/renderer/src/components/workspace/DocumentApprovalDialog.vue',
    panel:'/src/renderer/src/components/workspace/DocumentApprovalPanel.vue',
    inventory:'/src/renderer/src/components/workspace/InventoryDetailDialogs.vue',
    bom:'/src/renderer/src/views/workspace/catalog/BomDetailDialog.vue',
    association:'/src/renderer/src/components/workspace/ProductionAssociationDialog.vue',
    workOrder:'/src/renderer/src/components/workspace/WorkOrderMaterialFlowPanel.vue',
    quote:'/src/renderer/src/views/workspace/sales/CrmEvidence.vue',
    afterSales:'/src/renderer/src/views/workspace/sales/AfterSalesEvidence.vue',
    quality:'/src/renderer/src/views/workspace/production/QualityEvidence.vue',
    equipment:'/src/renderer/src/views/workspace/production/EquipmentEvidence.vue',
    mrp:'/src/renderer/src/views/workspace/production/MrpEvidence.vue'}
  const views={}
  async function render(name,props) {
    views[name]??=(await server.ssrLoadModule(paths[name])).default
    const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]})
    return renderToString(createSSRApp({render:()=>h(views[name],props)}).use(pinia).use(router))
  }
  function setApproval(record) {
    store.documentApprovalRecord=structuredClone(record)
    store.documentApprovalTarget={document_type:record.document_type,document_id:record.document_id,intent:record.intent}
  }
  async function flow() {
    const {useMaterialFlowStore}=await server.ssrLoadModule('\0parameter-view-flow')
    return useMaterialFlowStore(pinia)
  }
  return {store,calls,render,setApproval,flow}
}

const text=html=>html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim()
function table(html,title='物料明细') {
  const found=[...html.matchAll(/<table data-test-title="([^"]*)">([\s\S]*?)<\/table>/g)].find(match=>match[1]===title)
  assert.ok(found,`应渲染 ${title} 表格`);return found[2]
}
const rows=html=>[...html.matchAll(/<tr data-test-row="\d+">([\s\S]*?)<\/tr>/g)].map(match=>match[1])
const cell=(row,key)=>row.match(new RegExp(`<td data-test-cell="${key}">([\\s\\S]*?)<\\/td>`))?.[1]
function assertParameters(html) {
  // 所有真实单据入口默认只显示摘要，完整技术参数由公共组件交互测试覆盖。
  for(const value of ['查看资料','FR-4 1.6mm','双层板'])assert.ok(text(html).includes(value),value)
  assert.doesNotMatch(text(html),/当前档案参数|板厚|含铅|表面工艺|沉金/)
  assert.doesNotMatch(text(html),/当前档案名称|CURRENT-PCB|未填写/,'当前参数不能覆盖历史单据身份或铺满空字段')
}

test('其他入库只读明细使用当行授权参数，无全局物料缓存也可查看且不改变历史数量与名称',async t=>{
  const f=await fixture(t)
  f.store.otherInbounds=[structuredClone(inbound)];f.store.initialDetailId=7
  assert.deepEqual(f.store.materials,[])
  const before=JSON.stringify(f.store.otherInbounds)
  let html=await f.render('inbound'),body=rows(table(html))[0]
  assertParameters(cell(body,'name'))
  assert.match(text(cell(body,'name')),/历史物料名称/)
  assert.match(text(body),/2\.125/)
  assert.match(text(body),/块/)
  assert.equal(JSON.stringify(f.store.otherInbounds),before)
  assert.deepEqual(f.calls,[],'查看参数不能发起物料详情读取、审批或业务写入')
  assert.equal(f.store.can('inventory.view'),false)
  assert.equal(f.store.can('other_inbound.post'),false)
  // 当前档案规格变更只更新附加参数，原入库名称、数量及编码继续按原行展示。
  f.store.otherInbounds[0].lines[0].material.specification='FR-4 新工艺'
  html=await f.render('inbound');body=rows(table(html))[0]
  assert.match(text(body),/FR-4 新工艺/);assert.doesNotMatch(text(body),/FR-4 1\.6mm/)
  assert.match(text(body),/历史物料名称/);assert.match(text(body),/2\.125/)
})

test('其他入库错配物料身份不串参数，旧简要响应仍保留正文并可按真实 ID 使用授权缓存',async t=>{
  const f=await fixture(t)
  f.store.initialDetailId=7
  f.store.otherInbounds=[{...structuredClone(inbound),lines:[{...structuredClone(line),material:{...structuredClone(material),id:99}},
    {...structuredClone(line),id:72,material_id:2,sku:'OLD-2',material_name:'第二历史物料',quantity:'5',material:undefined}]}]
  let body=rows(table(await f.render('inbound')))
  assert.doesNotMatch(text(body[0]),/沉金|FR-4/);assert.match(text(body[0]),/详细资料暂不可用/)
  assert.match(text(body[1]),/第二历史物料/);assert.match(text(body[1]),/5/);assert.doesNotMatch(text(body[1]),/沉金/)
  f.store.materials=[{...structuredClone(material),specification:'已授权缓存参数'}]
  body=rows(table(await f.render('inbound')))
  assert.match(text(body[0]),/已授权缓存参数/);assert.doesNotMatch(text(body[1]),/已授权缓存参数|沉金/)
  assert.deepEqual(f.calls,[])
})

test('其他入库审批物料表附加参数保留原送审标签与数量，错 ID 及旧摘要不借全局缓存串料',async t=>{
  const f=await fixture(t)
  f.setApproval(approval('WarehouseInbound',[{label:'仓库',value:'送审主仓库'},structuredClone(summaryItem),
    {label:'OLD-2 · 第二送审名称',value:'5 件',material_id:2,material:structuredClone(material)},
    {label:'LEGACY · 旧摘要',value:'9 件'}]))
  f.store.materials=[{...structuredClone(material),id:2,specification:'不应读取的缓存'}]
  const before=JSON.stringify(f.store.documentApprovalRecord),html=await f.render('approval'),body=rows(table(html))
  assert.equal(body.length,3);assertParameters(cell(body[0],'label'))
  assert.match(text(cell(body[0],'label')),/OLD-PCB · 历史送审名称/)
  assert.equal(text(cell(body[0],'value')),'2.125 块')
  assert.match(text(body[1]),/第二送审名称/);assert.equal(text(cell(body[1],'value')),'5 件')
  assert.doesNotMatch(text(body[1]),/沉金|FR-4|不应读取的缓存/)
  assert.match(text(body[1]),/详细资料暂不可用/)
  assert.match(text(body[2]),/LEGACY · 旧摘要/);assert.equal(text(cell(body[2],'value')),'9 件')
  assert.doesNotMatch(text(body[2]),/当前档案参数/)
  assert.equal(JSON.stringify(f.store.documentApprovalRecord),before)
  assert.deepEqual(f.calls,[])
})

test('其他领域审批在基础信息显示同款参数，金额与旧送审正文完整保留',async t=>{
  const f=await fixture(t)
  f.setApproval(approval('PurchaseOrder',[{label:'订单金额',value:'1,234.50 元'},structuredClone(summaryItem),
    {label:'旧服务说明',value:'仅历史摘要，无物料详情'}]))
  const html=await f.render('approval')
  assertParameters(html)
  assert.match(text(html),/订单金额 1,234\.50 元/)
  assert.match(text(html),/OLD-PCB · 历史送审名称 2\.125 块/)
  assert.match(text(html),/仅历史摘要，无物料详情/)
  assert.doesNotMatch(html,/data-test-title="物料明细"/,'非入库审批不额外制造空的物料表')
  assert.deepEqual(f.calls,[])
})

test('内嵌详情的原送审参考使用当前参数标识，不能把参考资料误写成旧快照',async t=>{
  const f=await fixture(t),record=approval()
  record.content_matches=false;f.setApproval(record)
  const before=JSON.stringify(f.store.documentApprovalRecord)
  let html=await f.render('panel',{part:'progress',liveDetails:true})
  assert.match(text(html),/原送审内容/);assert.match(text(html),/OLD-PCB · 历史送审名称/)
  assert.match(text(html),/2\.125 块/);assertParameters(html)
  assert.equal(JSON.stringify(f.store.documentApprovalRecord),before)
  f.store.documentApprovalRecord.summary[1].material={...structuredClone(material),id:99}
  html=await f.render('panel',{part:'progress',liveDetails:true})
  assert.match(text(html),/原送审内容/);assert.match(text(html),/历史送审名称|2\.125 块/)
  assert.match(text(html),/详细资料暂不可用/);assert.doesNotMatch(text(html),/沉金|FR-4/)
  html=await f.render('panel',{part:'progress',liveDetails:false})
  assert.doesNotMatch(text(html),/原送审内容|当前档案参数/)
  assert.deepEqual(f.calls,[])
})

test('库存来源单据共用参数展示，物料表和基础摘要均保留历史业务字段及旧响应',async t=>{
  const f=await fixture(t)
  f.store.ledgerDocumentTarget={id:10,material_id:1,sku:'OLD-PCB',material_name:'历史物料名称',warehouse_id:1,source_type:'other_inbound',
    source_id:7,source_line_id:71,source_document_no:'QTRK-20261017-000007'}
  f.store.ledgerDocumentRecord=approval('WarehouseInbound',[{label:'仓库',value:'送审主仓库'},structuredClone(summaryItem),
    {label:'LEGACY · 旧来源摘要',value:'7 个'}])
  let html=await f.render('inventory'),body=rows(table(html))
  assertParameters(cell(body[0],'label'));assert.equal(text(cell(body[0],'value')),'2.125 块')
  assert.match(text(body[0]),/OLD-PCB · 历史送审名称/)
  assert.match(text(body[1]),/LEGACY · 旧来源摘要/);assert.equal(text(cell(body[1],'value')),'7 个')
  f.store.ledgerDocumentRecord=approval('PurchaseOrder',[{label:'来源金额',value:'123.00 元'},structuredClone(summaryItem)])
  html=await f.render('inventory');assertParameters(html)
  assert.match(text(html),/来源金额 123\.00 元/);assert.match(text(html),/2\.125 块/)
  assert.doesNotMatch(html,/data-test-title="物料明细"/)
  assert.deepEqual(f.calls,[])
})

test('BOM 版本详情从组件回执显示参数，保留旧组件名称数量单位且错 ID 不借同名资料',async t=>{
  const f=await fixture(t)
  f.store.bomDetailRecord={id:3,version:1,status:'active',product_material_id:10,product_name:'原 BOM 产品',product_sku:'PROD-OLD',
    product_unit:'台',base_quantity:'1',note:'历史版本说明',source_bom:null,lines:[
      {id:31,component_material_id:1,sku:'OLD-PCB',material_name:'旧版组件名称',unit:'块',quantity:'2.125',material:structuredClone(material)},
      {id:32,component_material_id:2,sku:'OLD-2',material_name:'第二组件',unit:'件',quantity:'5',material:structuredClone(material)}]}
  const before=JSON.stringify(f.store.bomDetailRecord),html=await f.render('bom'),body=rows(table(html))
  assertParameters(cell(body[0],'name'));assert.match(text(cell(body[0],'name')),/旧版组件名称/)
  assert.equal(text(cell(body[0],'sku')),'OLD-PCB');assert.equal(text(cell(body[0],'quantity')),'2.125')
  assert.equal(text(cell(body[0],'unit')),'块')
  assert.match(text(body[1]),/第二组件/);assert.match(text(body[1]),/详细资料暂不可用/)
  assert.doesNotMatch(text(body[1]),/沉金|FR-4/)
  assert.equal(JSON.stringify(f.store.bomDetailRecord),before)
  assert.deepEqual(f.calls,[],'参数展示不应调用 materialDetail 或重新读取 BOM')
  assert.equal(f.store.can('inventory.view'),false)
})

test('生产关联单据显示组件自身参数，需求净领和来源证据保留且参数无附加读取',async t=>{
  const f=await fixture(t),record=associationFixture()
  record.inventory_visible=false
  record.components[0]={...record.components[0],material_id:1,sku:'ASSOC-OLD',name:'原关联组件',unit:'块',
    required_quantity:'200.000',net_issued_quantity:'175.000',material:structuredClone(material)}
  f.store.productionAssociationTarget=record.target;f.store.productionAssociationRecord=record
  const before=JSON.stringify(f.store.productionAssociationRecord),html=await f.render('association')
  const body=rows(table(html,'物料需求与实际单据'))[0]
  assertParameters(cell(body,'material'));assert.match(text(cell(body,'material')),/原关联组件/)
  assert.match(text(cell(body,'material')),/ASSOC-OLD · 块/)
  assert.match(text(cell(body,'quantity')),/需求 200\.000/);assert.match(text(cell(body,'quantity')),/有效净领 175\.000/)
  assert.match(text(html),/缺少固定批次分配证据/)
  assert.match(text(html),/入库与供应商来源需库存查看权限/)
  assert.doesNotMatch(text(html),/确认领料|保存草稿|提交审批/)
  assert.equal(JSON.stringify(f.store.productionAssociationRecord),before);assert.deepEqual(f.calls,[])
})

test('工单材料核对使用原工单读取附带参数，保留需求数量单位且不逐行请求物料',async t=>{
  const f=await fixture(t),flow=await f.flow()
  f.store.permissions=['material_flow.view'];f.store.user={id:1,roles:[],permissions:['material_flow.view']}
  flow.orders={7:{work_order_id:7,lines:[{work_order_line_id:71,material_id:1,sku:'WO-OLD',material_name:'工单历史组件',unit:'块',
    required_quantity:'2.125',signed_quantity:'1.500',returned_quantity:'0.100',damaged_quantity:'0',in_transit_quantity:'0.625',
    reserved_quantity:'0',effective_quantity:'1.400',available_quantity:'3.000',dispatchable_quantity:'0.625',material:structuredClone(material)}],
    sources:[],dispatches:[],receipts:[],exchanges:[],returns:[]}}
  const before=JSON.stringify(flow.orders),html=await f.render('workOrder',{orderId:7}),body=rows(table(html,'工单材料核对'))[0]
  assertParameters(cell(body,'material'));assert.match(text(cell(body,'material')),/WO-OLD · 工单历史组件/)
  assert.equal(text(cell(body,'required')),'2.125 块');assert.equal(text(cell(body,'signed')),'1.500')
  assert.equal(text(cell(body,'transit')),'0.625')
  assert.equal(JSON.stringify(flow.orders),before)
  assert.deepEqual(f.calls,[['loadOrder',7]],'仅允许面板原有工单读取，不新增逐行 HTTP')
  assert.equal(f.store.can('inventory.view'),false)
})

// 本领域详情只能利用已经授权的缓存；资料展示不能读全局库存或改写原始业务身份。
test('报价、售后、质检和设备详情统一名称摘要，缺缓存仍保留原数量及名称且不额外读取',async t=>{
  const f=await fixture(t)
  f.store.crmOptions={materials:[structuredClone(material)]}
  f.store.crmDetail={kind:'quote',record:{id:7,reference:'QUOTE-7',version:1,status:'draft',party:{customer_name:'原客户'},
    review_blocked:[],lines:[{...structuredClone(line),unit_price:'12.50',line_total:'26.56'}]}}
  let html=await f.render('quote'),body=rows(table(html,'固定报价明细'))[0]
  assertParameters(cell(body,'material'));assert.match(text(body),/OLD-PCB\s+(?:·\s*)?历史物料名称/)
  assert.equal(text(cell(body,'quantity')),'2.125');assert.equal(text(cell(body,'unit_price')),'12.50')
  f.store.crmOptions=null;html=await f.render('quote')
  assert.match(text(html),/历史物料名称|详细资料暂不可用/);assert.doesNotMatch(text(html),/FR-4/)
  const source={material_id:1,sku:'OLD-PCB',material_name:'售后原物料名称',unit:'块',posted_at:'2026-10-17'}
  const after={id:7,reference:'AFTER-7',version:1,status:'approved',kind:'repair',quantity:'2.125',frozen_source:source,
    warranty_days:null,responsibilities:[],parts:[{...source,quantity:'0.500'}],labor:[],custody:[],changes:[],charge_mode:'free'}
  f.store.afterSalesOverview={materials:[structuredClone(material)]}
  html=await f.render('afterSales',{row:after,compact:true});assertParameters(html)
  assert.match(text(html),/售后原物料名称/);assert.match(text(html),/2\.125/);assert.match(text(html),/0\.500/)
  f.store.qualityOverview={materials:[structuredClone(material)]}
  html=await f.render('quality',{row:{id:7,reference:'Q-7',status:'draft',version:1,kind:'rework',quantity:'2.125',
    frozen_source:{product_material_id:1,product_sku:'OLD-PCB',product_name:'原质检成品'},
    materials:[{...source,quantity:'0.500'}],changes:[]},compact:true})
  assertParameters(html);assert.match(text(html),/原质检成品/);assert.match(text(html),/0\.500/)
  f.store.equipmentOverview={materials:[structuredClone(material)]}
  html=await f.render('equipment',{detail:{kind:'job',row:{id:7,reference:'M-7',version:1,status:'draft',kind:'corrective',
    equipment_snapshot:{code:'EQ-1',name:'设备'},plan_roll:{reversal_effect:'none'},parts:[{material_id:1,quantity:'0.500'}],changes:[],purchase_requests:[]}}})
  assert.match(text(html),/查看资料|0\.500/);assert.match(html,/workspace-material-name/)
  assert.deepEqual(f.calls,[])
})

test('MRP 名称组件只展示已保存的计划参数，不借当前缓存覆盖历史名称或冒充当前档案',async t=>{
  const f=await fixture(t)
  const row={material_id:1,sku:'MRP-OLD',name:'计划原物料名称',unit:'块',date:'2026-10-19',level:0,supply_mode:'buy',
    opening_quantity:'1',gross_quantity:'2.125',scheduled_quantity:'0',safety_stock:'0',net_quantity:'1.125',planned_quantity:'1.125',
    closing_quantity:'0',demand_sources:[],supply_sources:[]}
  f.store.materials=[{...structuredClone(material),specification:'不得混入的当前库存档案'}]
  f.store.mrpDetail={id:7,reference:'MRP-7',status:'draft',version:1,conversions:[],author_ids:[],snapshot:{warnings:[],assumptions:[],
    suggestions:[],rows:[row],sources:{materials:[{...structuredClone(material),specification:'计划保存参数'}],policies:[],boms:[],movements:[]}}}
  const before=JSON.stringify(f.store.mrpDetail),html=await f.render('mrp'),body=rows(table(html,'日期净需求'))[0]
  assert.match(text(cell(body,'material')),/MRP-OLD · 计划原物料名称/)
  assert.match(text(body),/计划保存参数|查看资料/)
  assert.doesNotMatch(text(body),/当前档案参数|不得混入的当前库存档案|沉金/)
  assert.equal(JSON.stringify(f.store.mrpDetail),before);assert.deepEqual(f.calls,[])
})
