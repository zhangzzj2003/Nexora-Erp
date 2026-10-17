import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateMaterialChoice, validateMaterialMetadata, validateDocumentMaterialResult } from '../src/shared/material-choice-validation.ts'
import { validateProductResult } from '../src/shared/product-api.ts'
import { validateMaterialFlowDocument, validateMaterialFlowResult } from '../src/shared/material-flow-api.ts'
import { validateProductionAssociations } from '../src/shared/production-association-api.ts'
import { validateDocumentApprovalRecord } from '../src/shared/document-approval-api.ts'
import { callBackend } from '../src/main/backend.ts'
import { associationFixture } from './production-association-fixture.mjs'

// 参数仍沿用十进制字符串与布尔值，零和 false 不能因真假判断被当成未填写。
const material=(id=22)=>({id,sku:`M-${id}`,name:'控制组件',unit:'个',category_code:'EL-IC',category_name:'电子 / 集成电路',
 specification:'原规格',package:'SOP-8',brand:'示例品牌',manufacturer_part_number:'PART-001',notes:'当前档案说明',
 spec_template_version:4,spec_summary:'阻值 0 Ω；防水 否',spec_values:[
  {field_id:1,category_code:'EL-IC',name:'阻值',kind:'number',unit:'Ω',status:'filled',value:'0',source:'实测',historical:false},
  {field_id:2,category_code:'EL-IC',name:'防水',kind:'boolean',unit:'',status:'filled',value:false,source:'说明书',historical:true},
  {field_id:3,category_code:'EL-IC',name:'确认中',kind:'text',unit:'',status:'pending',value:null,source:'待核对',historical:false},
  {field_id:4,category_code:'EL-IC',name:'不适用',kind:'text',unit:'',status:'not_applicable',value:null,source:'',historical:false},
  {field_id:5,category_code:'EL-IC',name:'未知',kind:'text',unit:'',status:'unknown',value:null,source:'',historical:true}
 ],extra_attributes:[{name:'自定义尺寸',value:'0',unit:'mm'}]})
const line=()=>({id:3,material_id:22,sku:'OLD-22',material_name:'历史单据组件名称',unit:'个',quantity:'1',material:material()})
const bom=()=>({id:7,version:2,product_material_id:11,product_sku:'P-11',product_name:'整机',product_unit:'台',
 status:'retired',base_quantity:'1',lines:[{id:3,component_material_id:22,sku:'OLD-22',material_name:'历史组件',unit:'个',quantity:'1',material:material()}]})
const flow=()=>({id:7,version:2,kind:'dispatch',work_order_id:2,warehouse_id:1,document_no:'SCFL-20261017-000001',
 lines:[{...line(),work_order_line_id:4,executed_quantity:'0',received_quantity:'0',remaining_quantity:'1'}],executions:[]})
const flowSummary=()=>({work_order_id:2,lines:[{work_order_line_id:4,material_id:22,material:material()}],sources:[],
 dispatches:[flow()],receipts:[],exchanges:[],returns:[]})
const approval=()=>({document_type:'WarehouseInbound',document_id:1,intent:'execute',document_no:null,business_status:'draft',
 reversal_reason:'',content_matches:true,status:'draft',version:0,generation:0,current_step:0,steps:[],policy_version:null,
 submitted_by:null,submitted_at:null,executed_by:null,executed_at:null,can_submit:true,can_review:false,can_withdraw:false,events:[],
 summary:[{label:'仓库',value:'主仓库'},{label:'OLD-22 · 历史名称',value:'1 个',material_id:22,material:material()}]})
const association=()=>{const row=associationFixture();row.components[0].material=material(7);return row}

// 不要求编辑版本，也不把当前档案名称与历史单据文字强行同步；只按稳定物料 ID 归属。
test('单条物料资料复用规格约束且无需版本，保留零布尔历史状态及扩展属性',()=>{
 const row=material(),before=structuredClone(row)
 validateMaterialChoice(row);validateMaterialMetadata(row,22)
 assert.equal(row.version,undefined);assert.deepEqual(row,before)
 assert.equal(row.spec_values[0].value,'0');assert.equal(row.spec_values[1].value,false)
 assert.equal(row.spec_values[1].historical,true);assert.equal(row.extra_attributes[0].value,'0')
 validateMaterialChoice({id:22,sku:'M-22',name:'旧服务简要物料',unit:'个'})
 assert.throws(()=>validateMaterialMetadata(row,23),/身份/)
 assert.throws(()=>validateMaterialMetadata(row,undefined),/身份/)
 assert.throws(()=>validateMaterialMetadata(row,'22'),/身份/)
})

