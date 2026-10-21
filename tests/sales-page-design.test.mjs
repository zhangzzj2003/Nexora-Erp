import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
import {salesSummaryGroup,salesBusinessStatus,salesApprovalStatus,salesListColumns,salesLineColumns} from '../src/renderer/src/utils/sales-presentation.ts'
import {matchesSalesFilters,newSalesFilters} from '../src/renderer/src/utils/sales-documents.ts'

// 统计必须依业务效力分组，批准草稿仍未出库，已冲销记录不能算已完成。
test('销售概览区分待办理、交付、终止与冲销，并能组合客户日期筛选',()=>{
  for(const [status,group] of [['draft','pending'],['confirmed','active'],['partially_shipped','active'],['shipped','completed'],['closed','completed'],['cancelled','cancelled']])
    assert.equal(salesSummaryGroup({status}),group)
  assert.equal(salesSummaryGroup({status:'posted',reversal_id:9}),'reversed')
  assert.equal(salesSummaryGroup({status:'posted',reversal_id:null}),'completed')
  const row={status:'draft',approval:{status:'approved'},created_at:'2026-10-20T12:00:00Z'}
  assert.equal(matchesSalesFilters(row,2,{...newSalesFilters(),group:'pending',customer:2,from:'2026-10-20',to:'2026-10-21'}),true)
  assert.equal(matchesSalesFilters(row,3,{...newSalesFilters(),group:'pending',customer:2}),false)
  assert.equal(matchesSalesFilters(row,2,{...newSalesFilters(),group:'completed'}),false)
  assert.equal(salesBusinessStatus(row,'shipment').label,'草稿')
  assert.equal(salesApprovalStatus(row).label,'已批准')
  assert.equal(salesBusinessStatus({status:'posted',reversal_id:1},'return').tone,'reversed')
})

const order={id:1,document_no:'XS-TEST-001',status:'draft',customer_id:1,customer_name:'页面测试客户',reference:'参考资料',created_at:'2026-10-21T01:00:00Z',created_by_name:'测试人员',approval:{status:'approved'},total_amount:'0.67',
  lines:[{id:1,sku:'M-001',material_id:1,material_name:'第一物料',unit:'件',quantity:'2',unit_price:'0.335',line_total:'0.67',shipped_quantity:'0',returned_quantity:'0',net_delivered_quantity:'0',remaining_quantity:'2',warranty_days:null,warranty_basis:''}]}
async function fixture(t){
  // 保留真实展示组件和状态标签；表格按字段展开以验证各字段所属单元格。
  const server=await createServer({configFile:false,plugins:[{name:'sales-page-design-test',enforce:'pre',resolveId(id,importer){
    if(!importer?.includes('/src/renderer/'))return
    if(id.endsWith('/WorkspaceTable.vue'))return '\0sales-design-table'
    if(id.endsWith('/AppButton.vue'))return '\0sales-design-button'
    if(id.endsWith('/AppModal.vue'))return '\0sales-design-modal'
    if(id.endsWith('/SalesRecordFilters.vue'))return '\0sales-design-filter'
  },load(id){
    if(id==='\0sales-design-button')return `import {h} from 'vue';export default {props:['disabled'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}`
    if(id==='\0sales-design-modal')return `import {h} from 'vue';export default {props:['show'],setup:(p,{slots})=>()=>p.show?h('section',slots.default?.()):null}`
    if(id==='\0sales-design-filter')return 'export default {render:()=>null}'
    if(id==='\0sales-design-table')return `import {h} from 'vue';export default {props:['columns','data','amountTotal','pagination'],setup:(p,{slots})=>()=>h('section',[
      h('header',slots.actions?.()),h('aside',slots.filters?.()),...p.data.map(row=>h('article',p.columns.map(col=>h('div',{'data-field':col.key},[h('h3',col.title),slots['cell-'+col.key]?.({row})??String(row[col.key]??'')])))),h('footer',p.amountTotal),h('p',{'data-total':true},p.pagination?.total)])}`
  }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  async function render(file,props){
    const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/'+file+'.vue')
    let vnode;const context={}
    const html=await renderToString(createSSRApp({render:()=>vnode=h(Component,props)}),context)
    return {html,context,state:vnode.component.setupState}
  }
  return render
}
test('销售列表字段分开，完整统计不受分页搜索影响，概览保留其他筛选并清除冲突状态',async t=>{
  const render=await fixture(t),records=Array.from({length:24},(_,index)=>({...order,id:index+1,document_no:`XS-${index+1}`}))
  let selected,viewed
  const {html,context,state}=await render('SalesDocumentList',{kind:'order',title:'销售订单',records,filtered:records,customers:[],disabled:false,localTime:v=>v,query:'',
    filters:{...newSalesFilters(),customer:2,from:'2026-10-20',status:'approved'},'onUpdate:filters':value=>selected=value,onView:row=>viewed=row})
  assert.equal((html.match(/<article>/g)??[]).length,20)
  assert.match(context.teleports['#workspace-page-summary'],/全部订单，24 条/)
  assert.match(html,/data-field="customer_name"[^]*?页面测试客户/)
  const documentCell=html.split('data-field="document"')[1].split('</div>')[0]
  assert.doesNotMatch(documentCell,/页面测试客户|参考资料|0.67/)
  assert.match(html,/data-field="amount"[^]*?0.67/)
  assert.match(html,/app-status-tag--ready/)
  state.selectGroup('pending')
  assert.deepEqual(selected,{...newSalesFilters(),customer:2,from:'2026-10-20',status:'',group:'pending'})
  state.changePage(2,20);assert.equal(state.pageRows.length,4)
  assert.equal(state.total,24)
  assert.equal(viewed,undefined)
  const narrowed=await render('SalesDocumentList',{kind:'order',title:'销售订单',records,filtered:[records[0]],customers:[],disabled:true,localTime:v=>v,query:'XS-1',filters:newSalesFilters()})
  assert.match(narrowed.context.teleports['#workspace-page-summary'],/全部订单，24 条/)
  assert.match(narrowed.html,/<button[^>]*disabled[^>]*>XS-1/)
  assert.match(narrowed.html,/data-total="true">1</)
})
test('业务详情先显示独立基础字段和物料表，保留金额精度、保修空值和原批次',async t=>{
  const render=await fixture(t)
  const detail=await render('SalesDocumentDetail',{record:order,kind:'order',title:'销售订单',busy:false,disabled:false,localTime:v=>v})
  assert.match(detail.html,/基础信息/)
  assert.match(detail.html,/data-field="quantity"[^]*?订购数量[^]*?>2</)
  assert.match(detail.html,/data-field="unit_price"[^]*?>0.335</)
  assert.match(detail.html,/data-field="warranty_days"[^]*?>—</)
  assert.doesNotMatch(detail.html,/提交审批|审批步骤|>保存草稿</)
  assert.equal(detail.state.lines[0].line_total,'0.67')
  const shipment={...order,status:'posted',lines:[{...order.lines[0],returned_quantity:'1',returnable_quantity:'1',physical_lots:[{code:'LOT-1',quantity:'2',source_kind:'purchase_receipt'}]}]}
  const posted=await render('SalesDocumentDetail',{record:shipment,kind:'shipment',title:'销售出库',busy:false,disabled:false,localTime:v=>v})
  assert.match(posted.html,/LOT-1/)
  assert.equal(posted.state.lines[0].returned_quantity,'1')
  assert.equal(posted.state.lines[0].returnable_quantity,'1')
  const legacy=await render('SalesDocumentDetail',{record:{...shipment,lines:[order.lines[0]]},kind:'shipment',title:'销售出库',busy:false,disabled:false,localTime:v=>v})
  assert.match(legacy.html,/普通确认未指定实物批次/)
  for(const kind of ['order','shipment','return']){
    const keys=salesListColumns(kind).map(col=>col.key)
    assert.ok(keys.includes('customer_name')&&keys.includes('approval')&&keys.includes('status'))
    assert.equal(new Set(keys).size,keys.length)
    assert.ok(salesLineColumns(kind).some(col=>col.key==='sku'))
    assert.ok(salesLineColumns(kind).some(col=>col.key==='material_name'))
  }
})