test('单条物料资料拒绝畸形参数超长字段及无独立身份的任意对象',()=>{
 const bad=[null,[],{},false,{...material(),id:0},{...material(),sku:22},{...material(),notes:'x'.repeat(1001)},
  {...material(),category_name:'x'.repeat(201)},{...material(),name:'x'.repeat(121)},
  {...material(),spec_summary:{}},{...material(),spec_summary:'x'.repeat(40001)},
  {...material(),spec_template_version:0},{...material(),spec_values:{}},
  {...material(),spec_values:[{...material().spec_values[0],value:0}]},
  {...material(),spec_values:[{...material().spec_values[0],value:'x'.repeat(501)}]},
  {...material(),spec_values:[{...material().spec_values[1],historical:'true'}]},
  {...material(),spec_values:[{...material().spec_values[0],status:'pending',value:'1'}]},
  {...material(),spec_values:[{...material().spec_values[0],name:'x'.repeat(81)}]},
  {...material(),spec_values:[material().spec_values[0],material().spec_values[0]]},
  {...material(),extra_attributes:[{name:'尺寸',value:{value:'1'},unit:'mm'}]},
  {...material(),extra_attributes:[{name:'尺寸',value:'x'.repeat(501),unit:'mm'}]},
  {...material(),extra_attributes:[{name:'尺寸',value:'1',unit:'mm'},{name:' 尺寸 ',value:'2',unit:'mm'}]},
  {...material(),extra_attributes:Array.from({length:21},(_,id)=>({name:`扩展${id}`,value:'1',unit:''}))}]
 for(const row of bad)assert.throws(()=>validateMaterialChoice(row),/物料|规格/)
 const summaryOnly={id:22,sku:'M',name:'料',unit:'个',spec_summary:42}
 assert.throws(()=>validateMaterialChoice(summaryOnly),/摘要/)
})

test('BOM列表详情与版本写回按组件物料身份校验参数，老服务无metadata继续通过',()=>{
 for(const status of ['draft','active','retired','cancelled']){
  const row={...bom(),status}
  for(const action of ['bomDetail','productBoms','boms','createBom','activateBom','retireBom','cancelBom']){
   const result=['productBoms','boms'].includes(action)?[row]:row
   validateProductResult(action,result)
   const older=structuredClone(row);delete older.lines[0].material
   validateProductResult(action,['productBoms','boms'].includes(action)?[older]:older)
   const wrong=structuredClone(row);wrong.lines[0].material.id=11
   assert.throws(()=>validateProductResult(action,['productBoms','boms'].includes(action)?[wrong]:wrong),/身份/)
   const malformed=structuredClone(row);malformed.lines[0].material.notes='x'.repeat(1001)
   assert.throws(()=>validateProductResult(action,['productBoms','boms'].includes(action)?[malformed]:malformed),/物料/)
  }
 }
 // 当前资料可以更名，但不能把产成品 ID 或单据行号误当成组件的物料 ID。
 assert.notEqual(bom().lines[0].material.sku,bom().lines[0].sku)
})

test('生产物料单据工单汇总和关联组件拒绝错位参数，旧响应不强制新增metadata',()=>{
 validateMaterialFlowDocument(flow())
 const older=flow();delete older.lines[0].material;validateMaterialFlowDocument(older)
 const broken=flow();broken.lines[0].material.id=3
 assert.throws(()=>validateMaterialFlowDocument(broken),/身份/)
 const page={items:[broken],total:1,page:1,page_size:20,summary:{draft:1}}
 assert.throws(()=>validateMaterialFlowResult('materialFlowQuery',page,{kind:'dispatch'}),/身份/)
 const summary=flowSummary();validateMaterialFlowResult('workOrderMaterialFlow',summary,{orderId:2})
 summary.lines[0].material.id=4
 assert.throws(()=>validateMaterialFlowResult('workOrderMaterialFlow',summary,{orderId:2}),/身份/)
 delete summary.lines[0].material;validateMaterialFlowResult('workOrderMaterialFlow',summary,{orderId:2})
 const child=flowSummary();child.dispatches[0].lines[0].material.extra_attributes=[{name:'尺寸',value:'x'.repeat(501),unit:''}]
 assert.throws(()=>validateMaterialFlowResult('workOrderMaterialFlow',child,{orderId:2}),/物料/)
 const linked=association();validateProductionAssociations(linked)
 linked.components[0].material.id=linked.components[0].id
 assert.throws(()=>validateProductionAssociations(linked),/身份/)
 delete linked.components[0].material;validateProductionAssociations(linked)
})

test('审批摘要参数要求独立material_id，普通摘要与旧历史缺字段保持兼容',()=>{
 const row=approval();validateDocumentApprovalRecord(row)
 const legacy=approval();delete legacy.summary[1].material;delete legacy.summary[1].material_id
 validateDocumentApprovalRecord(legacy)
 for(const mutation of [entry=>{delete entry.material_id},entry=>{entry.material_id=0},entry=>{entry.material.id=1},
  entry=>{entry.material=null},entry=>{entry.material.spec_values[1].value='x'.repeat(501)}]){
  const wrong=approval();mutation(wrong.summary[1]);assert.throws(()=>validateDocumentApprovalRecord(wrong),/物料/)
 }
 const labelOnly=approval();labelOnly.summary[0].material_id=false
 assert.throws(()=>validateDocumentApprovalRecord(labelOnly),/物料/)
})

test('ReceiptLine所属单据逐行校验可选metadata，单据旧字段与历史标签不受影响',()=>{
 for(const action of ['otherInbounds','createOtherInbound','reopenOtherInbound','postOtherInbound','cancelOtherInbound','reverseOtherInbound',
  'warehouseOutbounds','postWarehouseOutbound','stockAdjustments','postStockAdjustment','receipts','postReceipt','transfers','postTransfer']){
  const row={id:1,lines:[line(),{...line(),id:4,material_id:23,material:material(23)}]}
  const list=['otherInbounds','warehouseOutbounds','stockAdjustments','receipts','transfers'].includes(action)
  validateDocumentMaterialResult(action,list?[row]:row)
  row.lines[1].material.id=22
  assert.throws(()=>validateDocumentMaterialResult(action,list?[row]:row),/身份/)
  row.lines.forEach(entry=>{delete entry.material})
  validateDocumentMaterialResult(action,list?[row]:row)
 }
})

// 使用真实主进程分发，证明校验并非仅供单元测试调用；所有读取/写回均拒绝相邻物料的参数快照。
test('主IPC对入库BOM生产流转关联及审批返回逐行核对metadata，不增加请求或改写历史值',async t=>{
 let response
 const paths=[]
 t.mock.method(globalThis,'fetch',async(url,options)=>{
  paths.push([url.pathname,options.method])
  return Response.json(url.pathname.endsWith('/login')?{token:'metadata-test',user:{id:1}}:response)
 })
 await callBackend('login',{})
 const inboundInput={warehouse_id:1,reason:'other',note:'',reference:'',lines:[{material_id:22,quantity:'1'}]}
 const cases=[
  ['otherInbounds',undefined,()=>[{id:1,lines:[line()]}],row=>row[0].lines[0]],
  ['createOtherInbound',inboundInput,()=>({id:1,lines:[line()]}),row=>row.lines[0]],
  ['reopenOtherInbound',{...inboundInput,inboundId:1},()=>({id:1,lines:[line()]}),row=>row.lines[0]],
  ['postOtherInbound',{inboundId:1},()=>({id:1,lines:[line()]}),row=>row.lines[0]],
  ['cancelOtherInbound',{inboundId:1},()=>({id:1,lines:[line()]}),row=>row.lines[0]],
  ['reverseOtherInbound',{inboundId:1,reason:'更正'},()=>({id:1,lines:[line()]}),row=>row.lines[0]],
  ['receipts',undefined,()=>[{id:1,lines:[line()]}],row=>row[0].lines[0]],
  ['bomDetail',{bomId:7},bom,row=>row.lines[0]],
  ['boms',undefined,()=>[bom()],row=>row[0].lines[0]],
  ['productBoms',{materialId:11},()=>[bom()],row=>row[0].lines[0]],
  ['createBom',{product_material_id:11,base_quantity:'1',note:'',lines:[{component_material_id:22,quantity:'1'}]},bom,row=>row.lines[0]],
  ['activateBom',{bomId:7},bom,row=>row.lines[0]],
  ['retireBom',{bomId:7},bom,row=>row.lines[0]],
  ['cancelBom',{bomId:7},bom,row=>row.lines[0]],
  ['materialFlowDetail',{kind:'dispatch',id:7},flow,row=>row.lines[0]],
  ['materialFlowQuery',{kind:'dispatch',page:1,page_size:20},()=>({items:[flow()],total:1,page:1,page_size:20,summary:{draft:1}}),row=>row.items[0].lines[0]],
  ['workOrderMaterialFlow',{orderId:2},flowSummary,row=>row.lines[0]],
  ['productionAssociations',{kind:'work_order',id:1,include_references:false},association,row=>row.components[0]],
  ['documentApproval',{document_type:'WarehouseInbound',document_id:1,intent:'execute'},approval,row=>row.summary[1]],
  ['actDocumentApproval',{document_type:'WarehouseInbound',document_id:1,intent:'execute',action:'submit',version:0,reason:'核对'},approval,row=>row.summary[1]],
  ['inventoryLedgerDocument',{movement_id:19},()=>({movement_id:19,document:approval()}),row=>row.document.summary[1]]
 ]
 for(const [action,payload,make,select] of cases){
  response=make();const original=structuredClone(response),before=paths.length
  assert.deepEqual(await callBackend(action,payload),original)
  assert.equal(paths.length,before+1,'资料随原响应返回，不追加物料请求')
  response=make();select(response).material.id=999
  await assert.rejects(callBackend(action,payload),/身份/)
  response=make();delete select(response).material
  assert.deepEqual(await callBackend(action,payload),response,'不带metadata的旧服务继续通过')
 }
})
